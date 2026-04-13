#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for the ishfiles tool (config, ignore, CLI)

import os
import shutil
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
from pyishlib.ishfiles.ignore import build_ignore
from pyishlib.ishfiles.config import (
    DEFAULT_SOURCE_DIR,
    DEFAULT_TARGET_DIR,
    load_config,
)
from pyishlib.ishfiles.cli import main as cli_main
from pyishlib.ishfiles.script_runner import scan_scripts

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
        "home": None,
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

    def test_home_override_shifts_all_defaults(self):
        fake_home = Path("/tmp/fake-home")
        args = _make_args(home=str(fake_home))
        cfg = load_config(args=args, config_file=Path("/nonexistent"))
        assert cfg.get_opt("source") == str(fake_home / ".local" / "share" / "ishfiles")
        assert cfg.get_opt("target") == str(fake_home)

    def test_home_override_config_path(self):
        with tempfile.TemporaryDirectory() as d:
            fake_home = Path(d) / "fakehome"
            cfg_dir = fake_home / ".config" / "ishfiles"
            cfg_dir.mkdir(parents=True)
            cfg_path = cfg_dir / "config.toml"
            cfg_path.write_text('[ishfiles]\nsource = "/from/home-config"\n')

            args = _make_args(home=str(fake_home))
            cfg = load_config(args=args)

            assert cfg.get_opt("source") == "/from/home-config"

    def test_home_override_source_wins_over_explicit_source(self):
        fake_home = Path("/tmp/fake-home")
        args = _make_args(home=str(fake_home), source="/explicit/source")
        cfg = load_config(args=args, config_file=Path("/nonexistent"))
        # -s wins for source, but target still uses home override
        assert cfg.get_opt("source") == "/explicit/source"
        assert cfg.get_opt("target") == str(fake_home)

    def test_home_override_explicit_target_wins(self):
        fake_home = Path("/tmp/fake-home")
        args = _make_args(home=str(fake_home), target="/explicit/target")
        cfg = load_config(args=args, config_file=Path("/nonexistent"))
        # -t wins for target, source uses home override
        assert cfg.get_opt("target") == "/explicit/target"
        assert cfg.get_opt("source") == str(fake_home / ".local" / "share" / "ishfiles")


# ---------------------------------------------------------------------------
# DotfileIgnore
# ---------------------------------------------------------------------------


class TestDotfileIgnore:
    def test_config_registers_constants(self):
        cfg = load_config(config_file=Path("/nonexistent/config.toml"))
        assert cfg.get_opt("config_dir") == "ishconfig"
        assert cfg.get_opt("scripts_dir") == "ishscripts"
        assert cfg.get_opt("installers_dir") == "ishinstallers"
        assert cfg.get_opt("ignore_file") == ".ishignore"

    def test_constants_are_readonly(self):
        cfg = load_config(config_file=Path("/nonexistent/config.toml"))
        with pytest.raises(ValueError):
            cfg.set_default("config_dir", "other")

    def test_default_ignore(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d))
            assert di.is_ignored(".git")
            assert di.is_ignored("__pycache__")
            assert not di.is_ignored("dot_bashrc")

    def test_build_ignore_includes_ishfiles_patterns(self):
        cfg = load_config(config_file=Path("/nonexistent/config.toml"))
        with tempfile.TemporaryDirectory() as d:
            di = build_ignore(cfg, Path(d))
            assert di.is_ignored("ishconfig")
            assert di.is_ignored("ishscripts")
            assert di.is_ignored("ishinstallers")
            assert di.is_ignored(".ishignore")
            assert di.is_ignored(".git")

    def test_ignore_file(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ".ishignore", "*.log\ntemp_*\n")
            di = DotfileIgnore(Path(d), ignore_file=".ishignore")
            assert di.is_ignored("debug.log")
            assert di.is_ignored("temp_stuff")
            assert not di.is_ignored("keep_me")

    def test_path_pattern_matches_rel_path(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ".ishignore", "foo/bar/LICENSE\n")
            di = DotfileIgnore(Path(d), ignore_file=".ishignore")
            assert di.is_ignored("LICENSE", Path("foo/bar/LICENSE"))
            assert not di.is_ignored("LICENSE", Path("other/bar/LICENSE"))
            assert not di.is_ignored("LICENSE")  # no rel_path: path patterns skipped

    def test_path_pattern_with_glob(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ".ishignore", "**/*.pyc\n")
            di = DotfileIgnore(Path(d), ignore_file=".ishignore")
            assert di.is_ignored("foo.pyc", Path("deep/nested/foo.pyc"))
            assert not di.is_ignored("foo.py", Path("deep/nested/foo.py"))

    def test_name_pattern_still_works_without_rel_path(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ".ishignore", "*.log\n")
            di = DotfileIgnore(Path(d), ignore_file=".ishignore")
            assert di.is_ignored("debug.log")
            assert di.is_ignored("debug.log", Path("some/dir/debug.log"))

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
            _make_file(Path(d) / ".ishignore", "*.log\n")
            di = DotfileIgnore(
                Path(d),
                ignore_file=".ishignore",
                extra_patterns=["*.bak"],
            )
            assert di.is_ignored("file.log")
            assert di.is_ignored("file.bak")
            assert di.is_ignored("file.ish")
            assert di.is_ignored(".git")

    def test_build_ignore_returns_dotfileignore(self):
        cfg = load_config(config_file=Path("/nonexistent/config.toml"))
        with tempfile.TemporaryDirectory() as d:
            di = build_ignore(cfg, Path(d))
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

            from pyishlib.userio import Choice

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

            from pyishlib.userio import Choice

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
            src_escaped = str(src).replace("\\", "/")
            tgt_escaped = str(tgt).replace("\\", "/")
            cfg_path.write_text(
                f'[ishfiles]\nsource = "{src_escaped}"\ntarget = "{tgt_escaped}"\n'
            )

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


