#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Incus container lifecycle for isholate.

Handles launching an ephemeral Ubuntu container with host user mirroring,
bind mounts, and interactive exec.
"""

from __future__ import annotations

import json
import os
import random
import string
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

# Root of the ishlib checkout — used to mount the ishfiles CLI into containers.
# Path: container.py -> isholate/ -> pyishlib/ -> src/ -> ishlib/
_ISHLIB_ROOT: Path = Path(__file__).resolve().parents[3]

# Path inside the container where isholate mounts its helper files.
_ISHOLATE_RUN_DIR = "/run/isholate"


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
    import re

    s = username.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "user"


def generate_name(username: str) -> str:
    """Generate a short random container name."""
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"isholate-{_sanitize_for_name(username)}-{suffix}"


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
        # Flush both streams so any container output printed before the
        # failure appears before our error message.
        sys.stdout.flush()
        sys.stderr.flush()
        print(
            f"\nisholate: {step} failed (exit {exc.returncode})",
            file=sys.stderr,
            flush=True,
        )
        raise


def purge_containers(username: str, *, quiet: bool = False) -> int:
    """Delete all isholate containers belonging to the given username.

    Args:
        username: The host username whose containers should be purged.
        quiet:    Suppress isholate's own progress messages.

    Returns:
        0 if all deletions succeeded, 1 if any failed.
    """
    # Match the prefix produced by generate_name(), which sanitises the
    # username (e.g. "john_doe" -> "john-doe").  Using the raw username
    # here would miss containers for users with non-alphanumeric names.
    prefix = f"isholate-{_sanitize_for_name(username)}-"
    result = subprocess.run(
        ["incus", "list", "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    )
    containers = [
        c["name"] for c in json.loads(result.stdout) if c["name"].startswith(prefix)
    ]

    if not containers:
        _say(f"no isholate containers found for user '{username}'", quiet=quiet)
        return 0

    failed = False
    for name in containers:
        _say(f"deleting {name}...", quiet=quiet)
        r = _run(["incus", "delete", name, "--force"], check=False)
        if r.returncode != 0:
            print(f"isholate: failed to delete {name}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


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

    Runs as root (no ``--user`` flag) so that package managers succeed.
    After all apply passes complete, the user's home directory is
    chown'd back to the container UID.

    Pass 1 (host ishfiles) is skipped when *host_source* is ``None``.
    Pass 2 (project overlay) is skipped when *project_overlay* is ``None``.

    Args:
        name:            Incus container name.
        username:        Username inside the container.
        uid:             UID of the container user (for final chown).
        host_config_dir: Host ``~/.config/ishfiles/`` directory, mounted
                         read-only at its natural path so pass 1 picks it
                         up without any ``-c`` override.
        host_source:     Host ishfiles source tree, mounted at the same
                         absolute path inside the container.
        project_overlay: Project ``.isholate/`` directory, mounted
                         read-only at ``/run/isholate/ishsrc-project``.
        verbose:         0 keeps apt/ishfiles quiet; 1 streams their
                         output; 2+ also passes ``--debug`` to ishfiles.
        quiet:           Suppress isholate's own progress messages.
    """
    ishfiles_bin = f"{_ISHOLATE_RUN_DIR}/ishlib/bin/ishfiles"
    container_home = f"/home/{username}"

    # Ishfiles verbosity flags (global flags, before the subcommand).
    ishfiles_flags: List[str] = []
    if verbose >= 2:
        ishfiles_flags.append("--debug")
    elif verbose >= 1:
        ishfiles_flags.append("-v")

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

    # Install python3 and sudo (needed by ishfiles' apt backend).
    # First-run image initialisation (apt update + install) is the
    # slowest part of provisioning, so announce it; with -v, stream
    # apt output so users can see progress.
    _say(
        "installing base packages in container (python3, sudo); "
        "this can take a minute on first run...",
        quiet=quiet,
    )
    apt_update = "apt-get update" if verbose else "apt-get update -qq"
    apt_install = (
        "apt-get install -y --no-install-recommends python3 sudo"
        if verbose
        else "apt-get install -qq -y --no-install-recommends python3 sudo"
    )
    # Force apt to use IPv4.  Incus bridges typically provide IPv4 NAT but
    # may not route IPv6, causing apt to waste time on unreachable addresses
    # before falling back to IPv4.
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
        check=False,  # best-effort: non-apt images silently skip this
        stdin=subprocess.DEVNULL,
    )

    # Pass DEBIAN_FRONTEND=noninteractive so debconf (e.g. the tzdata
    # postinst pulled in by python3) uses the non-interactive frontend
    # instead of prompting on stdin.  Also detach stdin from the
    # controlling terminal so no postinst hook can read from it.
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

    # --- Pass 1: host ishfiles ---
    if host_source is not None:
        _say("applying host ishfiles (pass 1)...", quiet=quiet)
        # Mount host config dir at its natural container path so ishfiles
        # discovers it without any -c override.
        if host_config_dir is not None and host_config_dir.is_dir():
            _add_ro_device(
                name,
                "isholate-ishconf",
                host_config_dir,
                f"{container_home}/.config/ishfiles",
            )
        # Mount host source tree at the same absolute path so the config
        # file's `source = ...` entry resolves correctly.
        _add_ro_device(
            name,
            "isholate-ishsrc",
            host_source,
            str(host_source),
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
                "apply",
                "--isholate",
            ],
            "ishfiles apply (pass 1: host dotfiles)",
            stdin=subprocess.DEVNULL,
        )

    # --- Pass 2: project overlay ---
    if project_overlay is not None:
        _say("applying project overlay (pass 2)...", quiet=quiet)
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
            ],
            "ishfiles apply (pass 2: project overlay)",
            stdin=subprocess.DEVNULL,
        )

    # Fix ownership of the user's home after root-driven provisioning.
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


