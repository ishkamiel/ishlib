#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper commands for running commands and common shell tasks.

Also provides OS detection utilities (:func:`detect_os`,
:func:`should_skip_for_os`, :func:`should_skip_for_os_from_metadata`)
used for platform-conditional ignore rules and metadata filtering.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Iterable, Sequence

from .ish_config import IshConfig
from .ish_comp import die, prompt_yes_no_always

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OS / distro detection utilities
# ---------------------------------------------------------------------------

#: Recognised OS and distro identifiers for ``only_on`` / ``ignore_on``.
#: Platform level: ``linux``, ``macos``, ``windows``.
#: Distro families: ``debian`` (Ubuntu, Debian, …), ``fedora`` (Fedora,
#: Asahi Remix, …).
RECOGNISED_OS = ("linux", "macos", "windows", "debian", "fedora")

# Distro family detection rules.  Each entry maps a canonical family name
# to a set of patterns matched against os-release ``ID`` and ``ID_LIKE``
# tokens.  Because derivative distros often use compound IDs containing
# hyphens (e.g. ``pop-os``, ``fedora-asahi-remix``) or set ``ID_LIKE``
# to one or more ancestor IDs (e.g. ``"rhel centos fedora"``), we check
# whether any token *starts with* a pattern rather than requiring an
# exact match.  This avoids having to enumerate every derivative.
#
# Patterns are checked against:
#   1. Each space-separated word in ``ID_LIKE`` (preferred -- this is
#      the canonical way distros declare their lineage).
#   2. The ``ID`` value itself (fallback for root distros like ``debian``
#      and ``fedora`` that don't set ``ID_LIKE``).
_DISTRO_FAMILY_PATTERNS: Dict[str, list] = {
    "debian": ["debian", "ubuntu", "raspbian"],
    "fedora": ["fedora", "rhel", "centos"],
}


def _read_os_release() -> Dict[str, str]:
    """Parse ``/etc/os-release`` into a dict.

    Returns an empty dict when the file does not exist or cannot be read.
    """
    result: Dict[str, str] = {}
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return result
    for line in text.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip optional quotes
        value = value.strip('"').strip("'")
        result[key] = value
    return result


def _match_distro_family(tokens: list) -> Optional[str]:
    """Match a list of os-release tokens against distro family patterns.

    Each token is checked with :func:`str.startswith` against the
    patterns in :data:`_DISTRO_FAMILY_PATTERNS`, so ``"fedora-asahi-remix"``
    matches the ``"fedora"`` pattern and ``"pop-os"`` does not need to be
    listed explicitly because ``ID_LIKE=ubuntu debian`` already covers it.

    Args:
        tokens: Lowercased ID / ID_LIKE tokens to match.

    Returns:
        The canonical family name, or *None*.
    """
    for family, patterns in _DISTRO_FAMILY_PATTERNS.items():
        for token in tokens:
            for pat in patterns:
                if token.startswith(pat):
                    return family
    return None


def detect_distro() -> Optional[str]:
    """Detect the Linux distro family from ``/etc/os-release``.

    Detection uses ``ID_LIKE`` first (the canonical lineage declaration)
    then falls back to ``ID``.  Tokens are matched with startswith so
    that compound IDs like ``fedora-asahi-remix`` or ``pop-os`` are
    handled automatically.

    Returns:
        ``"debian"`` for Debian-like distros (Ubuntu, Mint, Pop!_OS, …),
        ``"fedora"`` for Fedora-like distros (Fedora, RHEL, Asahi Remix, …),
        or *None* if the distro is unknown or not on Linux.
    """
    if not sys.platform.startswith("linux"):
        return None

    info = _read_os_release()
    if not info:
        return None

    # Prefer ID_LIKE -- it's how distros declare their ancestry
    id_like = info.get("ID_LIKE", "").lower().split()
    result = _match_distro_family(id_like)
    if result is not None:
        return result

    # Fall back to ID (handles root distros like "debian", "fedora")
    distro_id = info.get("ID", "").lower()
    if distro_id:
        return _match_distro_family([distro_id])

    return None


def detect_os() -> str:
    """Return the current OS as a recognised identifier.

    Returns:
        One of ``"linux"``, ``"macos"``, or ``"windows"``.

    Raises:
        RuntimeError: If the platform cannot be mapped to a recognised OS.
    """
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise RuntimeError(f"Unrecognised platform: {sys.platform}")


def detect_os_tags() -> list:
    """Return all OS/distro tags that apply to the current platform.

    The list always starts with the broad OS identifier (``linux``,
    ``macos``, ``windows``) and may include a distro family tag
    (``debian``, ``fedora``) when running on Linux.

    This is used by :func:`should_skip_for_os` so that rules like
    ``only_on = ["debian"]`` match on Ubuntu, and ``only_on = ["linux"]``
    still matches on any Linux distro.
    """
    tags = [detect_os()]
    distro = detect_distro()
    if distro is not None:
        tags.append(distro)
    return tags


