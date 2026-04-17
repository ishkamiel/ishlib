# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Engine for fetching, applying, and updating externals git-repo entries.

Public API
----------
- :class:`ExternalsEngine` -- fetch / apply / update one external at a time.
- :func:`copy_tree_nondestructive` -- per-file, never-prune copy helper.
- :class:`FetchResult` -- result of :meth:`ExternalsEngine.fetch`.
- :class:`ApplyResult` -- result of :meth:`ExternalsEngine.apply`.
- :class:`UpdateCandidate` -- result of :meth:`ExternalsEngine.check_update`.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from ..command_runner import CommandRunner
from .externals_config import ExternalSpec
from .externals_state import ExternalsState

log = logging.getLogger(__name__)

# Built-in exclusion patterns applied before user-supplied ones.
_DEFAULT_EXCLUDES = {".git", ".github", "__pycache__"}
_DEFAULT_EXCLUDE_GLOBS: tuple = ("*.pyc",)

_PRERELEASE_RE = re.compile(r"(?i)(rc|alpha|beta|dev|pre|preview|snapshot|nightly)")


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Result of a single :meth:`ExternalsEngine.fetch` call.

    Attributes:
        path:         Relative target path (TOML key).
        commit_sha:   Resolved git commit SHA after checkout.
        fetched:      ``True`` if a remote fetch was performed.
        cache_dir:    Path to the local git clone.
    """

    path: str
    commit_sha: str
    fetched: bool
    cache_dir: Path


@dataclass
class ApplyResult:
    """Result of a single :meth:`ExternalsEngine.apply` call.

    Attributes:
        path:         Relative target path.
        copied:       Number of files written to the target.
        skipped:      Number of files unchanged (hash match).
        created_dirs: Number of new directories created in the target.
    """

    path: str
    copied: int = 0
    skipped: int = 0
    created_dirs: int = 0


@dataclass
class UpdateCandidate:
    """A newer tag is available for an external.

    Attributes:
        path:        Relative target path.
        current_rev: Currently pinned revision.
        latest_tag:  Latest available stable tag from the remote.
    """

    path: str
    current_rev: str
    latest_tag: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ExternalsEngine:
    """Fetch, apply, and update external git-repo entries.

    Args:
        cfg:     :class:`~pyishlib.ish_config.IshConfig` providing ``source``,
                 ``target``, and constants.
        runner:  :class:`~pyishlib.command_runner.CommandRunner` for all
                 subprocess and file operations (respects dry-run).
        state:   :class:`~.externals_state.ExternalsState` for fetch
                 timestamps and commit SHAs.
    """

    def __init__(self, cfg, runner: CommandRunner, state: ExternalsState) -> None:
        self._cfg = cfg
        self._runner = runner
        self._state = state

    # -- public ----------------------------------------------------------------

    def fetch(self, spec: ExternalSpec, force: bool = False) -> FetchResult:
        """Ensure the local clone exists and is checked out at ``spec.revision``.

        Args:
            spec:  External specification.
            force: When ``True``, skip the refresh-period check and always
                   re-fetch from the remote.

        Returns:
            A :class:`FetchResult` with the resolved commit SHA.
        """
        cache_dir = self._cache_dir(spec)
        needs_fetch = force or self._state.is_stale(spec.path, spec.refresh_period)

        verbose = getattr(self._cfg, "verbose", False)
        if not cache_dir.exists():
            log.info("Cloning %s into %s", spec.url, cache_dir)
            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            git_kwargs: dict = {} if verbose else {"capture_output": True, "text": True}
            try:
                self._runner.git(
                    [
                        "clone",
                        "--filter=blob:none",
                        "--no-checkout",
                        spec.url,
                        str(cache_dir),
                    ],
                    **git_kwargs,
                )
            except subprocess.CalledProcessError as exc:
                log.error(
                    "git clone failed for %s: %s\n%s",
                    spec.path,
                    exc,
                    getattr(exc, "stderr", "") or "",
                )
                raise
            needs_fetch = True  # always checkout after a fresh clone

        if needs_fetch:
            log.info("Fetching tags for %s", spec.path)
            git_kwargs = {} if verbose else {"capture_output": True, "text": True}
            try:
                self._runner.git(
                    ["fetch", "--tags", spec.url],
                    work_dir=cache_dir,
                    **git_kwargs,
                )
            except subprocess.CalledProcessError as exc:
                log.error(
                    "git fetch failed for %s: %s\n%s",
                    spec.path,
                    exc,
                    getattr(exc, "stderr", "") or "",
                )
                raise

        log.info("Checking out %s for %s", spec.revision, spec.path)
        git_kwargs = {} if verbose else {"capture_output": True, "text": True}
        try:
            self._runner.git(
                ["checkout", spec.revision],
                work_dir=cache_dir,
                **git_kwargs,
            )
        except subprocess.CalledProcessError as exc:
            log.error(
                "git checkout failed for %s: %s\n%s",
                spec.path,
                exc,
                getattr(exc, "stderr", "") or "",
            )
            raise

        # Resolve HEAD to a commit SHA.
        commit_sha = ""
        if not self._runner.dry_run:
            try:
                result = self._runner.git(
                    ["rev-parse", "HEAD"],
                    work_dir=cache_dir,
                    capture_output=True,
                    text=True,
                )
                commit_sha = result.stdout.strip()
            except subprocess.CalledProcessError:
                commit_sha = spec.revision  # fallback

        self._state.set(
            path=spec.path,
            revision=spec.revision,
            commit_sha=commit_sha,
            url=spec.url,
        )
        self._state.save()

        return FetchResult(
            path=spec.path,
            commit_sha=commit_sha,
            fetched=needs_fetch,
            cache_dir=cache_dir,
        )

    def apply(self, spec: ExternalSpec, target_root: Path) -> ApplyResult:
        """Copy the cached checkout into the target directory (non-destructive).

        Args:
            spec:        External specification.
            target_root: Root target directory (usually ``$HOME``).

        Returns:
            An :class:`ApplyResult` with copy/skip counts.
        """
        cache_dir = self._cache_dir(spec)
        src = cache_dir
        if spec.strip_prefix:
            src = cache_dir / spec.strip_prefix

        dst = (target_root / spec.path).expanduser().resolve()
        return copy_tree_nondestructive(
            src=src,
            dst=dst,
            runner=self._runner,
            include=spec.include,
            exclude=spec.exclude,
            label=spec.path,
        )

    def check_update(
        self,
        spec: ExternalSpec,
        include_prereleases: bool = False,
    ) -> Optional[UpdateCandidate]:
        """Query the remote for a newer stable tag.

        Args:
            spec:               External specification.
            include_prereleases: When ``True``, pre-release tags (rc, beta …)
                                 are also considered.

        Returns:
            An :class:`UpdateCandidate` when a newer tag exists, else ``None``.
        """
        log.info("Checking remote tags for %s", spec.path)
        try:
            result = self._runner.git(
                [
                    "ls-remote",
                    "--tags",
                    "--sort=-v:refname",
                    spec.url,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("git ls-remote failed for %s: %s", spec.path, exc)
            return None

        if result.returncode != 0:
            log.warning(
                "git ls-remote returned %d for %s", result.returncode, spec.path
            )
            return None

        tags = _parse_remote_tags(result.stdout)
        current_is_pre = bool(_PRERELEASE_RE.search(spec.revision))
        if not include_prereleases and not current_is_pre:
            tags = [t for t in tags if not _PRERELEASE_RE.search(t)]

        if not tags:
            return None

        latest = _pick_latest_tag(tags)
        if latest is None:
            return None

        if latest == spec.revision:
            return None

        # If the latest appears earlier in sort order than current (meaning
        # current is "newer" somehow), skip.
        try:
            if _tag_tuple(latest) <= _tag_tuple(spec.revision) and not current_is_pre:
                return None
        except (ValueError, TypeError):
            pass  # lexicographic fallback already handled in _pick_latest_tag

        return UpdateCandidate(
            path=spec.path,
            current_rev=spec.revision,
            latest_tag=latest,
        )

    def rewrite_revision(
        self, spec: ExternalSpec, new_tag: str, config_path: Path
    ) -> None:
        """Update the ``revision`` field for *spec* in ``externals.toml`` in-place.

        Preserves all other content (comments, whitespace, other sections).
        Handles both quoted (``[".fzf"]``) and unquoted TOML table keys.

        Args:
            spec:        External specification to update.
            new_tag:     New tag to write.
            config_path: Absolute path to ``externals.toml``.
        """
        text = config_path.read_text(encoding="utf-8")

        # TOML keys with dots or special chars are quoted: [".fzf"].
        # Match both [".fzf"] and [.fzf] (unquoted fallback).
        escaped = re.escape(spec.path)
        header_pattern = re.compile(
            r'^\["?' + escaped + r'"?\]',
            re.MULTILINE,
        )
        m = header_pattern.search(text)
        if not m:
            log.warning(
                "rewrite_revision: section for %r not found in %s",
                spec.path,
                config_path,
            )
            return

        section_start = m.end()
        # Find end of section (next table header or EOF)
        next_section = re.search(r"^\[", text[section_start:], re.MULTILINE)
        section_end = (
            section_start + next_section.start() if next_section else len(text)
        )

        section = text[section_start:section_end]
        new_section = re.sub(
            r'(revision\s*=\s*")[^"]*(")',
            rf"\g<1>{new_tag}\g<2>",
            section,
        )

        if new_section == section:
            log.warning(
                "rewrite_revision: 'revision' key not found in section for %r",
                spec.path,
            )
            return

        new_text = text[:section_start] + new_section + text[section_end:]
        config_path.write_text(new_text, encoding="utf-8")
        log.info("Updated %s revision: %s -> %s", spec.path, spec.revision, new_tag)

    # -- private ---------------------------------------------------------------

    def _cache_dir(self, spec: ExternalSpec) -> Path:
        cache_dir = (
            Path(self._cfg.get_opt("externals_cache_dir") or "").expanduser().resolve()
        )
        return cache_dir / spec.path.lstrip("/")


# ---------------------------------------------------------------------------
# copy_tree_nondestructive
# ---------------------------------------------------------------------------


def copy_tree_nondestructive(
    src: Path,
    dst: Path,
    runner: CommandRunner,
    include: Optional[Sequence[str]] = None,
    exclude: Optional[Sequence[str]] = None,
    label: str = "",
) -> ApplyResult:
    """Copy files from *src* into *dst* without deleting anything in *dst*.

    Change detection uses size + SHA-256 so that:
    - Git checkouts (which reset mtimes) do not trigger spurious rewrites.
    - User edits downstream (e.g. oh-my-zsh custom configs) are preserved.

    Files in *dst* that have no counterpart in *src* are left untouched.

    Args:
        src:     Source directory (local git checkout).
        dst:     Target directory.
        runner:  :class:`~pyishlib.command_runner.CommandRunner` used for
                 ``mkdir`` and ``copy`` operations (respects dry-run).
        include: If non-empty, only paths matching at least one glob are
                 copied.
        exclude: Additional glob patterns to exclude (beyond the built-in
                 ``.git``, ``.github``, ``__pycache__``, ``*.pyc``).
        label:   Human-readable label for log messages.

    Returns:
        :class:`ApplyResult` with copy/skip/dir counts.
    """
    result = ApplyResult(path=label)

    if not src.exists():
        log.warning("copy_tree_nondestructive: source %s does not exist", src)
        return result

    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        dir_rel = Path(dirpath).relative_to(src)

        # Prune reserved directory names from the walk (in-place).
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _DEFAULT_EXCLUDES and not _matches_any(d, exclude or [])
        ]

        for filename in filenames:
            rel = dir_rel / filename

            # Apply built-in glob excludes.
            if _matches_any(str(rel.name), _DEFAULT_EXCLUDE_GLOBS):
                continue
            # Apply user excludes.
            if exclude and _matches_any(str(rel), list(exclude)):
                continue
            # Apply user includes.
            if include and not _matches_any(str(rel), list(include)):
                continue

            src_file = src / rel
            dst_file = dst / rel

            # Handle symlinks in source.
            if src_file.is_symlink():
                link_target = os.readlink(src_file)
                if dst_file.is_symlink() and os.readlink(dst_file) == link_target:
                    result.skipped += 1
                    continue
                if runner.dry_run:
                    result.copied += 1
                    continue
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                if dst_file.exists() or dst_file.is_symlink():
                    dst_file.unlink()
                os.symlink(link_target, dst_file)
                result.copied += 1
                continue

            # Regular file: compare size + hash before copying.
            if dst_file.exists() and not dst_file.is_symlink():
                if dst_file.stat().st_size == src_file.stat().st_size and _sha256(
                    dst_file
                ) == _sha256(src_file):
                    result.skipped += 1
                    continue

            dst_file.parent.mkdir(parents=True, exist_ok=True)
            runner.copy(src_file, dst_file)
            result.copied += 1

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches_any(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_hash(path: Path) -> str:
    """Stable SHA-256 of all regular files under *path* (sorted by path)."""
    h = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file() and not file.is_symlink():
            rel = str(file.relative_to(path))
            h.update(rel.encode("utf-8"))
            h.update(_sha256(file).encode("utf-8"))
    return h.hexdigest()


def _parse_remote_tags(ls_remote_output: str) -> List[str]:
    """Extract and de-duplicate tag names from ``git ls-remote`` output."""
    seen: dict[str, None] = {}
    for line in ls_remote_output.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        ref = parts[1].strip()
        if "refs/tags/" not in ref:
            continue
        tag = ref.replace("refs/tags/", "").rstrip("^{}")
        # de-dup: keep first occurrence (ls-remote --sort=-v:refname gives
        # annotated "^{}" entries after the base ref; first = the base ref)
        if tag not in seen:
            seen[tag] = None
    return list(seen.keys())


def _tag_tuple(tag: str) -> tuple:
    """Convert a version tag to a comparable numeric tuple.

    Strips a leading ``v`` then splits on ``.``, ``-``, ``_``.
    Non-numeric components remain as strings (sorts after ints).
    """
    raw = tag.lstrip("vV")
    parts = re.split(r"[.\-_]", raw)
    result: List[tuple] = []
    for p in parts:
        try:
            result.append((0, int(p)))
        except ValueError:
            result.append((1, p))
    return tuple(result)


def _pick_latest_tag(tags: List[str]) -> Optional[str]:
    """Return the latest tag from *tags* using numeric version comparison.

    Falls back to lexicographic sort if numeric parsing fails entirely.

    Args:
        tags: List of tag strings (already filtered for prereleases if
              desired).

    Returns:
        The tag that sorts highest, or ``None`` when *tags* is empty.
    """
    if not tags:
        return None
    try:
        return max(tags, key=_tag_tuple)
    except TypeError:
        return sorted(tags)[-1]
