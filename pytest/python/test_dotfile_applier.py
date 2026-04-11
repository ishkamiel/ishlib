#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for DotfileApplier and DotFile classes

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.dotfile_applier import DotfileApplier
from pyishlib.dotfile import (
    ChangeType,
    DotFile,
    translate_name,
    translate_path,
)
from pyishlib.dotfile_ignore import (
    DotfileIgnore,
    load_ignore_file,
)
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig
from pyishlib.ish_comp import Choice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# translate_name / translate_path (module-level functions)
# ---------------------------------------------------------------------------


class TestTranslateName:
    def test_dot_prefix(self):
        assert translate_name("dot_bashrc") == ".bashrc"

    def test_no_prefix(self):
        assert translate_name("README") == "README"

    def test_dot_prefix_nested(self):
        assert translate_name("dot_config") == ".config"

    def test_dot_only(self):
        assert translate_name("dot_") == "."

    def test_contains_dot_not_prefix(self):
        assert translate_name("my_dot_file") == "my_dot_file"


class TestTranslatePath:
    def test_single_component(self):
        assert translate_path(Path("dot_bashrc")) == Path(".bashrc")

    def test_multi_component(self):
        result = translate_path(Path("dot_config/dot_git/config"))
        assert result == Path(".config/.git/config")

    def test_no_translation_needed(self):
        assert translate_path(Path("bin/script")) == Path("bin/script")

    def test_mixed(self):
        result = translate_path(Path("dot_config/nvim/init.vim"))
        assert result == Path(".config/nvim/init.vim")


# ---------------------------------------------------------------------------
# DotFile
# ---------------------------------------------------------------------------


class TestDotFile:
    def test_properties(self):
        with tempfile.TemporaryDirectory() as tgt:
            src = Path("/repo/dot_bashrc")
            df = DotFile(src, Path("dot_bashrc"), Path(tgt))

            assert df.source == src
            assert df.rel_path == Path("dot_bashrc")
            assert df.translated == Path(".bashrc")
            assert df.target == Path(tgt) / ".bashrc"

    def test_nested_path(self):
        with tempfile.TemporaryDirectory() as tgt:
            df = DotFile(
                Path("/repo/dot_config/nvim/init.vim"),
                Path("dot_config/nvim/init.vim"),
                Path(tgt),
            )
            assert df.translated == Path(".config/nvim/init.vim")
            assert df.target == Path(tgt) / ".config" / "nvim" / "init.vim"

    def test_staged_default_none(self):
        df = DotFile(Path("/a"), Path("a"), Path("/home"))
        assert df.staged is None

    def test_staged_setter(self):
        df = DotFile(Path("/a"), Path("a"), Path("/home"))
        df.staged = Path("/tmp/staged/a")
        assert df.staged == Path("/tmp/staged/a")

    def test_effective_source_without_staging(self):
        df = DotFile(Path("/repo/file"), Path("file"), Path("/home"))
        assert df.effective_source == Path("/repo/file")

    def test_effective_source_with_staging(self):
        df = DotFile(Path("/repo/file"), Path("file"), Path("/home"))
        df.staged = Path("/tmp/staged/file")
        assert df.effective_source == Path("/tmp/staged/file")

    def test_change_type_new(self):
        with tempfile.TemporaryDirectory() as tgt:
            with tempfile.TemporaryDirectory() as src_dir:
                src = _make_file(Path(src_dir) / "dot_bashrc", "content\n")
                df = DotFile(src, Path("dot_bashrc"), Path(tgt))
                assert df.get_change_type() == ChangeType.NEW

    def test_change_type_modified(self):
        with tempfile.TemporaryDirectory() as tgt:
            with tempfile.TemporaryDirectory() as src_dir:
                src = _make_file(Path(src_dir) / "dot_bashrc", "new\n")
                _make_file(Path(tgt) / ".bashrc", "old\n")
                df = DotFile(src, Path("dot_bashrc"), Path(tgt))
                assert df.get_change_type() == ChangeType.MODIFIED

    def test_change_type_unchanged(self):
        with tempfile.TemporaryDirectory() as tgt:
            with tempfile.TemporaryDirectory() as src_dir:
                src = _make_file(Path(src_dir) / "dot_bashrc", "same\n")
                _make_file(Path(tgt) / ".bashrc", "same\n")
                df = DotFile(src, Path("dot_bashrc"), Path(tgt))
                assert df.get_change_type() is None

    def test_repr(self):
        df = DotFile(Path("/repo/dot_bashrc"), Path("dot_bashrc"), Path("/home"))
        r = repr(df)
        assert "dot_bashrc" in r
        assert ".bashrc" in r


