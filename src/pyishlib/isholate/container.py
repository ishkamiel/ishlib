#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
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
from typing import Any, List


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


def purge_containers(username: str) -> int:
    """Delete all isholate containers belonging to the given username.

    Args:
        username: The host username whose containers should be purged.

    Returns:
        0 if all deletions succeeded, 1 if any failed.
    """
    prefix = f"isholate-{username}-"
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
        print(f"No isholate containers found for user '{username}'.")
        return 0

    failed = False
    for name in containers:
        print(f"Deleting {name}...")
        r = _run(["incus", "delete", name, "--force"], check=False)
        if r.returncode != 0:
            print(f"  Failed to delete {name}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


def launch_and_exec(args: Any) -> int:
    """Launch an ephemeral Incus container and exec into it as the host user.

    Lifecycle:
    1. Create (but don't start) a container from the specified image.
    2. Start the container.
    3. Create a user matching the host username (UID assigned by Incus).
    4. Add disk devices for any requested bind mounts.
    5. Exec into the container as that user.
    6. Stop and delete the container.

    Args:
        args: Parsed argparse namespace with fields: name, image, shell,
              ro_home, rw_cwd, ro_cwd, command.

    Returns:
        Exit code from the exec'd command.
    """
    username, home, cwd = get_host_user_info()
    name: str = args.name or generate_name(username)
    started = False

    # 1. Create container without starting it for cleaner error handling.
    _run(
        ["incus", "init", args.image, name],
        check=True,
    )

    try:
        # 2. Start the container
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

        # 4. Add disk devices for bind mounts
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

        # 5. Exec into the container as the user
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
        else:
            exec_cmd.append(args.shell)

        result = _run(exec_cmd, check=False)
        return result.returncode

    finally:
        # 6. Stop and delete the container (only if it started successfully)
        if started:
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)
