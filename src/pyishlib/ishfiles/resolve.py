#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Resolve user-supplied file paths to relative source paths.

Given a file argument that may refer to either a source file (inside the
dotfiles repository) or a target file (e.g. under ``$HOME``), determine
the corresponding relative path inside the source directory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from ..dotfile import reverse_translate_path, translate_path

log = logging.getLogger(__name__)


def resolve_file_arg(
    file_arg: str,
    source_dir: Path,
    target_dir: Path,
) -> Optional[Path]:
    """Resolve a single file argument to a relative source path.

    The argument may be:

    * An absolute or relative path under *source_dir* -- returned as-is
      (relative to source).
    * An absolute or relative path under *target_dir* -- reverse-translated
      (e.g. ``.bashrc`` becomes ``dot_bashrc``).
    * A bare filename -- tried first as a source-relative path, then as a
      target-relative path.

    Returns:
        The relative path inside the source directory, or *None* if the
        argument could not be resolved.
    """
    p = Path(file_arg).expanduser()

    # Absolute path under source_dir
    if p.is_absolute():
        try:
            return p.resolve().relative_to(source_dir.resolve())
        except ValueError:
            pass
        try:
            rel_target = p.resolve().relative_to(target_dir.resolve())
            return reverse_translate_path(rel_target)
        except ValueError:
            pass
        log.warning("Path %s is not under source or target directory", file_arg)
        return None

    # Relative path: check if it exists under source first
    if (source_dir / p).exists():
        return p

    # Try as a target-relative path (e.g. ".bashrc" -> "dot_bashrc")
    reverse = reverse_translate_path(p)
    if (source_dir / reverse).exists():
        return reverse

    # Try as already-translated source path
    if (source_dir / p).exists():
        return p

    # Last resort: return the reverse-translated version even if
    # the file doesn't exist yet (for add command)
    log.debug(
        "Could not verify %s in source; using reverse-translated: %s", file_arg, reverse
    )
    return reverse


def resolve_file_args(
    file_args: List[str],
    source_dir: Path,
    target_dir: Path,
) -> List[Path]:
    """Resolve multiple file arguments to relative source paths.

    Logs a warning and skips any argument that cannot be resolved.

    Returns:
        List of relative paths inside the source directory.
    """
    results: List[Path] = []
    for arg in file_args:
        resolved = resolve_file_arg(arg, source_dir, target_dir)
        if resolved is not None:
            results.append(resolved)
        else:
            log.warning("Skipping unresolvable file argument: %s", arg)
    return results
