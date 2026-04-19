# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Incus container lifecycle for isholate.

Handles launching Incus containers with host user mirroring, bind mounts,
and interactive exec.  Supports a three-tier caching model:

1. **Host base** (``isholate-base-<user>-<image-tag>``) — persistent container
   with apt bootstrap and the host ishfiles applied.  Reused across runs; only
   rebuilt when the source fingerprint changes or ``--rebuild-base`` is set.

2. **Project base** (``isholate-pbase-<user>-<project-hash>``) — persistent
   container derived from the host base with the project overlay applied.
   One per project directory.

3. **Ephemeral** (``isholate-<user>-<rand>``) — one-shot container cloned from
   the project base (or host base), used for the actual exec session, always
   stopped and deleted afterwards.

When no ishfiles sources are available, or when ``--no-cache`` is set, a simple
one-shot container is created from the raw image (original behaviour).
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import socket
import string
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

from ..container import incus as _incus
from ..ish_logging import log_level_from_args, log_level_to_cli_flags
from .claude import (
    _add_claude_mounts,
    _apply_network_restrictions,
    _install_claude_base_auth,
)
from .config import FAILED_LOGS_STATE_DIR
from .locks import base_build_lock

log = logging.getLogger(__name__)


# Root of the ishlib checkout — used to mount the ishfiles CLI into containers.
# Path: container.py -> isholate/ -> pyishlib/ -> src/ -> ishlib/
_ISHLIB_ROOT: Path = Path(__file__).resolve().parents[3]

# Path inside the container where isholate mounts its helper files.
_ISHOLATE_RUN_DIR = "/run/isholate"

# Incus user-data keys for metadata stored on persistent bases.
_META_SOURCE_HASH = "user.isholate.source_hash"
_META_UID = "user.isholate.uid"

# Pinned version of the sandbox runtime installed globally in base containers.
# Update this constant when bumping the package so cache-key logic can track it.
_SANDBOX_RUNTIME_VERSION = "0.0.49"


def _say(msg: str, *, quiet: bool = False) -> None:  # noqa: ARG001
    """Log an isholate progress message at INFO level.

    The ``quiet`` parameter is accepted for backwards compatibility but is no
    longer used — level filtering is done by the logging handler configured
    in :func:`~pyishlib.isholate.cli.main`.
    """
    log.info(msg)


def get_host_user_info() -> "tuple[str, Path, Path]":
    """Return (username, home, cwd) for the current host user."""
    username = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    home = Path.home()
    cwd = Path.cwd()
    return username, home, cwd


# Shells known to accept ``-l``/``--login`` to start as a login shell.
# Other shells (``dash``, ``/bin/sh``, …) are invoked without the flag so
# they don't bail out on an unknown option; the shell is still interactive
# when stdin is a TTY, which is the case under ``incus exec``.
_LOGIN_FLAG_SHELLS = frozenset({"bash", "zsh", "fish", "ksh", "mksh", "tcsh", "csh"})


def _login_shell_argv(shell: str) -> List[str]:
    """Return the argv to invoke *shell* as a login shell.

    A login shell is needed so profile files (``.bash_profile`` / ``.profile``
    / ``.zprofile`` / ``.zlogin`` / fish's config) are sourced on container
    entry — otherwise the user has to re-exec the shell by hand to pick up
    their dotfiles.  The shell will also be interactive when ``incus exec``
    is attached to a TTY (the default for terminal sessions).

    For shells known to accept ``-l`` the flag is appended; for others the
    shell is invoked bare to avoid breaking exec when the flag is unsupported.
    """
    base = os.path.basename(shell)
    if base in _LOGIN_FLAG_SHELLS:
        return [shell, "-l"]
    return [shell]


def _sanitize_for_name(username: str) -> str:
    """Sanitize a username for use in an Incus instance name.

    Incus names must be lowercase alphanumeric with hyphens only.
    """
    s = username.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "user"


def generate_name(username: str) -> str:
    """Generate a short random ephemeral container name."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"isholate-{_sanitize_for_name(username)}-{suffix}"


# ---------------------------------------------------------------------------
# Naming helpers for persistent bases
# ---------------------------------------------------------------------------


def _image_tag(image: str) -> str:
    """Derive a short, filesystem-safe tag from an Incus image string.

    The scheme/remote prefix (everything up to and including the first ``:``)
    is stripped before sanitising.

    Examples::

        "images:ubuntu/24.04"  ->  "ubuntu-24-04"
        "ubuntu:22.04"         ->  "22-04"
    """
    tag = re.sub(r"^[^:]+:", "", image)  # strip scheme
    tag = re.sub(r"[^a-z0-9]+", "-", tag.lower())
    return tag.strip("-")[:30]


def _project_hash(project_path: Path) -> str:
    """Return an 8-character hex hash of the project's absolute path."""
    return hashlib.sha256(str(project_path).encode()).hexdigest()[:8]


def _host_base_name(username: str, image: str) -> str:
    """Container name for the host-ishfiles base."""
    return f"isholate-base-{_sanitize_for_name(username)}-{_image_tag(image)}"


def _project_base_name(username: str, project_path: Path) -> str:
    """Container name for the project-overlay base."""
    return (
        f"isholate-pbase-{_sanitize_for_name(username)}-{_project_hash(project_path)}"
    )


# ---------------------------------------------------------------------------
# Container state helpers
# ---------------------------------------------------------------------------


def _container_exists(name: str) -> bool:
    """Return True if an Incus container with *name* exists (any state)."""
    r = _incus._run(["incus", "info", name], capture_output=True, check=False)
    return r.returncode == 0


