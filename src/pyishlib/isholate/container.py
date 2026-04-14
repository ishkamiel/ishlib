#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

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
import json
import os
import random
import re
import socket
import string
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

from .config import FAILED_LOGS_STATE_DIR

# Root of the ishlib checkout — used to mount the ishfiles CLI into containers.
# Path: container.py -> isholate/ -> pyishlib/ -> src/ -> ishlib/
_ISHLIB_ROOT: Path = Path(__file__).resolve().parents[3]

# Path inside the container where isholate mounts its helper files.
_ISHOLATE_RUN_DIR = "/run/isholate"

# Incus user-data keys for metadata stored on persistent bases.
_META_SOURCE_HASH = "user.isholate.source_hash"
_META_UID = "user.isholate.uid"


def _say(msg: str, *, quiet: bool = False) -> None:
    """Print an isholate progress message to stderr unless *quiet*."""
    if not quiet:
        print(f"isholate: {msg}", file=sys.stderr, flush=True)


def get_host_user_info() -> "tuple[str, Path, Path]":
    """Return (username, home, cwd) for the current host user."""
    username = os.environ.get("USER") or os.environ.get("LOGNAME") or "user"
    home = Path.home()
    cwd = Path.cwd()
    return username, home, cwd


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
# Low-level Incus wrappers
# ---------------------------------------------------------------------------