def normalise_os(name: str) -> str:
    """Normalise an OS name to its canonical form.

    Accepts common aliases (case-insensitive) and maps them to the
    canonical identifiers used internally.

    Raises:
        ValueError: If the name is not recognised.
    """
    mapping = {
        "linux": "linux",
        "macos": "macos",
        "mac": "macos",
        "darwin": "macos",
        "windows": "windows",
        "win": "windows",
        "win32": "windows",
        "debian": "debian",
        "ubuntu": "debian",
        "fedora": "fedora",
    }
    canonical = mapping.get(name.lower())
    if canonical is None:
        raise ValueError(
            f"Unrecognised OS name: {name!r}; "
            f"expected one of {', '.join(RECOGNISED_OS)}"
        )
    return canonical


def should_skip_for_os(
    only_on: Optional[Sequence[str]] = None,
    ignore_on: Optional[Sequence[str]] = None,
    current_os: Optional[str] = None,
) -> bool:
    """Determine whether an item should be skipped based on OS rules.

    Matching is hierarchical: a rule specifying ``linux`` matches any
    Linux system, while ``debian`` matches only Debian-family distros.
    Conversely, a system running Ubuntu matches rules for both
    ``debian`` and ``linux``.

    Args:
        only_on:     If set, the item applies *only* on these OSes.
                     It is skipped on all others.
        ignore_on:   If set, the item is skipped on these OSes.
        current_os:  Override for the detected OS (for testing).
                     Can be a single tag or comma-separated tags
                     (e.g. ``"linux,debian"``).

    Returns:
        *True* if the item should be skipped on the current platform.
    """
    if current_os is not None:
        current_tags = [t.strip() for t in current_os.split(",")]
    else:
        current_tags = detect_os_tags()

    if only_on is not None:
        try:
            normalised = [normalise_os(o) for o in only_on]
        except ValueError as exc:
            log.warning("Bad only_on value, skipping OS filter: %s", exc)
            return False
        if not any(tag in normalised for tag in current_tags):
            return True

    if ignore_on is not None:
        try:
            normalised = [normalise_os(o) for o in ignore_on]
        except ValueError as exc:
            log.warning("Bad ignore_on value, skipping OS filter: %s", exc)
            return False
        if any(tag in normalised for tag in current_tags):
            return True

    return False


def should_skip_for_os_from_metadata(
    metadata: Optional[Dict[str, Any]],
    current_os: Optional[str] = None,
) -> bool:
    """Check ``only_on`` / ``ignore_on`` keys in a metadata dictionary.

    Convenience wrapper around :func:`should_skip_for_os` for use with
    ``__ISH__`` metadata dictionaries.

    Args:
        metadata:    Parsed metadata dict (may be *None*).
        current_os:  Override for the detected OS (for testing).

    Returns:
        *True* if the item should be skipped on the current platform.
    """
    if metadata is None:
        return False

    only_on = metadata.get("only_on")
    ignore_on = metadata.get("ignore_on")

    if only_on is None and ignore_on is None:
        return False

    # Accept both a single string and a list
    if isinstance(only_on, str):
        only_on = [only_on]
    if isinstance(ignore_on, str):
        ignore_on = [ignore_on]

    return should_skip_for_os(
        only_on=only_on, ignore_on=ignore_on, current_os=current_os
    )


