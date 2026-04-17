# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Persistent state for externals fetch/apply tracking.

Stores per-external records in
``<target>/.config/ishfiles/externals-state.json``.  Each record tracks:

- ``revision`` -- the pinned revision that was last fetched.
- ``commit_sha`` -- the resolved git commit SHA.
- ``url`` -- the clone URL (for sanity-checking).
- ``last_fetched`` -- Unix timestamp of the last successful fetch.

Public API
----------
- :class:`ExternalsState` -- load / save / query per-external records.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class ExternalsState:
    """Persistent state store for external git-repo records.

    Args:
        state_path: Path to the JSON state file.  Parent directories are
                    created on first :meth:`save`.
    """

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._data: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- factory ---------------------------------------------------------------

    @classmethod
    def from_cfg(cls, cfg) -> "ExternalsState":
        """Create an :class:`ExternalsState` rooted at *cfg*'s target home.

        Args:
            cfg: :class:`~pyishlib.ish_config.IshConfig` providing ``target``
                 and ``externals_state_filename``.
        """
        target = Path(cfg.get_opt("target") or Path.home()).expanduser().resolve()
        filename = cfg.get_opt("externals_state_filename")
        return cls(target / ".config" / "ishfiles" / filename)

    # -- public interface ------------------------------------------------------

    def get(self, path: str) -> Optional[Dict[str, Any]]:
        """Return the state record for *path*, or ``None`` if absent.

        Args:
            path: Relative target path (TOML key, e.g. ``".fzf"``).
        """
        return self._data.get(path)

    def set(
        self,
        path: str,
        revision: str,
        commit_sha: str,
        url: str,
        last_fetched: Optional[float] = None,
    ) -> None:
        """Record a successful fetch for *path*.

        Args:
            path:         Relative target path.
            revision:     Pinned revision (tag or SHA) that was checked out.
            commit_sha:   Resolved git commit SHA.
            url:          Clone URL (for sanity-checking on reload).
            last_fetched: Unix timestamp; defaults to ``time.time()``.
        """
        self._data[path] = {
            "revision": revision,
            "commit_sha": commit_sha,
            "url": url,
            "last_fetched": last_fetched if last_fetched is not None else time.time(),
        }

    def is_stale(self, path: str, refresh_period_secs: Optional[int]) -> bool:
        """Return ``True`` if the cached entry needs a remote re-fetch.

        An entry is stale when:
        - There is no record for *path*, or
        - *refresh_period_secs* is ``None`` (always refresh), or
        - More than *refresh_period_secs* seconds have elapsed since the
          last fetch.

        Args:
            path:                Relative target path.
            refresh_period_secs: Minimum gap in seconds between re-fetches.
        """
        record = self._data.get(path)
        if record is None:
            return True
        if refresh_period_secs is None:
            return True
        last = record.get("last_fetched", 0)
        return (time.time() - float(last)) >= refresh_period_secs

    def save(self) -> None:
        """Write the current state to :attr:`path` (atomic replace)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("Could not save externals state to %s: %s", self._path, exc)

    @property
    def path(self) -> Path:
        """Path to the backing JSON file."""
        return self._path

    # -- internals -------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Top-level JSON value is not an object")
            self._data = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            log.warning(
                "Could not load externals state from %s: %s — starting empty",
                self._path,
                exc,
            )