def _run(cmd: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run an incus command. Pass check=True to raise on failure."""
    return subprocess.run(cmd, **kwargs)


def _run_checked(
    cmd: List[str], step: str, **kwargs: Any
) -> subprocess.CompletedProcess:
    """Run *cmd* with ``check=True``; on failure flush output and re-raise with a
    labelled message so the user knows which provisioning step broke.

    Args:
        cmd:  Command to run.
        step: Human-readable label for this step (shown on failure).
    """
    kwargs["check"] = True
    try:
        return _run(cmd, **kwargs)
    except subprocess.CalledProcessError as exc:
        sys.stdout.flush()
        sys.stderr.flush()
        print(
            f"\nisholate: {step} failed (exit {exc.returncode})",
            file=sys.stderr,
            flush=True,
        )
        raise


# ---------------------------------------------------------------------------
# Container state helpers
# ---------------------------------------------------------------------------


def _container_exists(name: str) -> bool:
    """Return True if an Incus container with *name* exists (any state)."""
    r = _run(["incus", "info", name], capture_output=True, check=False)
    return r.returncode == 0


def _get_stored_fingerprint(name: str) -> Optional[str]:
    """Read the source fingerprint stored on a base container's metadata."""
    r = _run(
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
    _run(
        ["incus", "config", "set", name, _META_SOURCE_HASH, fingerprint],
        check=True,
    )


def _get_stored_uid(name: str) -> Optional[int]:
    """Read the container user UID from a base container's metadata."""
    r = _run(
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
    _run(
        ["incus", "config", "set", name, _META_UID, str(uid)],
        check=True,
    )


def _remove_isholate_devices(name: str) -> None:
    """Remove all disk devices whose names start with ``isholate-`` from *name*.

    Called before stopping a base container so that it carries no stale
    host-path bind-mount references.
    """
    r = _run(
        ["incus", "config", "device", "list", name, "--format=json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return
    try:
        devices = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return
    # Incus returns a dict keyed by device name.
    if not isinstance(devices, dict):
        return
    for device_name in list(devices.keys()):
        if device_name.startswith("isholate-"):
            _run(
                ["incus", "config", "device", "remove", name, device_name],
                check=False,
            )


def _source_fingerprint(source: Path) -> str:
    """Compute a reproducible fingerprint for a source tree.

    Uses ``git rev-parse HEAD`` + ``git status --porcelain`` when the path
    is inside a git repo (fast).  Falls back to a recursive content hash for
    non-git trees.
    """
    try:
        head = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(source), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        raw = f"{head}\n{status}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Non-git or git not available: hash the file tree.
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


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def _network_preflight(name: str, *, verbose: int = 0, quiet: bool = False) -> None:
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
        r = _run(
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
        if verbose:
            print(
                "isholate: ping not found in image — skipping network pre-flight",
                file=sys.stderr,
            )
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

    if verbose:
        print("isholate: network pre-flight ok", file=sys.stderr)


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


def _add_ro_device(
    name: str, device_name: str, source: Path, container_path: str
) -> None:
    """Add a read-only disk device to a running container."""
    _run(
        [
            "incus",
            "config",
            "device",
            "add",
            name,
            device_name,
            "disk",
            f"source={source}",
            f"path={container_path}",
            "readonly=true",
        ],
        check=True,
    )


# ---------------------------------------------------------------------------
# Provisioning helpers (shared by both one-shot and base-creation paths)
# ---------------------------------------------------------------------------


def _bootstrap_base(name: str, *, verbose: int = 0, quiet: bool = False) -> None:
    """Bootstrap a freshly-started container: staging dir, ishlib mount, apt.

    Sets up the ``/run/isholate`` staging area, mounts the ishlib checkout,
    probes network connectivity, and installs ``python3`` + ``sudo`` via apt
    (or dnf on Fedora-family images).  Called once during host-base creation.

    Args:
        name:    Container name.
        verbose: 0 = quiet apt; 1 = stream output; 2 = also --debug.
        quiet:   Suppress isholate's own progress messages.
    """
    # Create the /run/isholate staging directory.
    _run_checked(
        ["incus", "exec", name, "--", "mkdir", "-p", _ISHOLATE_RUN_DIR],
        "create staging directory",
        stdin=subprocess.DEVNULL,
    )

    # Mount ishlib checkout so ishfiles CLI is reachable without pip.
    _add_ro_device(
        name,
        "isholate-ishlib",
        _ISHLIB_ROOT,
        f"{_ISHOLATE_RUN_DIR}/ishlib",
    )

    _say(
        "installing base packages in container (python3, sudo); "
        "this can take a minute on first run...",
        quiet=quiet,
    )
    _network_preflight(name, verbose=verbose, quiet=quiet)

    # Force apt to use IPv4.
    _run(
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
        _run(
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

    apt_update = "apt-get update" if verbose else "apt-get update -qq"
    apt_install = (
        "apt-get install -y --no-install-recommends python3 sudo"
        if verbose
        else "apt-get install -qq -y --no-install-recommends python3 sudo"
    )
    _run_checked(
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
            "dnf install -y python3 sudo; "
            "fi",
        ],
        "bootstrap (python3 + sudo install)",
        stdin=subprocess.DEVNULL,
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

    _add_ro_device(
        name,
        "isholate-ishsrc",
        host_source,
        f"{_ISHOLATE_RUN_DIR}/ishsrc",
    )
    pass1_cmd = [
        "incus",
        "exec",
        name,
        "--env",
        f"HOME={container_home}",
        "--",
        "python3",
        ishfiles_bin,
        *ishfiles_flags,
        "--home",
        container_home,
        "-s",
        f"{_ISHOLATE_RUN_DIR}/ishsrc",
    ]
    if host_config_dir is not None and host_config_dir.is_dir():
        _add_ro_device(
            name,
            "isholate-ishconf",
            host_config_dir,
            f"{_ISHOLATE_RUN_DIR}/ishconf",
        )
        pass1_cmd += ["-c", f"{_ISHOLATE_RUN_DIR}/ishconf/config.toml"]
    pass1_cmd += ["apply", "--isholate", "--yes"]
    _run_checked(
        pass1_cmd,
        "ishfiles apply (pass 1: host dotfiles)",
        stdin=subprocess.DEVNULL,
    )

    _say("finalising ownership of container home...", quiet=quiet)
    _run_checked(
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

    _add_ro_device(
        name,
        "isholate-overlay",
        project_overlay,
        f"{_ISHOLATE_RUN_DIR}/ishsrc-project",
    )
    _run_checked(
        [
            "incus",
            "exec",
            name,
            "--env",
            f"HOME={container_home}",
            "--",
            "python3",
            ishfiles_bin,
            *ishfiles_flags,
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

    _say("finalising ownership of container home...", quiet=quiet)
    _run_checked(
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
    verbose: int = 0,
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
        verbose:         Verbosity level.
        quiet:           Suppress isholate progress messages.
    """
    ishfiles_flags: List[str] = []
    if verbose >= 2:
        ishfiles_flags.append("--debug")
    elif verbose >= 1:
        ishfiles_flags.append("-v")

    _bootstrap_base(name, verbose=verbose, quiet=quiet)

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
    verbose: int = 0,
    quiet: bool = False,
    rebuild: bool = False,
) -> str:
    """Return the name of a stopped, up-to-date host-ishfiles base container.

    Builds the base on first use or when the source fingerprint changes.
    If *rebuild* is True the base is always rebuilt regardless of fingerprint.

    The base container is left **stopped** so it can be cloned cheaply via
    ``incus copy``.  All host-path bind mounts are removed before stopping.

    Args:
        image:           Incus image (e.g. ``"images:ubuntu/24.04"``).
        username:        Host username (mirrored inside the container).
        host_source:     Host ishfiles source tree.
        host_config_dir: Optional ``~/.config/ishfiles/`` directory.
        shell:           Login shell to create the user with.
        verbose:         Verbosity level.
        quiet:           Suppress isholate progress messages.
        rebuild:         Force rebuild even if fingerprint matches.

    Returns:
        Container name of the (stopped) host base.

    Raises:
        subprocess.CalledProcessError: if any Incus command fails.
        RuntimeError: if the network preflight fails.
    """
    name = _host_base_name(username, image)
    fingerprint = _source_fingerprint(host_source)

    # Check whether an up-to-date base already exists.
    if not rebuild and _container_exists(name):
        stored = _get_stored_fingerprint(name)
        if stored == fingerprint:
            _say(f"reusing host base '{name}'", quiet=quiet)
            return name
        _say(
            f"host base '{name}' is stale (source changed) — rebuilding...", quiet=quiet
        )
        _run(["incus", "delete", name, "--force"], check=False)
    elif rebuild and _container_exists(name):
        _say(f"rebuilding host base '{name}' (--rebuild requested)...", quiet=quiet)
        _run(["incus", "delete", name, "--force"], check=False)

    _say(
        f"creating host base '{name}' from {image} "
        "(may pull the image on first use)...",
        quiet=quiet,
    )
    _run(["incus", "init", image, name], check=True)
    started = False

    try:
        _say(f"starting host base '{name}'...", quiet=quiet)
        _run(["incus", "start", name], check=True)
        started = True

        # Create the container user matching the host username.
        _say(f"creating user '{username}' in host base...", quiet=quiet)
        _run(
            ["incus", "exec", name, "--", "userdel", "-r", "ubuntu"],
            check=False,
        )
        _run(
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
        ishfiles_flags: List[str] = []
        if verbose >= 2:
            ishfiles_flags.append("--debug")
        elif verbose >= 1:
            ishfiles_flags.append("-v")

        _bootstrap_base(name, verbose=verbose, quiet=quiet)
        _apply_host_ishfiles(
            name,
            username,
            uid,
            host_source,
            host_config_dir,
            ishfiles_flags,
            quiet=quiet,
        )

        # Remove host-path mounts before freezing the base.
        _remove_isholate_devices(name)

        # Stop and persist the fingerprint.
        _say(f"stopping and saving host base '{name}'...", quiet=quiet)
        _run(["incus", "stop", name, "--force"], check=False)
        _set_stored_fingerprint(name, fingerprint)

        return name

    except (subprocess.CalledProcessError, RuntimeError):
        if started:
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)
        raise


def ensure_project_base(
    host_base: str,
    username: str,
    project_overlay: Path,
    *,
    project_root: Path,
    verbose: int = 0,
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
        verbose:          Verbosity level.
        quiet:            Suppress isholate progress messages.
        rebuild:          Force rebuild even if fingerprint matches.

    Returns:
        Container name of the (stopped) project base.

    Raises:
        subprocess.CalledProcessError: if any Incus command fails.
        RuntimeError: if provisioning raises.
    """
    name = _project_base_name(username, project_root)

    # Combine host-base fingerprint with the overlay content fingerprint so
    # that rebuilding the host base automatically cascades to the project base.
    host_fp = _get_stored_fingerprint(host_base) or ""
    overlay_fp = _source_fingerprint(project_overlay)
    combined_fp = f"{host_fp}:{overlay_fp}"

    if not rebuild and _container_exists(name):
        stored = _get_stored_fingerprint(name)
        if stored == combined_fp:
            _say(f"reusing project base '{name}'", quiet=quiet)
            return name
        _say(
            f"project base '{name}' is stale (overlay changed) — rebuilding...",
            quiet=quiet,
        )
        _run(["incus", "delete", name, "--force"], check=False)
    elif rebuild and _container_exists(name):
        _say(f"rebuilding project base '{name}' (--rebuild requested)...", quiet=quiet)
        _run(["incus", "delete", name, "--force"], check=False)

    _say(f"creating project base '{name}' from host base '{host_base}'...", quiet=quiet)
    _run(["incus", "copy", host_base, name], check=True)
    started = False

    try:
        _say(f"starting project base '{name}'...", quiet=quiet)
        _run(["incus", "start", name], check=True)
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
        _run_checked(
            ["incus", "exec", name, "--", "mkdir", "-p", _ISHOLATE_RUN_DIR],
            "create staging directory",
            stdin=subprocess.DEVNULL,
        )

        # Re-mount the ishlib so the ishfiles CLI is available.
        _add_ro_device(
            name,
            "isholate-ishlib",
            _ISHLIB_ROOT,
            f"{_ISHOLATE_RUN_DIR}/ishlib",
        )

        # Apply the project overlay.
        ishfiles_flags: List[str] = []
        if verbose >= 2:
            ishfiles_flags.append("--debug")
        elif verbose >= 1:
            ishfiles_flags.append("-v")

        _apply_project_overlay(
            name, username, uid, project_overlay, ishfiles_flags, quiet=quiet
        )

        # Remove host-path mounts before freezing.
        _remove_isholate_devices(name)

        _say(f"stopping and saving project base '{name}'...", quiet=quiet)
        _run(["incus", "stop", name, "--force"], check=False)
        _set_stored_fingerprint(name, combined_fp)

        return name

    except (subprocess.CalledProcessError, RuntimeError):
        if started:
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)
        raise


# ---------------------------------------------------------------------------
# Ephemeral container launch
# ---------------------------------------------------------------------------


def _launch_ephemeral_from_base(
    parent_base: str,
    args: Any,
    stored_uid: Optional[int],
    *,
    verbose: int = 0,
    quiet: bool = False,
    username: str,
    cwd: Path,
) -> int:
    """Clone *parent_base*, exec into the clone, then stop and delete it.

    Args:
        parent_base: Name of the stopped base container to clone.
        args:        Parsed argparse namespace (name, shell, rw_cwd, ro_cwd, command).
        stored_uid:  UID read from the base's metadata; falls back to a live
                     ``id -u`` lookup inside the ephemeral if None.
        verbose:     Verbosity level.
        quiet:       Suppress isholate progress messages.
        username:    Host username (already inside the base).
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
    _run(["incus", "copy", parent_base, name], check=True)

    try:
        _say(f"starting container '{name}'...", quiet=quiet)
        _run(["incus", "start", name], check=True)
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
            _run(
                [
                    "incus",
                    "config",
                    "device",
                    "add",
                    name,
                    "hostcwd",
                    "disk",
                    f"source={cwd}",
                    f"path={cwd}",
                    "shift=true",
                ],
                check=True,
            )
        elif args.ro_cwd:
            _run(
                [
                    "incus",
                    "config",
                    "device",
                    "add",
                    name,
                    "hostcwd",
                    "disk",
                    f"source={cwd}",
                    f"path={cwd}",
                    "readonly=true",
                    "shift=true",
                ],
                check=True,
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
            exec_cmd.append(args.shell)
            _say(f"launching {args.shell} in '{name}'...", quiet=quiet)

        result = _run(exec_cmd, check=False)
        return result.returncode

    finally:
        if started:
            _say(f"stopping and deleting '{name}'...", quiet=quiet)
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)


# ---------------------------------------------------------------------------
# One-shot path (original behaviour; used when --no-cache or no sources)
# ---------------------------------------------------------------------------


def _launch_one_shot(
    args: Any,
    *,
    host_ishfiles_source: Optional[Path],
    project_overlay: Optional[Path],
    verbose: int,
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
        verbose:              Verbosity level.
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
    _run(["incus", "init", args.image, name], check=True)

    try:
        _say(f"starting container '{name}'...", quiet=quiet)
        try:
            _run(["incus", "start", name], check=True)
            started = True
        except subprocess.CalledProcessError:
            print(
                f"\nContainer failed to start. Fetching logs for '{name}':\n",
                file=sys.stderr,
            )
            _run(["incus", "info", "--show-log", name], check=False)
            print(
                f"\nContainer '{name}' left in place for manual inspection.\n"
                f"Clean up with: incus delete {name} --force",
                file=sys.stderr,
            )
            return 1

        _say(f"creating user '{username}' inside container...", quiet=quiet)
        _run(
            ["incus", "exec", name, "--", "userdel", "-r", "ubuntu"],
            check=False,
        )
        _run(
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
                verbose=verbose,
                quiet=quiet,
            )

        if args.rw_cwd:
            _run(
                [
                    "incus",
                    "config",
                    "device",
                    "add",
                    name,
                    "hostcwd",
                    "disk",
                    f"source={cwd}",
                    f"path={cwd}",
                    "shift=true",
                ],
                check=True,
            )
        elif args.ro_cwd:
            _run(
                [
                    "incus",
                    "config",
                    "device",
                    "add",
                    name,
                    "hostcwd",
                    "disk",
                    f"source={cwd}",
                    f"path={cwd}",
                    "readonly=true",
                    "shift=true",
                ],
                check=True,
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
            exec_cmd.append(args.shell)
            _say(f"launching {args.shell} in '{name}'...", quiet=quiet)

        result = _run(exec_cmd, check=False)
        return result.returncode

    except subprocess.CalledProcessError as exc:
        sys.stdout.flush()
        sys.stderr.flush()
        print(
            f"\nisholate: provisioning failed — see output above for details.\n"
            f"  Failed command: {' '.join(str(a) for a in exc.cmd)}\n"
            f"  Exit status: {exc.returncode}\n"
            "  Tip: re-run with -vv to stream full debug output from inside the container.",
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
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)


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

    check = _run(
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

    result = _run(
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
# Purge
# ---------------------------------------------------------------------------


def purge_containers(
    username: str, *, quiet: bool = False, include_bases: bool = False
) -> int:
    """Delete isholate containers belonging to the given username.

    By default only ephemeral containers are deleted; persistent base
    containers are preserved so the cache remains valid.  Pass
    ``include_bases=True`` (via ``--purge-bases``) to also remove them.

    Args:
        username:      The host username whose containers should be purged.
        quiet:         Suppress isholate's own progress messages.
        include_bases: When True, also delete host-base and project-base
                       containers (``isholate-base-*`` and ``isholate-pbase-*``).

    Returns:
        0 if all deletions succeeded, 1 if any failed.
    """
    safe_user = _sanitize_for_name(username)
    ephemeral_prefix = f"isholate-{safe_user}-"
    host_base_prefix = f"isholate-base-{safe_user}-"
    pbase_prefix = f"isholate-pbase-{safe_user}-"

    result = subprocess.run(
        ["incus", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )

    all_names = [c["name"] for c in json.loads(result.stdout)]

    containers = []
    for n in all_names:
        if n.startswith(host_base_prefix) or n.startswith(pbase_prefix):
            if include_bases:
                containers.append(n)
        elif n.startswith(ephemeral_prefix):
            containers.append(n)

    if not containers:
        kind = (
            "isholate containers" if include_bases else "ephemeral isholate containers"
        )
        _say(f"no {kind} found for user '{username}'", quiet=quiet)
        return 0

    failed = False
    for name in containers:
        _say(f"deleting {name}...", quiet=quiet)
        r = _run(["incus", "delete", name, "--force"], check=False)
        if r.returncode != 0:
            print(f"isholate: failed to delete {name}", file=sys.stderr)
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
              rw_cwd, ro_cwd, command, verbose, quiet, no_cache,
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

    verbose: int = int(getattr(args, "verbose", 0) or 0)
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
            verbose=verbose,
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
                verbose=verbose,
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
                    "  Tip: re-run with -vv to stream full debug output.",
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
                    verbose=verbose,
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
                        "  Tip: re-run with -vv to stream full debug output.",
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
                verbose=verbose,
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
            verbose=verbose,
            quiet=quiet,
            username=username,
            cwd=cwd,
        )

    # Should not be reached (no-source case is handled above), but guard anyway.
    return _launch_one_shot(
        args,
        host_ishfiles_source=None,
        project_overlay=None,
        verbose=verbose,
        quiet=quiet,
        username=username,
        home=home,
        cwd=cwd,
    )
