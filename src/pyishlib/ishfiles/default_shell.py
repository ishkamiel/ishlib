# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Phase 6 of ``ishfiles apply`` -- set the user's login shell.

Applies the ``[ishfiles] default_shell`` option from the main config by
invoking ``chsh -s <path>``.  Designed to be safe by default:

- Reads the current **login** shell from ``/etc/passwd`` (not ``$SHELL``)
  and does nothing if it already matches the desired shell by basename.
- Resolves a bare name via ``shutil.which`` and verifies absolute paths
  exist before calling ``chsh``.
- Skips cleanly (rc 0) when the shell or ``chsh`` itself is unavailable
  so containers without the desired shell don't fail the pipeline.
- Prompts for confirmation when the resolved path lives outside the
  standard directories and is not listed in ``/etc/shells``.
- Honours dry-run / verbose / quiet via :class:`CommandRunner`.

Public API
----------
- :func:`apply_default_shell_stage` -- entry point called from ``apply.run``.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from ..command_runner import CommandRunner
from ..environment import is_windows
from ..ish_config import IshConfig
from ..userio import prompt_yes_no_always

log = logging.getLogger(__name__)

# Directories that are considered safe homes for a login shell without
# extra confirmation from the user.  Paths outside these directories
# trigger a prompt unless they are listed in /etc/shells.
_SAFE_DIRS = frozenset(
    {
        "/bin",
        "/usr/bin",
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/opt/local/bin",
    }
)

_ETC_SHELLS = Path("/etc/shells")


def _current_login_shell(username: Optional[str] = None) -> Optional[str]:
    """Return the login shell for *username* (or the current user) from ``/etc/passwd``.

    When *username* is given, the lookup is by name (``getpwnam``); otherwise
    it falls back to the current UID (``getpwuid``).  Returns *None* when the
    passwd entry cannot be read (e.g. the ``pwd`` module is unavailable on
    Windows, or the entry does not exist).
    """
    try:
        import pwd  # local import: module is POSIX-only
    except ImportError:
        return None
    try:
        entry = pwd.getpwnam(username) if username else pwd.getpwuid(os.getuid())
    except KeyError:
        return None
    shell = entry.pw_shell or ""
    return shell or None


def _resolve_target_shell(desired: str) -> Optional[Path]:
    """Resolve *desired* to an absolute shell path, or *None* if not found.

    - Absolute paths are returned as-is when the target exists.
    - Bare names (e.g. ``"zsh"``) are resolved via :func:`shutil.which`.
    """
    d = desired.strip()
    if not d:
        return None
    if os.path.isabs(d):
        p = Path(d)
        return p if p.exists() else None
    found = shutil.which(d)
    return Path(found) if found else None


def _read_etc_shells() -> List[str]:
    """Return the non-comment, non-blank lines of ``/etc/shells``.

    Returns an empty list if the file is missing or unreadable.
    """
    try:
        text = _ETC_SHELLS.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return []
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _is_safe_location(path: Path) -> bool:
    """True if *path* is in a standard shell directory or ``/etc/shells``.

    The ``/etc/shells`` match is against the *unresolved* string so that
    symlink-based entries (``/usr/bin/zsh`` -> ``/usr/bin/zsh-5.9``)
    still match when the file lists the symlink.
    """
    if str(path.parent) in _SAFE_DIRS:
        return True
    shells = _read_etc_shells()
    return str(path) in shells


def apply_default_shell_stage(cfg: IshConfig) -> int:
    """Phase 6: set the login shell to ``default_shell`` if configured.

    Returns 0 on success or clean no-op, 1 on unexpected error.
    """
    try:
        raw = cfg.get_opt("default_shell", default=None)
        desired = (raw or "").strip() if isinstance(raw, str) else ""
        if not desired:
            return 0

        if is_windows():
            log.info("default_shell: no-op on Windows")
            return 0

        username: Optional[str] = cfg.get_opt("custom_username", default=None) or None
        current = _current_login_shell(username)
        if current and Path(current).name == Path(desired).name:
            log.info("Login shell already %s, skipping", current)
            return 0

        resolved = _resolve_target_shell(desired)
        if resolved is None:
            if os.path.isabs(desired):
                log.info("default_shell path %r does not exist; skipping", desired)
            else:
                log.info("default_shell %r not found on PATH; skipping", desired)
            return 0

        if not _is_safe_location(resolved):
            if not cfg.get_opt("yes", default=False):
                choice = prompt_yes_no_always(
                    f"Shell {resolved} is not in a standard location or "
                    "/etc/shells. Use anyway?"
                )
                if choice.no:
                    log.info("Skipping default_shell change (user declined)")
                    return 0

        runner = CommandRunner(cfg)
        chsh_argv = ["chsh", "-s", str(resolved)]
        if username:
            chsh_argv.append(username)
        try:
            result = runner.run(
                chsh_argv,
                check=False,
                quiet=cfg.quiet,
            )
        except FileNotFoundError:
            log.info("chsh not found; skipping default_shell change")
            return 0

        if result.returncode != 0:
            log.warning(
                "chsh failed (rc=%d) while setting login shell to %s",
                result.returncode,
                resolved,
            )
            return 1

        if not cfg.dry_run:
            log.info("Login shell changed to %s", resolved)
        return 0
    except Exception as exc:  # noqa: BLE001 - phase must not raise
        log.warning("default_shell stage failed: %s", exc)
        return 1
