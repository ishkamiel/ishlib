#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
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
import shutil
import socket
import string
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

import logging

from ..environment import detect_distro
from .config import FAILED_LOGS_STATE_DIR

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


def _incus_install_hint() -> str:
    """Return a distro-aware hint for installing the ``incus`` package."""
    distro = detect_distro()
    if distro == "debian":
        return (
            "Install incus:\n"
            "  sudo apt install incus\n"
            "(On older Ubuntu releases you may need the zabbly repository:\n"
            "  https://github.com/zabbly/incus)"
        )
    if distro == "fedora":
        return "Install incus:\n  sudo dnf install incus incus-tools"
    return (
        "Install incus following the instructions at\n"
        "  https://linuxcontainers.org/incus/"
    )


def _check_incus_available() -> Optional[str]:
    """Probe the incus daemon and return setup guidance on failure.

    Returns ``None`` when incus is installed and the daemon is reachable by
    the current user via a successful ``incus info`` probe.  Otherwise
    returns a multi-line, user-facing message (with the ``isholate:`` prefix
    already applied) describing what to do next.

    The probe is deliberately cheap — a single ``incus info`` invocation
    with a short timeout and no further output inspection — so the healthy
    path adds negligible overhead.
    """
    if shutil.which("incus") is None:
        return (
            "isholate: error: the 'incus' command was not found on PATH.\n"
            f"{_incus_install_hint()}\n"
            "After installing, run 'sudo incus admin init' and add your user\n"
            "to the 'incus-admin' group."
        )

    try:
        result = subprocess.run(
            ["incus", "info"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (
            f"isholate: error: failed to run 'incus info': {exc}\n"
            "Make sure the incus daemon is installed and running."
        )

    if result.returncode == 0:
        return None

    stderr = (result.stderr or "").strip()
    lowered = stderr.lower()
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "$USER"

    # Permission / socket access — user not in the incus(-admin) group.
    permission_markers = (
        "permission denied",
        "permission is denied",
        "access denied",
        "forbidden",
    )
    if any(marker in lowered for marker in permission_markers):
        return (
            "isholate: error: cannot talk to the incus daemon (permission denied).\n"
            "Your user is probably not in the 'incus-admin' group.\n"
            "Fix it with:\n"
            f"  sudo usermod -aG incus-admin {user}\n"
            "  newgrp incus-admin   # or log out and back in\n"
            "(Some distros use the 'incus' group instead of 'incus-admin'.)\n"
            f"Raw error from incus:\n  {stderr or '(no stderr output)'}"
        )

    # Daemon not initialized yet.
    init_markers = (
        "not initialized",
        "no storage pool",
        "no storage pools",
        "no profiles",
        "no such file or directory",
        "connection refused",
        "cannot connect",
        "connect: ",
    )
    if any(marker in lowered for marker in init_markers):
        return (
            "isholate: error: the incus daemon is not ready.\n"
            "Run the one-time setup:\n"
            "  sudo incus admin init           # interactive\n"
            "  sudo incus admin init --minimal # non-interactive defaults\n"
            "If the daemon is not running, start it with:\n"
            "  sudo systemctl enable --now incus\n"
            f"Raw error from incus:\n  {stderr or '(no stderr output)'}"
        )

    # Unknown failure — surface the raw error so the user can act on it.
    return (
        "isholate: error: 'incus info' failed "
        f"(exit {result.returncode}).\n"
        f"Raw error from incus:\n  {stderr or '(no stderr output)'}"
    )


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
        log.error("%s failed (exit %d)", step, exc.returncode)
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
    r = _run(
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
        _run(
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
    r = _run(
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
    _run(cmd, check=True)


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


def _add_claude_mounts(
    name: str, home: Path, username: str, *, quiet: bool = False
) -> None:
    """Mount the host's Claude config (``~/.claude/`` and ``~/.claude.json``).

    Adds read-write disk devices with ``shift=true`` so the in-container user
    can read and write the host user's Claude credentials and state.  Either
    source can be missing; only existing paths are mounted.

    Args:
        name:     Incus container name.
        home:     Host user's home directory.
        username: Container username (used to derive the in-container path).
        quiet:    Suppress isholate's own progress messages.
    """
    mounted: List[str] = []

    if (home / ".claude").is_dir() and _add_home_mount(
        name, "isholate-claude", home, ".claude", username, shift=True
    ):
        mounted.append(str(home / ".claude"))

    if (home / ".claude.json").is_file() and _add_home_mount(
        name, "isholate-claude-json", home, ".claude.json", username, shift=True
    ):
        mounted.append(str(home / ".claude.json"))

    if mounted:
        _say(f"exposing host Claude config: {', '.join(mounted)}", quiet=quiet)
    else:
        _say(
            "warning: --claude requested but no host Claude config found "
            "(~/.claude or ~/.claude.json)",
            quiet=quiet,
        )


def _add_claude_base_mounts(
    name: str, home: Path, username: str, *, quiet: bool = False
) -> None:
    """Mount only ``~/.claude/.credentials.json`` read-write with shift=true.

    Args:
        name:     Incus container name.
        home:     Host user's home directory.
        username: Container username (used to derive the in-container path).
        quiet:    Suppress isholate's own progress messages.
    """
    rel = ".claude/.credentials.json"
    if (home / rel).is_file() and _add_home_mount(
        name, "isholate-claude-cred", home, rel, username, shift=True
    ):
        _say(f"exposing host Claude credentials: {home / rel}", quiet=quiet)
    else:
        _say(
            "warning: --claude-base requested but ~/.claude/.credentials.json not found",
            quiet=quiet,
        )


# ---------------------------------------------------------------------------
# Network isolation
# ---------------------------------------------------------------------------

# Domain suffixes the Claude CLI needs to reach when running inside a
# locked-down container.  The bridge's dnsmasq forwards queries for these
# domains (and all their subdomains) to _CLAUDE_DNS_UPSTREAM; everything
# else returns NXDOMAIN via the ``local=/#/`` catch-all.
_CLAUDE_ALLOW_DOMAINS = (
    "anthropic.com",  # api., console., statsig., auth fronts
    "claude.ai",  # OAuth redirect target
    "statsig.com",  # feature flags / analytics
    "statsigapi.net",  # Statsig events endpoint
    "sentry.io",  # covers *.ingest.*.sentry.io too
)

# Incus managed network used when --no-network --claude is in effect.
# Created on first use and reused across runs.  The bridge owns its own
# FORWARD policy (ipv4.firewall=false tells Incus not to auto-generate
# rules for it) — host-side iptables + ipset enforce the allowlist at the
# packet level so a malicious process inside the container cannot bypass
# DNS filtering by hard-coding IPs.
_CLAUDE_NETWORK_NAME = "isholate-claude"

# Upstream DNS server the bridge forwards allowlisted queries to.  A public
# resolver is used deliberately so the setup does not depend on the host's
# own resolver configuration.
_CLAUDE_DNS_UPSTREAM = "1.1.1.1"

# Host-side firewall state names.  The ipset is populated by the bridge's
# dnsmasq via the ``ipset=`` directive on every DNS lookup of an
# allowlisted domain; the iptables chain gates FORWARD against it so only
# IPs dnsmasq has just resolved can receive packets on port 443.
_CLAUDE_IPSET_NAME = "isholate-claude-allowed"
_CLAUDE_IPTABLES_CHAIN = "ISHOLATE-CLAUDE"

# Where the persistent apply script and systemd unit are installed.  The
# systemd unit runs the apply script on boot so rules survive reboots
# without further sudo prompts.
_CLAUDE_FIREWALL_APPLY_SCRIPT = "/usr/local/libexec/isholate-claude-firewall"
_CLAUDE_FIREWALL_SYSTEMD_UNIT = "/etc/systemd/system/isholate-claude-firewall.service"


def _build_claude_raw_dnsmasq() -> str:
    """Build the ``raw.dnsmasq`` value for the isholate-claude bridge.

    The config combines three dnsmasq features to give us DNS-level
    allowlisting AND live population of a host ipset that iptables can
    match against:

    - ``local=/#/`` — catch-all: answer non-allowlisted queries locally
      with NXDOMAIN.
    - ``server=/<domain>/<upstream>`` — more specific match wins, so
      allowlisted domains (and subdomains) forward to the upstream.
    - ``ipset=/<d1>/<d2>/.../<setname>`` — on every successful lookup of
      an allowlisted domain, dnsmasq adds each resolved IP to the host
      ipset ``isholate-claude-allowed`` with the set's timeout.  Host
      iptables matches ``-m set --match-set`` against this set to allow
      only just-resolved destinations.
    """
    lines = ["local=/#/"]
    for domain in _CLAUDE_ALLOW_DOMAINS:
        lines.append(f"server=/{domain}/{_CLAUDE_DNS_UPSTREAM}")
    # ipset= takes a slash-separated domain list followed by the set name:
    #   ipset=/anthropic.com/claude.ai/.../<setname>
    ipset_spec = "/".join(_CLAUDE_ALLOW_DOMAINS)
    lines.append(f"ipset=/{ipset_spec}/{_CLAUDE_IPSET_NAME}")
    return "\n".join(lines)


def _ensure_claude_network(*, quiet: bool = False) -> str:
    """Ensure the ``isholate-claude`` Incus managed network exists and is current.

    Creates the bridge on first use and always updates ``raw.dnsmasq`` +
    ``ipv4.firewall`` so the config stays in sync with the current isholate
    version.  The bridge is a persistent host resource: it outlives
    individual isholate runs and is shared across all containers launched
    with ``--no-network --claude``.

    ``ipv4.firewall=false`` tells Incus not to auto-generate FORWARD rules
    for this bridge — we own them via :func:`_install_claude_firewall`.
    ``ipv4.nat=true`` is (re-)applied on every run so the container can
    reach allowlisted IPs via MASQUERADE even if a previous run or manual
    edit toggled the flag off.

    No ``sudo`` is required here — the Incus daemon (running as root)
    configures the bridge and dnsmasq.  Host iptables rules are installed
    separately by :func:`_install_claude_firewall`.

    Returns:
        The name of the Incus managed network (``isholate-claude``).
    """
    show_r = _run(
        ["incus", "network", "show", _CLAUDE_NETWORK_NAME],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if show_r.returncode != 0:
        _say(
            f"creating Incus managed network '{_CLAUDE_NETWORK_NAME}' "
            "(one-time setup for --no-network --claude)...",
            quiet=quiet,
        )
        _run_checked(
            [
                "incus",
                "network",
                "create",
                _CLAUDE_NETWORK_NAME,
                "ipv4.address=auto",
                "ipv4.nat=true",
                "ipv4.firewall=false",
                "ipv6.address=none",
            ],
            f"create isholate-claude bridge '{_CLAUDE_NETWORK_NAME}'",
            stdin=subprocess.DEVNULL,
        )

    # Always (re-)apply the dnsmasq allowlist, the ipv4.firewall flag, and
    # ipv4.nat so upgrades that change the allowlist or toggle flags are
    # picked up regardless of whether the network already existed.
    # Use separate key/value arguments to avoid CLI parsing edge cases with
    # multi-line values or embedded '=' characters.
    raw_dnsmasq = _build_claude_raw_dnsmasq()
    _run_checked(
        [
            "incus",
            "network",
            "set",
            _CLAUDE_NETWORK_NAME,
            "raw.dnsmasq",
            raw_dnsmasq,
        ],
        "configure DNS allowlist on isholate-claude bridge",
        stdin=subprocess.DEVNULL,
    )
    _run_checked(
        [
            "incus",
            "network",
            "set",
            _CLAUDE_NETWORK_NAME,
            "ipv4.firewall",
            "false",
        ],
        "disable Incus auto-firewall on isholate-claude bridge",
        stdin=subprocess.DEVNULL,
    )
    _run_checked(
        [
            "incus",
            "network",
            "set",
            _CLAUDE_NETWORK_NAME,
            "ipv4.nat",
            "true",
        ],
        "ensure NAT is enabled on isholate-claude bridge",
        stdin=subprocess.DEVNULL,
    )
    return _CLAUDE_NETWORK_NAME


# ---------------------------------------------------------------------------
# Host firewall (ipset + iptables) for the isholate-claude bridge
# ---------------------------------------------------------------------------


def _claude_firewall_rules_in_place() -> bool:
    """Return True if the host-side ipset + iptables rules are already set up.

    Checked without sudo so the common happy path (rules already installed)
    never prompts for a password.  Six preconditions must all hold:

    1. The ipset ``isholate-claude-allowed`` exists.
    2. The iptables chain ``ISHOLATE-CLAUDE`` exists.
    3. The FORWARD chain has a jump to ``ISHOLATE-CLAUDE`` for traffic
       arriving on the ``isholate-claude`` interface.
    4. The on-disk apply script matches the embedded content — otherwise
       an isholate upgrade that changed the rules would silently fail to
       roll out (in-kernel state would stay current for the session, but
       reboot would restore the stale script's old rules).
    5. The on-disk systemd unit matches the embedded content — same
       reasoning as (4).

    6. The systemd unit is enabled (so rules survive reboot).  Checked
       via ``systemctl is-enabled`` — a non-zero return triggers
       reinstallation, which re-enables the unit.

    ``ipset list -n`` and ``iptables -S`` are read-only operations that
    work for non-root users on most distros via the netfilter netlink
    permissions; when they do require root the check simply reports
    "rules not in place" and :func:`_install_claude_firewall` runs, which
    is harmless because install is itself idempotent.
    """
    ipset_r = _run(
        ["ipset", "list", "-n"],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if ipset_r.returncode != 0:
        return False
    if _CLAUDE_IPSET_NAME not in ipset_r.stdout.splitlines():
        return False

    chain_r = _run(
        ["iptables", "-S", _CLAUDE_IPTABLES_CHAIN],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if chain_r.returncode != 0:
        return False

    fwd_r = _run(
        [
            "iptables",
            "-C",
            "FORWARD",
            "-i",
            _CLAUDE_NETWORK_NAME,
            "-j",
            _CLAUDE_IPTABLES_CHAIN,
        ],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if fwd_r.returncode != 0:
        return False

    # Detect drift between the embedded content and what is actually
    # installed on disk.  If an isholate upgrade changes the rules, the
    # in-kernel state still matches the *old* rules (because the current
    # running chain was installed by the old version), so we cannot rely
    # on iptables -S alone to spot the drift.  File content comparison is
    # cheap and catches the issue on the next isholate run.
    if not _claude_firewall_on_disk_matches():
        return False

    # Verify the systemd unit is enabled so rules survive a reboot.
    # A unit whose files match but which is disabled would leave the host
    # unprotected after the next boot.
    unit_name = Path(_CLAUDE_FIREWALL_SYSTEMD_UNIT).name
    enabled_r = _run(
        ["systemctl", "is-enabled", unit_name],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if enabled_r.returncode != 0:
        return False

    return True


def _claude_firewall_on_disk_matches() -> bool:
    """Return True if the installed apply script + systemd unit match the
    embedded content.

    A mismatch (or missing file) means an isholate upgrade changed the
    embedded content and the on-disk version is stale; we must reinstall
    so reboots restore the current rules.
    """
    for path, expected in (
        (_CLAUDE_FIREWALL_APPLY_SCRIPT, _CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT),
        (_CLAUDE_FIREWALL_SYSTEMD_UNIT, _CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT),
    ):
        try:
            with open(path, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            return False
        if current != expected:
            return False
    return True


# The shell script that (re-)applies the ipset + iptables rules.  Installed
# to _CLAUDE_FIREWALL_APPLY_SCRIPT and invoked by the systemd unit on boot.
# Idempotent: safe to run any number of times.
_CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT = f"""#!/bin/sh
# Managed by isholate.  Do not edit by hand — changes are overwritten on
# the next `isholate --no-network --claude` invocation that needs to
# reinstall rules.
set -eu

SET={_CLAUDE_IPSET_NAME}
CHAIN={_CLAUDE_IPTABLES_CHAIN}
BRIDGE={_CLAUDE_NETWORK_NAME}

# 1. Ensure the ipset exists.  Dnsmasq on the bridge requires it to be
#    present before it can add resolved IPs; ``create ... -exist`` is a
#    no-op if the set already exists (Linux >= ipset 6.x).
ipset create "$SET" hash:ip family inet timeout 3600 -exist

# 2. Ensure our chain exists and contains exactly our ruleset.
iptables -N "$CHAIN" 2>/dev/null || true
iptables -F "$CHAIN"

# Return/related traffic on flows we allowed out.
iptables -A "$CHAIN" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# DNS: allow only to the bridge's gateway, which runs the restricted
# dnsmasq.  Any attempt to contact external resolvers (e.g. 8.8.8.8) is
# dropped by the default policy at the end of this chain.
BRIDGE_IP=$(ip -4 addr show "$BRIDGE" 2>/dev/null | awk '/inet /{{split($2,a,"/"); print a[1]; exit}}')
if [ -n "$BRIDGE_IP" ]; then
    iptables -A "$CHAIN" -d "$BRIDGE_IP" -p udp --dport 53 -j ACCEPT
    iptables -A "$CHAIN" -d "$BRIDGE_IP" -p tcp --dport 53 -j ACCEPT
fi

# HTTPS only to IPs in the live ipset (populated by the bridge's dnsmasq
# on every DNS lookup of an allowlisted domain).
iptables -A "$CHAIN" -p tcp --dport 443 -m set --match-set "$SET" dst -j ACCEPT

# Default deny for everything else.
iptables -A "$CHAIN" -j DROP

# 3. FORWARD jump: egress from the bridge goes through our chain.
#    Remove any duplicates first so the rule appears exactly once.
while iptables -C FORWARD -i "$BRIDGE" -j "$CHAIN" 2>/dev/null; do
    iptables -D FORWARD -i "$BRIDGE" -j "$CHAIN"
done
iptables -I FORWARD -i "$BRIDGE" -j "$CHAIN"

# 4. Return direction: allow established/related responses back to the
#    container (belt-and-braces; the default FORWARD policy is ACCEPT on
#    most distros, but we cannot rely on that).
while iptables -C FORWARD -o "$BRIDGE" -m conntrack \\
    --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; do
    iptables -D FORWARD -o "$BRIDGE" -m conntrack \\
        --ctstate ESTABLISHED,RELATED -j ACCEPT
done
iptables -I FORWARD -o "$BRIDGE" -m conntrack \\
    --ctstate ESTABLISHED,RELATED -j ACCEPT
"""

_CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT = f"""# Managed by isholate.
[Unit]
Description=isholate-claude bridge firewall rules (ipset + iptables)
Documentation=https://github.com/ishkamiel/ishlib
After=network-online.target incus.service
Wants=network-online.target
PartOf=incus.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={_CLAUDE_FIREWALL_APPLY_SCRIPT}

[Install]
WantedBy=multi-user.target
"""


def _build_claude_firewall_install_script() -> str:
    """Return the bootstrap shell script run under ``sudo``.

    The script writes the persistent apply script and systemd unit to the
    host, runs the apply script once, and enables the unit so rules come
    back on boot.  Writing via ``cat <<'EOF'`` avoids quoting pitfalls from
    subprocess argv interpolation.
    """
    # Use a non-clashing heredoc terminator since the apply script itself
    # contains a bunch of shell syntax.
    apply_script = _CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT
    unit = _CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT
    return (
        "set -eu\n"
        f"mkdir -p {os.path.dirname(_CLAUDE_FIREWALL_APPLY_SCRIPT)}\n"
        # Write the apply script.
        f"cat > {_CLAUDE_FIREWALL_APPLY_SCRIPT} <<'ISHOLATE_APPLY_EOF'\n"
        f"{apply_script}"
        "ISHOLATE_APPLY_EOF\n"
        f"chmod +x {_CLAUDE_FIREWALL_APPLY_SCRIPT}\n"
        # Write the systemd unit.
        f"cat > {_CLAUDE_FIREWALL_SYSTEMD_UNIT} <<'ISHOLATE_UNIT_EOF'\n"
        f"{unit}"
        "ISHOLATE_UNIT_EOF\n"
        # Reload systemd, enable the unit, and apply rules now.
        "systemctl daemon-reload\n"
        "systemctl enable isholate-claude-firewall.service >/dev/null\n"
        f"{_CLAUDE_FIREWALL_APPLY_SCRIPT}\n"
    )


# Host tools the install script invokes.  Checked up-front so missing
# dependencies produce targeted errors instead of an opaque "sudo exit
# status N" failure.  Each entry is (tool, distro-neutral install hint).
_CLAUDE_FIREWALL_REQUIRED_TOOLS: "tuple[tuple[str, str], ...]" = (
    ("ipset", "install the 'ipset' package (apt/dnf install ipset)"),
    (
        "iptables",
        "install the 'iptables' package "
        "(apt install iptables / dnf install iptables-nft)",
    ),
    (
        "systemctl",
        "systemd is required for the boot-time firewall restore unit; "
        "isholate currently only supports systemd hosts for --no-network --claude",
    ),
)


def _install_claude_firewall(*, quiet: bool = False) -> None:
    """Install the host-side ipset + iptables rules under ``sudo``.

    Idempotent: the underlying apply script is safe to run any number of
    times, and writing the systemd unit overwrites an existing copy with
    the current content.  Uses an interactive sudo (no ``-n``) so a first
    invocation on a fresh host prompts the user once for their password;
    subsequent isholate runs pass :func:`_claude_firewall_rules_in_place`
    and skip this step entirely.

    A short preflight runs before the sudo prompt so that missing host
    tools (``ipset``, ``iptables``, ``systemctl``, ``sudo``) produce
    specific, actionable errors instead of a generic "sudo exit status N"
    after the password prompt.

    Raises:
        RuntimeError: if any required tool is missing, or sudo fails
            (password refused, sudo not installed, install script exits
            non-zero).
    """
    _say(
        "installing host-side firewall rules for --no-network --claude "
        "(requires sudo on first run)...",
        quiet=quiet,
    )

    # Preflight: targeted errors for each missing dependency.  Cheap (a
    # handful of PATH lookups) and avoids prompting for sudo when we
    # already know the subsequent command will fail.
    missing: "list[str]" = []
    for tool, hint in _CLAUDE_FIREWALL_REQUIRED_TOOLS:
        if shutil.which(tool) is None:
            missing.append(f"  - {tool}: {hint}")
    if missing:
        raise RuntimeError(
            "cannot install host-side firewall rules — missing host tools:\n"
            + "\n".join(missing)
            + "\nInstall the packages above and re-run --no-network --claude."
        )

    if shutil.which("sudo") is None:
        raise RuntimeError(
            "sudo not found on PATH; cannot install host-side firewall rules "
            "automatically.\n"
            "Install sudo and re-run, or follow the documented manual firewall "
            "installation steps as root."
        )

    script = _build_claude_firewall_install_script()
    result = _run(
        ["sudo", "/bin/sh", "-c", script],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "failed to install host-side firewall rules "
            f"(sudo exit status {result.returncode}).  "
            "Re-run with --no-network --claude after resolving the sudo issue, "
            "or install the rules manually (see isholate docs)."
        )


def _apply_network_restrictions(
    name: str, *, allow_claude: bool, quiet: bool = False
) -> None:
    """Lock down network egress for the ephemeral container.

    Both paths operate at the Incus layer via device overrides on the running
    container — nothing is configured inside the container.  This runs after
    provisioning, so the provisioning phase (apt, ishfiles) still has full
    network access.

    Args:
        name:         Incus container name.
        allow_claude: If True, switch ``eth0`` to the dedicated
                      ``isholate-claude`` Incus managed network whose dnsmasq
                      only resolves Claude API domains (see
                      :data:`_CLAUDE_ALLOW_DOMAINS`).  If False, detach
                      ``eth0`` entirely at the Incus layer — a simpler,
                      config-free cut-off.
        quiet:        Suppress isholate progress messages.
    """
    if not allow_claude:
        _say(
            f"--no-network: detaching eth0 from '{name}' via Incus device override...",
            quiet=quiet,
        )
        # Override the profile-provided eth0 NIC with a 'none' device at the
        # Incus layer.  This hot-detaches the NIC from the running container so
        # systemd-networkd / netplan cannot bring it back up — unlike
        # `ip link set eth0 down`, which is advisory inside the container and
        # gets immediately undone by the DHCP client.
        #
        # `device add` fails if eth0 already exists at the instance level (e.g.
        # from a prior run or an instance-level config override).  Remove any
        # existing instance-level device first; this is a no-op (returns non-zero)
        # if eth0 only comes from a profile, which is the common case.
        _run(
            ["incus", "config", "device", "remove", name, "eth0"],
            check=False,
            stdin=subprocess.DEVNULL,
        )
        _run_checked(
            ["incus", "config", "device", "add", name, "eth0", "none"],
            "detach eth0 via Incus device override (--no-network)",
        )
        return

    # --no-network --claude: attach eth0 to the dedicated isholate-claude
    # bridge and enforce an IP-level allowlist via host iptables + a
    # dnsmasq-populated ipset.  Nothing is configured inside the container,
    # so a malicious process cannot tamper with the rules.
    network = _ensure_claude_network(quiet=quiet)

    # Install the host firewall if it is not already in place.  The check
    # runs without sudo; only the install step elevates.  Idempotent: once
    # the rules are loaded (and the systemd unit is enabled), this branch
    # is skipped on subsequent runs and across reboots.
    if not _claude_firewall_rules_in_place():
        _install_claude_firewall(quiet=quiet)

    _say(
        f"--no-network --claude: switching '{name}' to the '{network}' bridge...",
        quiet=quiet,
    )
    # Remove any existing instance-level eth0 so the profile/previous override
    # cannot conflict with the new NIC device.  Best-effort: exits non-zero
    # when eth0 comes only from a profile, which is the common case.
    _run(
        ["incus", "config", "device", "remove", name, "eth0"],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    _run_checked(
        [
            "incus",
            "config",
            "device",
            "add",
            name,
            "eth0",
            "nic",
            f"network={network}",
            "name=eth0",
        ],
        f"attach eth0 to '{network}' bridge (--no-network --claude)",
    )


# ---------------------------------------------------------------------------
# Provisioning helpers (shared by both one-shot and base-creation paths)
# ---------------------------------------------------------------------------


def _bootstrap_base(name: str, *, verbose: int = 0, quiet: bool = False) -> None:
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
        name:    Container name.
        verbose: 0 = quiet apt/npm; 1 = stream output; 2 = also --debug.
        quiet:   Suppress isholate's own progress messages.
    """
    # Create the /run/isholate staging directory.
    _run_checked(
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
    _base_pkgs = "python3 sudo bubblewrap nodejs npm socat"
    apt_install = (
        f"apt-get install -y --no-install-recommends {_base_pkgs}"
        if verbose
        else f"apt-get install -qq -y --no-install-recommends {_base_pkgs}"
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
            f"dnf install -y {_base_pkgs}; "
            "fi",
        ],
        f"bootstrap ({_base_pkgs} install)",
        stdin=subprocess.DEVNULL,
    )
    _say("installing @anthropic-ai/sandbox-runtime via npm...", quiet=quiet)
    npm_flags = "" if verbose else "--loglevel=error "
    _run_checked(
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
    r = _run(
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
        "--",
        "python3",
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
        _run_checked(
            pass1_cmd,
            "ishfiles apply (pass 1: host dotfiles)",
            stdin=subprocess.DEVNULL,
        )
    finally:
        host_log = Path.home() / FAILED_LOGS_STATE_DIR / name / "pass1.log"
        _pull_container_log(name, container_log, host_log)

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
    container_log = "/tmp/isholate-ishfiles-pass2.log"

    _add_mount(
        name,
        "isholate-overlay",
        project_overlay,
        f"{_ISHOLATE_RUN_DIR}/ishsrc-project",
        readonly=True,
    )
    try:
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
    ishfiles_flags.extend(["--custom-username", username])

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
    fingerprint = _host_base_fingerprint(host_source)

    # Check whether an up-to-date base already exists.
    if not rebuild and _container_exists(name):
        stored = _get_stored_fingerprint(name)
        if stored == fingerprint:
            _say(f"reusing host base '{name}'", quiet=quiet)
            # Scrub any stale isholate-* devices that may have been left by a
            # previously interrupted run before returning the cached base, and
            # verify the scrub succeeded so we never return a poisoned base.
            _remove_isholate_devices(name)
            try:
                _assert_no_isholate_devices(name)
            except RuntimeError:
                # Poisoned base — devices could not be removed.  Force a
                # rebuild so the user is not permanently stuck.
                _say(
                    f"host base '{name}' has un-removable isholate devices "
                    "— forcing rebuild...",
                    quiet=quiet,
                )
                del_r = _run(
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
    _run(
        ["incus", "init", image, name, "--config", "security.nesting=true"], check=True
    )
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
        ishfiles_flags.extend(["--custom-username", username])

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

        # Stop the base, then remove host-path mounts and verify they are gone.
        # Device removal runs after stop so Incus can cleanly detach bind-mounts
        # without racing a live container.  The assertion ensures a silently-failing
        # removal cannot poison the base for future copies.
        _say(f"stopping and saving host base '{name}'...", quiet=quiet)
        _run(["incus", "stop", name, "--force"], check=False)
        _remove_isholate_devices(name)
        _assert_no_isholate_devices(name)
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
    # Strip any isholate-* devices inherited from the host base.  The host base
    # is supposed to be device-free when stopped, but a stale base from an
    # interrupted earlier run may still carry them; starting a container with a
    # stale disk device causes "The device already exists" from Incus.  The
    # assertion ensures a silently-failing removal cannot leave devices behind.
    _remove_isholate_devices(name)
    _assert_no_isholate_devices(name)
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
        _add_mount(
            name,
            "isholate-ishlib",
            _ISHLIB_ROOT,
            f"{_ISHOLATE_RUN_DIR}/ishlib",
            readonly=True,
        )

        # Apply the project overlay.
        ishfiles_flags: List[str] = []
        if verbose >= 2:
            ishfiles_flags.append("--debug")
        elif verbose >= 1:
            ishfiles_flags.append("-v")
        ishfiles_flags.extend(["--custom-username", username])

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
        if started and verbose >= 1:
            dev_r = _run(
                ["incus", "config", "device", "list", name],
                capture_output=True,
                text=True,
                check=False,
            )
            if dev_r.returncode == 0 and dev_r.stdout.strip():
                _say(f"devices on '{name}' at failure: {dev_r.stdout.strip()}")
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
        verbose:     Verbosity level.
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
            _add_mount(name, "hostcwd", cwd, str(cwd), shift=True)
        elif args.ro_cwd:
            _add_mount(name, "hostcwd", cwd, str(cwd), readonly=True, shift=True)

        _claude_on = getattr(args, "claude", False)
        _claude_base_on = getattr(args, "claude_base", False)
        if _claude_on:
            _add_claude_mounts(name, home, username, quiet=quiet)
        elif _claude_base_on:
            _add_claude_base_mounts(name, home, username, quiet=quiet)

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
    _run(
        ["incus", "init", args.image, name, "--config", "security.nesting=true"],
        check=True,
    )

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
            _add_mount(name, "hostcwd", cwd, str(cwd), shift=True)
        elif args.ro_cwd:
            _add_mount(name, "hostcwd", cwd, str(cwd), readonly=True, shift=True)

        _claude_on = getattr(args, "claude", False)
        _claude_base_on = getattr(args, "claude_base", False)
        if _claude_on:
            _add_claude_mounts(name, home, username, quiet=quiet)
        elif _claude_base_on:
            _add_claude_base_mounts(name, home, username, quiet=quiet)

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
            home=home,
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
