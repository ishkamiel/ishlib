#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for the ishfiles tool (config, ignore, CLI)

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.dotfile_ignore import DotfileIgnore
from pyishlib.ishfiles.ignore import ISHFILES_PATTERNS, ISHIGNORE_FILE, build_ignore
from pyishlib.ishfiles.config import (
    DEFAULT_SOURCE_DIR,
    DEFAULT_TARGET_DIR,
    load_config,
)
from pyishlib.ishfiles.cli import main as cli_main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _make_args(**overrides):
    """Create a minimal argparse-like namespace."""
    defaults = {
        "source": None,
        "target": None,
        "config": None,
        "dry_run": False,
        "verbose": False,
        "debug": False,
        "quiet": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:

    def test_defaults(self):
        cfg = load_config(config_file=Path("/nonexistent/config.toml"))
        assert cfg.get_opt("source") == str(DEFAULT_SOURCE_DIR)
        assert cfg.get_opt("target") == str(DEFAULT_TARGET_DIR)
        assert cfg.dry_run is False

    def test_load_with_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text(
                '[ishfiles]\nsource = "/tmp/my-dotfiles"\ntarget = "/tmp/my-home"\n'
                '\n[ignore]\npatterns = ["*.bak", "temp_*"]\n'
            )

            cfg = load_config(config_file=cfg_path)

            assert cfg.get_opt("source") == "/tmp/my-dotfiles"
            assert cfg.get_opt("target") == "/tmp/my-home"
            assert "*.bak" in cfg.get_opt("patterns")
            assert "temp_*" in cfg.get_opt("patterns")

    def test_args_override_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text('[ishfiles]\nsource = "/from/config"\n')

            args = _make_args(source="/from/args", dry_run=True)
            cfg = load_config(args=args, config_file=cfg_path)

            assert cfg.get_opt("source") == "/from/args"
            assert cfg.dry_run is True

    def test_args_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "custom.toml"
            cfg_path.write_text('[ishfiles]\nsource = "/custom/source"\n')

            args = _make_args(config=str(cfg_path))
            cfg = load_config(args=args)

            assert cfg.get_opt("source") == "/custom/source"

    def test_verbose(self):
        args = _make_args(verbose=True)
        cfg = load_config(args=args, config_file=Path("/nonexistent"))
        assert cfg.log_level == 20  # logging.INFO

    def test_debug(self):
        args = _make_args(debug=True)
        cfg = load_config(args=args, config_file=Path("/nonexistent"))
        assert cfg.log_level == 10  # logging.DEBUG


# ---------------------------------------------------------------------------
# DotfileIgnore
# ---------------------------------------------------------------------------


class TestDotfileIgnore:

    def test_ishfiles_patterns(self):
        assert "ishconfig" in ISHFILES_PATTERNS
        assert "ishscripts" in ISHFILES_PATTERNS

    def test_default_ignore(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d))
            assert di.is_ignored(".git")
            assert di.is_ignored("__pycache__")
            assert not di.is_ignored("dot_bashrc")

    def test_build_ignore_includes_ishfiles_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            di = build_ignore(Path(d))
            assert di.is_ignored("ishconfig")
            assert di.is_ignored("ishscripts")
            assert di.is_ignored(ISHIGNORE_FILE)
            assert di.is_ignored(".git")

    def test_ignore_file(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ISHIGNORE_FILE, "*.log\ntemp_*\n")
            di = DotfileIgnore(Path(d), ignore_file=ISHIGNORE_FILE)
            assert di.is_ignored("debug.log")
            assert di.is_ignored("temp_stuff")
            assert not di.is_ignored("keep_me")

    def test_extra_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), extra_patterns=["*.bak"])
            assert di.is_ignored("file.bak")

    def test_default_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d))
            assert di.is_ignored("file.ish")

    def test_combines_all_sources(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ISHIGNORE_FILE, "*.log\n")
            di = DotfileIgnore(
                Path(d),
                ignore_file=ISHIGNORE_FILE,
                extra_patterns=["*.bak"],
            )
            assert di.is_ignored("file.log")
            assert di.is_ignored("file.bak")
            assert di.is_ignored("file.ish")
            assert di.is_ignored(".git")

    def test_build_ignore_returns_dotfileignore(self):
        with tempfile.TemporaryDirectory() as d:
            di = build_ignore(Path(d))
            assert isinstance(di, DotfileIgnore)
            assert di.is_ignored(".git")

    def test_patterns_property(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), extra_patterns=["*.bak"])
            assert "*.bak" in di.patterns
            assert "*.ish" in di.patterns


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCli:

    def test_no_command_returns_2(self):
        with patch("sys.stdout"):
            ret = cli_main([])
        assert ret == 2

    def test_diff_empty_source(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "diff"])
        assert ret == 0

    def test_diff_with_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            ret = cli_main(["--source", src, "--target", tgt, "diff"])
        assert ret == 1

    def test_diff_no_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "same\n")
            _make_file(Path(tgt) / ".bashrc", "same\n")
            ret = cli_main(["--source", src, "--target", tgt, "diff"])
        assert ret == 0

    def test_apply_dry_run(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "apply"])
        assert ret == 0
        assert not (Path(tgt) / ".bashrc").exists()

    def test_apply_user_confirms(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            from pyishlib.ish_comp import Choice

            with patch(
                "pyishlib.dotfile_applier.prompt_yes_no_always",
                return_value=Choice.YES,
            ):
                ret = cli_main(["--source", src, "--target", tgt, "apply"])

            assert ret == 0
            assert (Path(tgt) / ".bashrc").read_text() == "content\n"

    def test_apply_user_declines(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            from pyishlib.ish_comp import Choice

            with patch(
                "pyishlib.dotfile_applier.prompt_yes_no_always",
                return_value=Choice.NO,
            ):
                ret = cli_main(["--source", src, "--target", tgt, "apply"])

            assert ret == 0
            assert not (Path(tgt) / ".bashrc").exists()

    def test_apply_with_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source"
            tgt = Path(d) / "target"
            src.mkdir()
            tgt.mkdir()
            _make_file(src / "dot_bashrc", "content\n")

            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text(f'[ishfiles]\nsource = "{src}"\ntarget = "{tgt}"\n')

            ret = cli_main(["--config", str(cfg_path), "--dry-run", "apply"])

        assert ret == 0

    def test_cli_verbose(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "--verbose", "diff"])
        assert ret == 0

    def test_ignores_ishconfig_and_ishscripts(self):
        """Hardcoded ignore dirs are skipped by DotfileApplier."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "ishconfig" / "something.toml")
            _make_file(Path(src) / "ishscripts" / "setup.sh")

            ret = cli_main(["--source", src, "--target", tgt, "diff"])

        # Only dot_bashrc is new -- ishconfig/ishscripts are ignored
        assert ret == 1  # one change (dot_bashrc)

    def test_ishignore_respected(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "same\n")
            _make_file(Path(tgt) / ".bashrc", "same\n")
            _make_file(Path(src) / "notes.bak")
            _make_file(Path(src) / ".ishignore", "*.bak\n")

            ret = cli_main(["--source", src, "--target", tgt, "diff"])

        assert ret == 0  # notes.bak ignored, dot_bashrc unchanged


if __name__ == "__main__":
    pytest.main()
