#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for the ishfiles tool (config, ignore, scanner, CLI)

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.config import (
    IshfilesConfig,
    DEFAULT_SOURCE_DIR,
    DEFAULT_TARGET_DIR,
)
from pyishlib.ishfiles.ignore import (
    HARDCODED_IGNORE,
    HARDCODED_IGNORE_DIRS,
    HARDCODED_IGNORE_PATTERNS,
    ISHIGNORE_FILE,
    build_ignore_set,
)
from pyishlib.ishfiles.scanner import IshfilesScanner
from pyishlib.ishfiles.cli import main as cli_main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# IshfilesConfig
# ---------------------------------------------------------------------------


class TestIshfilesConfig:

    def test_defaults(self):
        cfg = IshfilesConfig()
        assert cfg.source_dir == DEFAULT_SOURCE_DIR
        assert cfg.target_dir == DEFAULT_TARGET_DIR
        assert cfg.dry_run is False

    def test_load_without_config_file(self):
        cfg = IshfilesConfig.load(config_file=Path("/nonexistent/config.toml"))
        assert cfg.source_dir == DEFAULT_SOURCE_DIR
        assert cfg.target_dir == DEFAULT_TARGET_DIR

    def test_load_with_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text(
                '[ishfiles]\nsource = "/tmp/my-dotfiles"\ntarget = "/tmp/my-home"\n'
                '\n[ignore]\npatterns = ["*.bak", "temp_*"]\n'
            )

            cfg = IshfilesConfig.load(config_file=cfg_path)

            assert cfg.source_dir == Path("/tmp/my-dotfiles")
            assert cfg.target_dir == Path("/tmp/my-home")
            assert "*.bak" in cfg.ignore_patterns
            assert "temp_*" in cfg.ignore_patterns

    def test_load_args_override_config_file(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "config.toml"
            cfg_path.write_text('[ishfiles]\nsource = "/from/config"\n')

            args = type(
                "Args",
                (),
                {
                    "source": "/from/args",
                    "target": None,
                    "config": None,
                    "dry_run": True,
                    "verbose": False,
                    "debug": False,
                    "quiet": False,
                },
            )()

            cfg = IshfilesConfig.load(config_file=cfg_path, args=args)

            assert cfg.source_dir == Path("/from/args")
            assert cfg.dry_run is True

    def test_load_args_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_path = Path(d) / "custom.toml"
            cfg_path.write_text('[ishfiles]\nsource = "/custom/source"\n')

            args = type(
                "Args",
                (),
                {
                    "source": None,
                    "target": None,
                    "config": str(cfg_path),
                    "dry_run": False,
                    "verbose": False,
                    "debug": False,
                    "quiet": False,
                },
            )()

            cfg = IshfilesConfig.load(args=args)

            assert cfg.source_dir == Path("/custom/source")

    def test_load_verbose(self):
        args = type(
            "Args",
            (),
            {
                "source": None,
                "target": None,
                "config": None,
                "dry_run": False,
                "verbose": True,
                "debug": False,
                "quiet": False,
            },
        )()
        cfg = IshfilesConfig.load(args=args)
        assert cfg.log_level == 20  # logging.INFO

    def test_load_debug(self):
        args = type(
            "Args",
            (),
            {
                "source": None,
                "target": None,
                "config": None,
                "dry_run": False,
                "verbose": False,
                "debug": True,
                "quiet": False,
            },
        )()
        cfg = IshfilesConfig.load(args=args)
        assert cfg.log_level == 10  # logging.DEBUG


# ---------------------------------------------------------------------------
# Ignore
# ---------------------------------------------------------------------------


class TestIgnore:

    def test_hardcoded_dirs(self):
        assert "ishconfig" in HARDCODED_IGNORE_DIRS
        assert "ishscripts" in HARDCODED_IGNORE_DIRS

    def test_hardcoded_names(self):
        assert ".git" in HARDCODED_IGNORE
        assert ".github" in HARDCODED_IGNORE

    def test_hardcoded_combined(self):
        assert "ishconfig" in HARDCODED_IGNORE
        assert ".git" in HARDCODED_IGNORE

    def test_build_ignore_set_without_ishignore(self):
        with tempfile.TemporaryDirectory() as d:
            names, patterns = build_ignore_set(Path(d))
            assert names == HARDCODED_IGNORE
            assert patterns == HARDCODED_IGNORE_PATTERNS

    def test_build_ignore_set_with_ishignore(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ISHIGNORE_FILE, "*.log\ntemp_*\n")
            names, patterns = build_ignore_set(Path(d))
            assert "*.log" in patterns
            assert "temp_*" in patterns

    def test_build_ignore_set_with_extra_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            names, patterns = build_ignore_set(Path(d), extra_patterns=["*.bak"])
            assert "*.bak" in patterns

    def test_build_ignore_set_combines_all_sources(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ISHIGNORE_FILE, "*.log\n")
            names, patterns = build_ignore_set(Path(d), extra_patterns=["*.bak"])
            # hardcoded
            assert "*.ish" in patterns
            # from .ishignore
            assert "*.log" in patterns
            # from extra
            assert "*.bak" in patterns


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class TestIshfilesScanner:

    def test_scan_basic(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "dot_profile")

            scanner = IshfilesScanner(Path(src), Path(tgt))
            dotfiles = scanner.scan()

            names = [df.translated.name for df in dotfiles]
            assert ".bashrc" in names
            assert ".profile" in names

    def test_scan_ignores_hardcoded_dirs(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "ishconfig" / "something.toml")
            _make_file(Path(src) / "ishscripts" / "setup.sh")

            scanner = IshfilesScanner(Path(src), Path(tgt))
            dotfiles = scanner.scan()

            names = [df.source.name for df in dotfiles]
            assert "dot_bashrc" in names
            assert "something.toml" not in names
            assert "setup.sh" not in names

    def test_scan_ignores_git(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / ".git" / "config")

            scanner = IshfilesScanner(Path(src), Path(tgt))
            dotfiles = scanner.scan()

            assert len(dotfiles) == 1

    def test_scan_ignores_ishignore_patterns(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "notes.bak")
            _make_file(Path(src) / ISHIGNORE_FILE, "*.bak\n")

            scanner = IshfilesScanner(Path(src), Path(tgt))
            dotfiles = scanner.scan()

            names = [df.source.name for df in dotfiles]
            assert "dot_bashrc" in names
            assert "notes.bak" not in names

    def test_scan_extra_patterns(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "temp_file")

            scanner = IshfilesScanner(Path(src), Path(tgt), extra_patterns=["temp_*"])
            dotfiles = scanner.scan()

            names = [df.source.name for df in dotfiles]
            assert "temp_file" not in names

    def test_scan_nested(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_config" / "nvim" / "init.vim")

            scanner = IshfilesScanner(Path(src), Path(tgt))
            dotfiles = scanner.scan()

            assert len(dotfiles) == 1
            assert dotfiles[0].target == Path(tgt) / ".config" / "nvim" / "init.vim"

    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scanner = IshfilesScanner(Path(src), Path(tgt))
            assert scanner.scan() == []

    def test_scan_nonexistent_dir(self):
        scanner = IshfilesScanner(Path("/nonexistent/dir"), Path("/tmp"))
        assert scanner.scan() == []

    def test_scan_sorted(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_zshrc")
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "dot_profile")

            scanner = IshfilesScanner(Path(src), Path(tgt))
            dotfiles = scanner.scan()

            names = [df.translated.name for df in dotfiles]
            assert names == sorted(names)


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
                "pyishlib.ishfiles.commands.apply.prompt_yes_no_always",
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
                "pyishlib.ishfiles.commands.apply.prompt_yes_no_always",
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


if __name__ == "__main__":
    pytest.main()