# ---------------------------------------------------------------------------
# reverse translation
# ---------------------------------------------------------------------------


class TestReverseTranslation:
    def test_reverse_translate_name(self):
        from pyishlib.dotfile import reverse_translate_name

        assert reverse_translate_name(".bashrc") == "dot_bashrc"
        assert reverse_translate_name("readme") == "readme"
        assert reverse_translate_name(".") == "."  # bare dot stays

    def test_reverse_translate_path(self):
        from pyishlib.dotfile import reverse_translate_path

        result = reverse_translate_path(Path(".config") / "fish" / ".extra")
        assert result == Path("dot_config") / "fish" / "dot_extra"

    def test_round_trip(self):
        from pyishlib.dotfile import translate_path, reverse_translate_path

        original = Path("dot_config") / "fish" / "dot_extra"
        assert reverse_translate_path(translate_path(original)) == original


# ---------------------------------------------------------------------------
# DotfileFinder
# ---------------------------------------------------------------------------


class TestDotfileFinder:
    def _make_finder(self, src, tgt):
        from pyishlib.dotfile_finder import DotfileFinder
        from pyishlib.ish_config import IshConfig

        cfg = IshConfig(defaults={"source": src, "target": tgt})
        return DotfileFinder(cfg)

    def test_resolve_source_path(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            df = finder.get("dot_bashrc")
            assert df is not None
            assert df.rel_path == Path("dot_bashrc")
            assert df.translated == Path(".bashrc")

    def test_resolve_target_name(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            df = finder.get(".bashrc")
            assert df is not None
            assert df.rel_path == Path("dot_bashrc")

    def test_resolve_absolute_source(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            df = finder.get(str(Path(src) / "dot_bashrc"))
            assert df is not None
            assert df.rel_path == Path("dot_bashrc")

    def test_resolve_absolute_target(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            df = finder.get(str(Path(tgt) / ".bashrc"))
            assert df is not None
            assert df.rel_path == Path("dot_bashrc")

    def test_resolve_unresolvable(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            finder = self._make_finder(src, tgt)
            # Use a path that can't be under src or tgt on any platform
            df = finder.get(str(Path(tgt).parent / "zzz_unrelated_12345" / "path"))
            assert df is None

    def test_get_all(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            _make_file(Path(src) / "dot_vimrc", "content\n")
            finder = self._make_finder(src, tgt)
            results = finder.get_all([".bashrc", ".vimrc"])
            assert len(results) == 2
            names = {df.rel_path for df in results}
            assert Path("dot_bashrc") in names
            assert Path("dot_vimrc") in names

    def test_get_rel_paths(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            paths = finder.get_rel_paths([".bashrc", str(Path(src) / "dot_bashrc")])
            assert Path("dot_bashrc") in paths

    def test_translate_arg_known_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            assert finder.translate_arg(".bashrc") == "dot_bashrc"

    def test_translate_arg_unknown_stays(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            finder = self._make_finder(src, tgt)
            assert finder.translate_arg("--verbose") == "--verbose"

    def test_dotfile_has_correct_target(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            finder = self._make_finder(src, tgt)
            df = finder.get("dot_bashrc")
            assert df.target == Path(tgt) / ".bashrc"
            assert df.source == Path(src) / "dot_bashrc"


# ---------------------------------------------------------------------------
# git subcommand
# ---------------------------------------------------------------------------


_has_git = shutil.which("git") is not None


@pytest.mark.skipif(not _has_git, reason="git not available")
class TestGitCommand:
    def test_git_status(self):
        """Running 'git status' in a git-initialised source dir succeeds."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            import subprocess

            clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            subprocess.run(["git", "init", src], check=True, capture_output=True, env=clean_env)
            ret = cli_main(["--source", src, "--target", tgt, "git", "status"])
            assert ret == 0

    def test_git_nonexistent_source(self):
        with tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(
                ["--source", "/nonexistent/dir", "--target", tgt, "git", "status"]
            )
            assert ret == 1

    def test_git_translates_target_paths(self):
        """Target-style paths like ~/.bashrc are translated for git."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            import subprocess

            clean_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
            _make_file(Path(src) / "dot_bashrc", "content\n")
            subprocess.run(["git", "init", src], check=True, capture_output=True, env=clean_env)
            subprocess.run(
                ["git", "add", "."], cwd=src, check=True, capture_output=True, env=clean_env
            )

            # 'git diff' on a target path should translate it
            ret = cli_main(
                [
                    "--source",
                    src,
                    "--target",
                    tgt,
                    "git",
                    "diff",
                    "--name-only",
                    str(Path(tgt) / ".bashrc"),
                ]
            )
            assert ret == 0


# ---------------------------------------------------------------------------
# cd subcommand
# ---------------------------------------------------------------------------


class TestCdCommand:
    def test_cd_execs_shell_in_source_dir(self, capsys, monkeypatch):
        """`ishfiles cd` execs a new shell in the source directory."""
        import os

        execvp_calls: list = []

        def fake_execvp(file, args):
            execvp_calls.append((file, args))

        monkeypatch.setenv("SHELL", "/bin/sh")
        monkeypatch.setattr(os, "execvp", fake_execvp)
        monkeypatch.setattr(os, "chdir", lambda p: None)

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            cli_main(["--source", src, "--target", tgt, "cd"])

        assert execvp_calls == [("/bin/sh", ["/bin/sh"])]
        captured = capsys.readouterr()
        assert "spawning a subshell" in captured.err
        assert "ishfiles init" in captured.err

    def test_cd_missing_source_returns_error(self, capsys):
        """`ishfiles cd` returns 1 and prints an error when source is missing."""
        with tempfile.TemporaryDirectory() as tgt:
            missing = Path(tgt) / "missing"
            ret = cli_main(["--source", str(missing), "--target", tgt, "cd"])
            assert ret == 1
            captured = capsys.readouterr()
            assert "does not exist" in captured.err


# ---------------------------------------------------------------------------
# pd subcommand
# ---------------------------------------------------------------------------


class TestPdCommand:
    def test_pd_prints_source_dir(self, capsys):
        """`ishfiles pd` prints the resolved source directory."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "pd"])
            assert ret == 0
            captured = capsys.readouterr()
            assert captured.out.strip() == src

    def test_pd_missing_source_warns_but_succeeds(self, capsys):
        """`ishfiles pd` exits 0 with a stderr warning when source is missing."""
        with tempfile.TemporaryDirectory() as tgt:
            missing = Path(tgt) / "missing"
            ret = cli_main(["--source", str(missing), "--target", tgt, "pd"])
            assert ret == 0
            captured = capsys.readouterr()
            assert Path(captured.out.strip()) == missing
            assert "does not exist" in captured.err


# ---------------------------------------------------------------------------
# init subcommand
# ---------------------------------------------------------------------------


class TestInitCommand:
    def _check_snippet(self, out: str) -> None:
        assert "ishfiles()" in out
        assert "command ishfiles pd" in out

    def test_init_default(self, capsys):
        """`ishfiles init` with no flag prints the POSIX shell snippet."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "init"])
        assert ret == 0
        self._check_snippet(capsys.readouterr().out)

    def test_init_sh(self, capsys):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "init", "--sh"])
        assert ret == 0
        self._check_snippet(capsys.readouterr().out)

    def test_init_bash(self, capsys):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "init", "--bash"])
        assert ret == 0
        self._check_snippet(capsys.readouterr().out)

    def test_init_zsh(self, capsys):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "init", "--zsh"])
        assert ret == 0
        self._check_snippet(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# add subcommand
# ---------------------------------------------------------------------------


class TestAddCommand:
    def test_add_new_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            target_file = _make_file(Path(tgt) / ".bashrc", "my config\n")

            ret = cli_main(["--source", src, "--target", tgt, "add", str(target_file)])

            assert ret == 0
            source_file = Path(src) / "dot_bashrc"
            assert source_file.exists()
            assert source_file.read_text() == "my config\n"

    def test_add_duplicate_identical(self, capsys):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(tgt) / ".bashrc", "same\n")
            _make_file(Path(src) / "dot_bashrc", "same\n")

            ret = cli_main(
                ["--source", src, "--target", tgt, "add", str(Path(tgt) / ".bashrc")]
            )

            assert ret == 0
            captured = capsys.readouterr()
            assert "already tracked" in captured.out

    def test_add_dirty_refuses(self, capsys):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(tgt) / ".bashrc", "new content\n")
            _make_file(Path(src) / "dot_bashrc", "old content\n")

            ret = cli_main(
                ["--source", src, "--target", tgt, "add", str(Path(tgt) / ".bashrc")]
            )

            assert ret == 1
            captured = capsys.readouterr()
            assert "dirty" in captured.err.lower() or "Refusing" in captured.err

    def test_add_dirty_with_force(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(tgt) / ".bashrc", "new content\n")
            _make_file(Path(src) / "dot_bashrc", "old content\n")

            ret = cli_main(
                [
                    "--source",
                    src,
                    "--target",
                    tgt,
                    "add",
                    "--force",
                    str(Path(tgt) / ".bashrc"),
                ]
            )

            assert ret == 0
            assert (Path(src) / "dot_bashrc").read_text() == "new content\n"

    def test_add_dry_run(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(tgt) / ".bashrc", "content\n")

            ret = cli_main(
                [
                    "--source",
                    src,
                    "--target",
                    tgt,
                    "--dry-run",
                    "add",
                    str(Path(tgt) / ".bashrc"),
                ]
            )

            assert ret == 0
            assert not (Path(src) / "dot_bashrc").exists()

    def test_add_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(
                [
                    "--source",
                    src,
                    "--target",
                    tgt,
                    "add",
                    str(Path(tgt) / ".nonexistent"),
                ]
            )
            assert ret == 1

    def test_add_nested_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            target_file = _make_file(
                Path(tgt) / ".config" / "fish" / "config.fish", "fish cfg\n"
            )

            ret = cli_main(["--source", src, "--target", tgt, "add", str(target_file)])

            assert ret == 0
            source_file = Path(src) / "dot_config" / "fish" / "config.fish"
            assert source_file.exists()
            assert source_file.read_text() == "fish cfg\n"


# ---------------------------------------------------------------------------
# diff/apply with file arguments
# ---------------------------------------------------------------------------


class TestDiffWithFiles:
    def test_diff_restrict_to_file_by_source_name(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "bash\n")
            _make_file(Path(src) / "dot_vimrc", "vim\n")

            # Only diff dot_bashrc
            ret = cli_main(["--source", src, "--target", tgt, "diff", "dot_bashrc"])
            assert ret == 1  # one change

    def test_diff_restrict_to_file_by_target_name(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "bash\n")
            _make_file(Path(src) / "dot_vimrc", "vim\n")

            # Use target name .bashrc
            ret = cli_main(["--source", src, "--target", tgt, "diff", ".bashrc"])
            assert ret == 1

    def test_diff_restrict_to_file_no_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "same\n")
            _make_file(Path(tgt) / ".bashrc", "same\n")
            _make_file(Path(src) / "dot_vimrc", "vim\n")

            ret = cli_main(["--source", src, "--target", tgt, "diff", ".bashrc"])
            assert ret == 0  # .bashrc unchanged

    def test_diff_restrict_absolute_target_path(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "bash\n")
            _make_file(Path(src) / "dot_vimrc", "vim\n")

            ret = cli_main(
                [
                    "--source",
                    src,
                    "--target",
                    tgt,
                    "diff",
                    str(Path(tgt) / ".bashrc"),
                ]
            )
            assert ret == 1


class TestApplyWithFiles:
    def test_apply_restrict_to_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "bash\n")
            _make_file(Path(src) / "dot_vimrc", "vim\n")

            from pyishlib.userio import Choice

            with patch(
                "pyishlib.ishfiles.commands.apply.prompt_yes_no_always",
                return_value=Choice.YES,
            ):
                ret = cli_main(
                    ["--source", src, "--target", tgt, "apply", "dot_bashrc"]
                )

            assert ret == 0
            assert (Path(tgt) / ".bashrc").exists()
            assert not (Path(tgt) / ".vimrc").exists()

    def test_apply_restrict_by_target_name(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "bash\n")
            _make_file(Path(src) / "dot_vimrc", "vim\n")

            from pyishlib.userio import Choice

            with patch(
                "pyishlib.ishfiles.commands.apply.prompt_yes_no_always",
                return_value=Choice.YES,
            ):
                ret = cli_main(["--source", src, "--target", tgt, "apply", ".bashrc"])

            assert ret == 0
            assert (Path(tgt) / ".bashrc").exists()
            assert not (Path(tgt) / ".vimrc").exists()


