#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for metadata package collection and the scan-first apply pipeline.

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
from pyishlib.ish_metadata import extract_packages_from_metadata
from pyishlib.dotfile import DotFile
from pyishlib.ish_config import IshConfig
from pyishlib.ishfiles.installer_helper import merge_package_lists

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# extract_packages_from_metadata
# ---------------------------------------------------------------------------


class TestExtractPackagesFromMetadata:

    def test_simple_packages(self):
        section = {"vim": {}, "git": {}}
        result = extract_packages_from_metadata(section)
        names = {p["name"] for p in result}
        assert names == {"vim", "git"}

    def test_packages_with_attributes(self):
        section = {"vim": {"pref": ["apt"]}, "ripgrep": {"pref": ["cargo"]}}
        result = extract_packages_from_metadata(section)
        by_name = {p["name"]: p for p in result}
        assert by_name["vim"]["pref"] == ["apt"]
        assert by_name["ripgrep"]["pref"] == ["cargo"]

    def test_empty_section(self):
        assert extract_packages_from_metadata({}) == []

    def test_mixed_empty_and_attributed(self):
        section = {"curl": {}, "fd": {"pref": ["apt", "cargo"]}}
        result = extract_packages_from_metadata(section)
        assert len(result) == 2
        by_name = {p["name"]: p for p in result}
        assert "pref" not in by_name["curl"] or by_name["curl"]["pref"] is None
        assert by_name["fd"]["pref"] == ["apt", "cargo"]


# ---------------------------------------------------------------------------
# merge_package_lists
# ---------------------------------------------------------------------------


class TestMergePackageLists:

    def test_no_overlap(self):
        base = [{"name": "vim"}]
        extra = [{"name": "git"}]
        result = merge_package_lists(base, extra)
        names = [p["name"] for p in result]
        assert names == ["vim", "git"]

    def test_duplicate_uses_base(self):
        base = [{"name": "vim", "pref": ["apt"]}]
        extra = [{"name": "vim", "pref": ["brew"]}]
        result = merge_package_lists(base, extra)
        assert len(result) == 1
        assert result[0]["pref"] == ["apt"]

    def test_empty_base(self):
        result = merge_package_lists([], [{"name": "git"}])
        assert len(result) == 1
        assert result[0]["name"] == "git"

    def test_empty_extra(self):
        result = merge_package_lists([{"name": "vim"}], [])
        assert len(result) == 1

    def test_both_empty(self):
        assert merge_package_lists([], []) == []

    def test_preserves_order(self):
        base = [{"name": "a"}, {"name": "b"}]
        extra = [{"name": "c"}, {"name": "d"}]
        result = merge_package_lists(base, extra)
        assert [p["name"] for p in result] == ["a", "b", "c", "d"]

    def test_extra_duplicates_deduped(self):
        base = [{"name": "a"}]
        extra = [{"name": "b"}, {"name": "b"}]
        result = merge_package_lists(base, extra)
        assert len(result) == 2
        assert [p["name"] for p in result] == ["a", "b"]


# ---------------------------------------------------------------------------
# DotfileApplier.scan
# ---------------------------------------------------------------------------


class TestDotfileApplierScan:

    def test_scan_no_metadata(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            kept, packages = applier.scan(dotfiles)

            assert len(kept) == 1
            assert packages == []
            assert kept[0].scanned is True
            assert kept[0].metadata is None

    def test_scan_collects_packages(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                ": <<'__ISH__'\n"
                "[packages]\n"
                "vim = {}\n"
                'git = {pref = ["apt"]}\n'
                "__ISH__\n"
                "export PATH=$PATH\n",
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            kept, packages = applier.scan(dotfiles)

            assert len(kept) == 1
            names = {p["name"] for p in packages}
            assert names == {"vim", "git"}

    def test_scan_skips_os_excluded(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                ": <<'__ISH__'\n"
                'only_on = ["windows"]\n'
                "[packages]\n"
                "vim = {}\n"
                "__ISH__\n"
                "content\n",
            )

            with patch(
                "pyishlib.dotfile_applier.should_skip_for_os_from_metadata",
                return_value=True,
            ):
                applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
                dotfiles = applier.discover()
                kept, packages = applier.scan(dotfiles)

            assert len(kept) == 0
            assert packages == []

    def test_scan_multiple_files(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                ": <<'__ISH__'\n" "[packages]\n" "vim = {}\n" "__ISH__\n" "content\n",
            )
            _make_file(
                Path(src) / "dot_zshrc",
                ": <<'__ISH__'\n"
                "[packages]\n"
                "zsh-completions = {}\n"
                "__ISH__\n"
                "content\n",
            )
            _make_file(Path(src) / "dot_profile", "plain content\n")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            kept, packages = applier.scan(dotfiles)

            assert len(kept) == 3
            names = {p["name"] for p in packages}
            assert names == {"vim", "zsh-completions"}

    def test_scan_then_prepare(self):
        """Verify that prepare() works correctly after scan()."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                ": <<'__ISH__'\n"
                "[packages]\n"
                "vim = {}\n"
                "__ISH__\n"
                "export PATH=$PATH\n",
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles, packages = applier.scan(dotfiles)
            dotfiles = applier.prepare(dotfiles)

            assert len(dotfiles) == 1
            assert dotfiles[0].staged is not None
            # Metadata block should be stripped in staged output
            staged_content = dotfiles[0].staged.read_text()
            assert "__ISH__" not in staged_content
            assert "export PATH=$PATH" in staged_content


# ---------------------------------------------------------------------------
# Script scanning
# ---------------------------------------------------------------------------


class TestScanScripts:

    def test_scan_scripts_collects_packages(self):
        from pyishlib.ishfiles.script_runner import scan_scripts

        with tempfile.TemporaryDirectory() as src:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(
                scripts_dir / "setup.sh",
                "#!/bin/sh\n"
                ": <<'__ISH__'\n"
                "[packages]\n"
                "curl = {}\n"
                "__ISH__\n"
                "echo setup\n",
            )

            cfg = IshConfig()
            cfg.set_default("source", src)
            cfg.set_constant("scripts_dir", "ishscripts")

            kept, packages = scan_scripts(cfg)
            assert len(kept) == 1
            assert len(packages) == 1
            assert packages[0]["name"] == "curl"

    def test_scan_scripts_os_filtering(self):
        from pyishlib.ishfiles.script_runner import scan_scripts

        with tempfile.TemporaryDirectory() as src:
            scripts_dir = Path(src) / "ishscripts"
            scripts_dir.mkdir()
            _make_file(
                scripts_dir / "setup.sh",
                "#!/bin/sh\n"
                ": <<'__ISH__'\n"
                'only_on = ["windows"]\n'
                "[packages]\n"
                "curl = {}\n"
                "__ISH__\n"
                "echo setup\n",
            )

            cfg = IshConfig()
            cfg.set_default("source", src)
            cfg.set_constant("scripts_dir", "ishscripts")

            with patch(
                "pyishlib.ishfiles.script_runner.should_skip_for_os_from_metadata",
                return_value=True,
            ):
                kept, packages = scan_scripts(cfg)
            assert len(kept) == 0
            assert packages == []

    def test_scan_scripts_no_scripts_dir(self):
        from pyishlib.ishfiles.script_runner import scan_scripts

        with tempfile.TemporaryDirectory() as src:
            cfg = IshConfig()
            cfg.set_default("source", src)
            cfg.set_constant("scripts_dir", "ishscripts")

            kept, packages = scan_scripts(cfg)
            assert kept == []
            assert packages == []


if __name__ == "__main__":
    pytest.main()
