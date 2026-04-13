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


def _network_preflight(name: str, *, verbose: int = 0, quiet: bool = False) -> None:
    """Probe outbound IPv4 connectivity inside the container.

    Runs before apt so that network failures produce actionable diagnostics
    instead of a wall of apt timeout messages.

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
    dns_rc, dns_out = _probe(["getent", "hosts", "archive.ubuntu.com"])

    # Test raw IPv4 egress using ping (available in all Ubuntu base images;
    # avoids the curl dependency that isn't present before bootstrapping).
    raw_rc, _ = _probe(["ping", "-c", "1", "-W", "5", "1.1.1.1"])

    if raw_rc != 0:
        # No raw IPv4 egress → bridge/NAT/firewall problem.
        dns_status = "ok" if dns_rc == 0 else "fail"
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

    # Test mirror reachability (DNS + egress).
    mirror_rc, _ = _probe(["ping", "-c", "1", "-W", "10", "archive.ubuntu.com"])

    if mirror_rc != 0:
        container_ip = _extract_container_ip(addr_out)
        print(
            f"\nisholate: container reaches the internet (1.1.1.1 ok) but "
            f"cannot reach archive.ubuntu.com.\n"
            f"\n"
            f"  container IP:    {container_ip}\n"
            f"  ping 1.1.1.1:    ok\n"
            f"  ping archive.ubuntu: timeout\n"
            f"\n"
            f"This is an upstream / mirror problem, not a container-setup issue.\n"
            f"Try again later.\n",
            file=sys.stderr,
            flush=True,
        )
        raise RuntimeError("container cannot reach archive.ubuntu.com")

    if verbose:
        print("isholate: network pre-flight ok", file=sys.stderr)


def _extract_container_ip(addr_output: str) -> str:
    """Extract the first non-loopback IPv4 address from `ip addr show` output."""
    import re

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
                         read-only at ``/run/isholate/ishconf`` and passed
                         via ``-c`` so it never lands inside the user home.
        host_source:     Host ishfiles source tree, mounted read-only at
                         ``/run/isholate/ishsrc`` and passed via ``-s``.
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
    # Pre-flight network probe before apt so failures produce clear diagnostics.
    _network_preflight(name, verbose=verbose, quiet=quiet)

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

    # If apt-cacher-ng is running on the host, point containers at it via the
    # bridge IP so they benefit from the local package cache.  Containers
    # cannot use "localhost" because that resolves to the container itself;
    # the bridge IP (incusbr0) is the host-side address reachable from inside.
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
            check=False,  # best-effort: non-apt images silently skip this
            stdin=subprocess.DEVNULL,
        )
    elif not quiet:
        print(
            "isholate: tip: install apt-cacher-ng on the host to cache apt downloads\n"
            "  across container runs (speeds up repeated provisioning significantly):\n"
            "    sudo apt-get install apt-cacher-ng",
            file=sys.stderr,
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
        # Mount host source and config under /run/isholate (outside the user
        # home) so that the final `chown -R` over container_home never crosses
        # a read-only bind mount boundary.
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
                "--yes",
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

    # Check whether the log directory exists inside the container before
    # attempting a pull (avoids a confusing incus error on fresh failures).
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
              rw_cwd, ro_cwd, command.
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
        # Pull ishfiles logs out of the container before it is deleted.
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
        # Raised by _network_preflight with a message already printed.
        return 1

    finally:
        # 7. Stop and delete the container (only if it started successfully)
        if started:
            _say(f"stopping and deleting '{name}'...", quiet=quiet)
            _run(["incus", "stop", name, "--force"], check=False)
            _run(["incus", "delete", name, "--force"], check=False)