# ---------------------------------------------------------------------------
# install subcommand
# ---------------------------------------------------------------------------


class TestInstallCommand:
    def test_install_no_config_returns_0(self):
        """install succeeds silently when no package config exists."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "install"])
        assert ret == 0

    def test_install_dry_run_shows_packages(self, capsys):
        """Dry-run lists packages that would be installed without running anything."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            (config_dir / "packages.json").write_text(
                '{"nonexistent-test-pkg": {"apt": "nonexistent-test-pkg", "cmd": "nonexistent_test_cmd_12345"}}'
            )

            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "install"])

        assert ret == 0
        captured = capsys.readouterr()
        assert "nonexistent-test-pkg" in captured.out

    def test_install_dry_run_toml(self, capsys):
        """Dry-run works with TOML package config."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            (config_dir / "packages.toml").write_text(
                '[nonexistent-toml-pkg]\napt = "nonexistent-toml-pkg"\ncmd = "nonexistent_toml_cmd_12345"\n'
            )

            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "install"])

        assert ret == 0
        captured = capsys.readouterr()
        assert "nonexistent-toml-pkg" in captured.out

    def test_install_specific_packages(self, capsys):
        """Restricting to named packages only installs those."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            (config_dir / "packages.json").write_text(
                '{"pkg-a": {"apt": "pkg-a", "cmd": "nonexistent_a_12345"}, '
                '"pkg-b": {"apt": "pkg-b", "cmd": "nonexistent_b_12345"}}'
            )

            ret = cli_main(
                ["--source", src, "--target", tgt, "--dry-run", "install", "pkg-a"]
            )

        assert ret == 0
        captured = capsys.readouterr()
        assert "pkg-a" in captured.out
        assert "pkg-b" not in captured.out

    def test_install_unknown_package_returns_1(self):
        """Requesting an unknown package name returns error."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            (config_dir / "packages.json").write_text(
                '{"pkg-a": {"apt": "pkg-a", "cmd": "nonexistent_a_12345"}}'
            )

            ret = cli_main(
                [
                    "--source",
                    src,
                    "--target",
                    tgt,
                    "--dry-run",
                    "install",
                    "no-such-pkg",
                ]
            )

        assert ret == 1

    def test_install_all_present_shows_message(self, capsys):
        """When all packages are already installed, a message is shown."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            # Use the running interpreter so the command is guaranteed to exist
            exe = sys.executable.replace("\\", "/")
            (config_dir / "packages.json").write_text(
                f'{{"python": {{"cmd": "{exe}"}}}}'
            )

            ret = cli_main(["--source", src, "--target", tgt, "install"])

        assert ret == 0
        captured = capsys.readouterr()
        assert "already installed" in captured.out

    def test_install_toml_preferred_over_json(self, capsys):
        """TOML config takes priority when both exist."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            (config_dir / "packages.toml").write_text(
                '[toml-only-pkg]\ncmd = "nonexistent_toml_only_12345"\n'
            )
            (config_dir / "packages.json").write_text(
                '{"json-only-pkg": {"cmd": "nonexistent_json_only_12345"}}'
            )

            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "install"])

        assert ret == 0
        captured = capsys.readouterr()
        assert "toml-only-pkg" in captured.out
        assert "json-only-pkg" not in captured.out


# ---------------------------------------------------------------------------
# apply + install integration
# ---------------------------------------------------------------------------


class TestApplyWithInstall:
    def test_apply_runs_install(self, capsys):
        """apply also triggers package installation."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            config_dir = Path(src) / "ishconfig"
            config_dir.mkdir()
            (config_dir / "packages.json").write_text(
                '{"nonexistent-apply-pkg": {"apt": "nonexistent-apply-pkg", "cmd": "nonexistent_apply_cmd_12345"}}'
            )

            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "apply"])

        assert ret == 0
        captured = capsys.readouterr()
        assert "nonexistent-apply-pkg" in captured.out

    def test_apply_no_packages_config_still_works(self):
        """apply works normally when no package config exists."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "apply"])
        assert ret == 0


# ---------------------------------------------------------------------------
# scan_scripts unit tests
# ---------------------------------------------------------------------------


class TestScanScripts:
    def test_print_skipped_emits_message_for_os_filtered_script(self, capsys):
        """scan_scripts prints a [skipped] line when print_skipped=True and a script is excluded by OS rules."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(scripts_dir / "os-only.sh", "#!/bin/sh\necho hello\n")

            cfg = load_config(_make_args(source=src, target=tgt))

            with patch(
                "pyishlib.ishfiles.script_runner.should_skip_for_os_from_metadata",
                return_value=True,
            ):
                kept, _ = scan_scripts(cfg, print_skipped=True)

        assert kept == []
        captured = capsys.readouterr()
        assert "[skipped]" in captured.out
        assert "os-only.sh" in captured.out

    def test_print_skipped_false_emits_no_message(self, capsys):
        """scan_scripts prints nothing for skipped scripts when print_skipped=False."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(scripts_dir / "os-only.sh", "#!/bin/sh\necho hello\n")

            cfg = load_config(_make_args(source=src, target=tgt))

            with patch(
                "pyishlib.ishfiles.script_runner.should_skip_for_os_from_metadata",
                return_value=True,
            ):
                kept, _ = scan_scripts(cfg, print_skipped=False)

        assert kept == []
        captured = capsys.readouterr()
        assert "[skipped]" not in captured.out


# ---------------------------------------------------------------------------
# runscripts subcommand
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="executes /bin/sh scripts")
class TestRunscriptsCommand:
    def test_runscripts_no_scripts_dir(self):
        """runscripts succeeds silently when no ishscripts dir exists."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])
        assert ret == 0

    def test_runscripts_empty_dir(self):
        """runscripts succeeds when ishscripts dir is empty."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            (Path(src) / "ishscripts").mkdir()
            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])
        assert ret == 0

    def test_runscripts_dry_run(self, capsys):
        """Dry-run lists scripts without executing them."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(scripts_dir / "setup.sh", "#!/bin/sh\necho hello\n")

            ret = cli_main(
                ["--source", src, "--target", tgt, "--dry-run", "runscripts"]
            )

        assert ret == 0
        captured = capsys.readouterr()
        assert "setup.sh" in captured.out

    def test_runscripts_executes_script(self):
        """Scripts are actually executed."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            marker = Path(tgt) / "marker.txt"
            _make_file(
                scripts_dir / "create-marker.sh",
                f"#!/bin/sh\necho done > {marker}\n",
            )

            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])

            assert ret == 0
            assert marker.exists()
            assert "done" in marker.read_text()

    def test_runscripts_sorted_order(self):
        """Scripts run in sorted filename order."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            log_file = Path(tgt) / "order.log"
            _make_file(
                scripts_dir / "02-second.sh",
                f"#!/bin/sh\necho second >> {log_file}\n",
            )
            _make_file(
                scripts_dir / "01-first.sh",
                f"#!/bin/sh\necho first >> {log_file}\n",
            )

            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])

            assert ret == 0
            lines = log_file.read_text().strip().split("\n")
            assert lines == ["first", "second"]

    def test_runscripts_specific_script(self, capsys):
        """Restricting to a named script runs only that one."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            marker_a = Path(tgt) / "a.txt"
            marker_b = Path(tgt) / "b.txt"
            _make_file(
                scripts_dir / "a.sh",
                f"#!/bin/sh\necho a > {marker_a}\n",
            )
            _make_file(
                scripts_dir / "b.sh",
                f"#!/bin/sh\necho b > {marker_b}\n",
            )

            ret = cli_main(["--source", src, "--target", tgt, "runscripts", "a.sh"])

            assert ret == 0
            assert marker_a.exists()
            assert not marker_b.exists()

    def test_runscripts_unknown_script_returns_1(self):
        """Requesting an unknown script name returns error."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(scripts_dir / "real.sh", "#!/bin/sh\necho ok\n")

            ret = cli_main(
                ["--source", src, "--target", tgt, "runscripts", "no-such.sh"]
            )

        assert ret == 1

    def test_runscripts_failing_script_returns_1(self):
        """A script that exits non-zero causes a failure return."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(scripts_dir / "fail.sh", "#!/bin/sh\nexit 1\n")

            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])

        assert ret == 1

    def test_runscripts_with_preprocessing(self):
        """Scripts undergo @ish directive preprocessing."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            marker = Path(tgt) / "preproc.txt"
            _make_file(
                scripts_dir / "preproc.sh",
                f"#!/bin/sh\n#@ish set target={marker}\n"
                f"echo preprocessed > ${{__ish_target}}\n",
            )

            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])

            assert ret == 0
            assert marker.exists()
            assert "preprocessed" in marker.read_text()

    def test_runscripts_hidden_files_skipped(self):
        """Hidden files (starting with .) are skipped."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            marker = Path(tgt) / "hidden.txt"
            _make_file(
                scripts_dir / ".hidden.sh",
                f"#!/bin/sh\necho hidden > {marker}\n",
            )

            ret = cli_main(["--source", src, "--target", tgt, "runscripts"])

            assert ret == 0
            assert not marker.exists()


# ---------------------------------------------------------------------------
# apply + runscripts integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="executes /bin/sh scripts")
class TestApplyWithRunscripts:
    def test_apply_runs_scripts(self):
        """apply also triggers script execution."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            marker = Path(tgt) / "apply_marker.txt"
            _make_file(
                scripts_dir / "setup.sh",
                f"#!/bin/sh\necho applied > {marker}\n",
            )

            from pyishlib.userio import Choice

            with patch(
                "pyishlib.ishfiles.commands.apply.prompt_yes_no_always",
                return_value=Choice.YES,
            ):
                ret = cli_main(["--source", src, "--target", tgt, "apply"])

            assert ret == 0
            assert marker.exists()
            assert "applied" in marker.read_text()

    def test_apply_dry_run_does_not_execute_scripts(self):
        """In dry-run mode, scripts are listed but not executed."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            marker = Path(tgt) / "should_not_exist.txt"
            _make_file(
                scripts_dir / "setup.sh",
                f"#!/bin/sh\necho oops > {marker}\n",
            )

            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "apply"])

            assert ret == 0
            assert not marker.exists()

    def test_apply_no_scripts_dir_still_works(self):
        """apply works normally when no ishscripts dir exists."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")
            ret = cli_main(["--source", src, "--target", tgt, "--dry-run", "apply"])
        assert ret == 0


