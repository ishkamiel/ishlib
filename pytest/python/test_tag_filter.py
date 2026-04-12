#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for the shared tag_filter module."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.tag_filter import passes_tags, tag_matches
from pyishlib.dotfile_context import DotfileContext


def _make_cfg(ctx_vars: dict, template: dict):
    """Build a minimal config-like object."""
    ctx = DotfileContext()
    ctx.update(ctx_vars)
    return SimpleNamespace(context=ctx, data_template=template)


_BOOL_TEMPLATE = {
    "isWork": {"type": "bool"},
    "isGaming": {"type": "bool"},
}

_ORDERED_TEMPLATE = {
    "machineType": {
        "type": "ordered_tags",
        "values": ["min", "def", "personal"],
    }
}

_TAGS_TEMPLATE = {
    "tier": {
        "type": "tags",
        "values": ["free", "pro", "enterprise"],
    }
}


class TestPassesTagsEmpty(unittest.TestCase):
    def test_empty_tags_always_passes(self):
        cfg = _make_cfg({}, {})
        assert passes_tags([], cfg)

    def test_none_cfg_empty_tags_passes(self):
        assert passes_tags([], None)


class TestPassesTagsBool(unittest.TestCase):
    def test_bool_tag_true(self):
        cfg = _make_cfg({"isWork": "true"}, _BOOL_TEMPLATE)
        assert passes_tags(["isWork"], cfg)

    def test_bool_tag_false(self):
        cfg = _make_cfg({"isWork": "false"}, _BOOL_TEMPLATE)
        assert not passes_tags(["isWork"], cfg)

    def test_bool_tag_unset_is_false(self):
        cfg = _make_cfg({}, _BOOL_TEMPLATE)
        assert not passes_tags(["isWork"], cfg)

    def test_negated_bool_when_false(self):
        cfg = _make_cfg({"isWork": "false"}, _BOOL_TEMPLATE)
        assert passes_tags(["!isWork"], cfg)

    def test_negated_bool_when_true(self):
        cfg = _make_cfg({"isWork": "true"}, _BOOL_TEMPLATE)
        assert not passes_tags(["!isWork"], cfg)

    def test_bool_accepts_yes_synonym(self):
        cfg = _make_cfg({"isWork": "yes"}, _BOOL_TEMPLATE)
        assert passes_tags(["isWork"], cfg)

    def test_bool_accepts_1_synonym(self):
        cfg = _make_cfg({"isWork": "1"}, _BOOL_TEMPLATE)
        assert passes_tags(["isWork"], cfg)

    def test_multiple_bool_tags_all_must_pass(self):
        cfg = _make_cfg({"isWork": "true", "isGaming": "false"}, _BOOL_TEMPLATE)
        assert not passes_tags(["isWork", "isGaming"], cfg)

    def test_multiple_bool_tags_all_true(self):
        cfg = _make_cfg({"isWork": "true", "isGaming": "true"}, _BOOL_TEMPLATE)
        assert passes_tags(["isWork", "isGaming"], cfg)


