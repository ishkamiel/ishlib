#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Persistent state for ``run_once`` / ``run_onchange`` script gating.

Stores a ``{script_name: sha256_hex}`` mapping in a JSON file under
``<target>/.config/ishfiles/script-state.json``.  A sha256 of the
preprocessed script content is used as the change-detection key so that
edits to a script body (or to its ``@ish`` variables) trigger a re-run
even if the file modification time has not changed.

Public API
----------
- :class:`ScriptState` -- load / save / query per-script hashes.
- :func:`hash_content`  -- produce the sha256 digest for a script text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger(__name__)

_STATE_FILE_SUFFIX = ".config/ishfiles/script-state.json"


def hash_content(text: str) -> str:
    """Return the SHA-256 hex digest of *text*.

    Args:
        text: Preprocessed script content (UTF-8 string).

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ScriptState:
    """Persistent hash store for ``run_once`` / ``run_onchange`` gating.

    Args:
        state_path: Path to the JSON state file.  Parent directories
                    are created on first :meth:`save`.
    """

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._data: Dict[str, str] = {}
        self._load()

    # -- factory ---------------------------------------------------------------

    @classmethod
    def from_cfg(cls, cfg) -> "ScriptState":
        """Create a :class:`ScriptState` rooted at ``cfg``'s target home.

        Args:
            cfg: :class:`~pyishlib.ish_config.IshConfig` providing ``target``.
        """
        target = Path(cfg.get_opt("target") or Path.home()).expanduser().resolve()
        return cls(target / _STATE_FILE_SUFFIX)

    # -- public interface ------------------------------------------------------

    def seen(self, script_name: str) -> bool:
        """True if *script_name* has ever run successfully.

        Used for ``run_when = "once"`` gating.

        Args:
            script_name: The bare script filename (e.g. ``"00_init.sh"``).
        """
        return script_name in self._data

    def changed(self, script_name: str, content: str) -> bool:
        """True if *content* differs from the last recorded hash.

        Used for ``run_when = "onchange"`` gating.  Returns ``True`` when
        the script has never run (no stored hash).

        Args:
            script_name: The bare script filename.
            content:     Preprocessed script text to compare.
        """
        stored = self._data.get(script_name)
        return stored is None or stored != hash_content(content)

    def record(self, script_name: str, content: str) -> None:
        """Update the stored hash for *script_name* and save to disk.

        Call after a script completes successfully.

        Args:
            script_name: The bare script filename.
            content:     Preprocessed script text that was executed.
        """
        self._data[script_name] = hash_content(content)
        self.save()

    def clear(self, script_name: Optional[str] = None) -> None:
        """Remove stored state for one script or all scripts.

        Clears the stored hash so the script will run on the next invoke
        (regardless of ``run_when``).

        Args:
            script_name: If provided, clear only this script; otherwise
                         clear all entries.
        """
        if script_name is None:
            self._data.clear()
        elif script_name in self._data:
            del self._data[script_name]
        self.save()

    def save(self) -> None:
        """Write the current state to :attr:`path`."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(self._data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            log.warning("Could not save script state to %s: %s", self._path, exc)

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
            if isinstance(raw, dict):
                self._data = {k: v for k, v in raw.items() if isinstance(v, str)}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            log.warning("Could not load script state from %s: %s", self._path, exc)
