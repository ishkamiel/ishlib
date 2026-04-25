# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for ishfiles.externals_state."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.externals_state import ExternalsState


def _make_cfg(tmp_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
        get_opt=lambda name, default=None: {
            "target": tmp_dir,
            "externals_state_filename": "externals-state.json",
        }.get(name, default)
    )


class TestExternalsStateBasics(unittest.TestCase):
    def test_get_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ExternalsState(Path(tmp) / "state.json")
            assert state.get(".fzf") is None

    def test_set_and_get_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = ExternalsState(path)
            state.set(".fzf", "v0.62.0", "abc123" * 6 + "abcd", "https://example.com")
            record = state.get(".fzf")
            assert record is not None
            assert record["revision"] == "v0.62.0"
            assert record["url"] == "https://example.com"

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = ExternalsState(path)
            state.set(".fzf", "v0.62.0", "abc123", "https://example.com")
            state.save()

            state2 = ExternalsState(path)
            record = state2.get(".fzf")
            assert record is not None
            assert record["revision"] == "v0.62.0"

    def test_save_is_atomic(self):
        """The state file is written atomically (tmp then rename)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = ExternalsState(path)
            state.set(".fzf", "v1", "sha1", "url")
            state.save()
            # Only the final file should exist; no stale .tmp
            assert path.exists()
            assert not path.with_suffix(".json.tmp").exists()

    def test_tolerant_of_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("not valid json {{{{", encoding="utf-8")
            with self.assertLogs(level="WARNING"):
                state = ExternalsState(path)
            assert state.get(".fzf") is None

    def test_tolerant_of_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertLogs(level="WARNING"):
                state = ExternalsState(path)
            assert state.get(".fzf") is None

    def test_missing_file_returns_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ExternalsState(Path(tmp) / "nonexistent.json")
            # No error, no log — just empty
            assert state.get(".anything") is None

    def test_from_cfg(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = str(Path(raw_tmp).resolve())
            cfg = _make_cfg(tmp)
            state = ExternalsState.from_cfg(cfg)
            assert state.path.name == "externals-state.json"
            assert ".config/ishfiles" in state.path.as_posix()


class TestExternalsStateStale(unittest.TestCase):
    def test_absent_entry_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ExternalsState(Path(tmp) / "state.json")
            assert state.is_stale(".fzf", 3600)

    def test_none_refresh_period_is_always_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ExternalsState(Path(tmp) / "state.json")
            state.set(".fzf", "v1", "sha", "url", last_fetched=time.time())
            assert state.is_stale(".fzf", None)

    def test_fresh_entry_is_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ExternalsState(Path(tmp) / "state.json")
            state.set(".fzf", "v1", "sha", "url", last_fetched=time.time())
            assert not state.is_stale(".fzf", 3600)

    def test_expired_entry_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ExternalsState(Path(tmp) / "state.json")
            # last_fetched far in the past
            state.set(".fzf", "v1", "sha", "url", last_fetched=time.time() - 7200)
            assert state.is_stale(".fzf", 3600)


if __name__ == "__main__":
    unittest.main()