class TestPassesTagsOrderedTags(unittest.TestCase):
    def test_min_matches_when_current_is_min(self):
        cfg = _make_cfg({"machineType": "min"}, _ORDERED_TEMPLATE)
        assert passes_tags(["min"], cfg)

    def test_min_matches_when_current_is_def(self):
        cfg = _make_cfg({"machineType": "def"}, _ORDERED_TEMPLATE)
        assert passes_tags(["min"], cfg)

    def test_min_matches_when_current_is_personal(self):
        cfg = _make_cfg({"machineType": "personal"}, _ORDERED_TEMPLATE)
        assert passes_tags(["min"], cfg)

    def test_def_not_matches_when_current_is_min(self):
        cfg = _make_cfg({"machineType": "min"}, _ORDERED_TEMPLATE)
        assert not passes_tags(["def"], cfg)

    def test_def_matches_when_current_is_def(self):
        cfg = _make_cfg({"machineType": "def"}, _ORDERED_TEMPLATE)
        assert passes_tags(["def"], cfg)

    def test_def_matches_when_current_is_personal(self):
        cfg = _make_cfg({"machineType": "personal"}, _ORDERED_TEMPLATE)
        assert passes_tags(["def"], cfg)

    def test_personal_not_matches_when_current_is_min(self):
        cfg = _make_cfg({"machineType": "min"}, _ORDERED_TEMPLATE)
        assert not passes_tags(["personal"], cfg)

    def test_personal_not_matches_when_current_is_def(self):
        cfg = _make_cfg({"machineType": "def"}, _ORDERED_TEMPLATE)
        assert not passes_tags(["personal"], cfg)

    def test_personal_matches_when_current_is_personal(self):
        cfg = _make_cfg({"machineType": "personal"}, _ORDERED_TEMPLATE)
        assert passes_tags(["personal"], cfg)

    def test_unset_variable_does_not_match(self):
        cfg = _make_cfg({}, _ORDERED_TEMPLATE)
        assert not passes_tags(["def"], cfg)

    def test_case_insensitive_tag(self):
        cfg = _make_cfg({"machineType": "personal"}, _ORDERED_TEMPLATE)
        assert passes_tags(["Personal"], cfg)

    def test_case_insensitive_value(self):
        cfg = _make_cfg({"machineType": "DEF"}, _ORDERED_TEMPLATE)
        assert passes_tags(["def"], cfg)


class TestPassesTagsTagsType(unittest.TestCase):
    def test_exact_match(self):
        cfg = _make_cfg({"tier": "pro"}, _TAGS_TEMPLATE)
        assert passes_tags(["pro"], cfg)

    def test_no_match(self):
        cfg = _make_cfg({"tier": "free"}, _TAGS_TEMPLATE)
        assert not passes_tags(["pro"], cfg)

    def test_case_insensitive(self):
        cfg = _make_cfg({"tier": "PRO"}, _TAGS_TEMPLATE)
        assert passes_tags(["pro"], cfg)


class TestPassesTagsUnknown(unittest.TestCase):
    def test_unknown_tag_excluded(self):
        cfg = _make_cfg({}, _BOOL_TEMPLATE)
        assert not passes_tags(["totally_unknown"], cfg)

    def test_unknown_tag_produces_warning(self):
        cfg = _make_cfg({}, _BOOL_TEMPLATE)
        with self.assertLogs("pyishlib.tag_filter", level="WARNING"):
            passes_tags(["totally_unknown"], cfg)


class TestTagMatches(unittest.TestCase):
    def test_bool_true(self):
        cfg = _make_cfg({"isWork": "true"}, _BOOL_TEMPLATE)
        assert tag_matches("isWork", _BOOL_TEMPLATE, cfg=cfg)

    def test_bool_false(self):
        cfg = _make_cfg({"isWork": "false"}, _BOOL_TEMPLATE)
        assert not tag_matches("isWork", _BOOL_TEMPLATE, cfg=cfg)

    def test_ordered_tags_higher_implies_lower(self):
        cfg = _make_cfg({"machineType": "personal"}, _ORDERED_TEMPLATE)
        assert tag_matches("min", _ORDERED_TEMPLATE, cfg=cfg)
        assert tag_matches("def", _ORDERED_TEMPLATE, cfg=cfg)
        assert tag_matches("personal", _ORDERED_TEMPLATE, cfg=cfg)

    def test_ordered_tags_lower_does_not_imply_higher(self):
        cfg = _make_cfg({"machineType": "min"}, _ORDERED_TEMPLATE)
        assert tag_matches("min", _ORDERED_TEMPLATE, cfg=cfg)
        assert not tag_matches("def", _ORDERED_TEMPLATE, cfg=cfg)
        assert not tag_matches("personal", _ORDERED_TEMPLATE, cfg=cfg)


if __name__ == "__main__":
    unittest.main()