# ---------------------------------------------------------------------------
# Ignore handling
# ---------------------------------------------------------------------------


class TestIgnore:
    def test_load_ignore_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".dotfileignore"
            p.write_text("# comment\n*.bak\ntemp_*\n\n")
            patterns, only_on, ignore_on = load_ignore_file(p)
            assert patterns == ["*.bak", "temp_*"]
            assert only_on == {}
            assert ignore_on == {}

    def test_load_ignore_file_missing(self):
        patterns, only_on, ignore_on = load_ignore_file(
            Path("/nonexistent/.dotfileignore")
        )
        assert patterns == []
        assert only_on == {}
        assert ignore_on == {}

    def test_is_ignored_default(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d))
            assert di.is_ignored(".git")

    def test_is_ignored_by_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), extra_patterns=["*.bak"])
            assert di.is_ignored("file.bak")

    def test_not_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), extra_patterns=["*.bak"])
            assert not di.is_ignored("dot_bashrc")


# ---------------------------------------------------------------------------
# DotfileApplier.discover (Stage 1)
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_discover_scan(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "dot_profile")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            names = [df.translated.name for df in dotfiles]
            assert ".bashrc" in names
            assert ".profile" in names

    def test_discover_nested(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_config" / "nvim" / "init.vim")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            assert len(dotfiles) == 1
            assert dotfiles[0].target == Path(tgt) / ".config" / "nvim" / "init.vim"

    def test_discover_ignores_defaults(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / ".git" / "config")
            _make_file(Path(src) / "dot_bashrc")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            assert len(dotfiles) == 1

    def test_discover_custom_ignore(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "SKIPME")

            di = DotfileIgnore(Path(src), extra_patterns=["SKIPME"])
            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                dotfile_ignore=di,
            )
            dotfiles = applier.discover()

            names = [df.source.name for df in dotfiles]
            assert "SKIPME" not in names

    def test_discover_dotfileignore(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "notes.bak")
            _make_file(Path(src) / ".dotfileignore", "*.bak\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            names = [df.source.name for df in dotfiles]
            assert "notes.bak" not in names
            assert "dot_bashrc" in names

    def test_discover_empty_dir(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            assert applier.discover() == []

    def test_discover_explicit_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "dot_profile")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover(files=[Path("dot_bashrc")])

            assert len(dotfiles) == 1
            assert dotfiles[0].translated == Path(".bashrc")

    def test_discover_explicit_missing_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover(files=[Path("nonexistent")])

            assert dotfiles == []


# ---------------------------------------------------------------------------
# DotfileApplier.prepare (Stage 2)
# ---------------------------------------------------------------------------


class TestPrepare:
    def test_prepare_stages_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            assert len(dotfiles) == 1
            assert dotfiles[0].staged is not None
            assert dotfiles[0].staged.is_file()
            assert dotfiles[0].staged.read_text() == "content\n"

    def test_prepare_preserves_translated_path(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_config" / "nvim" / "init.vim", "set nu\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            staged = dotfiles[0].staged
            assert staged.name == "init.vim"
            assert ".config" in str(staged)

    def test_prepare_effective_source_is_staged(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            assert dotfiles[0].effective_source == dotfiles[0].staged


# ---------------------------------------------------------------------------
# DotfileApplier.get_changes + apply_changes (Stage 3)
# ---------------------------------------------------------------------------


class TestGetChanges:
    def test_new_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)

            assert len(changes) == 1
            assert changes[0].get_change_type() == ChangeType.NEW

    def test_modified_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "new\n")
            _make_file(Path(tgt) / ".bashrc", "old\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)

            assert len(changes) == 1
            assert changes[0].get_change_type() == ChangeType.MODIFIED

    def test_unchanged_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "same\n")
            _make_file(Path(tgt) / ".bashrc", "same\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)

            assert len(changes) == 0

    def test_mixed_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "new\n")
            _make_file(Path(src) / "dot_profile", "changed\n")
            _make_file(Path(src) / "dot_vimrc", "same\n")
            _make_file(Path(tgt) / ".profile", "old\n")
            _make_file(Path(tgt) / ".vimrc", "same\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)

            types = {c.get_change_type() for c in changes}
            assert ChangeType.NEW in types
            assert ChangeType.MODIFIED in types
            assert len(changes) == 2


class TestApplyChanges:
    def test_apply_new_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "export FOO=bar\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert (Path(tgt) / ".bashrc").read_text() == "export FOO=bar\n"

    def test_apply_modified_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "new content\n")
            _make_file(Path(tgt) / ".bashrc", "old content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert (Path(tgt) / ".bashrc").read_text() == "new content\n"

    def test_apply_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_config" / "nvim" / "init.vim", "set nu\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert (
                Path(tgt) / ".config" / "nvim" / "init.vim"
            ).read_text() == "set nu\n"

    def test_apply_dry_run(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert not (Path(tgt) / ".bashrc").exists()


# ---------------------------------------------------------------------------
# apply (full pipeline)
# ---------------------------------------------------------------------------


class TestApply:
    def test_apply_no_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            result = applier.apply()
            assert result == 0

    def test_apply_user_confirms(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))

            with patch(
                "pyishlib.dotfile_applier.prompt_yes_no_always", return_value=Choice.YES
            ):
                result = applier.apply()

            assert result == 1
            assert (Path(tgt) / ".bashrc").read_text() == "content\n"

    def test_apply_user_declines(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))

            with patch(
                "pyishlib.dotfile_applier.prompt_yes_no_always", return_value=Choice.NO
            ):
                result = applier.apply()

            assert result == 0
            assert not (Path(tgt) / ".bashrc").exists()

    def test_apply_dry_run_skips_prompt(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )

            with patch("pyishlib.dotfile_applier.prompt_yes_no_always") as mock_prompt:
                result = applier.apply()
                mock_prompt.assert_not_called()

            assert result == 1
            assert not (Path(tgt) / ".bashrc").exists()

    def test_apply_explicit_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "bash\n")
            _make_file(Path(src) / "dot_profile", "profile\n")

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            result = applier.apply(files=[Path("dot_bashrc")])

            assert result == 1


# ---------------------------------------------------------------------------
# CommandRunner.copy
# ---------------------------------------------------------------------------


class TestCommandRunnerCopy:
    def test_copy_file(self):
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            src = _make_file(Path(tmpdir) / "src" / "file.txt", "data\n")
            dst = Path(tmpdir) / "dst" / "file.txt"

            result = runner.copy(src, dst)

            assert result is True
            assert dst.read_text() == "data\n"

    def test_copy_creates_parent(self):
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            src = _make_file(Path(tmpdir) / "file.txt", "data\n")
            dst = Path(tmpdir) / "a" / "b" / "c" / "file.txt"

            runner.copy(src, dst)

            assert dst.read_text() == "data\n"

    def test_copy_dry_run(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        with tempfile.TemporaryDirectory() as tmpdir:
            src = _make_file(Path(tmpdir) / "file.txt", "data\n")
            dst = Path(tmpdir) / "dst" / "file.txt"

            result = runner.copy(src, dst)

            assert result is True
            assert not dst.exists()


if __name__ == "__main__":
    pytest.main()