def _get_stored_fingerprint(name: str) -> Optional[str]:
    """Read the source fingerprint stored on a base container's metadata."""
    r = _incus._run(
        ["incus", "config", "get", name, _META_SOURCE_HASH],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def _set_stored_fingerprint(name: str, fingerprint: str) -> None:
    """Store *fingerprint* on *name*'s container metadata."""
    _incus._run(
        ["incus", "config", "set", name, _META_SOURCE_HASH, fingerprint],
        check=True,
    )


def _get_stored_uid(name: str) -> Optional[int]:
    """Read the container user UID from a base container's metadata."""
    r = _incus._run(
        ["incus", "config", "get", name, _META_UID],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        return None
    val = r.stdout.strip()
    try:
        return int(val) if val else None
    except ValueError:
        return None


def _set_stored_uid(name: str, uid: int) -> None:
    """Store *uid* on *name*'s container metadata."""
    _incus._run(
        ["incus", "config", "set", name, _META_UID, str(uid)],
        check=True,
    )


def _parse_isholate_devices(stdout: str) -> List[str]:
    """Filter ``incus config device list`` output to just ``isholate-*`` names.

    Takes the raw stdout (one device name per line) and returns the names
    whose whitespace-stripped value starts with ``isholate-``.  Shared by
    both the lenient listing path and the strict assertion path so their
    parsing stays consistent.
    """
    return [
        line.strip()
        for line in stdout.splitlines()
        if line.strip().startswith("isholate-")
    ]


def _list_isholate_devices(name: str) -> List[str]:
    """Return the names of all ``isholate-*`` devices configured on *name*.

    Uses ``incus config device list`` which prints one device name per line
    (plain text, no ``--format`` flag support).  Returns an empty list when
    the container does not exist or the command fails.
    """
    r = _incus._run(
        ["incus", "config", "device", "list", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return _parse_isholate_devices(r.stdout)


def _remove_isholate_devices(name: str) -> None:
    """Remove all devices whose names start with ``isholate-`` from *name*.

    Called before stopping a base container so that it carries no stale
    host-path bind-mount references.
    """
    for device_name in _list_isholate_devices(name):
        _incus._run(
            ["incus", "config", "device", "remove", name, device_name],
            check=False,
        )


def _assert_no_isholate_devices(name: str) -> None:
    """Raise RuntimeError if *name* still carries any ``isholate-*`` devices.

    Called after ``_remove_isholate_devices`` on a stopped base so that a
    silently-failing removal cannot poison the base for future copies.

    Fails closed: unlike ``_list_isholate_devices`` (which is lenient for the
    best-effort cleanup path), this helper raises on a non-zero exit from
    ``incus config device list`` so a failed device-list call cannot mask a
    poisoned base.
    """
    r = _incus._run(
        ["incus", "config", "device", "list", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        stderr = (r.stderr or "").strip()
        raise RuntimeError(
            f"failed to verify isholate devices for '{name}': "
            f"'incus config device list' exited with {r.returncode}"
            + (f": {stderr}" if stderr else "")
        )
    leftovers = _parse_isholate_devices(r.stdout)
    if leftovers:
        raise RuntimeError(
            f"failed to remove isholate devices from '{name}': {leftovers}"
        )


def _source_fingerprint(source: Path) -> str:
    """Compute a reproducible fingerprint for a source tree.

    When *source* is inside a git repo, the fingerprint is **path-scoped**:
    it only reflects state of files under *source*, not the whole repo.
    This matters when *source* is a subdirectory (e.g. ``.ishlib/ishfiles/``)
    of a larger, actively developed repo — unrelated commits or working-tree
    changes elsewhere in the repo must not invalidate the cache.

    Git strategy:

    - ``git log -1 --format=%H -- .`` → the SHA of the last commit that
      touched anything under *source*.
    - ``git status --porcelain -- .`` → dirty/untracked files under *source*
      only.

    Falls back to a recursive content hash for non-git trees, when git is
    unavailable, or when nothing under *source* has ever been committed
    (so untracked-only directories still contribute to the fingerprint).
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(source), "log", "-1", "--format=%H", "--", "."],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not head:
            # No committed history under this path — fall back to content
            # hash so untracked files still contribute to the fingerprint.
            raise subprocess.CalledProcessError(1, "git log")
        status = subprocess.run(
            ["git", "-C", str(source), "status", "--porcelain", "--", "."],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        raw = f"{head}\n{status}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Non-git, git not available, or no committed history under the path:
        # hash the file tree.
        h = hashlib.sha256()
        for p in sorted(source.rglob("*")):
            if p.is_file():
                try:
                    h.update(str(p.relative_to(source)).encode())
                    h.update(p.read_bytes())
                except OSError:
                    pass
        raw = h.hexdigest()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _host_base_fingerprint(source: Path) -> str:
    """Fingerprint used as the cache key for persistent host-base containers.

    Combines the source-tree fingerprint with :data:`_SANDBOX_RUNTIME_VERSION`
    so that bumping the pinned npm package version automatically invalidates
    any cached base that was built without it.
    """
    source_fp = _source_fingerprint(source)
    combined = f"{source_fp}:{_SANDBOX_RUNTIME_VERSION}"
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def _network_preflight(name: str, *, quiet: bool = False) -> None:
    """Probe outbound IPv4 connectivity inside the container.

    Runs before the package manager so that network failures produce
    actionable diagnostics instead of a wall of timeout messages.

    Uses ``ping`` to test raw IPv4 egress.  If ``ping`` is not present in
    the image (exit 127) the check is skipped — minimal images that lack
    ``ping`` typically still have working network configured by Incus.
    Similarly ``ip`` and ``getent`` are used for diagnostic output only; a
    missing tool degrades gracefully rather than aborting.

    Raises:
        RuntimeError: if the container cannot reach the internet.
    """
    _say("checking container network connectivity...", quiet=quiet)

    def _probe(cmd: List[str]) -> "tuple[int, str]":
        r = _incus._run(
            ["incus", "exec", name, "--"] + cmd,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        return r.returncode, (r.stdout or "").strip()

    _, route_out = _probe(["ip", "-4", "route", "show", "default"])
    _, addr_out = _probe(["ip", "-4", "addr", "show"])
    dns_rc, _ = _probe(["getent", "hosts", "1.1.1.1"])

    raw_rc, _ = _probe(["ping", "-c", "1", "-W", "5", "1.1.1.1"])

    # Exit 127 means the tool is not installed — skip the check rather than
    # misreporting a connectivity failure.
    if raw_rc == 127:
        log.debug("ping not found in image — skipping network pre-flight")
        return

    if raw_rc != 0:
        dns_status = "ok" if dns_rc == 0 else ("unknown" if dns_rc == 127 else "fail")
        container_ip = _extract_container_ip(addr_out)
        default_route = route_out or "none"
        docker_running = Path("/run/docker.sock").exists()
        docker_hint = (
            "  * Docker is running (detected) and its FORWARD DROP policy blocks\n"
            "    incus bridge traffic.  Use a systemd drop-in so the fix persists\n"
            "    across reboots and Docker restarts (avoids iptables-persistent):\n"
            "      sudo mkdir -p /etc/systemd/system/docker.service.d\n"
            "      sudo tee /etc/systemd/system/docker.service.d/incus-forward.conf <<'EOF'\n"
            "    [Service]\n"
            "    ExecStartPost=/sbin/iptables -I DOCKER-USER -i incusbr0 -j ACCEPT\n"
            "    ExecStartPost=/sbin/iptables -I DOCKER-USER -o incusbr0 -j ACCEPT\n"
            "    EOF\n"
            "      sudo systemctl daemon-reload && sudo systemctl restart docker\n"
        )
        other_hints = (
            "  * ufw is active and blocking forwarded traffic.\n"
            "    Fix:  sudo ufw allow in on incusbr0\n"
            "          sudo ufw route allow in on incusbr0\n"
            "\n"
            "  * firewalld is active and the 'incusbr0' zone is missing.\n"
            "    Fix:  sudo firewall-cmd --zone=trusted "
            "--change-interface=incusbr0 --permanent\n"
            "          sudo firewall-cmd --reload\n"
            "\n"
            "  * net.ipv4.ip_forward is 0.\n"
            "    Check: sysctl net.ipv4.ip_forward\n"
            "    Fix:   sudo sysctl -w net.ipv4.ip_forward=1\n"
            "\n"
            "  * Docker is running and its FORWARD DROP policy blocks incus traffic.\n"
            "    Fix:  sudo mkdir -p /etc/systemd/system/docker.service.d\n"
            "    (see Docker-detected variant above for full persistent fix)\n"
            "\n"
            "  * Incus bridge NAT is stale after an upgrade.\n"
            "    Fix:   sudo systemctl restart incus\n"
        )
        hints = (docker_hint + "\n" + other_hints) if docker_running else other_hints
        print(
            f"\nisholate: container has no outbound IPv4 connectivity.\n"
            f"\n"
            f"  default route:  {default_route}\n"
            f"  container IP:   {container_ip}\n"
            f"  DNS:            {dns_status}\n"
            f"  ping 1.1.1.1:   timeout\n"
            f"\n"
            f"The container can't reach the internet at all.  The host can, so this\n"
            f"is almost certainly an incus bridge / host firewall issue.  Common\n"
            f"causes on a plain LAN:\n"
            f"\n"
            f"{hints}\n"
            f"Retry isholate after applying one of the fixes above.\n",
            file=sys.stderr,
            flush=True,
        )
        raise RuntimeError("container has no outbound IPv4 connectivity")

    log.debug("network pre-flight ok")


def _extract_container_ip(addr_output: str) -> str:
    """Extract the first non-loopback IPv4 address from `ip addr show` output."""
    for line in addr_output.splitlines():
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", line)
        if m and not m.group(1).startswith("127."):
            return m.group(1)
    return "unknown"


def _host_apt_cacher_running() -> bool:
    """Return True if apt-cacher-ng appears to be listening on localhost:3142."""
    try:
        with socket.create_connection(("localhost", 3142), timeout=1):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _get_incus_bridge_ip() -> Optional[str]:
    """Return the IPv4 address of the incusbr0 bridge, or None if unavailable."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "incusbr0"],
            capture_output=True,
            text=True,
            check=True,
        )
        ip = _extract_container_ip(result.stdout)
        return ip if ip != "unknown" else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# Disk device helper
# ---------------------------------------------------------------------------


def _add_mount(
    name: str,
    device_name: str,
    src: Path,
    dst: str,
    *,
    readonly: bool = False,
    shift: bool = False,
) -> None:
    """Attach a disk device mapping host *src* → in-container *dst*."""
    cmd = [
        "incus",
        "config",
        "device",
        "add",
        name,
        device_name,
        "disk",
        f"source={src}",
        f"path={dst}",
    ]
    if readonly:
        cmd.append("readonly=true")
    if shift:
        cmd.append("shift=true")
    _incus._run(cmd, check=True)


def _add_home_mount(
    name: str,
    device_name: str,
    host_home: Path,
    rel: str,
    container_username: str,
    *,
    readonly: bool = False,
    shift: bool = True,
) -> bool:
    """Mirror ``<host_home>/<rel>`` into ``/home/<container_username>/<rel>``.

    Returns False if the source path does not exist; the source may be a file
    or a directory.
    """
    src = host_home / rel
    if not src.is_dir() and not src.is_file():
        return False
    dst = f"/home/{container_username}/{rel}"
    _add_mount(name, device_name, src, dst, readonly=readonly, shift=shift)
    return True


# ---------------------------------------------------------------------------
# Provisioning helpers (shared by both one-shot and base-creation paths)
# ---------------------------------------------------------------------------


def _bootstrap_base(
    name: str, *, log_level: int = logging.WARNING, quiet: bool = False
) -> None:
    """Bootstrap a freshly-started container: staging dir, ishlib mount, apt, npm.

    Sets up the ``/run/isholate`` staging area, mounts the ishlib checkout,
    probes network connectivity, installs base packages via apt (or dnf on
    Fedora-family images), then globally installs
    ``@anthropic-ai/sandbox-runtime@_SANDBOX_RUNTIME_VERSION`` via npm.
    Called once during host-base creation so all derived containers inherit
    the full toolchain.

    Base packages installed:
    - ``python3``, ``sudo`` — required for ishfiles provisioning.
    - ``bubblewrap``, ``nodejs``, ``npm``, ``socat`` — required for the
      sandbox runtime.

    Network isolation (``--no-network --claude``) is enforced at the Incus
    layer by attaching the ephemeral container to the ``isholate-claude``
    managed network, so no firewalling packages are needed inside the
    container.

    Args:
        name:      Container name.
        log_level: Terminal log level (``logging.INFO`` and below stream apt /
                   npm output instead of using their quiet flags).
        quiet:     Suppress isholate's own progress messages.
    """
    chatty = log_level <= logging.INFO
    # Create the /run/isholate staging directory.
    _incus._run_checked(
        ["incus", "exec", name, "--", "mkdir", "-p", _ISHOLATE_RUN_DIR],
        "create staging directory",
        stdin=subprocess.DEVNULL,
    )

    # Mount ishlib checkout so ishfiles CLI is reachable without pip.
    _add_mount(
        name,
        "isholate-ishlib",
        _ISHLIB_ROOT,
        f"{_ISHOLATE_RUN_DIR}/ishlib",
        readonly=True,
    )

    _say(
        "installing base packages in container "
        "(python3, sudo, bubblewrap, nodejs, npm, socat); "
        "this can take a minute on first run...",
        quiet=quiet,
    )
    _network_preflight(name, quiet=quiet)

    # Force apt to use IPv4.
    _incus._run(
        [
            "incus",
            "exec",
            name,
            "--",
            "/bin/sh",
            "-c",
            "mkdir -p /etc/apt/apt.conf.d && "
            "printf 'Acquire::ForceIPv4 \"true\";\\n' "
            "> /etc/apt/apt.conf.d/99isholate-force-ipv4",
        ],
        check=False,
        stdin=subprocess.DEVNULL,
    )

    bridge_ip = _get_incus_bridge_ip()
    if bridge_ip and _host_apt_cacher_running():
        _say(
            f"apt-cacher-ng detected on host — configuring proxy ({bridge_ip}:3142) in container...",
            quiet=quiet,
        )
        _incus._run(
            [
                "incus",
                "exec",
                name,
                "--",
                "/bin/sh",
                "-c",
                "mkdir -p /etc/apt/apt.conf.d && "
                f"printf 'Acquire::http::Proxy \"http://{bridge_ip}:3142\";\\n' "
                "> /etc/apt/apt.conf.d/01proxy",
            ],
            check=False,
            stdin=subprocess.DEVNULL,
        )
    elif not quiet:
        print(
            "isholate: tip: install apt-cacher-ng on the host to cache apt downloads\n"
            "  across container runs (speeds up repeated provisioning significantly):\n"
            "    sudo apt-get install apt-cacher-ng",
            file=sys.stderr,
        )

    apt_update = "apt-get update" if chatty else "apt-get update -qq"
    _base_pkgs = "python3 sudo bubblewrap nodejs npm socat"
    apt_install = (
        f"apt-get install -y --no-install-recommends {_base_pkgs}"
        if chatty
        else f"apt-get install -qq -y --no-install-recommends {_base_pkgs}"
    )
    _incus._run_checked(
        [
            "incus",
            "exec",
            name,
            "--env",
            "DEBIAN_FRONTEND=noninteractive",
            "--",
            "/bin/sh",
            "-c",
            f"if command -v apt-get >/dev/null 2>&1; then "
            f"{apt_update} && {apt_install}; "
            "elif command -v dnf >/dev/null 2>&1; then "
            f"dnf install -y {_base_pkgs}; "
            "fi",
        ],
        f"bootstrap ({_base_pkgs} install)",
        stdin=subprocess.DEVNULL,
    )
    _say("installing @anthropic-ai/sandbox-runtime via npm...", quiet=quiet)
    npm_flags = "" if chatty else "--loglevel=error "
    _incus._run_checked(
        [
            "incus",
            "exec",
            name,
            "--env",
            "npm_config_update_notifier=false",
            "--env",
            "npm_config_audit=false",
            "--env",
            "npm_config_fund=false",
            "--",
            "/bin/sh",
            "-c",
            f"npm install -g {npm_flags}@anthropic-ai/sandbox-runtime@{_SANDBOX_RUNTIME_VERSION}",
        ],
        "bootstrap (@anthropic-ai/sandbox-runtime install)",
        stdin=subprocess.DEVNULL,
    )


def _pull_container_log(
    container_name: str,
    container_log_path: str,
    host_dest: Path,
) -> None:
    """Pull a log file out of the container and save it on the host.

    Failures are logged at DEBUG (the file may not exist if ishfiles
    exited before creating it) and do not raise.

    Args:
        container_name:    Incus container name.
        container_log_path: Absolute path inside the container (e.g.
                            ``/tmp/ishfiles-pass1.log``).
        host_dest:          Host file path to write the pulled log to.
    """
    host_dest.parent.mkdir(parents=True, exist_ok=True)
    r = _incus._run(
        [
            "incus",
            "file",
            "pull",
            f"{container_name}{container_log_path}",
            str(host_dest),
        ],
        capture_output=True,
        check=False,
    )
    if r.returncode == 0:
        log.info("Container log saved to: %s", host_dest)
    else:
        log.debug(
            "Could not pull container log %s (may not exist yet): %s",
            container_log_path,
            r.stderr.decode(errors="replace").strip() if r.stderr else "",
        )


def _apply_host_ishfiles(
    name: str,
    username: str,
    uid: int,
    host_source: Path,
    host_config_dir: Optional[Path],
    ishfiles_flags: List[str],
    *,
    quiet: bool = False,
) -> None:
    """Apply the host ishfiles source inside the container (pass 1).

    Mounts the host source tree at ``/run/isholate/ishsrc`` and runs
    ``ishfiles apply --isholate --yes``.  Also mounts the host config dir
    if it exists.  Fixes up home ownership afterwards.

    Args:
        name:            Container name.
        username:        Container username.
        uid:             Container user UID (for the final chown).
        host_source:     Host ishfiles source tree path.
        host_config_dir: Optional ``~/.config/ishfiles/`` path to mount.
        ishfiles_flags:  Global flags to pass to the ishfiles command.
        quiet:           Suppress isholate's own progress messages.
    """
    _say("applying host ishfiles (pass 1)...", quiet=quiet)
    container_home = f"/home/{username}"
    ishfiles_bin = f"{_ISHOLATE_RUN_DIR}/ishlib/bin/ishfiles"
    container_log = "/tmp/isholate-ishfiles-pass1.log"

    _add_mount(
        name,
        "isholate-ishsrc",
        host_source,
        f"{_ISHOLATE_RUN_DIR}/ishsrc",
        readonly=True,
    )
    pass1_cmd = [
        "incus",
        "exec",
        name,
        "--env",
        f"HOME={container_home}",
        "--env",
        "ISHLIB_PYTHON=/usr/bin/python3",
        "--",
        ishfiles_bin,
        *ishfiles_flags,
        "--log-file",
        container_log,
        "--home",
        container_home,
        "-s",
        f"{_ISHOLATE_RUN_DIR}/ishsrc",
    ]
    if host_config_dir is not None and host_config_dir.is_dir():
        _add_mount(
            name,
            "isholate-ishconf",
            host_config_dir,
            f"{_ISHOLATE_RUN_DIR}/ishconf",
            readonly=True,
        )
        pass1_cmd += ["-c", f"{_ISHOLATE_RUN_DIR}/ishconf/config.toml"]
    pass1_cmd += ["apply", "--isholate", "--yes"]
    try:
        _incus._run_checked(
            pass1_cmd,
            "ishfiles apply (pass 1: host dotfiles)",
            stdin=subprocess.DEVNULL,
        )
    finally:
        host_log = Path.home() / FAILED_LOGS_STATE_DIR / name / "pass1.log"
        _pull_container_log(name, container_log, host_log)

    _say("finalising ownership of container home...", quiet=quiet)
    _incus._run_checked(
        [
            "incus",
            "exec",
            name,
            "--",
            "chown",
            "-R",
            f"{uid}:{uid}",
            container_home,
        ],
        "finalise container home ownership",
        stdin=subprocess.DEVNULL,
    )


def _apply_project_overlay(
    name: str,
    username: str,
    uid: int,
    project_overlay: Path,
    ishfiles_flags: List[str],
    *,
    quiet: bool = False,
) -> None:
    """Apply the project overlay inside the container (pass 2).

    Mounts the project overlay directory at ``/run/isholate/ishsrc-project``
    and runs ``ishfiles apply --isholate --yes``.  Fixes up home ownership.

    Args:
        name:            Container name.
        username:        Container username.
        uid:             Container user UID (for the final chown).
        project_overlay: Project ``.ishlib/ishfiles/`` directory path.
        ishfiles_flags:  Global flags to pass to the ishfiles command.
        quiet:           Suppress isholate's own progress messages.
    """
    _say("applying project overlay (pass 2)...", quiet=quiet)
    container_home = f"/home/{username}"
    ishfiles_bin = f"{_ISHOLATE_RUN_DIR}/ishlib/bin/ishfiles"
    container_log = "/tmp/isholate-ishfiles-pass2.log"

    _add_mount(
        name,
        "isholate-overlay",
        project_overlay,
        f"{_ISHOLATE_RUN_DIR}/ishsrc-project",
        readonly=True,
    )
    try:
        _incus._run_checked(
            [
                "incus",
                "exec",
                name,
                "--env",
                f"HOME={container_home}",
                "--env",
                "ISHLIB_PYTHON=/usr/bin/python3",
                "--",
                ishfiles_bin,
                *ishfiles_flags,
                "--log-file",
                container_log,
                "--home",
                container_home,
                "-s",
                f"{_ISHOLATE_RUN_DIR}/ishsrc-project",
                "apply",
                "--isholate",
                "--yes",
            ],
            "ishfiles apply (pass 2: project overlay)",
            stdin=subprocess.DEVNULL,
        )
    finally:
        host_log = Path.home() / FAILED_LOGS_STATE_DIR / name / "pass2.log"
        _pull_container_log(name, container_log, host_log)

    _say("finalising ownership of container home...", quiet=quiet)
    _incus._run_checked(
        [
            "incus",
            "exec",
            name,
            "--",
            "chown",
            "-R",
            f"{uid}:{uid}",
            container_home,
        ],
        "finalise container home ownership",
        stdin=subprocess.DEVNULL,
    )


def _provision(
    name: str,
    username: str,
    uid: int,
    host_config_dir: Optional[Path],
    host_source: Optional[Path],
    project_overlay: Optional[Path],
    *,
    log_level: int = logging.WARNING,
    quiet: bool = False,
) -> None:
    """Run ishfiles inside the container to bootstrap the user's environment.

    Used by the **one-shot** path (``--no-cache`` or no sources).  For the
    cached path, use :func:`ensure_host_base` / :func:`ensure_project_base`
    instead.

    Args:
        name:            Incus container name.
        username:        Username inside the container.
        uid:             UID of the container user (for final chown).
        host_config_dir: Host ``~/.config/ishfiles/`` directory.
        host_source:     Host ishfiles source tree (pass 1).  ``None`` skips pass 1.
        project_overlay: Project ``.ishlib/ishfiles/`` directory (pass 2).  ``None`` skips pass 2.
        log_level:       Terminal log level; propagated to the in-container
                         ishfiles invocation as ``--debug``/``-v``/``-q``.
        quiet:           Suppress isholate progress messages.
    """
    ishfiles_flags: List[str] = list(log_level_to_cli_flags(log_level))
    ishfiles_flags.extend(["--custom-username", username])

    _bootstrap_base(name, log_level=log_level, quiet=quiet)

    if host_source is not None:
        _apply_host_ishfiles(
            name,
            username,
            uid,
            host_source,
            host_config_dir,
            ishfiles_flags,
            quiet=quiet,
        )

    if project_overlay is not None:
        _apply_project_overlay(
            name, username, uid, project_overlay, ishfiles_flags, quiet=quiet
        )


# ---------------------------------------------------------------------------
# Persistent base management
# ---------------------------------------------------------------------------


def ensure_host_base(
    image: str,
    username: str,
    host_source: Path,
    host_config_dir: Optional[Path],
    shell: str,
    *,
    log_level: int = logging.WARNING,
    quiet: bool = False,
    rebuild: bool = False,
) -> str:
    """Return the name of a stopped, up-to-date host-ishfiles base container.

    Builds the base on first use or when the source fingerprint changes.
    If *rebuild* is True the base is always rebuilt regardless of fingerprint.

    The base container is left **stopped** so it can be cloned cheaply via
    ``incus copy``.  After provisioning, the base is stopped and then all
    host-path bind-mount devices are removed and verified to be gone;
    device removal intentionally runs after stop so Incus can cleanly
    detach bind-mounts without racing a live container.

    Args:
        image:           Incus image (e.g. ``"images:ubuntu/24.04"``).
        username:        Host username (mirrored inside the container).
        host_source:     Host ishfiles source tree.
        host_config_dir: Optional ``~/.config/ishfiles/`` directory.
        shell:           Login shell to create the user with.
        log_level:       Terminal log level; propagated to the in-container
                         ishfiles invocation as ``--debug``/``-v``/``-q``.
        quiet:           Suppress isholate progress messages.
        rebuild:         Force rebuild even if fingerprint matches.

    Returns:
        Container name of the (stopped) host base.

    Raises:
        subprocess.CalledProcessError: if any Incus command fails.
        RuntimeError: if the network preflight fails.
    """
    name = _host_base_name(username, image)
    fingerprint = _host_base_fingerprint(host_source)

    # Fast path (no lock): up-to-date base already exists.  Keeps the common
    # no-op case zero-cost — no lock file touch, no fcntl syscalls.
    if not rebuild and _container_exists(name):
        stored = _get_stored_fingerprint(name)
        if stored == fingerprint:
            _say(f"reusing host base '{name}'", quiet=quiet)
            _remove_isholate_devices(name)
            try:
                _assert_no_isholate_devices(name)
            except RuntimeError:
                # Poisoned — fall through to the locked rebuild path below.
                pass
            else:
                return name

    # Slow path: build or rebuild under a per-base lock so parallel isholate
    # invocations targeting the same base serialize instead of racing.  The
    # double-checked re-read inside the lock lets a waiter observe a peer's
    # just-finished build and skip its own redundant rebuild.
    with base_build_lock(name):
        # Re-check under the lock: a peer may have just built the base.
        if not rebuild and _container_exists(name):
            stored = _get_stored_fingerprint(name)
            if stored == fingerprint:
                _remove_isholate_devices(name)
                try:
                    _assert_no_isholate_devices(name)
                except RuntimeError:
                    # Poisoned base — devices could not be removed.  Force a
                    # rebuild so the user is not permanently stuck.  Use the
                    # strict post-delete check because a poisoned base that
                    # won't delete would leave us stuck in a rebuild loop.
                    _say(
                        f"host base '{name}' has un-removable isholate devices "
                        "— forcing rebuild...",
                        quiet=quiet,
                    )
                    del_r = _incus._run(
                        ["incus", "delete", name, "--force"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if _container_exists(name):
                        detail = (del_r.stderr or del_r.stdout or "").strip()
                        raise RuntimeError(
                            f"failed to delete poisoned host base '{name}' "
                            f"(incus delete exited with {del_r.returncode})"
                            + (f": {detail}" if detail else "")
                            + "; remove it manually with "
                            "'incus delete --force' and retry"
                        )
                    # Fall through to the create path below.
                else:
                    _say(
                        f"reusing host base '{name}' (built by peer)",
                        quiet=quiet,
                    )
                    return name
            else:
                _say(
                    f"host base '{name}' is stale (source changed) — rebuilding...",
                    quiet=quiet,
                )
                _incus._run(["incus", "delete", name, "--force"], check=False)
        elif rebuild and _container_exists(name):
            _say(
                f"rebuilding host base '{name}' (--rebuild requested)...",
                quiet=quiet,
            )
            _incus._run(["incus", "delete", name, "--force"], check=False)

        _say(
            f"creating host base '{name}' from {image} "
            "(may pull the image on first use)...",
            quiet=quiet,
        )
        _incus._run(
            ["incus", "init", image, name, "--config", "security.nesting=true"],
            check=True,
        )
        started = False

        try:
            _say(f"starting host base '{name}'...", quiet=quiet)
            _incus._run(["incus", "start", name], check=True)
            started = True

            # Create the container user matching the host username.
            _say(f"creating user '{username}' in host base...", quiet=quiet)
            _incus._run(
                ["incus", "exec", name, "--", "userdel", "-r", "ubuntu"],
                check=False,
            )
            _incus._run(
                ["incus", "exec", name, "--", "useradd", "-m", "-s", shell, username],
                check=True,
            )
            uid_result = subprocess.run(
                ["incus", "exec", name, "--", "id", "-u", username],
                capture_output=True,
                text=True,
                check=True,
            )
            uid = int(uid_result.stdout.strip())
            _set_stored_uid(name, uid)

            # Bootstrap (apt) and apply host ishfiles.
            ishfiles_flags: List[str] = list(log_level_to_cli_flags(log_level))
            ishfiles_flags.extend(["--custom-username", username])

            _bootstrap_base(name, log_level=log_level, quiet=quiet)
            _apply_host_ishfiles(
                name,
                username,
                uid,
                host_source,
                host_config_dir,
                ishfiles_flags,
                quiet=quiet,
            )

            # Stop the base, then remove host-path mounts and verify they are gone.
            # Device removal runs after stop so Incus can cleanly detach bind-mounts
            # without racing a live container.  The assertion ensures a silently-failing
            # removal cannot poison the base for future copies.
            _say(f"stopping and saving host base '{name}'...", quiet=quiet)
            _incus._run(["incus", "stop", name, "--force"], check=False)
            _remove_isholate_devices(name)
            _assert_no_isholate_devices(name)
            _set_stored_fingerprint(name, fingerprint)

            return name

        except (subprocess.CalledProcessError, RuntimeError):
            if started:
                _incus._run(["incus", "stop", name, "--force"], check=False)
                _incus._run(["incus", "delete", name, "--force"], check=False)
            raise


def ensure_project_base(
    host_base: str,
    username: str,
    project_overlay: Path,
    *,
    project_root: Path,
    log_level: int = logging.WARNING,
    quiet: bool = False,
    rebuild: bool = False,
) -> str:
    """Return the name of a stopped, up-to-date project-overlay base container.

    Derives the base from *host_base* via ``incus copy`` and applies the
    project overlay.  Rebuilds automatically when the overlay or the host base
    fingerprint changes, or when *rebuild* is True.

    Args:
        host_base:        Name of the (stopped) host-base container.
        username:         Host username (already mirrored from the host base).
        project_overlay:  Project ``.ishlib/ishfiles/`` directory.
        project_root:     Project root directory (the dir containing
                          ``.ishlib/``). Used for stable container naming.
        log_level:        Terminal log level; propagated to the in-container
                          ishfiles invocation as ``--debug``/``-v``/``-q``.
        quiet:            Suppress isholate progress messages.
        rebuild:          Force rebuild even if fingerprint matches.

    Returns:
        Container name of the (stopped) project base.

    Raises:
        subprocess.CalledProcessError: if any Incus command fails.
        RuntimeError: if provisioning raises.
    """
    name = _project_base_name(username, project_root)
    overlay_fp = _source_fingerprint(project_overlay)

    # Fast path (no lock): up-to-date project base already exists.  Combine
    # host-base fingerprint with the overlay content fingerprint so that
    # rebuilding the host base automatically cascades to the project base.
    host_fp = _get_stored_fingerprint(host_base) or ""
    combined_fp = f"{host_fp}:{overlay_fp}"

    if not rebuild and _container_exists(name):
        if _get_stored_fingerprint(name) == combined_fp:
            _say(f"reusing project base '{name}'", quiet=quiet)
            return name

    # Slow path: build/rebuild under a per-base lock.  Re-read the host-base
    # fingerprint *inside* the lock — a third party may have rebuilt the host
    # base while we were queued, which cascades into the combined fingerprint.
    with base_build_lock(name):
        host_fp = _get_stored_fingerprint(host_base) or ""
        combined_fp = f"{host_fp}:{overlay_fp}"

        if not rebuild and _container_exists(name):
            if _get_stored_fingerprint(name) == combined_fp:
                _say(
                    f"reusing project base '{name}' (built by peer)",
                    quiet=quiet,
                )
                return name

        if _container_exists(name):
            if rebuild:
                _say(
                    f"rebuilding project base '{name}' (--rebuild requested)...",
                    quiet=quiet,
                )
            else:
                _say(
                    f"project base '{name}' is stale (host base or overlay changed) — rebuilding...",
                    quiet=quiet,
                )
            _incus._run(["incus", "delete", name, "--force"], check=False)

        _say(
            f"creating project base '{name}' from host base '{host_base}'...",
            quiet=quiet,
        )
        _incus._run(["incus", "copy", host_base, name], check=True)
        # Strip any isholate-* devices inherited from the host base.  The host
        # base is supposed to be device-free when stopped, but a stale base from
        # an interrupted earlier run may still carry them; starting a container
        # with a stale disk device causes "The device already exists" from
        # Incus.  The assertion ensures a silently-failing removal cannot leave
        # devices behind.
        _remove_isholate_devices(name)
        _assert_no_isholate_devices(name)
        started = False

        try:
            _say(f"starting project base '{name}'...", quiet=quiet)
            _incus._run(["incus", "start", name], check=True)
            started = True

            # Retrieve the uid stored in the host base (inherited by the copy).
            uid = _get_stored_uid(name)
            if uid is None:
                uid_result = subprocess.run(
                    ["incus", "exec", name, "--", "id", "-u", username],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                uid = int(uid_result.stdout.strip())

            # Re-create the staging dir (it lives in /run, which is tmpfs and
            # does not persist across container stop/start).
            _incus._run_checked(
                ["incus", "exec", name, "--", "mkdir", "-p", _ISHOLATE_RUN_DIR],
                "create staging directory",
                stdin=subprocess.DEVNULL,
            )

            # Re-mount the ishlib so the ishfiles CLI is available.
            _add_mount(
                name,
                "isholate-ishlib",
                _ISHLIB_ROOT,
                f"{_ISHOLATE_RUN_DIR}/ishlib",
                readonly=True,
            )

            # Apply the project overlay.
            ishfiles_flags: List[str] = list(log_level_to_cli_flags(log_level))
            ishfiles_flags.extend(["--custom-username", username])

            _apply_project_overlay(
                name, username, uid, project_overlay, ishfiles_flags, quiet=quiet
            )

            # Remove host-path mounts before freezing.
            _remove_isholate_devices(name)

            _say(f"stopping and saving project base '{name}'...", quiet=quiet)
            _incus._run(["incus", "stop", name, "--force"], check=False)
            _set_stored_fingerprint(name, combined_fp)

            return name

        except (subprocess.CalledProcessError, RuntimeError):
            if started:
                dev_r = _incus._run(
                    ["incus", "config", "device", "list", name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if dev_r.returncode == 0 and dev_r.stdout.strip():
                    log.info(
                        "devices on '%s' at failure: %s", name, dev_r.stdout.strip()
                    )
                _incus._run(["incus", "stop", name, "--force"], check=False)
                _incus._run(["incus", "delete", name, "--force"], check=False)
            raise


# ---------------------------------------------------------------------------
# Ephemeral container launch
# ---------------------------------------------------------------------------


def _launch_ephemeral_from_base(
    parent_base: str,
    args: Any,
    stored_uid: Optional[int],
    *,
    quiet: bool = False,
    username: str,
    home: Path,
    cwd: Path,
) -> int:
    """Clone *parent_base*, exec into the clone, then stop and delete it.

    Args:
        parent_base: Name of the stopped base container to clone.
        args:        Parsed argparse namespace (name, shell, rw_cwd, ro_cwd,
                     claude, command).
        stored_uid:  UID read from the base's metadata; falls back to a live
                     ``id -u`` lookup inside the ephemeral if None.
        quiet:       Suppress isholate progress messages.
        username:    Host username (already inside the base).
        home:        Host user's home directory.
        cwd:         Host current working directory.

    Returns:
        Exit code from the exec'd command.
    """
    name: str = args.name or generate_name(username)
    started = False

    _say(
        f"creating ephemeral container '{name}' from base '{parent_base}'...",
        quiet=quiet,
    )
    _incus._run(["incus", "copy", parent_base, name], check=True)

    try:
        _say(f"starting container '{name}'...", quiet=quiet)
        _incus._run(["incus", "start", name], check=True)
        started = True

        # Determine container UID; fall back to live lookup if metadata was lost.
        container_uid: int
        if stored_uid is not None:
            container_uid = stored_uid
        else:
            uid_result = subprocess.run(
                ["incus", "exec", name, "--", "id", "-u", username],
                capture_output=True,
                text=True,
                check=True,
            )
            container_uid = int(uid_result.stdout.strip())

        # Bind-mount cwd if requested.
        if args.rw_cwd:
            _add_mount(name, "hostcwd", cwd, str(cwd), shift=True)
        elif args.ro_cwd:
            _add_mount(name, "hostcwd", cwd, str(cwd), readonly=True, shift=True)

        _claude_on = getattr(args, "claude", False)
        _claude_base_on = getattr(args, "claude_base", False)
        if _claude_on:
            _add_claude_mounts(name, home, username, quiet=quiet)
        elif _claude_base_on:
            _install_claude_base_auth(name, home, username, container_uid, quiet=quiet)

        if getattr(args, "no_network", False):
            _apply_network_restrictions(
                name,
                allow_claude=_claude_on or _claude_base_on,
                quiet=quiet,
            )

        exec_cwd = str(cwd) if (args.rw_cwd or args.ro_cwd) else f"/home/{username}"
        exec_cmd = [
            "incus",
            "exec",
            name,
            "--user",
            str(container_uid),
            "--cwd",
            exec_cwd,
            "--env",
            f"HOME=/home/{username}",
            "--env",
            f"USER={username}",
            "--env",
            f"LOGNAME={username}",
            "--",
        ]
        command = args.command
        if command and command[0] == "--":
            command = command[1:]

        if command:
            exec_cmd.extend(command)
            _say(f"running command in '{name}'...", quiet=quiet)
        else:
            exec_cmd.extend(_login_shell_argv(args.shell))
            _say(f"launching {args.shell} as login shell in '{name}'...", quiet=quiet)

        result = _incus._run(exec_cmd, check=False)
        return result.returncode

    finally:
        if started:
            _say(f"stopping and deleting '{name}'...", quiet=quiet)
            _incus._run(["incus", "stop", name, "--force"], check=False)
            _incus._run(["incus", "delete", name, "--force"], check=False)


# ---------------------------------------------------------------------------
# One-shot path (original behaviour; used when --no-cache or no sources)
# ---------------------------------------------------------------------------


def _launch_one_shot(
    args: Any,
    *,
    host_ishfiles_source: Optional[Path],
    project_overlay: Optional[Path],
    log_level: int,
    quiet: bool,
    username: str,
    home: Path,
    cwd: Path,
) -> int:
    """Launch an ephemeral container from the raw image (no persistent bases).

    This replicates the original ``launch_and_exec`` behaviour: create the
    container from scratch, provision it with ishfiles, exec, then delete.

    Args:
        args:                 Parsed argparse namespace.
        host_ishfiles_source: Host ishfiles source tree (pass 1), or None.
        project_overlay:      Project overlay directory (pass 2), or None.
        log_level:            Terminal log level; propagated to the in-container
                              ishfiles invocation as ``--debug``/``-v``/``-q``.
        quiet:                Suppress isholate progress messages.
        username:             Host username.
        home:                 Host home directory.
        cwd:                  Host current working directory.

    Returns:
        Exit code from the exec'd command (or 1 on error).
    """
    name: str = args.name or generate_name(username)
    started = False

    _say(
        f"creating container '{name}' from {args.image} "
        "(may pull the image on first use)...",
        quiet=quiet,
    )
    _incus._run(
        ["incus", "init", args.image, name, "--config", "security.nesting=true"],
        check=True,
    )

    try:
        _say(f"starting container '{name}'...", quiet=quiet)
        try:
            _incus._run(["incus", "start", name], check=True)
            started = True
        except subprocess.CalledProcessError:
            print(
                f"\nContainer failed to start. Fetching logs for '{name}':\n",
                file=sys.stderr,
            )
            _incus._run(["incus", "info", "--show-log", name], check=False)
            print(
                f"\nContainer '{name}' left in place for manual inspection.\n"
                f"Clean up with: incus delete {name} --force",
                file=sys.stderr,
            )
            return 1

        _say(f"creating user '{username}' inside container...", quiet=quiet)
        _incus._run(
            ["incus", "exec", name, "--", "userdel", "-r", "ubuntu"],
            check=False,
        )
        _incus._run(
            ["incus", "exec", name, "--", "useradd", "-m", "-s", args.shell, username],
            check=True,
        )
        uid_result = subprocess.run(
            ["incus", "exec", name, "--", "id", "-u", username],
            capture_output=True,
            text=True,
            check=True,
        )
        container_uid = int(uid_result.stdout.strip())

        if host_ishfiles_source is not None or project_overlay is not None:
            host_config_dir = home / ".config" / "ishfiles"
            _provision(
                name,
                username,
                container_uid,
                host_config_dir if host_config_dir.is_dir() else None,
                host_ishfiles_source,
                project_overlay,
                log_level=log_level,
                quiet=quiet,
            )

        if args.rw_cwd:
            _add_mount(name, "hostcwd", cwd, str(cwd), shift=True)
        elif args.ro_cwd:
            _add_mount(name, "hostcwd", cwd, str(cwd), readonly=True, shift=True)

        _claude_on = getattr(args, "claude", False)
        _claude_base_on = getattr(args, "claude_base", False)
        if _claude_on:
            _add_claude_mounts(name, home, username, quiet=quiet)
        elif _claude_base_on:
            _install_claude_base_auth(name, home, username, container_uid, quiet=quiet)

        if getattr(args, "no_network", False):
            _apply_network_restrictions(
                name,
                allow_claude=_claude_on or _claude_base_on,
                quiet=quiet,
            )

        exec_cwd = str(cwd) if (args.rw_cwd or args.ro_cwd) else f"/home/{username}"
        exec_cmd = [
            "incus",
            "exec",
            name,
            "--user",
            str(container_uid),
            "--cwd",
            exec_cwd,
            "--env",
            f"HOME=/home/{username}",
            "--env",
            f"USER={username}",
            "--env",
            f"LOGNAME={username}",
            "--",
        ]
        command = args.command
        if command and command[0] == "--":
            command = command[1:]

        if command:
            exec_cmd.extend(command)
            _say(f"running command in '{name}'...", quiet=quiet)
        else:
            exec_cmd.extend(_login_shell_argv(args.shell))
            _say(f"launching {args.shell} as login shell in '{name}'...", quiet=quiet)

        result = _incus._run(exec_cmd, check=False)
        return result.returncode

    except subprocess.CalledProcessError as exc:
        sys.stdout.flush()
        sys.stderr.flush()
        print(
            f"\nisholate: provisioning failed — see output above for details.\n"
            f"  Failed command: {' '.join(str(a) for a in exc.cmd)}\n"
            f"  Exit status: {exc.returncode}\n"
            "  Tip: re-run with --debug to stream full debug output from inside the container.",
            file=sys.stderr,
            flush=True,
        )
        if started:
            log_dest = _pull_container_logs(name, f"/home/{username}", quiet=quiet)
            if log_dest is not None:
                print(
                    f"isholate: logs saved to {log_dest}",
                    file=sys.stderr,
                    flush=True,
                )
        return 1

    except RuntimeError:
        return 1

    finally:
        if started:
            _say(f"stopping and deleting '{name}'...", quiet=quiet)
            _incus._run(["incus", "stop", name, "--force"], check=False)
            _incus._run(["incus", "delete", name, "--force"], check=False)


# ---------------------------------------------------------------------------
# Log pull helper
# ---------------------------------------------------------------------------


def _pull_container_logs(
    name: str,
    container_home: str,
    *,
    quiet: bool = False,
) -> Optional[Path]:
    """Pull the ishfiles log directory from a (still-running) container to the host.

    Args:
        name:           Incus container name.
        container_home: Home directory path inside the container.
        quiet:          Suppress isholate's own progress messages.

    Returns:
        Local path where logs were written, or None if pull failed / no logs found.
    """
    log_dir_in_container = f"{container_home}/.local/state/ishfiles/logs"

    check = _incus._run(
        ["incus", "exec", name, "--", "test", "-d", log_dir_in_container],
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )
    if check.returncode != 0:
        return None

    local_log_root = Path.home() / FAILED_LOGS_STATE_DIR
    local_log_root.mkdir(parents=True, exist_ok=True)
    dest = local_log_root / name
    dest.mkdir(parents=True, exist_ok=True)

    result = _incus._run(
        [
            "incus",
            "file",
            "pull",
            "--recursive",
            f"{name}{log_dir_in_container}",
            str(dest),
        ],
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        if not quiet:
            print(
                f"isholate: warning: could not pull logs from container: {result.stderr.strip()}",
                file=sys.stderr,
            )
        return None

    return dest


# ---------------------------------------------------------------------------
# Container discovery (shared by purge / list / stop)
# ---------------------------------------------------------------------------


def _classify_isholate_name(
    name: str, *, safe_user: "Optional[str]" = None
) -> "Optional[tuple[str, str]]":
    """Classify *name* as an isholate container.

    When *safe_user* is given (already sanitised via :func:`_sanitize_for_name`),
    the prefix is matched against the expected canonical form for that user
    and the owner is returned verbatim.  Otherwise a best-effort heuristic is
    used to extract the owner (ambiguous for host-base containers whose image
    tag may contain hyphens — treated as ``"?"`` in that case).

    Returns ``(kind, owner)`` where *kind* is one of ``"host-base"``,
    ``"project-base"``, or ``"ephemeral"``.  Returns ``None`` for names that
    don't look like isholate containers or don't belong to *safe_user*.
    """
    if not name.startswith("isholate-"):
        return None
    rest = name[len("isholate-") :]

    # User-scoped matching uses exact prefixes.
    if safe_user is not None:
        if rest.startswith(f"base-{safe_user}-"):
            return "host-base", safe_user
        if rest.startswith(f"pbase-{safe_user}-"):
            return "project-base", safe_user
        if rest.startswith(f"{safe_user}-"):
            return "ephemeral", safe_user
        return None

    # All-users heuristic (best effort — owner may be approximate for host-base).
    if rest.startswith("base-"):
        tail = rest[len("base-") :]
        # Canonical form: <owner>-<image-tag>. Owner and image-tag can both
        # contain '-', so we cannot recover owner unambiguously. Use the
        # leading segment as a best-effort display value.
        owner = tail.split("-", 1)[0] if "-" in tail else tail
        return "host-base", owner or "?"
    if rest.startswith("pbase-"):
        tail = rest[len("pbase-") :]
        # Canonical form: <owner>-<8-hex>. Strip the trailing hex chunk to
        # recover owner.
        if "-" not in tail:
            return None
        owner = tail.rsplit("-", 1)[0]
        return "project-base", owner or "?"
    # Ephemeral: <owner>-<6-char-suffix>.
    if "-" not in rest:
        return None
    owner = rest.rsplit("-", 1)[0]
    return "ephemeral", owner or "?"


def _find_isholate_containers(
    username: str,
    *,
    include_bases: bool = False,
    all_users: bool = False,
) -> "List[dict]":
    """Return isholate containers known to Incus.

    Calls ``incus list --format=json`` and classifies entries by prefix.  When
    *all_users* is False (the default), only containers owned by *username*
    (after :func:`_sanitize_for_name`) are returned.

    Each returned dict has keys ``name``, ``status``, ``kind``, and ``owner``.
    ``kind`` is one of ``"ephemeral"``, ``"host-base"``, ``"project-base"``.
    ``status`` is passed through verbatim from Incus (e.g. ``"Running"``,
    ``"Stopped"``, ``"Frozen"``).
    """
    safe_user = _sanitize_for_name(username)

    entries = []
    for c in _incus.list_incus_containers():
        name = c.get("name", "")
        classified = _classify_isholate_name(
            name, safe_user=None if all_users else safe_user
        )
        if classified is None:
            continue
        kind, owner = classified
        if kind in ("host-base", "project-base") and not include_bases:
            continue
        entries.append(
            {
                "name": name,
                "status": c.get("status", ""),
                "kind": kind,
                "owner": owner,
            }
        )

    entries.sort(key=lambda e: e["name"])
    return entries


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------


def purge_containers(
    username: str, *, quiet: bool = False, include_bases: bool = False
) -> int:
    """Delete isholate containers belonging to the given username.

    By default only ephemeral containers are deleted; persistent base
    containers are preserved so the cache remains valid.  Pass
    ``include_bases=True`` (via ``--purge --bases``) to also remove them.

    Args:
        username:      The host username whose containers should be purged.
        quiet:         Suppress isholate's own progress messages.
        include_bases: When True, also delete host-base and project-base
                       containers (``isholate-base-*`` and ``isholate-pbase-*``).

    Returns:
        0 if all deletions succeeded, 1 if any failed.
    """
    entries = _find_isholate_containers(username, include_bases=include_bases)
    containers = [e["name"] for e in entries]

    if not containers:
        kind = (
            "isholate containers" if include_bases else "ephemeral isholate containers"
        )
        _say(f"no {kind} found for user '{username}'", quiet=quiet)
        return 0

    failed = False
    for name in containers:
        _say(f"deleting {name}...", quiet=quiet)
        r = _incus._run(["incus", "delete", name, "--force"], check=False)
        if r.returncode != 0:
            print(f"isholate: failed to delete {name}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


_KIND_LABELS = {
    "ephemeral": "ephemeral",
    "host-base": "host-base",
    "project-base": "project-base",
}


def list_containers(
    username: str,
    *,
    all_users: bool = False,
    running_only: bool = False,
    include_bases: bool = True,
) -> int:
    """Print a table of isholate containers to stdout.

    The table is the command's product output (per the logging convention),
    so it goes through :func:`print`.  When no containers match the filters,
    the function logs an INFO message and prints nothing.

    Args:
        username:      Host username to filter by (ignored when *all_users*).
        all_users:     When True, show containers for all users and add an
                       ``USER`` column.
        running_only:  When True, hide containers whose status is not
                       ``Running``.
        include_bases: When False, hide host-base and project-base
                       containers (only show ephemerals).

    Returns:
        ``0`` on success.
    """
    entries = _find_isholate_containers(
        username, include_bases=include_bases, all_users=all_users
    )

    if running_only:
        entries = [e for e in entries if e["status"].lower() == "running"]

    if not entries:
        log.info("no isholate containers found")
        return 0

    show_user = all_users
    columns: List[tuple] = [
        ("NAME", lambda e: e["name"]),
        ("STATE", lambda e: e["status"] or "-"),
        ("KIND", lambda e: _KIND_LABELS.get(e["kind"], e["kind"])),
    ]
    if show_user:
        columns.append(("USER", lambda e: e["owner"]))

    # Compute column widths.
    widths = []
    for header, fn in columns:
        w = len(header)
        for e in entries:
            w = max(w, len(fn(e)))
        widths.append(w)

    def _format_row(cells: List[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            if i == len(cells) - 1:
                parts.append(cell)
            else:
                parts.append(cell.ljust(widths[i]))
        return "  ".join(parts)

    print(_format_row([header for header, _ in columns]))
    for e in entries:
        print(_format_row([fn(e) for _, fn in columns]))

    return 0


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


def stop_containers(
    username: str,
    names: "Optional[List[str]]" = None,
    *,
    include_bases: bool = False,
) -> int:
    """Stop running isholate containers.

    With explicit *names*, each name is resolved against Incus state.
    Containers that don't exist are reported as errors; already-stopped
    containers are a no-op logged at INFO.

    Without *names*, every running ephemeral belonging to *username* is
    stopped.  When *include_bases* is True, running host-base and
    project-base containers for *username* are also stopped.

    Args:
        username:      Host username (used when *names* is empty, and to
                       produce the "no containers" message).
        names:         Optional explicit container names to stop.
        include_bases: When *names* is empty, also stop running bases.

    Returns:
        ``0`` if every targeted container stopped cleanly (or was already
        stopped); ``1`` if any stop failed or any requested name was unknown.
    """
    # Always look up full state so we can distinguish unknown / already-stopped.
    entries = _find_isholate_containers(username, include_bases=True)
    by_name = {e["name"]: e for e in entries}

    if names:
        targets: List[str] = []
        failed = False
        for requested in names:
            e = by_name.get(requested)
            if e is None:
                log.error("no such isholate container: %s", requested)
                failed = True
                continue
            if e["status"].lower() != "running":
                log.info("%s is already stopped", requested)
                continue
            targets.append(requested)
    else:
        kinds = (
            {"ephemeral", "host-base", "project-base"}
            if include_bases
            else {"ephemeral"}
        )
        targets = [
            e["name"]
            for e in entries
            if e["kind"] in kinds and e["status"].lower() == "running"
        ]
        failed = False
        if not targets:
            descr = (
                "isholate containers"
                if include_bases
                else "ephemeral isholate containers"
            )
            log.info("no running %s found for user '%s'", descr, username)
            return 0

    for name in targets:
        log.info("stopping %s...", name)
        r = _incus._run(["incus", "stop", name, "--force"], check=False)
        if r.returncode != 0:
            log.error("failed to stop %s", name)
            failed = True

    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def launch_and_exec(
    args: Any,
    *,
    host_ishfiles_source: Optional[Path] = None,
    project_overlay: Optional[Path] = None,
    project_root: Optional[Path] = None,
) -> int:
    """Launch an Incus container and exec into it as the host user.

    Orchestrates the three-tier caching model when ishfiles sources are
    available and ``--no-cache`` is not set.  Falls back to a one-shot
    ephemeral container otherwise.

    Lifecycle (cached path):
    1. :func:`ensure_host_base` — build or reuse the host-ishfiles base.
    2. :func:`ensure_project_base` — build or reuse the project-overlay base
       (only when a project overlay is present).
    3. :func:`_launch_ephemeral_from_base` — clone the best available base,
       add bind mounts, exec, stop and delete.

    One-shot path (no sources, or ``--no-cache``):
    :func:`_launch_one_shot` — original behaviour.

    Args:
        args: Parsed argparse namespace with fields: name, image, shell,
              rw_cwd, ro_cwd, command, verbose, debug, quiet, no_cache,
              rebuild_base, rebuild_project_base.
        host_ishfiles_source: Host ishfiles source tree (pass 1).
            ``None`` skips the host-base layer.
        project_overlay: Project ``.ishlib/ishfiles/`` directory (pass 2).
            ``None`` skips the project-base layer.
        project_root: Project root directory (the dir containing
            ``.ishlib/``). Required only when building a cached
            project-base from a parent base; used for stable
            project-base container naming.

    Returns:
        Exit code from the exec'd command.
    """
    username, home, cwd = get_host_user_info()

    log_level = log_level_from_args(args)
    quiet: bool = bool(getattr(args, "quiet", False))
    no_cache: bool = bool(getattr(args, "no_cache", False))
    rebuild_base: bool = bool(getattr(args, "rebuild_base", False))
    rebuild_project_base: bool = (
        bool(getattr(args, "rebuild_project_base", False)) or rebuild_base
    )

    # One-shot path: no caching, original behaviour.
    if no_cache or (host_ishfiles_source is None and project_overlay is None):
        return _launch_one_shot(
            args,
            host_ishfiles_source=host_ishfiles_source,
            project_overlay=project_overlay,
            log_level=log_level,
            quiet=quiet,
            username=username,
            home=home,
            cwd=cwd,
        )

    # --- Cached path ---

    parent_base: Optional[str] = None
    stored_uid: Optional[int] = None

    if host_ishfiles_source is not None:
        host_config_dir = home / ".config" / "ishfiles"
        try:
            parent_base = ensure_host_base(
                args.image,
                username,
                host_ishfiles_source,
                host_config_dir if host_config_dir.is_dir() else None,
                args.shell,
                log_level=log_level,
                quiet=quiet,
                rebuild=rebuild_base,
            )
            stored_uid = _get_stored_uid(parent_base)
        except (subprocess.CalledProcessError, RuntimeError) as exc:
            sys.stdout.flush()
            sys.stderr.flush()
            if isinstance(exc, subprocess.CalledProcessError):
                print(
                    "\nisholate: host-base provisioning failed — see output above.\n"
                    "  Tip: re-run with --debug to stream full debug output.",
                    file=sys.stderr,
                    flush=True,
                )
            return 1

    if project_overlay is not None:
        if parent_base is not None:
            # Derive the project base from the host base.
            try:
                if project_root is None:
                    raise ValueError(
                        "project_root is required when project_overlay is set"
                    )
                parent_base = ensure_project_base(
                    parent_base,
                    username,
                    project_overlay,
                    project_root=project_root,
                    log_level=log_level,
                    quiet=quiet,
                    rebuild=rebuild_project_base,
                )
                stored_uid = _get_stored_uid(parent_base)
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                sys.stdout.flush()
                sys.stderr.flush()
                if isinstance(exc, subprocess.CalledProcessError):
                    print(
                        "\nisholate: project-base provisioning failed — see output above.\n"
                        "  Tip: re-run with --debug to stream full debug output.",
                        file=sys.stderr,
                        flush=True,
                    )
                return 1
        else:
            # No host base (--no-host-ishfiles) but project overlay requested.
            # Fall back to one-shot so the overlay is still applied.
            return _launch_one_shot(
                args,
                host_ishfiles_source=None,
                project_overlay=project_overlay,
                log_level=log_level,
                quiet=quiet,
                username=username,
                home=home,
                cwd=cwd,
            )

    if parent_base is not None:
        return _launch_ephemeral_from_base(
            parent_base,
            args,
            stored_uid,
            quiet=quiet,
            username=username,
            home=home,
            cwd=cwd,
        )

    # Should not be reached (no-source case is handled above), but guard anyway.
    return _launch_one_shot(
        args,
        host_ishfiles_source=None,
        project_overlay=None,
        log_level=log_level,
        quiet=quiet,
        username=username,
        home=home,
        cwd=cwd,
    )
