#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for pyishlib.json_merge helpers.

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.json_merge import (
    canonical_json,
    deep_merge_json,
    semantic_equal,
)


class TestDeepMergeJson:
    def test_disjoint_keys_union(self):
        assert deep_merge_json({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_overlapping_scalar_patch_wins(self):
        assert deep_merge_json({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_object_deep_merge(self):
        base = {"nested": {"keep": 1, "replace": "old"}}
        patch = {"nested": {"replace": "new", "add": 3}}
        assert deep_merge_json(base, patch) == {
            "nested": {"keep": 1, "replace": "new", "add": 3}
        }

    def test_array_replaces_wholesale(self):
        assert deep_merge_json({"l": [1, 2, 3]}, {"l": [9]}) == {"l": [9]}

    def test_null_removes_key(self):
        assert deep_merge_json({"drop": 1, "keep": 2}, {"drop": None}) == {
            "keep": 2
        }

    def test_null_on_missing_key_is_noop(self):
        assert deep_merge_json({}, {"absent": None}) == {}

    def test_patch_replaces_when_either_side_not_dict(self):
        # List patch replaces dict base
        assert deep_merge_json({"a": 1}, [1, 2]) == [1, 2]
        # Dict patch replaces scalar base
        assert deep_merge_json(5, {"a": 1}) == {"a": 1}

    def test_does_not_mutate_inputs(self):
        base = {"nested": {"a": 1}}
        patch = {"nested": {"b": 2}}
        result = deep_merge_json(base, patch)
        assert base == {"nested": {"a": 1}}
        assert patch == {"nested": {"b": 2}}
        assert result == {"nested": {"a": 1, "b": 2}}


class TestCanonicalJson:
    def test_keys_are_sorted(self):
        out = canonical_json({"b": 1, "a": 2})
        # "a" must appear before "b"
        assert out.index('"a"') < out.index('"b"')

    def test_trailing_newline(self):
        assert canonical_json({}).endswith("\n")

    def test_preserves_unicode(self):
        assert "ä" in canonical_json({"k": "ä"})


class TestSemanticEqual:
    def test_equal_with_reordered_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text('{"a": 1, "b": 2}\n')
            b.write_text('{"b": 2, "a": 1}\n')
            assert semantic_equal(a, b) is True

    def test_list_order_matters(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text("[1, 2, 3]\n")
            b.write_text("[3, 2, 1]\n")
            assert semantic_equal(a, b) is False

    def test_missing_file_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            a.write_text("{}\n")
            assert semantic_equal(a, Path(tmp) / "missing.json") is False

    def test_invalid_json_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text("{}\n")
            b.write_text("not json")
            assert semantic_equal(a, b) is False

    def test_non_utf8_file_returns_false(self):
        """Binary / non-UTF-8 bytes must not propagate as an exception."""
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.json"
            b = Path(tmp) / "b.json"
            a.write_text("{}\n")
            b.write_bytes(b"\xff\xfe\x00\x00")
            assert semantic_equal(a, b) is False
