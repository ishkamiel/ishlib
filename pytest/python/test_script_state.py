#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for ishfiles.script_state."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.script_state import ScriptState, hash_content


class TestHashContent(unittest.TestCase):
    def test_returns_hex_string(self):
        h = hash_content("hello")
        assert isinstance(h, str)
        assert len(h) == 64

    def test_same_content_same_hash(self):
        assert hash_content("abc") == hash_content("abc")

    def test_different_content_different_hash(self):
        assert hash_content("abc") != hash_content("xyz")


class TestScriptStateBasic(unittest.TestCase):
    def test_new_state_not_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            assert not state.seen("script.sh")

    def test_new_state_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            assert state.changed("script.sh", "content")

    def test_record_marks_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            state.record("script.sh", "content")
            assert state.seen("script.sh")

    def test_record_marks_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            state.record("script.sh", "content")
            assert not state.changed("script.sh", "content")

    def test_changed_after_content_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            state.record("script.sh", "v1")
            assert state.changed("script.sh", "v2")

    def test_clear_one_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            state.record("a.sh", "content_a")
            state.record("b.sh", "content_b")
            state.clear("a.sh")
            assert not state.seen("a.sh")
            assert state.seen("b.sh")

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = ScriptState(Path(tmp) / "state.json")
            state.record("a.sh", "x")
            state.record("b.sh", "y")
            state.clear()
            assert not state.seen("a.sh")
            assert not state.seen("b.sh")


class TestScriptStatePersistence(unittest.TestCase):
    def test_state_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subdir" / "state.json"
            state1 = ScriptState(path)
            state1.record("myscript.sh", "body")

            state2 = ScriptState(path)
            assert state2.seen("myscript.sh")
            assert not state2.changed("myscript.sh", "body")

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a" / "b" / "c" / "state.json"
            state = ScriptState(path)
            state.record("x.sh", "content")
            assert path.is_file()

    def test_saved_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = ScriptState(path)
            state.record("s.sh", "code")
            data = json.loads(path.read_text())
            assert "s.sh" in data
            assert len(data["s.sh"]) == 64  # sha256 hex

    def test_corrupt_json_gracefully_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("not json!", encoding="utf-8")
            state = ScriptState(path)  # should not raise
            assert not state.seen("anything")

    def test_missing_file_is_empty_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.json"
            state = ScriptState(path)
            assert not state.seen("x.sh")


class TestScriptStateFromCfg(unittest.TestCase):
    def test_from_cfg_uses_target(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as tmp:
            cfg = SimpleNamespace(
                get_opt=lambda name, default=None: str(tmp) if name == "target" else None,
            )
            state = ScriptState.from_cfg(cfg)
            assert str(tmp) in str(state.path)


if __name__ == "__main__":
    unittest.main()
