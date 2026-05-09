# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for pyishlib._compat TOML loader helpers."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib import _compat
from pyishlib._compat import (
    HAS_TOML,
    is_toml_bare_key,
    load_toml_file,
    load_toml_file_strict,
    toml_escape_basic_string,
)


class TestLoadTomlFile(unittest.TestCase):
    """Tests for the soft loader :func:`load_toml_file`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_happy_path_returns_parsed_dict(self) -> None:
        path = self.tmp_path / "ok.toml"
        path.write_text('key = "value"\n[sect]\nn = 1\n', encoding="utf-8")

        result = load_toml_file(path, default={})

        self.assertEqual(result, {"key": "value", "sect": {"n": 1}})

    def test_missing_file_returns_default(self) -> None:
        missing = self.tmp_path / "does-not-exist.toml"

        self.assertEqual(load_toml_file(missing, default={}), {})
        self.assertIsNone(load_toml_file(missing, default=None))
        self.assertEqual(load_toml_file(missing, default=[]), [])

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_io_error_logs_warning_and_returns_default(self) -> None:
        # Passing a directory raises IsADirectoryError (an OSError), which
        # the docstring promises to log (unlike FileNotFoundError).
        with self.assertLogs("pyishlib._compat", level="WARNING") as captured:
            result = load_toml_file(self.tmp_path, default={})

        self.assertEqual(result, {})
        self.assertTrue(
            any("Failed to read TOML file" in msg for msg in captured.output),
            f"expected warning in {captured.output!r}",
        )

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_decode_error_logs_warning_and_returns_default(self) -> None:
        path = self.tmp_path / "bad.toml"
        path.write_text("this is = = not valid toml ===\n", encoding="utf-8")

        with self.assertLogs("pyishlib._compat", level="WARNING") as captured:
            result = load_toml_file(path, default={"fallback": True})

        self.assertEqual(result, {"fallback": True})
        self.assertTrue(
            any("Failed to read TOML file" in msg for msg in captured.output),
            f"expected warning in {captured.output!r}",
        )

    def test_tomllib_unavailable_silent_by_default(self) -> None:
        path = self.tmp_path / "irrelevant.toml"
        path.write_text("a = 1\n", encoding="utf-8")

        with patch.object(_compat, "tomllib", None):
            # No logs expected at WARNING level when warn_missing_toml=False.
            logger = logging.getLogger("pyishlib._compat")
            with self.assertLogs(logger, level="WARNING") as captured:
                # assertLogs fails if no logs are emitted, so emit a sentinel
                # at WARNING to keep the context manager happy, then verify
                # our message did NOT appear.
                logger.warning("sentinel")
                result = load_toml_file(path, default={})

        self.assertEqual(result, {})
        self.assertFalse(
            any("TOML support unavailable" in msg for msg in captured.output),
            f"unexpected warning in {captured.output!r}",
        )

    def test_tomllib_unavailable_warns_when_opted_in(self) -> None:
        path = self.tmp_path / "irrelevant.toml"
        path.write_text("a = 1\n", encoding="utf-8")

        with patch.object(_compat, "tomllib", None):
            with self.assertLogs("pyishlib._compat", level="WARNING") as captured:
                result = load_toml_file(path, default=None, warn_missing_toml=True)

        self.assertIsNone(result)
        self.assertTrue(
            any("TOML support unavailable" in msg for msg in captured.output),
            f"expected warning in {captured.output!r}",
        )


class TestLoadTomlFileStrict(unittest.TestCase):
    """Tests for the strict loader :func:`load_toml_file_strict`."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_happy_path_returns_mapping(self) -> None:
        path = self.tmp_path / "ok.toml"
        path.write_text('key = "value"\n', encoding="utf-8")

        self.assertEqual(load_toml_file_strict(path), {"key": "value"})

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_decode_error_raises_valueerror(self) -> None:
        path = self.tmp_path / "bad.toml"
        path.write_text("not = = toml\n", encoding="utf-8")

        with self.assertRaises(ValueError) as cm:
            load_toml_file_strict(path)

        self.assertIn("not valid TOML", str(cm.exception))

    def test_missing_tomllib_raises_importerror(self) -> None:
        path = self.tmp_path / "any.toml"
        path.write_text("a = 1\n", encoding="utf-8")

        with patch.object(_compat, "tomllib", None):
            with patch.object(_compat, "HAS_TOML", False):
                with self.assertRaises(ImportError):
                    load_toml_file_strict(path)

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_missing_file_raises_oserror(self) -> None:
        missing = self.tmp_path / "nope.toml"
        with self.assertRaises(OSError):
            load_toml_file_strict(missing)


class TestTomlEscapeBasicString(unittest.TestCase):
    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_round_trips_plain_strings(self) -> None:
        # Use _compat.tomllib so the fallback to `tomli` on 3.9/3.10 wins.
        for s in ["hello", 'a"b', "back\\slash", "tab\there", "new\nline"]:
            wrapped = f'k = "{toml_escape_basic_string(s)}"\n'
            self.assertEqual(_compat.tomllib.loads(wrapped), {"k": s})

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_escapes_del(self) -> None:
        # 0x7F (DEL) is forbidden unescaped in TOML basic strings.
        s = "before\x7fafter"
        escaped = toml_escape_basic_string(s)
        self.assertNotIn("\x7f", escaped)
        wrapped = f'k = "{escaped}"\n'
        self.assertEqual(_compat.tomllib.loads(wrapped), {"k": s})


class TestIsTomlBareKey(unittest.TestCase):
    def test_accepts_alpha_digit_dash_underscore(self) -> None:
        for k in ["foo", "Foo", "foo_bar", "foo-bar", "foo123", "_foo", "-foo", "a"]:
            self.assertTrue(is_toml_bare_key(k), k)

    def test_rejects_empty(self) -> None:
        self.assertFalse(is_toml_bare_key(""))

    def test_rejects_spaces_and_dots(self) -> None:
        for k in ["foo bar", "foo.bar", " foo", "foo "]:
            self.assertFalse(is_toml_bare_key(k), k)

    def test_rejects_special_chars(self) -> None:
        for k in ["foo/bar", "foo+bar", "foo!", "foo@bar"]:
            self.assertFalse(is_toml_bare_key(k), k)


if __name__ == "__main__":
    unittest.main()
