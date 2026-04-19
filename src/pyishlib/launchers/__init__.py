# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Launcher script generator for ishlib CLI tools.

Public API:

- :func:`render_launcher` — render the bash launcher for one tool.
- :func:`install_all` — write launchers for all registered tools into
  a destination directory.
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .. import tools as _tools
from ._template import TEMPLATE

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


def render_launcher(tool: "_tools.Tool", source_dir: Path) -> str:
    """Return the bash launcher script for *tool* as a string.

    Args:
        tool: A :class:`~pyishlib.tools.Tool` entry from the registry.
        source_dir: Absolute path to the ``src/`` directory that will be
            baked into the ``ISHLIB_SRC`` default in the generated script.

    Returns:
        The complete bash script as a string (including shebang).
    """
    return (
        TEMPLATE.replace("__TOOL_NAME__", tool.name)
        .replace("__TOOL_MODULE__", tool.module)
        .replace("__SOURCE_DIR__", str(source_dir))
    )


def install_all(
    dest_dir: Path,
    source_dir: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Write generated launchers for every registered tool into *dest_dir*.

    Creates *dest_dir* (and any missing parents) if it does not exist.
    Each generated script is written atomically via a temporary file and
    ``os.replace``, so a partially-written file is never visible. Existing
    files with identical content are skipped. Existing symlinks at the
    destination path are removed before writing.

    Args:
        dest_dir: Directory to write launchers into (e.g. ``~/.local/bin``).
        source_dir: Passed to :func:`render_launcher` as the baked-in
            ``ISHLIB_SRC`` default.
        dry_run: When ``True``, log what would happen but write nothing.

    Returns:
        0 on full success, 1 if any launcher could not be written.
    """
    if dry_run:
        for tool in _tools.all_tools():
            log.info("Would install launcher: %s", dest_dir / tool.name)
        return 0

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("Could not create launcher dir %s: %s", dest_dir, exc)
        return 1

    had_error = False
    for tool in _tools.all_tools():
        content = render_launcher(tool, source_dir)
        dest = dest_dir / tool.name

        if dest.is_symlink():
            dest.unlink()

        if dest.is_file():
            try:
                if dest.read_text() == content:
                    log.debug("Launcher already up to date: %s", dest)
                    continue
            except OSError:
                pass

        try:
            fd, tmp_path_str = tempfile.mkstemp(dir=dest_dir, prefix=f".{tool.name}.")
            tmp_path = Path(tmp_path_str)
            try:
                with os.fdopen(fd, "w") as fh:
                    fh.write(content)
                os.chmod(
                    tmp_path_str,
                    stat.S_IRWXU
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                    | stat.S_IROTH
                    | stat.S_IXOTH,
                )
                os.replace(tmp_path_str, dest)
                log.info("Installed launcher: %s", dest)
            except Exception:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
                raise
        except OSError as exc:
            log.warning("Failed to install launcher %s: %s", dest, exc)
            had_error = True

    return 1 if had_error else 0
