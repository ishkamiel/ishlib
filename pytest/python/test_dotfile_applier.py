# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

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
    is_executable_name,
    is_mergejson_name,
    reverse_translate_name,
    translate_name,
    translate_path,
)
from pyishlib.dotfile_ignore import (
    DotfileIgnore,
    load_ignore_file,
)
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig
from pyishlib.userio import Choice

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

    def test_executable_prefix(self):
        assert translate_name("executable_myscript") == "myscript"

    def test_executable_dot_combo(self):
        # executable_dot_foo → .foo  (executable_ stripped first, then dot_)
        assert translate_name("executable_dot_foo") == ".foo"

    def test_executable_only(self):
        assert translate_name("executable_") == ""


class TestIsExecutableName:
    def test_plain_executable_prefix(self):
        assert is_executable_name("executable_myscript") is True

    def test_dot_only_not_executable(self):
        assert is_executable_name("dot_bashrc") is False

    def test_no_prefix_not_executable(self):
        assert is_executable_name("script.sh") is False


class TestMergejsonTranslation:
    def test_plain_mergejson(self):
        assert translate_name("mergejson_settings.json") == "settings.json"

    def test_mergejson_dot_combo(self):
        assert translate_name("mergejson_dot_settings.json") == ".settings.json"

    def test_executable_mergejson_dot_combo(self):
        assert translate_name("executable_mergejson_dot_foo.json") == ".foo.json"

    def test_is_mergejson_name_plain(self):
        assert is_mergejson_name("mergejson_foo.json") is True

    def test_is_mergejson_name_with_executable(self):
        assert is_mergejson_name("executable_mergejson_foo.json") is True

    def test_is_mergejson_name_false_for_dot(self):
        assert is_mergejson_name("dot_foo.json") is False

    def test_is_mergejson_name_false_for_no_prefix(self):
        assert is_mergejson_name("foo.json") is False

    def test_reverse_translate_mergejson(self):
        assert (
            reverse_translate_name("settings.json", mergejson=True)
            == "mergejson_settings.json"
        )

    def test_reverse_translate_mergejson_dot(self):
        assert (
            reverse_translate_name(".settings.json", mergejson=True)
            == "mergejson_dot_settings.json"
        )

    def test_reverse_translate_executable_mergejson_dot(self):
        assert (
            reverse_translate_name(".foo.json", executable=True, mergejson=True)
            == "executable_mergejson_dot_foo.json"
        )


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

    # -- executable_ prefix --------------------------------------------------

    def test_executable_property_true(self):
        df = DotFile(
            Path("/repo/executable_myscript"),
            Path("executable_myscript"),
            Path("/home"),
        )
        assert df.executable is True

    def test_executable_property_false_for_dot(self):
        df = DotFile(Path("/repo/dot_bashrc"), Path("dot_bashrc"), Path("/home"))
        assert df.executable is False

    def test_executable_target_name(self):
        df = DotFile(
            Path("/repo/executable_myscript"),
            Path("executable_myscript"),
            Path("/home"),
        )
        assert df.target.name == "myscript"

    def test_executable_dot_combo_target_name(self):
        df = DotFile(
            Path("/repo/executable_dot_localbin"),
            Path("executable_dot_localbin"),
            Path("/home"),
        )
        assert df.target.name == ".localbin"
        assert df.executable is True

    @pytest.mark.skipif(
        sys.platform == "win32", reason="exec bits not meaningful on Windows"
    )
    def test_change_type_modified_when_not_executable(self):
        """File with executable_ prefix is MODIFIED if target lacks exec bit."""
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as tgt,
        ):
            src = _make_file(
                Path(src_dir) / "executable_myscript", "#!/bin/sh\necho hi\n"
            )
            # Install target with same content but no exec bit
            target = Path(tgt) / "myscript"
            target.write_text("#!/bin/sh\necho hi\n")
            target.chmod(0o644)

            df = DotFile(src, Path("executable_myscript"), Path(tgt))
            assert df.get_change_type() == ChangeType.MODIFIED

    @pytest.mark.skipif(
        sys.platform == "win32", reason="exec bits not meaningful on Windows"
    )
    def test_change_type_none_when_executable_and_correct_bit(self):
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as tgt,
        ):
            src = _make_file(
                Path(src_dir) / "executable_myscript", "#!/bin/sh\necho hi\n"
            )
            target = Path(tgt) / "myscript"
            target.write_text("#!/bin/sh\necho hi\n")
            target.chmod(0o755)

            df = DotFile(src, Path("executable_myscript"), Path(tgt))
            assert df.get_change_type() is None

    # -- mergejson_ prefix ---------------------------------------------------

    def test_mergejson_property_true(self):
        df = DotFile(
            Path("/repo/mergejson_settings.json"),
            Path("mergejson_settings.json"),
            Path("/home"),
        )
        assert df.mergejson is True

    def test_mergejson_property_false(self):
        df = DotFile(Path("/repo/dot_bashrc"), Path("dot_bashrc"), Path("/home"))
        assert df.mergejson is False

    def test_mergejson_target_name_stripped(self):
        df = DotFile(
            Path("/repo/mergejson_settings.json"),
            Path("mergejson_settings.json"),
            Path("/home"),
        )
        assert df.target.name == "settings.json"

    def test_mergejson_dot_combo_target_name(self):
        df = DotFile(
            Path("/repo/mergejson_dot_settings.json"),
            Path("mergejson_dot_settings.json"),
            Path("/home"),
        )
        assert df.target.name == ".settings.json"

    def test_mergejson_change_type_new(self):
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as tgt,
        ):
            src = _make_file(Path(src_dir) / "mergejson_settings.json", '{"a": 1}\n')
            df = DotFile(src, Path("mergejson_settings.json"), Path(tgt))
            assert df.get_change_type() == ChangeType.NEW

    def test_mergejson_change_type_none_for_reordered_keys(self):
        """Key reordering inside a JSON object does not count as a change."""
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as tgt,
        ):
            src = _make_file(
                Path(src_dir) / "mergejson_settings.json",
                '{\n  "a": 1,\n  "b": 2\n}\n',
            )
            _make_file(
                Path(tgt) / "settings.json",
                '{\n  "b": 2,\n  "a": 1\n}\n',
            )
            df = DotFile(src, Path("mergejson_settings.json"), Path(tgt))
            assert df.get_change_type() is None

    def test_mergejson_change_type_modified_when_value_differs(self):
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as tgt,
        ):
            src = _make_file(Path(src_dir) / "mergejson_settings.json", '{"a": 2}\n')
            _make_file(Path(tgt) / "settings.json", '{"a": 1}\n')
            df = DotFile(src, Path("mergejson_settings.json"), Path(tgt))
            assert df.get_change_type() == ChangeType.MODIFIED

    def test_mergejson_change_type_modified_when_target_invalid_json(self):
        with (
            tempfile.TemporaryDirectory() as src_dir,
            tempfile.TemporaryDirectory() as tgt,
        ):
            src = _make_file(Path(src_dir) / "mergejson_settings.json", '{"a": 1}\n')
            _make_file(Path(tgt) / "settings.json", "not json at all")
            df = DotFile(src, Path("mergejson_settings.json"), Path(tgt))
            assert df.get_change_type() == ChangeType.MODIFIED


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

    def test_discover_executable_prefix(self):
        """executable_-prefixed files appear in discovery with stripped target name."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "executable_myscript", "#!/bin/sh\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            assert len(dotfiles) == 1
            assert dotfiles[0].translated.name == "myscript"
            assert dotfiles[0].executable is True

    def test_discover_by_target_name_finds_executable_source(self):
        """Filtering by target name resolves to the executable_-prefixed source."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "executable_myscript", "#!/bin/sh\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            # Ask for "myscript" (the target name) — should find executable_myscript
            dotfiles = applier.discover(files=[Path("myscript")])

            assert len(dotfiles) == 1
            assert dotfiles[0].source.name == "executable_myscript"

    def test_discover_by_absolute_target_finds_executable_source(self):
        """Filtering by absolute target path resolves to executable_-prefixed source."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "executable_myscript", "#!/bin/sh\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            abs_target = str(Path(tgt) / "myscript")
            dotfiles = applier.discover(files=[Path(abs_target)])

            assert len(dotfiles) == 1
            assert dotfiles[0].source.name == "executable_myscript"

    def test_discover_mergejson_prefix(self):
        """mergejson_-prefixed files appear in discovery with stripped target name."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"a": 1}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            assert len(dotfiles) == 1
            assert dotfiles[0].translated.name == "settings.json"
            assert dotfiles[0].mergejson is True

    def test_discover_by_target_name_finds_mergejson_source(self):
        """Filtering by target name resolves to the mergejson_-prefixed source."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"a": 1}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover(files=[Path("settings.json")])

            assert len(dotfiles) == 1
            assert dotfiles[0].source.name == "mergejson_settings.json"

    def test_discover_by_target_name_finds_mergejson_dot_source(self):
        """Target name '.settings.json' resolves to 'mergejson_dot_settings.json'."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_dot_settings.json", '{"a": 1}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover(files=[Path(".settings.json")])

            assert len(dotfiles) == 1
            assert dotfiles[0].source.name == "mergejson_dot_settings.json"
            assert dotfiles[0].target.name == ".settings.json"

    def test_discover_by_absolute_target_finds_mergejson_source(self):
        """Filtering by absolute target path resolves to mergejson_-prefixed source."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"a": 1}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            abs_target = str(Path(tgt) / "settings.json")
            dotfiles = applier.discover(files=[Path(abs_target)])

            assert len(dotfiles) == 1
            assert dotfiles[0].source.name == "mergejson_settings.json"


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

    @pytest.mark.skipif(
        sys.platform == "win32", reason="exec bits not meaningful on Windows"
    )
    def test_apply_executable_sets_exec_bit(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "executable_myscript", "#!/bin/sh\necho hi\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applier.apply_changes(changes)

            target = Path(tgt) / "myscript"
            assert target.exists()
            assert os.access(target, os.X_OK), "target should be executable"

    def test_apply_executable_target_name_stripped(self):
        """executable_ prefix is removed from the installed filename."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "executable_myscript", "#!/bin/sh\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applier.apply_changes(changes)

            assert not (Path(tgt) / "executable_myscript").exists()
            assert (Path(tgt) / "myscript").exists()

    @pytest.mark.skipif(
        sys.platform == "win32", reason="exec bits not meaningful on Windows"
    )
    def test_apply_executable_dot_combo(self):
        """executable_dot_foo → .foo with exec bit."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "executable_dot_localscript", "#!/bin/sh\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            applier.apply_changes(changes)

            target = Path(tgt) / ".localscript"
            assert target.exists(), ".localscript should be installed"
            assert os.access(target, os.X_OK), ".localscript should be executable"

    @pytest.mark.skipif(
        sys.platform == "win32", reason="exec bits not meaningful on Windows"
    )
    def test_apply_executable_missing_bit_triggers_reapply(self):
        """Already-installed file with wrong permissions is re-applied."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            content = "#!/bin/sh\necho hi\n"
            _make_file(Path(src) / "executable_myscript", content)
            target = Path(tgt) / "myscript"
            target.write_text(content)
            target.chmod(0o644)  # correct content, missing exec bit

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)
            changes = applier.get_changes(dotfiles)
            assert len(changes) == 1, "missing exec bit should appear as a change"
            applier.apply_changes(changes)
            assert os.access(target, os.X_OK)


