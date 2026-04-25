# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for OS-tagged custom installer script lookup."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.installer_custom import InstallerCustom
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig


def _make_cfg(source):
    cfg = IshConfig(dry_run=True, defaults={"source": str(source)})
    return cfg


def _make_custom(source):
    cfg = _make_cfg(source)
    runner = CommandRunner(cfg=cfg)
    return InstallerCustom(runner, cfg=cfg)


def _write(path: Path, content: str = "#!/bin/sh\necho ok\n"):
    path.write_text(content, encoding="utf-8")
    return path


class TestOsTaggedLookup(unittest.TestCase):
    """_find_script() respects the install_<pkg>.<ostag>.<ext> convention."""

    def _installers(self, tmp):
        d = Path(tmp) / "ishinstallers"
        d.mkdir()
        return d

    # -- precedence: OS-specific over family over unixlike --------------------

    def test_os_specific_preferred_over_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.linux.sh")
            _write(d / "install_mytool.debian.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value="debian"),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None
            assert "linux" in found.name

    def test_family_preferred_over_unixlike(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.debian.sh")
            _write(d / "install_mytool.unixlike.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value="debian"),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None
            assert "debian" in found.name

    def test_unixlike_matches_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.unixlike.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None
            assert "unixlike" in found.name

    def test_unixlike_matches_macos(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.unixlike.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="macos"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None

    def test_unixlike_not_matches_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.unixlike.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="windows"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is None

    # -- bare extension convention --------------------------------------------

    def test_bare_sh_matches_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None and found.name == "install_mytool.sh"

    def test_bare_sh_matches_macos(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="macos"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None

    def test_bare_sh_not_matches_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="windows"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is None

    def test_ps1_matches_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.ps1", "Write-Host ok")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="windows"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None and found.name == "install_mytool.ps1"

    def test_ps1_not_matches_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.ps1", "Write-Host ok")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is None

    # -- no-extension fallback ------------------------------------------------

    def test_no_extension_matches_any_os(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None and found.name == "install_mytool"

    def test_no_extension_matches_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="windows"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None

    # -- fall-through when only wrong-OS scripts exist ------------------------

    def test_fallthrough_wrong_os_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.windows.ps1", "Write-Host ok")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is None

    def test_fallthrough_wrong_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._installers(tmp)
            _write(d / "install_mytool.fedora.sh")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value="debian"),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is None


class TestExistingBehaviourPreserved(unittest.TestCase):
    """The original _find_script() behaviour still works."""

    def test_exact_name_no_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "ishinstallers"
            d.mkdir()
            _write(d / "install_mytool")
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("mytool")
            assert found is not None

    def test_not_found_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "ishinstallers"
            d.mkdir()
            with (
                patch("pyishlib.installer_custom.detect_os", return_value="linux"),
                patch("pyishlib.installer_custom.detect_distro", return_value=None),
            ):
                custom = _make_custom(tmp)
                found = custom._find_script("nonexistent")
            assert found is None


if __name__ == "__main__":
    unittest.main()
