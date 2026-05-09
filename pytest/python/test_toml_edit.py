# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for pyishlib._toml_edit (surgical TOML editing helpers)."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib import _compat
from pyishlib._compat import HAS_TOML
from pyishlib._toml_edit import replace_or_append_section, set_kv_in_text


class TestReplaceOrAppendSection(unittest.TestCase):
    def test_replaces_existing_section_body(self) -> None:
        text = '[ishfiles]\nsource = "/tmp"\n'
        new = replace_or_append_section(text, "ishfiles", '[ishfiles]\nsource = "/x"\n')
        self.assertEqual(new, '[ishfiles]\nsource = "/x"\n')

    def test_appends_when_section_missing(self) -> None:
        text = '[ishfiles]\nsource = "/tmp"\n'
        new = replace_or_append_section(text, "data", '[data]\nemail = "x"\n')
        self.assertIn('[data]\nemail = "x"\n', new)
        self.assertIn('source = "/tmp"', new)
        # Blank-line separator between original and appended block.
        self.assertIn("\n\n[data]", new)

    def test_preserves_inline_brackets_in_body(self) -> None:
        """`[` inside an inline array must not truncate the section body."""
        text = (
            "[ishfiles]\n"
            'source = "/tmp"\n'
            "\n"
            "[ignore]\n"
            'patterns = ["*.bak", "[draft]*"]\n'
            "\n"
            "[data]\n"
            'email = "x"\n'
        )
        new = replace_or_append_section(text, "ignore", "[ignore]\nreplaced = true\n")
        # Trailing [data] section survived intact.
        self.assertIn("[data]", new)
        self.assertIn('email = "x"', new)
        # Old patterns line is gone.
        self.assertNotIn("patterns =", new)
        # Earlier [ishfiles] section untouched.
        self.assertIn('source = "/tmp"', new)

    def test_only_replaces_first_match(self) -> None:
        # Defensive: a duplicate header (invalid TOML, but possible in
        # corrupted files) should not cascade across the whole file.
        text = "[s]\na = 1\n[s]\nb = 2\n"
        new = replace_or_append_section(text, "s", "[s]\nx = 0\n")
        self.assertIn("[s]\nx = 0\n", new)
        # The second [s] block is left alone.
        self.assertIn("b = 2", new)

    def test_empty_text_appends_block(self) -> None:
        new = replace_or_append_section("", "data", '[data]\nk = "v"\n')
        self.assertEqual(new, '[data]\nk = "v"\n')


class TestSetKvInText(unittest.TestCase):
    def test_replaces_existing_key_line(self) -> None:
        text = '[ishfiles]\nsource = "/old"\n'
        new = set_kv_in_text(text, "ishfiles", "source", "/new")
        self.assertIn('source = "/new"', new)
        self.assertNotIn('source = "/old"', new)

    def test_appends_section_when_missing(self) -> None:
        text = '[ishfiles]\nsource = "/x"\n'
        new = set_kv_in_text(text, "data", "email", "me@example.com")
        self.assertIn("[data]", new)
        self.assertIn('email = "me@example.com"', new)
        # Original line untouched.
        self.assertIn('source = "/x"', new)

    def test_inserts_in_existing_section_when_key_missing(self) -> None:
        text = '[data]\ncount = 42\n\n[ishfiles]\nsource = "/x"\n'
        new = set_kv_in_text(text, "data", "email", "me@example.com")
        # New key inserted INSIDE [data] (before the trailing blank line),
        # not appended at the end of the file.
        self.assertLess(new.find("email ="), new.find("[ishfiles]"))
        self.assertIn("count = 42", new)

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_preserves_sibling_non_string_values(self) -> None:
        text = (
            "[data]\n"
            "count = 42\n"
            "enabled = true\n"
            'tags = ["a", "b"]\n'
            'email = "old@example.com"\n'
        )
        new = set_kv_in_text(text, "data", "email", "new@example.com")
        parsed = _compat.tomllib.loads(new)
        self.assertEqual(
            parsed["data"],
            {
                "count": 42,
                "enabled": True,
                "tags": ["a", "b"],
                "email": "new@example.com",
            },
        )

    def test_preserves_comments_and_blank_lines(self) -> None:
        text = (
            "# Top comment\n"
            "[ishfiles]\n"
            "# inline comment\n"
            'source = "/old"\n'
            "\n"
            "[data]\n"
            'email = "x"\n'
        )
        new = set_kv_in_text(text, "ishfiles", "source", "/new")
        self.assertIn("# Top comment", new)
        self.assertIn("# inline comment", new)
        self.assertIn('source = "/new"', new)
        self.assertNotIn('source = "/old"', new)

    def test_escapes_special_characters(self) -> None:
        text = ""
        tricky = 'a"b\\c\nd'
        new = set_kv_in_text(text, "data", "note", tricky)
        if HAS_TOML:
            self.assertEqual(_compat.tomllib.loads(new), {"data": {"note": tricky}})
        # Otherwise just ensure raw special chars don't appear unescaped.
        else:
            self.assertNotIn("\n", new[len('[data]\nnote = "') :].rstrip())


if __name__ == "__main__":
    unittest.main()
