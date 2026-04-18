# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Incus-backed implementation of :class:`pyishlib.container.Container`.

This module owns every ``incus`` CLI shell-out in the pyishlib codebase.
Higher-level tools (isholate, a future ishfiles backend, ...) must build
on top of :class:`IncusContainer` and the module-level helpers defined
here rather than call the ``incus`` binary directly.

Keep this module tool-agnostic: no isholate-specific, ishfiles-specific,
or Claude-specific logic belongs here.  Isholate-specific prefix filtering
and naming live in :mod:`pyishlib.isholate.container`; Claude-specific
network / firewall code lives in :mod:`pyishlib.isholate.claude`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..environment import detect_distro
from .container import Container

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level subprocess wrappers (tests patch these)
# ---------------------------------------------------------------------------


def _run(cmd: List[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run an incus command. Pass check=True to raise on failure."""
    return subprocess.run(cmd, **kwargs)


def _run_checked(
    cmd: List[str], step: str, **kwargs: Any
) -> subprocess.CompletedProcess:
    """Run *cmd* with ``check=True``; on failure flush output and re-raise
    with a labelled message so the user knows which provisioning step
    broke.

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
# Incus-daemon probes and misc helpers
# ---------------------------------------------------------------------------


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


def check_incus_available() -> Optional[str]:
    """Probe the incus daemon and return setup guidance on failure.

    Returns ``None`` when incus is installed and the daemon is reachable
    by the current user via a successful ``incus info`` probe.  Otherwise
    returns a multi-line, user-facing message (with the ``isholate:``
    prefix already applied) describing what to do next.

    The probe is deliberately cheap — a single ``incus info`` invocation
    with a short timeout and no further output inspection — so the
    healthy path adds negligible overhead.
    """
    if shutil.which("incus") is None:
        return (
            "isholate: error: the 'incus' command was not found on PATH.\n"
            f"{_incus_install_hint()}\n"
            "After installing, run 'sudo incus admin init' and add your user\n"
            "to the 'incus-admin' group."
        )

    try:
        result = _run(
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


def list_incus_containers() -> List[dict]:
    """Return all containers visible to the current incus user.

    Runs ``incus list --format=json`` and returns the parsed list.  Each
    entry is a dictionary with the raw keys Incus reports (``name``,
    ``status``, ...).  Raises :class:`subprocess.CalledProcessError` if
    the underlying command fails — callers that want a lenient path
    should catch it.
    """
    result = _run(
        ["incus", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def ensure_managed_network(
    name: str,
    *,
    create_config: List[str],
    set_config: Dict[str, str],
) -> None:
    """Ensure an Incus managed network named *name* exists and is up to date.

    If the network does not yet exist, it is created with the flags in
    *create_config* (e.g. ``["ipv4.address=auto", "ipv4.nat=true"]``).
    The entries in *set_config* are always applied afterwards so that
    configuration drift on upgrades converges to the current value.

    No sudo is required — the Incus daemon (running as root) owns the
    bridge and its dnsmasq; this helper only talks to the Incus CLI.
    """
    show = _run(
        ["incus", "network", "show", name],
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if show.returncode != 0:
        _run_checked(
            ["incus", "network", "create", name, *create_config],
            f"create managed network '{name}'",
            stdin=subprocess.DEVNULL,
        )

    for key, value in set_config.items():
        _run_checked(
            ["incus", "network", "set", name, key, value],
            f"set {key} on managed network '{name}'",
            stdin=subprocess.DEVNULL,
        )


# ---------------------------------------------------------------------------
# IncusContainer
# ---------------------------------------------------------------------------


class IncusContainer(Container):
    """Incus-backed :class:`Container` implementation.

    Every method shells out to the ``incus`` CLI via the module-level
    :func:`_run` / :func:`_run_checked` wrappers so tests can patch a
    single seam.
    """

    # ------------------------------------------------------------------
    # Lifecycle primitives
    # ------------------------------------------------------------------

    def exists(self) -> bool:
        r = _run(["incus", "info", self.name], capture_output=True, check=False)
        return r.returncode == 0

    def is_running(self) -> bool:
        r = _run(
            ["incus", "info", self.name],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            return False
        for line in (r.stdout or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("status:"):
                value = stripped.split(":", 1)[1].strip().lower()
                return value == "running"
        return False

    def create(self, image: str, **config: str) -> None:
        cmd: List[str] = ["incus", "init", image, self.name]
        for key, value in config.items():
            cmd += ["--config", f"{key}={value}"]
        _run(cmd, check=True)

    def start(self) -> None:
        _run(["incus", "start", self.name], check=True)

    def stop(self, *, force: bool = True) -> None:
        cmd = ["incus", "stop", self.name]
        if force:
            cmd.append("--force")
        _run(cmd, check=False)

    def delete(self, *, force: bool = True) -> None:
        cmd = ["incus", "delete", self.name]
        if force:
            cmd.append("--force")
        _run(cmd, check=False)

    def copy_to(self, dest_name: str) -> "IncusContainer":
        _run(["incus", "copy", self.name, dest_name], check=True)
        return IncusContainer(dest_name)

    # ------------------------------------------------------------------
    # Exec / file I/O
    # ------------------------------------------------------------------

    def exec(
        self,
        cmd: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        user: Optional[int] = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        stdin: Any = None,
    ) -> subprocess.CompletedProcess:
        argv: List[str] = ["incus", "exec", self.name]
        if user is not None:
            argv += ["--user", str(user)]
        if cwd is not None:
            argv += ["--cwd", cwd]
        if env:
            for key, value in env.items():
                argv += ["--env", f"{key}={value}"]
        argv.append("--")
        argv.extend(list(cmd))

        run_kwargs: Dict[str, Any] = {
            "check": check,
            "capture_output": capture_output,
            "text": text,
        }
        if stdin is not None:
            run_kwargs["stdin"] = stdin
        return _run(argv, **run_kwargs)

    def pull_file(
        self,
        container_path: str,
        host_dest: Path,
        *,
        recursive: bool = False,
    ) -> bool:
        host_dest.parent.mkdir(parents=True, exist_ok=True)
        cmd: List[str] = ["incus", "file", "pull"]
        if recursive:
            cmd.append("--recursive")
        cmd.extend([f"{self.name}{container_path}", str(host_dest)])
        r = _run(cmd, capture_output=True, check=False)
        return r.returncode == 0

    # ------------------------------------------------------------------
    # Device primitives
    # ------------------------------------------------------------------

    def add_device(self, device_name: str, device_type: str, **options: str) -> None:
        cmd: List[str] = [
            "incus",
            "config",
            "device",
            "add",
            self.name,
            device_name,
            device_type,
        ]
        for key, value in options.items():
            cmd.append(f"{key}={value}")
        _run(cmd, check=True)

    def remove_device(self, device_name: str) -> None:
        # Removal is best-effort — check=False so a missing device does not
        # raise, matching the pre-refactor behaviour of isholate's cleanup
        # paths.
        _run(
            ["incus", "config", "device", "remove", self.name, device_name],
            check=False,
        )

    def list_devices(self) -> List[str]:
        r = _run(
            ["incus", "config", "device", "list", self.name],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        return [line.strip() for line in r.stdout.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def get_metadata(self, key: str) -> Optional[str]:
        r = _run(
            ["incus", "config", "get", self.name, key],
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode != 0:
            return None
        value = (r.stdout or "").strip()
        return value or None

    def set_metadata(self, key: str, value: str) -> None:
        _run(
            ["incus", "config", "set", self.name, key, value],
            check=True,
        )