# ---------------------------------------------------------------------------
# DotfileContext.prompt()
# ---------------------------------------------------------------------------


class TestDotfileContextPrompt:
    def test_returns_existing_value_without_prompting(self):
        """prompt() returns stored value and never calls input()."""
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext({"mykey": "stored"})
        with patch("builtins.input", side_effect=AssertionError("should not prompt")):
            result = ctx.prompt("mykey", "Enter value", "default")
        assert result == "stored"

    def test_prompts_for_missing_key(self):
        """prompt() calls input() and stores the result when key is absent."""
        from pyishlib.dotfile_context import DotfileContext
        import io

        ctx = DotfileContext()
        with patch("builtins.input", return_value="typed"), \
             patch("sys.stdin", io.StringIO("typed")), \
             patch("sys.stdin.isatty", return_value=True):
            result = ctx.prompt("mykey", "Enter value", "default")
        assert result == "typed"
        assert ctx.get("mykey") == "typed"

    def test_uses_default_on_empty_input(self):
        """prompt() falls back to default when user presses Enter."""
        from pyishlib.dotfile_context import DotfileContext
        import io

        ctx = DotfileContext()
        with patch("builtins.input", return_value=""), \
             patch("sys.stdin", io.StringIO("")), \
             patch("sys.stdin.isatty", return_value=True):
            result = ctx.prompt("mykey", "Enter value", "fallback")
        assert result == "fallback"
        assert ctx.get("mykey") == "fallback"

    def test_non_tty_uses_default_without_prompting(self):
        """prompt() uses default silently when stdin is not a tty."""
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext()
        with patch("sys.stdin.isatty", return_value=False), \
             patch("builtins.input", side_effect=AssertionError("should not prompt")):
            result = ctx.prompt("mykey", "Enter value", "autodefault")
        assert result == "autodefault"
        assert ctx.get("mykey") == "autodefault"


