# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

#
# Tests for IshConfig, IshComp utilities, and related types

import sys
import os
import logging
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.ish_comp import die
from pyishlib.ish_logging import IshLogFormatter, setup_logging
from pyishlib.userio import Choice, prompt_yes_no_always
from pyishlib.ish_config import IshConfig


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


class TestIshConfig:
    def test_default_log_level_is_warning(self):
        cfg = IshConfig()
        assert cfg.log_level == logging.WARNING

    def test_debug_mode_via_log_level(self):
        cfg = IshConfig(log_level=logging.DEBUG)
        assert cfg.debug is True
        assert cfg.verbose is True

    def test_verbose_mode_via_log_level(self):
        cfg = IshConfig(log_level=logging.INFO)
        assert cfg.verbose is True
        assert cfg.debug is False

    def test_quiet_mode_via_log_level(self):
        cfg = IshConfig(log_level=logging.ERROR)
        assert cfg.quiet is True

    def test_not_quiet_by_default(self):
        cfg = IshConfig()
        assert cfg.quiet is False

    def test_dry_run_default_false(self):
        cfg = IshConfig()
        assert cfg.dry_run is False

    def test_dry_run_explicit(self):
        cfg = IshConfig(dry_run=True)
        assert cfg.dry_run is True

    def test_set_dry_run(self):
        cfg = IshConfig()
        cfg.dry_run = True
        assert cfg.dry_run is True

    def test_set_log_level(self):
        cfg = IshConfig()
        cfg.log_level = logging.DEBUG
        assert cfg.log_level == logging.DEBUG

    def test_from_args_dry_run(self):
        args = MagicMock()
        args.dry_run = True
        args.debug = False
        args.verbose = False
        args.quiet = False
        cfg = IshConfig.from_args(args)
        assert cfg.dry_run is True

    def test_from_args_conf_fallback(self):
        args = MagicMock(spec=[])  # no attributes
        conf = MagicMock()
        conf.dry_run = True
        cfg = IshConfig.from_args(args, conf)
        assert cfg.dry_run is True

    def test_from_args_args_takes_priority_over_conf(self):
        args = MagicMock()
        args.dry_run = False
        args.debug = False
        args.verbose = False
        args.quiet = False
        conf = MagicMock()
        conf.dry_run = True
        cfg = IshConfig.from_args(args, conf)
        # args should take priority
        assert cfg.dry_run is False

    def test_from_args_debug_sets_log_level(self):
        args = MagicMock()
        args.debug = True
        args.verbose = False
        args.quiet = False
        args.dry_run = False
        cfg = IshConfig.from_args(args)
        assert cfg.log_level == logging.DEBUG

    def test_die_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            die("fatal error")
        assert exc_info.value.code == 1

    def test_die_custom_exit_code(self):
        with pytest.raises(SystemExit) as exc_info:
            die("fatal error", exit_code=42)
        assert exc_info.value.code == 42

    def test_prompt_yes_no_always_yes(self):
        with patch("pyishlib.userio.getch", return_value="y"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = prompt_yes_no_always("Continue?")
        assert result == Choice.YES

    def test_prompt_yes_no_always_no(self):
        with patch("pyishlib.userio.getch", return_value="n"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = prompt_yes_no_always("Continue?")
        assert result == Choice.NO

    def test_prompt_yes_no_always_always(self):
        with patch("pyishlib.userio.getch", return_value="a"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = prompt_yes_no_always("Continue?")
        assert result == Choice.ALWAYS

    def test_setup_logging_sets_level(self):
        setup_logging(logging.DEBUG)
        pkg_logger = logging.getLogger("pyishlib")
        assert pkg_logger.level == logging.DEBUG
        # Reset
        setup_logging(logging.WARNING)

    def test_from_args_retains_args_and_conf(self):
        args = MagicMock()
        args.dry_run = False
        args.debug = False
        args.verbose = False
        args.quiet = False
        args.custom_opt = "hello"
        conf = MagicMock()
        conf.another_opt = 42
        cfg = IshConfig.from_args(args, conf)
        assert cfg.args is args
        assert cfg.conf is conf

    def test_get_opt_from_args(self):
        args = MagicMock()
        args.dry_run = False
        args.debug = False
        args.verbose = False
        args.quiet = False
        args.custom_opt = "from_args"
        cfg = IshConfig.from_args(args)
        assert cfg.get_opt("custom_opt") == "from_args"

    def test_get_opt_from_conf(self):
        args = MagicMock(spec=[])  # no attributes
        conf = MagicMock()
        conf.custom_opt = "from_conf"
        cfg = IshConfig.from_args(args, conf)
        assert cfg.get_opt("custom_opt") == "from_conf"

    def test_get_opt_args_priority_over_conf(self):
        args = MagicMock()
        args.custom_opt = "args_wins"
        conf = MagicMock()
        conf.custom_opt = "conf_loses"
        cfg = IshConfig.from_args(args, conf)
        assert cfg.get_opt("custom_opt") == "args_wins"

    def test_get_opt_default(self):
        cfg = IshConfig()
        assert cfg.get_opt("nonexistent", "fallback") == "fallback"

    def test_get_opt_none_without_default(self):
        cfg = IshConfig()
        assert cfg.get_opt("nonexistent") is None

    def test_getattr_from_args(self):
        args = MagicMock()
        args.custom_opt = "via_attr"
        cfg = IshConfig.from_args(args)
        assert cfg.custom_opt == "via_attr"

    def test_getattr_from_conf(self):
        args = MagicMock(spec=[])
        conf = MagicMock()
        conf.custom_opt = "from_conf"
        cfg = IshConfig.from_args(args, conf)
        assert cfg.custom_opt == "from_conf"

    def test_getattr_args_wins(self):
        args = MagicMock()
        args.custom_opt = "args"
        conf = MagicMock()
        conf.custom_opt = "conf"
        cfg = IshConfig.from_args(args, conf)
        assert cfg.custom_opt == "args"

    def test_getattr_raises_attributeerror(self):
        cfg = IshConfig()
        with pytest.raises(AttributeError):
            _ = cfg.nonexistent

    def test_getattr_does_not_shadow_fields(self):
        args = MagicMock()
        args.dry_run = True
        cfg = IshConfig(dry_run=False, args=args)
        # dataclass field wins, __getattr__ is not called
        assert cfg.dry_run is False

    # -- defaults / set_default ------------------------------------------------

    def test_from_args_with_defaults(self):
        args = MagicMock(spec=[])  # no attributes
        cfg = IshConfig.from_args(args, defaults={"custom": "default_val"})
        assert cfg.get_opt("custom") == "default_val"
        assert cfg.custom == "default_val"

    def test_from_args_defaults_lowest_priority(self):
        args = MagicMock()
        args.custom = "from_args"
        cfg = IshConfig.from_args(args, defaults={"custom": "default_val"})
        assert cfg.custom == "from_args"

    def test_from_args_defaults_below_conf(self):
        args = MagicMock(spec=[])
        conf = MagicMock()
        conf.custom = "from_conf"
        cfg = IshConfig.from_args(args, conf, defaults={"custom": "default_val"})
        assert cfg.custom == "from_conf"

    def test_from_args_defaults_dry_run(self):
        args = MagicMock(spec=[])
        cfg = IshConfig.from_args(args, defaults={"dry_run": True})
        assert cfg.dry_run is True

    def test_from_args_defaults_debug(self):
        args = MagicMock(spec=[])
        cfg = IshConfig.from_args(args, defaults={"debug": True})
        assert cfg.log_level == logging.DEBUG

    def test_set_default(self):
        cfg = IshConfig()
        cfg.set_default("my_opt", 42)
        assert cfg.get_opt("my_opt") == 42
        assert cfg.my_opt == 42

    def test_set_default_does_not_override_args(self):
        args = MagicMock()
        args.my_opt = "from_args"
        cfg = IshConfig.from_args(args)
        cfg.set_default("my_opt", "default")
        assert cfg.my_opt == "from_args"

    def test_set_default_missing_raises_without(self):
        cfg = IshConfig()
        with pytest.raises(AttributeError):
            _ = cfg.my_opt
        cfg.set_default("my_opt", "now_exists")
        assert cfg.my_opt == "now_exists"

    def test_get_opt_uses_defaults(self):
        cfg = IshConfig(defaults={"color": "blue"})
        assert cfg.get_opt("color") == "blue"

    def test_get_opt_explicit_default_over_defaults(self):
        cfg = IshConfig(defaults={"color": "blue"})
        assert cfg.get_opt("missing", "red") == "red"

    def test_dataclass_equality(self):
        cfg1 = IshConfig(dry_run=True, log_level=logging.DEBUG)
        cfg2 = IshConfig(dry_run=True, log_level=logging.DEBUG)
        assert cfg1 == cfg2

    def test_dataclass_equality_ignores_args_conf(self):
        args = MagicMock()
        cfg1 = IshConfig(dry_run=True, args=args)
        cfg2 = IshConfig(dry_run=True)
        assert cfg1 == cfg2

    def test_dataclass_repr(self):
        cfg = IshConfig(dry_run=True)
        r = repr(cfg)
        assert "dry_run=True" in r

    def test_dataclass_repr_excludes_args(self):
        args = MagicMock()
        cfg = IshConfig(dry_run=True, args=args)
        r = repr(cfg)
        assert "args" not in r


if __name__ == "__main__":
    pytest.main()