# ---------------------------------------------------------------------------
# mergejson_ prefix (apply pipeline)
# ---------------------------------------------------------------------------


def _json_target(path: Path):
    import json as _json

    return _json.loads(path.read_text(encoding="utf-8"))


class TestApplyMergejson:
    def test_apply_mergejson_new_target(self):
        """With no existing target, the merged file equals the source patch."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"a": 1, "b": {"c": 2}}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            result = _json_target(Path(tgt) / "settings.json")
            assert result == {"a": 1, "b": {"c": 2}}

    def test_apply_mergejson_strips_prefix_from_target_name(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"a": 1}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            assert not (Path(tgt) / "mergejson_settings.json").exists()
            assert (Path(tgt) / "settings.json").exists()

    def test_apply_mergejson_dot_combo(self):
        """mergejson_dot_foo.json -> .foo.json merged as JSON."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_dot_settings.json", '{"a": 1}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            target = Path(tgt) / ".settings.json"
            assert target.exists()
            assert _json_target(target) == {"a": 1}

    def test_apply_mergejson_preserves_disjoint_target_keys(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"new_key": 1}\n')
            _make_file(Path(tgt) / "settings.json", '{"existing_key": "keep"}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            result = _json_target(Path(tgt) / "settings.json")
            assert result == {"existing_key": "keep", "new_key": 1}

    def test_apply_mergejson_source_wins_on_overlap(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"theme": "dark"}\n')
            _make_file(Path(tgt) / "settings.json", '{"theme": "light"}\n')

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            assert _json_target(Path(tgt) / "settings.json") == {"theme": "dark"}

    def test_apply_mergejson_deep_merge(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"nested": {"b": 2}}\n',
            )
            _make_file(
                Path(tgt) / "settings.json",
                '{"nested": {"a": 1}}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            result = _json_target(Path(tgt) / "settings.json")
            assert result == {"nested": {"a": 1, "b": 2}}

    def test_apply_mergejson_array_replaces_wholesale(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"list": [9]}\n',
            )
            _make_file(
                Path(tgt) / "settings.json",
                '{"list": [1, 2, 3]}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            assert _json_target(Path(tgt) / "settings.json") == {"list": [9]}

    def test_apply_mergejson_null_removes_key(self):
        """RFC 7396: null in the patch deletes the key."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"drop": null}\n')
            _make_file(
                Path(tgt) / "settings.json",
                '{"drop": 1, "keep": 2}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            assert _json_target(Path(tgt) / "settings.json") == {"keep": 2}

    def test_apply_mergejson_reordered_keys_is_noop(self):
        """Target and merged-source semantically equal -> no change."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"a": 1, "b": 2}\n',
            )
            target = _make_file(
                Path(tgt) / "settings.json",
                '{\n  "b": 2,\n  "a": 1\n}\n',
            )
            original_content = target.read_text()

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.prepare(applier.discover())
            changes = applier.get_changes(dotfiles)

            assert changes == [], "reordered-only target should not be a change"
            assert target.read_text() == original_content

    def test_apply_mergejson_invalid_source_is_skipped(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", "not json {{{\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.prepare(applier.discover())
            assert dotfiles == [], "invalid JSON source should be dropped"
            assert not (Path(tgt) / "settings.json").exists()

    def test_apply_mergejson_invalid_target_is_overwritten(self):
        """An unparsable existing target is treated as an empty base."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "mergejson_settings.json", '{"a": 1}\n')
            _make_file(Path(tgt) / "settings.json", "garbage contents")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            applier.apply_changes(
                applier.get_changes(applier.prepare(applier.discover()))
            )

            assert _json_target(Path(tgt) / "settings.json") == {"a": 1}


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
