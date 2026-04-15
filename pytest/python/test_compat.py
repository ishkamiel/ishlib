#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
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
from pyishlib._compat import HAS_TOML, load_toml_file, load_toml_file_strict


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
        path.write_text('a = 1\n', encoding="utf-8")

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
        path.write_text('a = 1\n', encoding="utf-8")

        with patch.object(_compat, "tomllib", None):
            with self.assertLogs("pyishlib._compat", level="WARNING") as captured:
                result = load_toml_file(
                    path, default=None, warn_missing_toml=True
                )

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
        path.write_text('a = 1\n', encoding="utf-8")

        with patch.object(_compat, "tomllib", None):
            with patch.object(_compat, "HAS_TOML", False):
                with self.assertRaises(ImportError):
                    load_toml_file_strict(path)

    @unittest.skipUnless(HAS_TOML, "tomllib not available")
    def test_missing_file_raises_oserror(self) -> None:
        missing = self.tmp_path / "nope.toml"
        with self.assertRaises(OSError):
            load_toml_file_strict(missing)


if __name__ == "__main__":
    unittest.main()
