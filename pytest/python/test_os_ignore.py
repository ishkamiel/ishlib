#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for OS-conditional ignore rules and metadata filtering

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.os_info import (
    detect_os,
    should_skip_for_os,
    should_skip_for_os_from_metadata,
    _normalise_os,
)
from pyishlib.dotfile_ignore import (
    DotfileIgnore,
    load_ignore_file,
)
from pyishlib.dotfile_applier import DotfileApplier
from pyishlib.ish_config import IshConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# os_info: detect_os
# ---------------------------------------------------------------------------


class TestDetectOs:

    def test_linux(self):
        with patch("pyishlib.os_info.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert detect_os() == "linux"

    def test_macos(self):
        with patch("pyishlib.os_info.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert detect_os() == "macos"

    def test_windows(self):
        with patch("pyishlib.os_info.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert detect_os() == "windows"

    def test_unknown(self):
        with patch("pyishlib.os_info.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            with pytest.raises(RuntimeError):
                detect_os()


# ---------------------------------------------------------------------------
# os_info: _normalise_os
# ---------------------------------------------------------------------------


class TestNormaliseOs:

    def test_canonical(self):
        assert _normalise_os("linux") == "linux"
        assert _normalise_os("macos") == "macos"
        assert _normalise_os("windows") == "windows"

    def test_aliases(self):
        assert _normalise_os("mac") == "macos"
        assert _normalise_os("darwin") == "macos"
        assert _normalise_os("win") == "windows"
        assert _normalise_os("win32") == "windows"

    def test_case_insensitive(self):
        assert _normalise_os("Linux") == "linux"
        assert _normalise_os("MACOS") == "macos"
        assert _normalise_os("Windows") == "windows"

    def test_unknown(self):
        with pytest.raises(ValueError):
            _normalise_os("freebsd")


# ---------------------------------------------------------------------------
# os_info: should_skip_for_os
# ---------------------------------------------------------------------------


class TestShouldSkipForOs:

    def test_no_rules(self):
        assert should_skip_for_os(current_os="linux") is False

    def test_only_on_match(self):
        assert should_skip_for_os(only_on=["linux"], current_os="linux") is False

    def test_only_on_no_match(self):
        assert should_skip_for_os(only_on=["linux"], current_os="macos") is True

    def test_only_on_multiple(self):
        assert (
            should_skip_for_os(only_on=["linux", "macos"], current_os="macos")
            is False
        )
        assert (
            should_skip_for_os(only_on=["linux", "macos"], current_os="windows")
            is True
        )

    def test_ignore_on_match(self):
        assert (
            should_skip_for_os(ignore_on=["windows"], current_os="windows") is True
        )

    def test_ignore_on_no_match(self):
        assert (
            should_skip_for_os(ignore_on=["windows"], current_os="linux") is False
        )

    def test_ignore_on_multiple(self):
        assert (
            should_skip_for_os(
                ignore_on=["windows", "macos"], current_os="macos"
            )
            is True
        )

    def test_both_rules(self):
        # only_on=["linux", "macos"], ignore_on=["macos"]
        # On macos: only_on passes (macos in list), but ignore_on skips
        assert (
            should_skip_for_os(
                only_on=["linux", "macos"],
                ignore_on=["macos"],
                current_os="macos",
            )
            is True
        )


# ---------------------------------------------------------------------------
# os_info: should_skip_for_os_from_metadata
# ---------------------------------------------------------------------------


class TestShouldSkipFromMetadata:

    def test_none_metadata(self):
        assert should_skip_for_os_from_metadata(None) is False

    def test_empty_metadata(self):
        assert should_skip_for_os_from_metadata({}) is False

    def test_only_on_list(self):
        meta = {"only_on": ["linux"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False
        assert should_skip_for_os_from_metadata(meta, current_os="macos") is True

    def test_only_on_string(self):
        meta = {"only_on": "linux"}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False
        assert should_skip_for_os_from_metadata(meta, current_os="windows") is True

    def test_ignore_on_list(self):
        meta = {"ignore_on": ["windows"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False
        assert (
            should_skip_for_os_from_metadata(meta, current_os="windows") is True
        )

    def test_ignore_on_string(self):
        meta = {"ignore_on": "windows"}
        assert (
            should_skip_for_os_from_metadata(meta, current_os="windows") is True
        )

    def test_metadata_with_other_keys(self):
        meta = {"vars": {"foo": "bar"}, "only_on": ["linux"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False


# ---------------------------------------------------------------------------
# DotfileIgnore: OS-conditional sections in ignore file
# ---------------------------------------------------------------------------


class TestIgnoreFileSections:

    def test_global_only(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ".dotfileignore", "*.bak\ntemp_*\n")
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert pats == ["*.bak", "temp_*"]
            assert only_on == {}
            assert ignore_on == {}

    def test_only_on_section(self):
        with tempfile.TemporaryDirectory() as d:
            content = "*.bak\n\n[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert pats == ["*.bak"]
            assert only_on == {"linux": ["linux-conf"]}
            assert ignore_on == {}

    def test_ignore_on_section(self):
        with tempfile.TemporaryDirectory() as d:
            content = "[ignore_on.windows]\nunix-tool\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert pats == []
            assert only_on == {}
            assert ignore_on == {"windows": ["unix-tool"]}

    def test_multiple_sections(self):
        with tempfile.TemporaryDirectory() as d:
            content = (
                "*.bak\n"
                "[only_on.linux]\nlinux-only\n"
                "[only_on.macos]\nmac-only\n"
                "[ignore_on.windows]\nno-win\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert pats == ["*.bak"]
            assert only_on == {"linux": ["linux-only"], "macos": ["mac-only"]}
            assert ignore_on == {"windows": ["no-win"]}

    def test_comments_in_sections(self):
        with tempfile.TemporaryDirectory() as d:
            content = (
                "[only_on.linux]\n"
                "# This is a comment\n"
                "linux-conf\n"
                "\n"
                "another-linux\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert pats == []
            assert only_on == {"linux": ["linux-conf", "another-linux"]}

    def test_unknown_os_warning(self):
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.freebsd]\nsome-pattern\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert pats == []
            assert only_on == {}
            assert ignore_on == {}

    def test_os_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.mac]\nmac-conf\n[ignore_on.win]\nno-win\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(
                Path(d) / ".dotfileignore"
            )
            assert only_on == {"macos": ["mac-conf"]}
            assert ignore_on == {"windows": ["no-win"]}

    def test_missing_file(self):
        pats, only_on, ignore_on = load_ignore_file(Path("/nonexistent"))
        assert pats == []
        assert only_on == {}
        assert ignore_on == {}


# ---------------------------------------------------------------------------
# DotfileIgnore: is_ignored with OS rules
# ---------------------------------------------------------------------------


class TestDotfileIgnoreOs:

    def test_only_on_current_os(self):
        """Patterns under [only_on.linux] should NOT be ignored on linux."""
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="linux")
            assert not di.is_ignored("linux-conf")

    def test_only_on_other_os(self):
        """Patterns under [only_on.linux] SHOULD be ignored on macos."""
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="macos")
            assert di.is_ignored("linux-conf")

    def test_ignore_on_current_os(self):
        """Patterns under [ignore_on.windows] SHOULD be ignored on windows."""
        with tempfile.TemporaryDirectory() as d:
            content = "[ignore_on.windows]\nwin-only-tool\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="windows")
            assert di.is_ignored("win-only-tool")

    def test_ignore_on_other_os(self):
        """Patterns under [ignore_on.windows] should NOT be ignored on linux."""
        with tempfile.TemporaryDirectory() as d:
            content = "[ignore_on.windows]\nwin-only-tool\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="linux")
            assert not di.is_ignored("win-only-tool")

    def test_global_still_works(self):
        """Global patterns should still be applied regardless of OS."""
        with tempfile.TemporaryDirectory() as d:
            content = "*.bak\n[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="linux")
            assert di.is_ignored("file.bak")
            assert not di.is_ignored("linux-conf")

    def test_default_patterns_still_work(self):
        """Default patterns (.git etc.) should still be applied."""
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), current_os="linux")
            assert di.is_ignored(".git")

    def test_patterns_property_includes_os(self):
        """The patterns property should include OS-effective patterns."""
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.linux]\nlinux-only\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="macos")
            assert "linux-only" in di.patterns

    def test_complex_scenario(self):
        """Multiple sections with different OSes."""
        with tempfile.TemporaryDirectory() as d:
            content = (
                "*.tmp\n"
                "[only_on.linux]\nlinux-app\n"
                "[only_on.macos]\nmac-app\n"
                "[ignore_on.windows]\nunix-tool\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)

            # On linux: ignore *.tmp, mac-app (only_on.macos); keep linux-app, unix-tool
            di = DotfileIgnore(Path(d), current_os="linux")
            assert di.is_ignored("file.tmp")
            assert not di.is_ignored("linux-app")
            assert di.is_ignored("mac-app")
            assert not di.is_ignored("unix-tool")

            # On macos: ignore *.tmp, linux-app; keep mac-app, unix-tool
            di = DotfileIgnore(Path(d), current_os="macos")
            assert di.is_ignored("linux-app")
            assert not di.is_ignored("mac-app")
            assert not di.is_ignored("unix-tool")

            # On windows: ignore *.tmp, linux-app, mac-app, unix-tool
            di = DotfileIgnore(Path(d), current_os="windows")
            assert di.is_ignored("linux-app")
            assert di.is_ignored("mac-app")
            assert di.is_ignored("unix-tool")


# ---------------------------------------------------------------------------
# DotfileApplier: metadata OS filtering
# ---------------------------------------------------------------------------


class TestApplierOsFiltering:

    def test_prepare_skips_only_on_mismatch(self):
        """Files with only_on metadata not matching current OS are skipped."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            # File with only_on=["macos"] metadata
            _make_file(
                Path(src) / "dot_mac_conf",
                '# __ISH__\n# only_on = ["macos"]\n# __ISH__\ncontent\n',
            )
            _make_file(Path(src) / "dot_bashrc", "export FOO=bar\n")

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            with patch("pyishlib.dotfile_applier.should_skip_for_os_from_metadata") as mock_skip:
                # First call for dot_bashrc -> don't skip
                # Second call for dot_mac_conf -> skip
                def side_effect(meta):
                    if meta and meta.get("only_on") == ["macos"]:
                        return True
                    return False
                mock_skip.side_effect = side_effect
                prepared = applier.prepare(dotfiles)

            names = [df.translated.name for df in prepared]
            assert ".bashrc" in names
            assert ".mac_conf" not in names

    def test_prepare_keeps_only_on_match(self):
        """Files with only_on metadata matching current OS are kept."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_linux_conf",
                '# __ISH__\n# only_on = ["linux"]\n# __ISH__\ncontent\n',
            )

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            with patch("pyishlib.dotfile_applier.should_skip_for_os_from_metadata", return_value=False):
                prepared = applier.prepare(dotfiles)

            assert len(prepared) == 1

    def test_prepare_skips_ignore_on_match(self):
        """Files with ignore_on metadata matching current OS are skipped."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_unix_tool",
                '# __ISH__\n# ignore_on = ["windows"]\n# __ISH__\ncontent\n',
            )

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            with patch(
                "pyishlib.dotfile_applier.should_skip_for_os_from_metadata",
                return_value=True,
            ):
                prepared = applier.prepare(dotfiles)

            assert len(prepared) == 0


if __name__ == "__main__":
    pytest.main()