class CommandRunner:
    """Helper class for running commands and common shell tasks"""

    def __init__(
        self,
        cfg: Optional[IshConfig] = None,
        always_sudo: bool = False,
    ) -> None:
        self.cfg: IshConfig = cfg if cfg is not None else IshConfig()
        self._always_sudo: bool = always_sudo

    @property
    def on_windows(self) -> bool:
        """True if running on Windows"""
        return sys.platform == "win32"

    @property
    def dry_run(self) -> bool:
        """Is dry-run mode enabled"""
        return self.cfg.dry_run

    @dry_run.setter
    def dry_run(self, dry_run: bool) -> None:
        self.cfg.dry_run = dry_run

    @property
    def verbose(self) -> bool:
        """Is verbose mode enabled"""
        return self.cfg.verbose

    @property
    def quiet(self) -> bool:
        """Is quiet mode enabled"""
        return self.cfg.quiet

    @property
    def always_sudo(self) -> bool:
        """Is always-sudo mode enabled, i.e., sudo without asking"""
        return self._always_sudo

    @always_sudo.setter
    def always_sudo(self, always_sudo: bool) -> None:
        self._always_sudo = always_sudo

    def run_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False, **kwargs
    ) -> subprocess.CompletedProcess:
        """Run command with sudo (not available on Windows)"""
        if self.on_windows:
            raise OSError("sudo is not available on Windows")
        command = ["sudo"] + command
        if not self._check_sudo(command, force_sudo):
            raise KeyboardInterrupt("User aborted sudo command")
        return self.run(command, **kwargs)

    def run(
        self,
        command: Iterable[str],
        work_dir: Optional[Path] = None,
        quiet: bool = False,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run command"""

        command = [str(c) for c in command]

        if "check" not in kwargs:
            kwargs["check"] = True

        self._print_cmd(command)

        if quiet:
            if "stdout" not in kwargs:
                kwargs["stdout"] = subprocess.DEVNULL
            if "stderr" not in kwargs:
                kwargs["stderr"] = subprocess.DEVNULL

        if self.dry_run:
            # pylint: disable=W1510
            return subprocess.CompletedProcess(
                args=command, returncode=0, stdout=b"", stderr=b""
            )

        if work_dir is not None:
            old_path: Path = Path(os.getcwd())
            os.chdir(work_dir)

        # pylint: disable=W1510
        try:
            result = subprocess.run(command, **kwargs)
        finally:
            if work_dir is not None:
                os.chdir(old_path)
        return result

    def git(
        self, command: Iterable[str], work_dir: Optional[Path] = None, **kwargs
    ) -> subprocess.CompletedProcess:
        """Run git command using Commandrunner.run"""
        if work_dir is not None and "-C" not in command:
            command = ["-C", str(work_dir)] + command
        return self.run(["git"] + command, work_dir=work_dir, **kwargs)

    def chdir(
        self,
        path: Path,
        mkdir: Optional[bool] = False,
        may_fail: Optional[bool] = False,
    ) -> bool:
        """Change directory to path, optionally creating it if it does not exist"""
        if os.getcwd() == str(path):
            log.debug("Already in directory %s, skipping chdir", path)
            return True

        if not path.exists():
            if mkdir:
                self.mkdir(path)
            else:
                log.error("Path %s does not exist, cannot chdir", path)
                if not may_fail:
                    die(f"Path {path} does not exist, stopping")
                return False

        self._print_cmd([f"cd {path}"])
        if self.dry_run:
            return True

        os.chdir(path)
        return True

    def rm(self, path: Path, recursive: Optional[bool] = False) -> bool:
        """Remove path, optionally recursively"""
        if not path.exists():
            log.debug("Path %s does not exist, skipping delete", path)
            return True

        self._print_rm(path, recursive)
        if self.dry_run:
            return True

        if recursive:
            shutil.rmtree(path)
        else:
            path.unlink()
        return True

    def mkdir(self, path: Path, parents: Optional[bool] = False) -> bool:
        """Create path, optionally creating parent directories"""
        if path.exists():
            log.debug("Path %s already exists, skipping mkdir", path)
            return True

        self._print_mkdir(path, parents)
        if self.dry_run:
            return True

        path.mkdir(parents=parents)
        return True

    def copy(self, src: Path, dst: Path) -> bool:
        """Copy a file from src to dst, creating parent directories as needed"""
        self._print_cmd([f"cp {src} {dst}"])
        if self.dry_run:
            return True

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True

    def on_ubuntu(self) -> bool:
        """Check if running on Ubuntu"""
        if self.on_windows:
            return False
        try:
            result = self.run(["uname", "-a"], capture_output=True)
            stdout = result.stdout
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            return "Ubuntu" in stdout
        except FileNotFoundError:
            return False

    def on_ubuntu_desktop(self) -> bool:
        """Check if running on Ubuntu Desktop"""
        if self.on_windows:
            return False
        if not self.on_ubuntu():
            log.info("Not running on Ubuntu")
            return False

        session_type = os.getenv("XDG_SESSION_TYPE")
        if session_type not in ["x11", "wayland"]:
            log.info("Not running on X11/Wayland")
            return False
        return True

    def which(self, command: str) -> Optional[str]:
        """Find the path to a command"""
        return shutil.which(command)

    def _print_cmd(self, command: Iterable[str]) -> None:
        cmd_str: str = " ".join([str(c) for c in command])
        log.debug("_print_cmd: %s", cmd_str)
        if self.verbose or self.dry_run:
            print(cmd_str)

    def _print_rm(self, path: Path, recursive: Optional[bool] = False) -> None:
        if self.quiet:
            return

        if recursive:
            self._print_cmd([f"rm -rf {path}"])
        else:
            self._print_cmd([f"rm -f {path}"])

    def _print_mkdir(self, path: Path, parents: Optional[bool] = False) -> None:
        if self.quiet:
            return

        if parents:
            self._print_cmd([f"mkdir -p {path}"])
        else:
            self._print_cmd([f"mkdir {path}"])

    def _error_or_die(
        self, msg: str, is_fatal: Optional[bool] = False, exit_code: Optional[int] = 1
    ) -> None:
        if is_fatal:
            die(msg, exit_code)
        else:
            log.error(msg)

    def _check_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False
    ) -> bool:
        if self._always_sudo or force_sudo:
            return True

        if self.dry_run:
            log.info("Dry run, skipping sudo check")
            return True

        choice = prompt_yes_no_always(f"Going to run {' '.join(command)}")
        if choice.always:
            self._always_sudo = True
        return choice.yes
