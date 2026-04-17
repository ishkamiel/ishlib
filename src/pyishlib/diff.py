# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Diff utilities for comparing files.

Provides :func:`print_diff` which uses ``git diff --no-index`` for
coloured, familiar output and falls back to Python's :mod:`difflib`
when git is not available.

.. note::

   The git backend uses file paths as diff headers; the *old_label* and
   *new_label* parameters are only honoured by the Python fallback.
"""

from __future__ import annotations

import difflib
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def print_diff(
    old: Path,
    new: Path,
    old_label: str,
    new_label: str,
    force_python: bool = False,
) -> None:
    """Print a unified diff between two files.

    Tries ``git diff --no-index`` first for coloured output.  Falls back
    to :func:`difflib.unified_diff` when git is unavailable or fails.

    The *old_label* and *new_label* are used in the Python fallback's
    ``---`` / ``+++`` headers; git uses the actual file paths instead.
    Callers that need the labels honoured (e.g. because *old* or *new*
    is a temporary file that does not represent a meaningful path)
    should pass ``force_python=True`` to skip the git backend.

    Args:
        old:          Path to the "before" file.
        new:          Path to the "after" file.
        old_label:    Label for the ``---`` header (Python fallback only).
        new_label:    Label for the ``+++`` header (Python fallback only).
        force_python: When *True*, skip the git backend so the caller-
                      supplied labels are used verbatim.
    """
    if not force_python and _git_diff(old, new):
        return
    _python_diff(old, new, old_label, new_label)


def print_new_file(new: Path, new_label: str) -> None:
    """Print the contents of a new file as a diff against ``/dev/null``.

    Tries ``git diff --no-index`` first, falls back to a simple ``+``
    prefix display.

    Args:
        new:       Path to the new file.
        new_label: Label for the ``+++`` header (Python fallback only).
    """
    if _git_diff(Path(os.devnull), new):
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

_GIT_AVAILABLE: bool | None = None


def _has_git() -> bool:
    """Check (and cache) whether git is on PATH."""
    global _GIT_AVAILABLE
    if _GIT_AVAILABLE is None:
        _GIT_AVAILABLE = shutil.which("git") is not None
    return _GIT_AVAILABLE


def _git_diff(old: Path, new: Path) -> bool:
    """Try ``git diff --no-index``.  Returns True on success."""
    if not _has_git():
        return False
    color = "always" if sys.stdout.isatty() else "never"
    try:
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "diff",
                "--no-index",
                f"--color={color}",
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
    print("--- /dev/null")
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
