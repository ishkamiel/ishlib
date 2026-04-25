# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

import subprocess
import unittest
from unittest.mock import MagicMock

from pyishlib.version_check import (
    meets_min_version,
    parse_version,
    probe_version,
)


class TestParseVersion(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_version("1.2.3"), (1, 2, 3))

    def test_v_prefix(self):
        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))

    def test_with_suffix(self):
        self.assertEqual(parse_version("ripgrep 14.1.0-beta"), (14, 1, 0))

    def test_program_name_then_version(self):
        self.assertEqual(parse_version("git version 2.40.0"), (2, 40, 0))

    def test_multiline_stderr(self):
        text = 'openjdk version "17.0.2" 2022-01-18\nOpenJDK 64-Bit Server VM\n'
        self.assertEqual(parse_version(text), (17, 0, 2))

    def test_single_component(self):
        # Allows things like Java's "17" or "21" being used as a min_version
        # value from config.  Real tool output usually has more components.
        self.assertEqual(parse_version("17"), (17,))

    def test_two_components(self):
        self.assertEqual(parse_version("foo 1.2"), (1, 2))

    def test_four_components(self):
        self.assertEqual(parse_version("tool 1.2.3.4"), (1, 2, 3, 4))

    def test_five_or_more_components(self):
        self.assertEqual(parse_version("tool 1.2.3.4.5"), (1, 2, 3, 4, 5))
        self.assertEqual(parse_version("v6.1.2.3.4.5"), (6, 1, 2, 3, 4, 5))

    def test_unparsable(self):
        self.assertIsNone(parse_version("hello world"))

    def test_empty(self):
        self.assertIsNone(parse_version(""))

    def test_none(self):
        self.assertIsNone(parse_version(None))


class TestMeetsMinVersion(unittest.TestCase):
    def test_equal(self):
        self.assertTrue(meets_min_version("1.2.3", "1.2.3"))

    def test_greater(self):
        self.assertTrue(meets_min_version("1.3.0", "1.2.3"))

    def test_less(self):
        self.assertFalse(meets_min_version("1.2.0", "1.2.3"))

    def test_padding_actual_shorter(self):
        # "1.2" treated as 1.2.0 — equal to 1.2.0.
        self.assertTrue(meets_min_version("1.2", "1.2.0"))

    def test_padding_minimum_shorter(self):
        self.assertTrue(meets_min_version("1.2.0", "1.2"))
        self.assertFalse(meets_min_version("1.2.0", "1.2.0.1"))

    def test_unparsable_actual(self):
        self.assertFalse(meets_min_version("hello", "1.0"))

    def test_unparsable_minimum(self):
        self.assertFalse(meets_min_version("1.2.3", "not-a-version"))

    def test_real_world_ripgrep(self):
        self.assertTrue(meets_min_version("ripgrep 14.1.0\n", "13.0.0"))
        self.assertFalse(meets_min_version("ripgrep 12.0.0\n", "13.0.0"))


class TestProbeVersion(unittest.TestCase):
    def _runner(self, *, stdout=b"", stderr=b"", returncode=0, exc=None):
        runner = MagicMock()
        if exc is not None:
            runner.run.side_effect = exc
        else:
            runner.run.return_value = subprocess.CompletedProcess(
                args=[], returncode=returncode, stdout=stdout, stderr=stderr
            )
        return runner

    def test_stdout_only_tool(self):
        runner = self._runner(stdout=b"git version 2.40.0\n")
        out = probe_version(runner, "git --version")
        assert out is not None
        self.assertIn("2.40.0", out)
        runner.run.assert_called_once()
        argv = runner.run.call_args.args[0]
        self.assertEqual(argv, ["git", "--version"])

    def test_stderr_only_tool(self):
        runner = self._runner(stderr=b'openjdk version "17.0.2" 2022-01-18\n')
        out = probe_version(runner, "java -version")
        assert out is not None
        self.assertIn("17.0.2", out)

    def test_combined_streams(self):
        runner = self._runner(stdout=b"first ", stderr=b"second")
        out = probe_version(runner, "tool")
        assert out is not None
        self.assertIn("first", out)
        self.assertIn("second", out)

    def test_called_process_error_returns_none(self):
        runner = self._runner(exc=subprocess.CalledProcessError(1, ["x"]))
        self.assertIsNone(probe_version(runner, "x --version"))

    def test_file_not_found_returns_none(self):
        runner = self._runner(exc=FileNotFoundError("no such tool"))
        self.assertIsNone(probe_version(runner, "missing --version"))

    def test_oserror_returns_none(self):
        runner = self._runner(exc=OSError("nope"))
        self.assertIsNone(probe_version(runner, "x --version"))

    def test_empty_command_returns_none(self):
        runner = self._runner()
        self.assertIsNone(probe_version(runner, ""))
        runner.run.assert_not_called()

    def test_non_string_command_returns_none(self):
        # Defensive: schema usually rejects this, but if validation is off
        # (e.g. cerberus missing) a stray list/None must not raise.
        runner = self._runner()
        self.assertIsNone(probe_version(runner, ["x", "--version"]))  # type: ignore[arg-type]
        self.assertIsNone(probe_version(runner, None))  # type: ignore[arg-type]
        runner.run.assert_not_called()

    def test_failure_with_no_output_returns_none(self):
        runner = self._runner(returncode=1, stdout=b"", stderr=b"")
        self.assertIsNone(probe_version(runner, "x --version"))

    def test_failure_with_output_still_returns_text(self):
        # Some tools exit non-zero but still print version. Keep the text.
        runner = self._runner(returncode=1, stdout=b"tool 1.2.3", stderr=b"")
        out = probe_version(runner, "tool --version")
        assert out is not None
        self.assertIn("1.2.3", out)


if __name__ == "__main__":
    unittest.main()
