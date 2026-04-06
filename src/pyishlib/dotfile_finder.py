#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Dotfile path resolution and lookup.

Provides :class:`DotfileFinder` which centralises path resolution between
a dotfile source repository and a target directory.  Given any path -- an
absolute source or target path, a relative source name like ``dot_bashrc``,
or a target name like ``.bashrc`` -- :meth:`DotfileFinder.get` returns a
fully resolved :class:`~pyishlib.dotfile.DotFile` object.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence

from .dotfile import DotFile, reverse_translate_path, translate_path
from .ish_config import IshConfig

log = logging.getLogger(__name__)


class DotfileFinder:
    """Resolve arbitrary file paths to :class:`DotFile` objects.

    Encapsulates the source/target directories and all ``dot_``
    translation logic so that callers never need to deal with raw
    path manipulation.

    Args:
        cfg: Shared configuration.  ``source`` and ``target`` are read
             from it unless the explicit keyword arguments are given.
        source_dir: Override for the source directory.
        target_dir: Override for the target directory.
    """

    def __init__(
        self,
        cfg: IshConfig,
        source_dir: Optional[Path] = None,
        target_dir: Optional[Path] = None,
    ) -> None:
        self._cfg = cfg
        self._source_dir = (
            source_dir
            if source_dir is not None
            else Path(cfg.get_opt("source")).expanduser()
        )
        self._target_dir = (
            target_dir
            if target_dir is not None
            else Path(cfg.get_opt("target")).expanduser()
        )

    @property
    def source_dir(self) -> Path:
        """Root of the dotfile source repository."""
        return self._source_dir

    @property
    def target_dir(self) -> Path:
        """Target installation directory (typically ``$HOME``)."""
        return self._target_dir

    # ------------------------------------------------------------------
    # Single-file resolution
    # ------------------------------------------------------------------

    def get(self, path: str) -> Optional[DotFile]:
        """Resolve *path* to a :class:`DotFile`.

        *path* may be:

        * An absolute path under *source_dir* or *target_dir*.
        * A relative source name (e.g. ``dot_bashrc``).
        * A relative target name (e.g. ``.bashrc``).
        * A path relative to CWD that falls under source or target.

        Returns:
            A :class:`DotFile`, or *None* when the path cannot be
            resolved to anything meaningful.
        """
        rel = self._resolve_to_source_rel(path)
        if rel is None:
            return None
        source = self._source_dir / rel
        return DotFile(source, rel, self._target_dir)

    def get_all(self, paths: Sequence[str]) -> List[DotFile]:
        """Resolve multiple paths, skipping those that cannot be resolved.

        A warning is logged for each unresolvable path.
        """
        results: List[DotFile] = []
        for p in paths:
            df = self.get(p)
            if df is not None:
                results.append(df)
            else:
                log.warning("Skipping unresolvable path: %s", p)
        return results

    def get_rel_paths(self, paths: Sequence[str]) -> List[Path]:
        """Resolve multiple paths to relative source paths.

        Convenience wrapper that returns just the relative paths
        (for feeding into :meth:`DotfileApplier.discover`).
        """
        results: List[Path] = []
        for p in paths:
            rel = self._resolve_to_source_rel(p)
            if rel is not None:
                results.append(rel)
            else:
                log.warning("Skipping unresolvable path: %s", p)
        return results

    def translate_arg(self, arg: str) -> str:
        """Translate a single CLI argument if it looks like a file path.

        If *arg* resolves to a known dotfile, return the path relative
        to the source directory.  Otherwise return *arg* unchanged.
        This is useful for rewriting path arguments in pass-through
        commands (e.g. ``ishfiles git``).
        """
        rel = self._resolve_to_source_rel(arg)
        if rel is not None:
            return str(rel)
        return arg

    # ------------------------------------------------------------------
    # Internal resolution
    # ------------------------------------------------------------------

    def _resolve_to_source_rel(self, path: str) -> Optional[Path]:
        """Turn an arbitrary path string into a relative source path.

        Resolution order:

        1. Absolute path under source_dir → relative to source.
        2. Absolute path under target_dir → reverse-translate.
        3. Relative path that exists under source_dir → as-is.
        4. Relative path whose reverse-translation exists under
           source_dir → reverse-translated.
        5. As a last resort return the reverse-translated form even if
           the file does not yet exist (useful for ``add``).
        """
        p = Path(path).expanduser()

        if p.is_absolute():
            return self._resolve_absolute(p)
        return self._resolve_relative(p)

    def _resolve_absolute(self, p: Path) -> Optional[Path]:
        """Resolve an absolute path."""
        resolved = p.resolve()
        try:
            return resolved.relative_to(self._source_dir.resolve())
        except ValueError:
            pass
        try:
            rel_target = resolved.relative_to(self._target_dir.resolve())
            return reverse_translate_path(rel_target)
        except ValueError:
            pass
        log.warning(
            "Absolute path %s is not under source (%s) or target (%s)",
            p,
            self._source_dir,
            self._target_dir,
        )
        return None

    def _resolve_relative(self, p: Path) -> Optional[Path]:
        """Resolve a relative path."""
        # Direct match in source
        if (self._source_dir / p).exists():
            return p

        # Target name → reverse translate
        reverse = reverse_translate_path(p)
        if (self._source_dir / reverse).exists():
            return reverse

        # Last resort: return reverse-translated even if it doesn't exist
        log.debug(
            "Could not verify %s in source; using reverse-translated: %s",
            p,
            reverse,
        )
        return reverse
