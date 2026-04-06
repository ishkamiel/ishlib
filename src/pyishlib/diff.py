#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Diff utilities for comparing files.

Provides :func:`print_diff` which uses ``git diff --no-index`` for
coloured, familiar output and falls back to Python's :mod:`difflib`
when git is not available.
"""

from __future__ import annotations

import difflib
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


def print_diff(old: Path, new: Path, old_label: str, new_label: str) -> None:
    """Print a unified diff between two files.

    Tries ``git diff --no-index`` first for coloured output.  Falls back
    to :func:`difflib.unified_diff` when git is unavailable or fails.

    Args:
        old:       Path to the "before" file (or ``/dev/null`` for new files).
        new:       Path to the "after" file.
        old_label: Label shown in the ``---`` header.
        new_label: Label shown in the ``+++`` header.
    """
    if _git_diff(old, new, old_label, new_label):
        return
    _python_diff(old, new, old_label, new_label)


def print_new_file(new: Path, new_label: str) -> None:
    """Print the contents of a new file as a diff against ``/dev/null``.

    Tries ``git diff --no-index`` first, falls back to a simple ``+``
    prefix display.

    Args:
        new:       Path to the new file.
        new_label: Label shown in the ``+++`` header.
    """
    if _git_diff(Path("/dev/null"), new, "/dev/null", new_label):
        return
    _python_new_file(new, new_label)


def print_binary_diff(old_label: str, new_label: str) -> None:
    """Print a notice that binary files differ."""
    print(f"--- {old_label}")
    print(f"+++ {new_label}")
    print("<binary files differ>")
    print()


# ---------------------------------------------------------------------------
# git diff backend
# ---------------------------------------------------------------------------

_git_available: bool | None = None


def _has_git() -> bool:
    """Check (and cache) whether git is on PATH."""
    global _git_available  # noqa: PLW0603
    if _git_available is None:
        _git_available = shutil.which("git") is not None
    return _git_available


def _git_diff(old: Path, new: Path, old_label: str, new_label: str) -> bool:
    """Try ``git diff --no-index``.  Returns True on success."""
    if not _has_git():
        return False
    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--",
                str(old),
                str(new),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # exit 0 = no diff, exit 1 = diff found, >1 = error
        if result.returncode > 1:
            log.debug("git diff failed (rc=%d): %s", result.returncode, result.stderr)
            return False
        if result.stdout:
            print(result.stdout, end="")
        return True
    except OSError:
        log.debug("git diff failed with OSError")
        return False


# ---------------------------------------------------------------------------
# Python fallback
# ---------------------------------------------------------------------------


def _python_diff(old: Path, new: Path, old_label: str, new_label: str) -> None:
    """Unified diff via difflib."""
    try:
        old_lines = old.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = new.read_text(encoding="utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        print_binary_diff(old_label, new_label)
        return

    diff = difflib.unified_diff(
        old_lines, new_lines, fromfile=old_label, tofile=new_label
    )
    diff_text = "".join(diff)
    if diff_text:
        print(diff_text)


def _python_new_file(new: Path, new_label: str) -> None:
    """Show a new file as all-added lines."""
    print(f"--- /dev/null")
    print(f"+++ {new_label}")
    try:
        lines = new.read_text(encoding="utf-8").splitlines(keepends=True)
        for line in lines:
            print(f"+{line}", end="")
        if lines and not lines[-1].endswith("\n"):
            print()
        print()
    except UnicodeDecodeError:
        print("+<binary file>")
        print()
