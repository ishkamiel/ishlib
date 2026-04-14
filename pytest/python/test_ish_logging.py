#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
"""Tests for pyishlib.ish_logging."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

import pytest

from pyishlib.ish_logging import IshLogFormatter, _ScriptStdoutFilter, setup_logging


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_pkg_logger() -> logging.Logger:
    """Return the pyishlib logger with all handlers cleared."""
    pkg = logging.getLogger("pyishlib")
    pkg.handlers.clear()
    pkg.filters.clear()
    return pkg


# ---------------------------------------------------------------------------
# IshLogFormatter
# ---------------------------------------------------------------------------


class TestIshLogFormatter:
    """IshLogFormatter renders level tags and optional script labels."""

    def _fmt(self, level: int, msg: str, script: str | None = None) -> str:
        formatter = IshLogFormatter()
        record = logging.LogRecord("pyishlib.test", level, "", 0, msg, (), None)
        if script is not None:
            record.script = script  # type: ignore[attr-defined]
        return formatter.format(record)

    def test_debug_tag(self):
        assert "[DD]" in self._fmt(logging.DEBUG, "hi")

    def test_info_tag(self):
        assert "[--]" in self._fmt(logging.INFO, "hi")

    def test_warning_tag(self):
        assert "[WW]" in self._fmt(logging.WARNING, "hi")

    def test_error_tag(self):
        assert "[EE]" in self._fmt(logging.ERROR, "hi")

    def test_critical_tag(self):
        assert "[!!]" in self._fmt(logging.CRITICAL, "hi")

    def test_script_label_present(self):
        result = self._fmt(logging.WARNING, "boom", script="10_setup.sh")
        assert "[10_setup.sh]" in result
        assert "boom" in result

    def test_no_script_label_when_none(self):
        result = self._fmt(logging.INFO, "hello")
        assert "[None]" not in result
        assert "hello" in result


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """setup_logging() configures the pyishlib logger correctly."""

    def setup_method(self):
        _fresh_pkg_logger()

    def teardown_method(self):
        _fresh_pkg_logger()

    def test_sets_terminal_handler_level(self):
        setup_logging(logging.DEBUG)
        pkg = logging.getLogger("pyishlib")
        terminal = next(
            (h for h in pkg.handlers if not isinstance(h, logging.FileHandler)), None
        )
        assert terminal is not None
        assert terminal.level == logging.DEBUG

    def test_info_level(self):
        setup_logging(logging.INFO)
        pkg = logging.getLogger("pyishlib")
        terminal = next(
            (h for h in pkg.handlers if not isinstance(h, logging.FileHandler)), None
        )
        assert terminal.level == logging.INFO

    def test_log_file_attaches_file_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            lf = Path(tmp) / "run.log"
            setup_logging(logging.WARNING, log_file=lf)
            pkg = logging.getLogger("pyishlib")
            file_handlers = [h for h in pkg.handlers if isinstance(h, logging.FileHandler)]
            assert len(file_handlers) == 1
            assert file_handlers[0].level == logging.DEBUG
            # FileHandler stores os.path.abspath(filename); normalise both sides
            # so the comparison is robust on Windows (GetFullPathName may expand
            # 8.3 short names or adjust separators).
            assert file_handlers[0].baseFilename == os.path.abspath(str(lf))

    def test_log_file_written_on_emit(self):
        with tempfile.TemporaryDirectory() as tmp:
            lf = Path(tmp) / "out.log"
            setup_logging(logging.WARNING, log_file=lf)
            logging.getLogger("pyishlib.test").warning("persisted")
            assert lf.exists()
            assert "persisted" in lf.read_text()

    def test_quiet_adds_stdout_filter(self):
        setup_logging(logging.DEBUG, quiet=True)
        pkg = logging.getLogger("pyishlib")
        terminal = next(
            (h for h in pkg.handlers if not isinstance(h, logging.FileHandler)), None
        )
        assert any(isinstance(f, _ScriptStdoutFilter) for f in terminal.filters)

    def test_not_quiet_has_no_stdout_filter(self):
        setup_logging(logging.DEBUG, quiet=False)
        pkg = logging.getLogger("pyishlib")
        terminal = next(
            (h for h in pkg.handlers if not isinstance(h, logging.FileHandler)), None
        )
        assert not any(isinstance(f, _ScriptStdoutFilter) for f in terminal.filters)

    def test_second_call_reconfigures_level(self):
        setup_logging(logging.INFO)
        setup_logging(logging.ERROR)
        pkg = logging.getLogger("pyishlib")
        terminal = next(
            (h for h in pkg.handlers if not isinstance(h, logging.FileHandler)), None
        )
        assert terminal.level == logging.ERROR

    def test_pkg_logger_level_is_debug(self):
        # Package logger is always set to DEBUG so handlers filter individually.
        setup_logging(logging.WARNING)
        assert logging.getLogger("pyishlib").level == logging.DEBUG


# ---------------------------------------------------------------------------
# _ScriptStdoutFilter
# ---------------------------------------------------------------------------


class TestScriptStdoutFilter:
    """_ScriptStdoutFilter blocks pyishlib.script.stdout records only."""

    def _make_record(self, name: str, level: int = logging.DEBUG) -> logging.LogRecord:
        return logging.LogRecord(name, level, "", 0, "msg", (), None)

    def test_blocks_script_stdout(self):
        f = _ScriptStdoutFilter()
        record = self._make_record("pyishlib.script.stdout")
        assert f.filter(record) is False

    def test_allows_script_stderr(self):
        f = _ScriptStdoutFilter()
        record = self._make_record("pyishlib.script.stderr")
        assert f.filter(record) is True

    def test_allows_script_ish(self):
        f = _ScriptStdoutFilter()
        record = self._make_record("pyishlib.script.ish")
        assert f.filter(record) is True

    def test_allows_other_pyishlib(self):
        f = _ScriptStdoutFilter()
        record = self._make_record("pyishlib.ishfiles.cli")
        assert f.filter(record) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