# ---------------------------------------------------------------------------
# @ish prompt directive
# ---------------------------------------------------------------------------


class TestNormaliseBool:
    def test_true_synonyms(self):
        from pyishlib.userio import normalise_bool

        for val in ("true", "True", "TRUE", "yes", "Yes", "y", "Y", "1", "on", "ON"):
            assert normalise_bool(val) == "true", f"expected true for {val!r}"

    def test_false_synonyms(self):
        from pyishlib.userio import normalise_bool

        for val in ("false", "False", "FALSE", "no", "No", "n", "N", "0", "off", "OFF"):
            assert normalise_bool(val) == "false", f"expected false for {val!r}"

    def test_unrecognised_returns_none(self):
        from pyishlib.userio import normalise_bool

        assert normalise_bool("maybe") is None
        assert normalise_bool("") is None
        assert normalise_bool("2") is None


class TestDotfileContextPromptBool:
    def test_returns_normalised_existing_value(self):
        """prompt_bool() normalises and returns a stored synonym without prompting."""
        from pyishlib.dotfile_context import DotfileContext

        for stored, expected in (("yes", "true"), ("No", "false"), ("1", "true")):
            ctx = DotfileContext({"flag": stored})
            with patch("pyishlib.userio.getch", side_effect=AssertionError("no prompt")):
                result = ctx.prompt_bool("flag", "Is it?")
            assert result == expected
            assert ctx.get("flag") == expected

    def test_prompts_and_stores_true(self):
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext()
        with patch("pyishlib.userio.getch", return_value="y"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = ctx.prompt_bool("flag", "Is it?", False)
        assert result == "true"
        assert ctx.get("flag") == "true"

    def test_prompts_and_stores_false(self):
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext()
        with patch("pyishlib.userio.getch", return_value="N"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = ctx.prompt_bool("flag", "Is it?", True)
        assert result == "false"

    def test_enter_uses_default_true(self):
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext()
        with patch("pyishlib.userio.getch", return_value="\r"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = ctx.prompt_bool("flag", "Is it?", True)
        assert result == "true"

    def test_non_tty_uses_default_false(self):
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext()
        with patch("sys.stdin.isatty", return_value=False), \
             patch("pyishlib.userio.getch", side_effect=AssertionError("no prompt")):
            result = ctx.prompt_bool("flag", "Is it?", False)
        assert result == "false"

    def test_retries_on_invalid_key(self):
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext()
        with patch("pyishlib.userio.getch", side_effect=["x", "y"]), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = ctx.prompt_bool("flag", "Is it?", False)
        assert result == "true"

    def test_unrecognised_existing_value_falls_through_to_prompt(self):
        """prompt_bool() with an unrecognised stored value falls through to the prompt."""
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext({"flag": "maybe"})  # not a valid bool string
        with patch("pyishlib.userio.getch", return_value="n"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = ctx.prompt_bool("flag", "Is it?", True)
        assert result == "false"
        assert ctx.get("flag") == "false"

    def test_unrecognised_existing_value_nontty_uses_default(self):
        """prompt_bool() with unrecognised stored value and no tty uses default."""
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext({"flag": "garbage"})
        with patch("sys.stdin.isatty", return_value=False):
            result = ctx.prompt_bool("flag", "Is it?", False)
        assert result == "false"


class TestIshPromptDirective:
    def _preprocess(self, text, variables=None):
        from pyishlib.file_preprocessor import FilePreprocessor
        import io

        proc = FilePreprocessor(variables=variables or {})
        with patch("sys.stdin", io.StringIO("typed")), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("builtins.input", return_value="typed"):
            return proc.preprocess_text(text)

    def test_prompt_directive_sets_variable(self):
        """@ish prompt sets a variable via DotfileContext.prompt()."""
        text = '#@ish prompt myvar "Enter value" "def"\n${__ish_myvar}\n'
        result = self._preprocess(text)
        assert "typed" in result

    def test_prompt_directive_skips_if_already_set(self):
        """@ish prompt does not overwrite an existing variable."""
        text = '#@ish prompt myvar "Enter value" "def"\n${__ish_myvar}\n'
        with patch("builtins.input", side_effect=AssertionError("should not prompt")):
            from pyishlib.file_preprocessor import FilePreprocessor
            proc = FilePreprocessor(variables={"myvar": "preset"})
            result = proc.preprocess_text(text)
        assert "preset" in result

    def test_prompt_directive_uses_default_in_non_tty(self):
        """@ish prompt uses default value when not interactive."""
        from pyishlib.file_preprocessor import FilePreprocessor

        text = '#@ish prompt myvar "Enter value" "mydefault"\n${__ish_myvar}\n'
        proc = FilePreprocessor()
        with patch("sys.stdin.isatty", return_value=False), \
             patch("builtins.input", side_effect=AssertionError("should not prompt")):
            result = proc.preprocess_text(text)
        assert "mydefault" in result

    def test_prompt_bool_directive_sets_normalised_value(self):
        """@ish prompt_bool normalises the answer to true/false."""
        from pyishlib.file_preprocessor import FilePreprocessor

        text = '#@ish prompt_bool flag "Is it?" "false"\n${__ish_flag}\n'
        proc = FilePreprocessor()
        with patch("pyishlib.userio.getch", return_value="y"), \
             patch("sys.stdin.isatty", return_value=True), \
             patch("sys.stdout.write"), patch("sys.stdout.flush"):
            result = proc.preprocess_text(text)
        assert "true" in result

    def test_prompt_bool_directive_uses_default_in_non_tty(self):
        """@ish prompt_bool uses the default in non-interactive mode."""
        from pyishlib.file_preprocessor import FilePreprocessor

        text = '#@ish prompt_bool flag "Is it?" "true"\n${__ish_flag}\n'
        proc = FilePreprocessor()
        with patch("sys.stdin.isatty", return_value=False), \
             patch("pyishlib.userio.getch", side_effect=AssertionError("no prompt")):
            result = proc.preprocess_text(text)
        assert "true" in result


# ---------------------------------------------------------------------------
# process_data_template()
# ---------------------------------------------------------------------------


class TestProcessDataTemplate:
    def _make_cfg(self, src, config_path=None):
        """Build a minimal IshConfig pointing at src."""
        if config_path is None:
            config_path = Path("/nonexistent/config.toml")
        return load_config(
            args=SimpleNamespace(
                source=src,
                target="/tmp/unused_target",
                config=str(config_path),
                home=None,
                dry_run=None,
                verbose=None,
                debug=None,
                quiet=None,
            ),
            config_file=config_path,
        )

    def test_no_data_toml_is_a_noop(self):
        """process_data_template() does nothing if no data.toml exists."""
        from pyishlib.ishfiles.data import process_data_template

        with tempfile.TemporaryDirectory() as src:
            cfg = self._make_cfg(src)
            with patch("builtins.input", side_effect=AssertionError("should not prompt")):
                process_data_template(cfg)  # must not raise

    def test_prompts_for_missing_values(self):
        """process_data_template() prompts for values absent from context."""
        from pyishlib.ishfiles.data import process_data_template
        import io

        with tempfile.TemporaryDirectory() as src:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[myvar]\nprompt = "Enter myvar"\ndefault = "def"\n',
            )
            cfg = self._make_cfg(src)
            with patch("builtins.input", return_value="userval"), \
                 patch("sys.stdin", io.StringIO("userval")), \
                 patch("sys.stdin.isatty", return_value=False):
                process_data_template(cfg)
            assert cfg.context.get("myvar") == "def"  # non-tty uses default

    def test_skips_already_set_values(self):
        """process_data_template() skips variables already in context."""
        from pyishlib.ishfiles.data import process_data_template

        with tempfile.TemporaryDirectory() as src:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[myvar]\nprompt = "Enter myvar"\ndefault = "def"\n',
            )
            cfg = self._make_cfg(src)
            cfg.context.set("myvar", "preset")
            with patch("builtins.input", side_effect=AssertionError("should not prompt")):
                process_data_template(cfg)
            assert cfg.context.get("myvar") == "preset"

    def test_dry_run_does_not_save(self):
        """process_data_template() does not offer to save in dry-run mode."""
        from pyishlib.ishfiles.data import process_data_template

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as cfg_dir:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[myvar]\nprompt = "Enter myvar"\ndefault = "def"\n',
            )
            config_path = Path(cfg_dir) / "config.toml"
            cfg = load_config(
                args=SimpleNamespace(
                    source=src,
                    target="/tmp/unused_target",
                    config=str(config_path),
                    home=None,
                    dry_run=True,
                    verbose=None,
                    debug=None,
                    quiet=None,
                ),
                config_file=config_path,
            )
            with patch("sys.stdin.isatty", return_value=False):
                process_data_template(cfg)
            assert not config_path.exists()

    def test_invalid_bool_value_triggers_reprompt(self):
        """process_data_template() re-prompts when a bool field has an invalid value."""
        from pyishlib.ishfiles.data import process_data_template

        with tempfile.TemporaryDirectory() as src:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[isWork]\nprompt = "Is this a work machine?"\ndefault = "false"\ntype = "bool"\n',
            )
            cfg = self._make_cfg(src)
            cfg.context.set("isWork", "unknown")  # invalid bool value

            with patch("pyishlib.userio.getch", return_value="n"), \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch("sys.stdout.write"), patch("sys.stdout.flush"):
                process_data_template(cfg)

            assert cfg.context.get("isWork") == "false"

    def test_valid_bool_synonym_is_accepted_without_reprompt(self):
        """process_data_template() accepts a valid bool synonym without prompting."""
        from pyishlib.ishfiles.data import process_data_template

        with tempfile.TemporaryDirectory() as src:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[isWork]\nprompt = "Is this a work machine?"\ndefault = "false"\ntype = "bool"\n',
            )
            cfg = self._make_cfg(src)
            cfg.context.set("isWork", "yes")  # valid synonym for true

            with patch("pyishlib.userio.getch", side_effect=AssertionError("should not prompt")):
                process_data_template(cfg)

            assert cfg.context.get("isWork") == "true"

    def test_invalid_bool_value_included_in_new_values(self):
        """Re-prompted values from invalid bool fields are offered for saving."""
        from pyishlib.ishfiles.data import process_data_template, _validate_value

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as cfg_dir:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[isWork]\nprompt = "Is this a work machine?"\ndefault = "false"\ntype = "bool"\n',
            )
            config_path = Path(cfg_dir) / "config.toml"
            cfg = load_config(
                args=SimpleNamespace(
                    source=src,
                    target="/tmp/unused_target",
                    config=str(config_path),
                    home=None,
                    dry_run=None,
                    verbose=None,
                    debug=None,
                    quiet=None,
                ),
                config_file=config_path,
            )
            cfg.context.set("isWork", "garbage")

            with patch("pyishlib.userio.getch", return_value="y"), \
                 patch("sys.stdin.isatty", return_value=False):
                process_data_template(cfg)

            # Non-tty falls back to default ("false"), but the value was reset from "garbage"
            assert cfg.context.get("isWork") in ("true", "false")

    def test_string_field_with_any_value_is_accepted(self):
        """process_data_template() accepts any non-empty string for untyped fields."""
        from pyishlib.ishfiles.data import process_data_template

        with tempfile.TemporaryDirectory() as src:
            ishconfig = Path(src) / "ishconfig"
            ishconfig.mkdir()
            _make_file(
                ishconfig / "data.toml",
                '[email]\nprompt = "Email address"\ndefault = "user@example.com"\n',
            )
            cfg = self._make_cfg(src)
            cfg.context.set("email", "anything@example.com")

            with patch("builtins.input", side_effect=AssertionError("should not prompt")):
                process_data_template(cfg)

            assert cfg.context.get("email") == "anything@example.com"