def launch_and_exec(
    args: Any,
    *,
    host_ishfiles_source: Optional[Path] = None,
    project_overlay: Optional[Path] = None,
) -> int:
    """Launch an ephemeral Incus container and exec into it as the host user.

    Lifecycle:
    1. Create (but don't start) a container from the specified image.
    2. Start the container.
    3. Create a user matching the host username (UID assigned by Incus).
    4. If provisioning sources are provided, run ishfiles inside the
       container to apply dotfiles and packages (see :func:`_provision`).
    5. Add disk devices for any requested bind mounts.
    6. Exec into the container as that user.
    7. Stop and delete the container.

    Args:
        args: Parsed argparse namespace with fields: name, image, shell,
              ro_home, rw_cwd, ro_cwd, command.
        host_ishfiles_source: Host ishfiles source tree to apply (pass 1).
            When ``None``, pass 1 is skipped.
        project_overlay: Project ``.isholate/`` source tree to apply
            (pass 2).  When ``None``, pass 2 is skipped.

    Returns:
        Exit code from the exec'd command.
    """
    username, home, cwd = get_host_user_info()
    name: str = args.name or generate_name(username)
    started = False

    # Tolerate args namespaces that don't carry the new verbose/quiet
    # fields (e.g. older test fixtures).
    verbose: int = int(getattr(args, "verbose", 0) or 0)
    quiet: bool = bool(getattr(args, "quiet", False))

    # 1. Create container without starting it for cleaner error handling.
    _say(
        f"creating container '{name}' from {args.image} "
        "(may pull the image on first use)...",
        quiet=quiet,
    )
    _run(
        ["incus", "init", args.image, name],
        check=True,
    )

    try:
        # 2. Start the container
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

        # 3. Create a user with the same username as on the host.
        # Remove the default 'ubuntu' user first (UID 1000) so our user
        # naturally gets UID 1000, which is what shift=true maps host files to.
        _say(f"creating user '{username}' inside container...", quiet=quiet)
        _run(
            ["incus", "exec", name, "--", "userdel", "-r", "ubuntu"],
            check=False,  # may not exist in non-Ubuntu images
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

        # 4. Provision with ishfiles if sources are available.
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

        # 5. Add disk devices for bind mounts
        if args.ro_home:
            _run(
                [
                    "incus",
                    "config",
                    "device",
                    "add",
                    name,
                    "hosthome",
                    "disk",
                    f"source={home}",
                    f"path=/home/{username}",
                    "readonly=true",
                    "shift=true",
                ],
                check=True,
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

        # 6. Exec into the container as the user
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
        # argparse.REMAINDER may include a leading '--' separator; strip it.
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
        return 1

    finally:
        # 7. Stop and delete the container (only if it started successfully)
        if started:
            _say(f"stopping and deleting '{name}'...", quiet=quiet)
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)
