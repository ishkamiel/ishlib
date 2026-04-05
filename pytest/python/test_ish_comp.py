#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for IshComp base class and related utilities

import sys
import os
import logging
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.ish_comp import IshComp, Choice, IshLogFormatter


class TestChoice:

    def test_yes_value(self):
        assert Choice.YES.value == "y"

    def test_no_value(self):
        assert Choice.NO.value == "n"

    def test_always_value(self):
        assert Choice.ALWAYS.value == "a"

    def test_yes_is_yes(self):
        assert Choice.YES.yes is True

    def test_always_is_yes(self):
        assert Choice.ALWAYS.yes is True

    def test_no_is_not_yes(self):
        assert Choice.NO.yes is False

    def test_no_is_no(self):
        assert Choice.NO.no is True

    def test_yes_is_not_no(self):
        assert Choice.YES.no is False

    def test_always_is_always(self):
        assert Choice.ALWAYS.always is True

    def test_yes_is_not_always(self):
        assert Choice.YES.always is False

    def test_no_is_not_always(self):
        assert Choice.NO.always is False


class TestIshLogFormatter:

    def test_debug_prefix(self):
        formatter = IshLogFormatter()
        record = logging.LogRecord("test", logging.DEBUG, "", 0, "test msg", (), None)
        result = formatter.format(record)
        assert "[DD]" in result

    def test_info_prefix(self):
        formatter = IshLogFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "test msg", (), None)
        result = formatter.format(record)
        assert "[--]" in result

    def test_warning_prefix(self):
        formatter = IshLogFormatter()
        record = logging.LogRecord("test", logging.WARNING, "", 0, "test msg", (), None)
        result = formatter.format(record)
        assert "[WW]" in result

    def test_error_prefix(self):
        formatter = IshLogFormatter()
        record = logging.LogRecord("test", logging.ERROR, "", 0, "test msg", (), None)
        result = formatter.format(record)
        assert "[EE]" in result

    def test_critical_prefix(self):
        formatter = IshLogFormatter()
        record = logging.LogRecord(
            "test", logging.CRITICAL, "", 0, "test msg", (), None
        )
        result = formatter.format(record)
        assert "[!!]" in result


class TestIshComp:

    def test_default_log_level_is_warning(self):
        comp = IshComp()
        assert comp.log.level == logging.WARNING

    def test_debug_mode_via_log_level(self):
        comp = IshComp(log_level=logging.DEBUG)
        assert comp.debug is True
        assert comp.verbose is True

    def test_verbose_mode_via_log_level(self):
        comp = IshComp(log_level=logging.INFO)
        assert comp.verbose is True
        assert comp.debug is False

    def test_quiet_mode_via_log_level(self):
        comp = IshComp(log_level=logging.ERROR)
        assert comp.quiet is True

    def test_not_quiet_by_default(self):
        comp = IshComp()
        assert comp.quiet is False

    def test_dry_run_default_false(self):
        comp = IshComp()
        assert comp.dry_run is False

    def test_dry_run_explicit(self):
        comp = IshComp(dry_run=True)
        assert comp.dry_run is True

    def test_set_dry_run(self):
        comp = IshComp()
        comp.set_dry_run(True)
        assert comp.dry_run is True

    def test_set_log_level(self):
        comp = IshComp()
        comp.set_log_level(logging.DEBUG)
        assert comp.log.level == logging.DEBUG

    def test_set_args(self):
        comp = IshComp()
        args = MagicMock()
        args.dry_run = True
        comp.set_args(args)
        assert comp.dry_run is True

    def test_set_conf(self):
        comp = IshComp()
        conf = MagicMock()
        conf.dry_run = True
        comp.set_conf(conf)
        assert comp.dry_run is True

    def test_args_takes_priority_over_conf(self):
        args = MagicMock()
        args.dry_run = False
        conf = MagicMock()
        conf.dry_run = True
        comp = IshComp(args=args, conf=conf)
        # args should take priority
        assert comp.dry_run is False

    def test_die_exits(self):
        comp = IshComp()
        with pytest.raises(SystemExit) as exc_info:
            comp.die("fatal error")
        assert exc_info.value.code == 1

    def test_die_custom_exit_code(self):
        comp = IshComp()
        with pytest.raises(SystemExit) as exc_info:
            comp.die("fatal error", exit_code=42)
        assert exc_info.value.code == 42

    def test_print(self, capsys):
        comp = IshComp()
        comp.print("hello world")
        captured = capsys.readouterr()
        assert captured.out == "hello world\n"

    def test_prompt_yes_no_always_yes(self):
        comp = IshComp()
        with patch("builtins.input", return_value="y"):
            result = comp.prompt_yes_no_always("Continue?")
        assert result == Choice.YES

    def test_prompt_yes_no_always_no(self):
        comp = IshComp()
        with patch("builtins.input", return_value="n"):
            result = comp.prompt_yes_no_always("Continue?")
        assert result == Choice.NO

    def test_prompt_yes_no_always_always(self):
        comp = IshComp()
        with patch("builtins.input", return_value="a"):
            result = comp.prompt_yes_no_always("Continue?")
        assert result == Choice.ALWAYS

    def test_get_opt_from_internal(self):
        comp = IshComp(dry_run=True)
        assert comp._get_opt("dry_run") is True

    def test_get_opt_default(self):
        comp = IshComp()
        assert comp._get_opt("nonexistent", "default_val") == "default_val"

    def test_debug_log_level_from_args(self):
        args = MagicMock()
        args.debug = True
        args.verbose = False
        args.quiet = False
        comp = IshComp(args=args)
        assert comp.log.level == logging.DEBUG


if __name__ == "__main__":
    pytest.main()