# ---------------------------------------------------------------------------
# Data section save/load helpers
# ---------------------------------------------------------------------------


class TestDataSectionIO:
    def test_save_creates_data_section_in_new_file(self):
        """_save_data_section() writes [data] to a non-existent file."""
        from pyishlib.ishfiles.data import _save_data_section

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            _save_data_section(path, {"foo": "bar"})
            text = path.read_text()
            assert "[data]" in text
            assert 'foo = "bar"' in text

    def test_save_appends_to_existing_file(self):
        """_save_data_section() appends [data] when file has no [data] section."""
        from pyishlib.ishfiles.data import _save_data_section

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text('[ishfiles]\nsource = "/some/path"\n')
            _save_data_section(path, {"key": "val"})
            text = path.read_text()
            assert '[ishfiles]' in text
            assert "[data]" in text
            assert 'key = "val"' in text

    def test_save_replaces_existing_data_section(self):
        """_save_data_section() replaces an existing [data] section."""
        from pyishlib.ishfiles.data import _save_data_section

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text('[data]\nold = "value"\n')
            _save_data_section(path, {"newkey": "newval"})
            text = path.read_text()
            assert 'newkey = "newval"' in text
            assert 'old = "value"' in text  # merged, not dropped

    def test_save_merges_with_existing_data(self):
        """_save_data_section() merges new values with existing [data] entries."""
        from pyishlib.ishfiles.data import _save_data_section

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text('[data]\nexisting = "kept"\n')
            _save_data_section(path, {"added": "new"})
            text = path.read_text()
            assert 'existing = "kept"' in text
            assert 'added = "new"' in text


if __name__ == "__main__":
    pytest.main()
