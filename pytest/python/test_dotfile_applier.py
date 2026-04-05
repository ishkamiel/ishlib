# -*- coding: utf-8 -*-
#
# Tests for DotfileApplier class

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.dotfile_applier import DotfileApplier, DotfileChange, ChangeType
from pyishlib.command_runner import CommandRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# translate_name / translate_path
# ---------------------------------------------------------------------------


class TestTranslateName:

    def test_dot_prefix(self):
        assert DotfileApplier.translate_name("dot_bashrc") == ".bashrc"

    def test_no_prefix(self):
        assert DotfileApplier.translate_name("README") == "README"

    def test_dot_prefix_nested(self):
        assert DotfileApplier.translate_name("dot_config") == ".config"

    def test_dot_only(self):
        assert DotfileApplier.translate_name("dot_") == "."

    def test_contains_dot_not_prefix(self):
        assert DotfileApplier.translate_name("my_dot_file") == "my_dot_file"


class TestTranslatePath:

    def test_single_component(self):
        assert DotfileApplier.translate_path(Path("dot_bashrc")) == Path(".bashrc")

    def test_multi_component(self):
        result = DotfileApplier.translate_path(Path("dot_config/dot_git/config"))
        assert result == Path(".config/.git/config")

    def test_no_translation_needed(self):
        assert DotfileApplier.translate_path(Path("bin/script")) == Path("bin/script")

    def test_mixed(self):
        result = DotfileApplier.translate_path(Path("dot_config/nvim/init.vim"))
        assert result == Path(".config/nvim/init.vim")


# ---------------------------------------------------------------------------
# scan_source
# ---------------------------------------------------------------------------


class TestScanSource:

    def test_scan_simple(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "dot_profile")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            pairs = applier.scan_source()

            targets = [str(t.relative_to(tgt)) for _, t in pairs]
            assert ".bashrc" in targets
            assert ".profile" in targets

    def test_scan_nested(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_config" / "nvim" / "init.vim")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            pairs = applier.scan_source()

            assert len(pairs) == 1
            _, target = pairs[0]
            assert target == Path(tgt) / ".config" / "nvim" / "init.vim"

    def test_scan_ignores_git(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / ".git" / "config")
            _make_file(Path(src) / "dot_bashrc")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            pairs = applier.scan_source()

            assert len(pairs) == 1

    def test_scan_custom_ignore(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc")
            _make_file(Path(src) / "SKIPME")

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                ignore=frozenset({"SKIPME"}),
            )
            pairs = applier.scan_source()

            targets = [t.name for _, t in pairs]
            assert "SKIPME" not in targets

    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            pairs = applier.scan_source()
            assert pairs == []


# ---------------------------------------------------------------------------
# get_changes
# ---------------------------------------------------------------------------


class TestGetChanges:

    def test_new_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "export FOO=bar\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()

            assert len(changes) == 1
            assert changes[0].change_type == ChangeType.NEW

    def test_modified_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "new content\n")
            _make_file(Path(tgt) / ".bashrc", "old content\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()

            assert len(changes) == 1
            assert changes[0].change_type == ChangeType.MODIFIED

    def test_unchanged_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "same\n")
            _make_file(Path(tgt) / ".bashrc", "same\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()

            assert len(changes) == 0

    def test_mixed_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "new\n")
            _make_file(Path(src) / "dot_profile", "changed\n")
            _make_file(Path(src) / "dot_vimrc", "same\n")
            _make_file(Path(tgt) / ".profile", "old\n")
            _make_file(Path(tgt) / ".vimrc", "same\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()

            types = {c.change_type for c in changes}
            assert ChangeType.NEW in types
            assert ChangeType.MODIFIED in types
            assert len(changes) == 2


# ---------------------------------------------------------------------------
# apply_changes
# ---------------------------------------------------------------------------


class TestApplyChanges:

    def test_apply_new_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "export FOO=bar\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert (Path(tgt) / ".bashrc").read_text() == "export FOO=bar\n"

    def test_apply_modified_file(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "new content\n")
            _make_file(Path(tgt) / ".bashrc", "old content\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert (Path(tgt) / ".bashrc").read_text() == "new content\n"

    def test_apply_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_config" / "nvim" / "init.vim", "set nu\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            changes = applier.get_changes()
            applied = applier.apply_changes(changes)

            assert applied == 1
            target = Path(tgt) / ".config" / "nvim" / "init.vim"
            assert target.read_text() == "set nu\n"

    def test_apply_dry_run(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt), dry_run=True
            )
            changes = applier.get_changes()
            applied = applier.apply_changes(changes)

            assert applied == 1
            assert not (Path(tgt) / ".bashrc").exists()


# ---------------------------------------------------------------------------
# apply (full workflow)
# ---------------------------------------------------------------------------


class TestApply:

    def test_apply_no_changes(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )
            result = applier.apply()
            assert result == 0

    def test_apply_user_confirms(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )

            from pyishlib.ish_comp import Choice

            with patch.object(applier, "prompt_yes_no_always", return_value=Choice.YES):
                result = applier.apply()

            assert result == 1
            assert (Path(tgt) / ".bashrc").read_text() == "content\n"

    def test_apply_user_declines(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt)
            )

            from pyishlib.ish_comp import Choice

            with patch.object(applier, "prompt_yes_no_always", return_value=Choice.NO):
                result = applier.apply()

            assert result == 0
            assert not (Path(tgt) / ".bashrc").exists()

    def test_apply_dry_run_skips_prompt(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(
                source_dir=Path(src), target_dir=Path(tgt), dry_run=True
            )

            # Should not prompt at all in dry-run
            with patch.object(applier, "prompt_yes_no_always") as mock_prompt:
                result = applier.apply()
                mock_prompt.assert_not_called()

            assert result == 1
            assert not (Path(tgt) / ".bashrc").exists()


# ---------------------------------------------------------------------------
# DotfileChange
# ---------------------------------------------------------------------------


class TestDotfileChange:

    def test_repr(self):
        change = DotfileChange(
            Path("/src/dot_bashrc"), Path("/home/.bashrc"), ChangeType.NEW
        )
        assert "new" in repr(change)
        assert "dot_bashrc" in repr(change)

    def test_modified_repr(self):
        change = DotfileChange(
            Path("/src/dot_bashrc"), Path("/home/.bashrc"), ChangeType.MODIFIED
        )
        assert "modified" in repr(change)


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
        runner = CommandRunner(dry_run=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            src = _make_file(Path(tmpdir) / "file.txt", "data\n")
            dst = Path(tmpdir) / "dst" / "file.txt"

            result = runner.copy(src, dst)

            assert result is True
            assert not dst.exists()


if __name__ == "__main__":
    pytest.main()
