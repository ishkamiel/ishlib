# -*- coding: utf-8 -*-
#
# Tests for installer backend classes (AptInstaller, PipInstaller, etc.)

import sys
import os
import subprocess
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.installer import Installer
from pyishlib.apt_installer import AptInstaller
from pyishlib.brew_installer import BrewInstaller
from pyishlib.cargo_installer import CargoInstaller
from pyishlib.pip_installer import PipInstaller
from pyishlib.winget_installer import WingetInstaller
from pyishlib.command_runner import CommandRunner


def make_runner(which_returns=None):
    """Create a CommandRunner with a mocked which method."""
    runner = CommandRunner(dry_run=True)

    def mock_which(cmd):
        if which_returns is None:
            return None
        return which_returns.get(cmd, None)

    runner.which = mock_which
    return runner


def make_log():
    """Create a logger for testing."""
    log = logging.getLogger("test_installer")
    log.setLevel(logging.DEBUG)
    return log


def make_installer(which_returns=None):
    """Create an Installer with a mocked runner."""
    runner = make_runner(which_returns)
    installer = Installer(runner=runner, log_level=logging.DEBUG)
    return installer


class TestAptInstaller:

    def test_has_apt_true(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        assert apt.has_apt is True

    def test_has_apt_false(self):
        apt = AptInstaller(make_log(), make_runner({}))
        assert apt.has_apt is False

    def test_has_apt_cached(self):
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = AptInstaller(make_log(), runner)
        _ = apt.has_apt
        # Change which to return None — but result should be cached
        runner.which = lambda cmd: None
        assert apt.has_apt is True

    def test_can_use_apt_no_apt_key(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        pkg = {"name": "test", "pip": "test"}
        assert apt.can_use_apt(pkg) is False

    def test_can_use_apt_with_apt_key(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        pkg = {"name": "test", "apt": "test"}
        assert apt.can_use_apt(pkg) is True

    def test_can_use_apt_no_pkg(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        assert apt.can_use_apt() is True

    def test_get_apt_pkgs(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        pkgs = [
            {"name": "a", "apt": "a"},
            {"name": "b", "pip": "b"},
            {"name": "c", "apt": "c", "pip": "c"},
        ]
        result = apt.get_apt_pkgs(pkgs)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "c"

    def test_is_apt_pkg_installed_no_apt(self):
        apt = AptInstaller(make_log(), make_runner({}))
        pkg = {"name": "test", "apt": "test"}
        assert apt.is_apt_pkg_installed(pkg) is False

    def test_apt_namespace(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        ns = apt.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")
        assert hasattr(ns, "update")

    def test_install_apt_pkgs_dry_run(self):
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = AptInstaller(make_log(), runner)
        with patch.object(runner, "run_sudo",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)) as mock_sudo:
            pkgs = [{"name": "test", "apt": "test-pkg"}]
            result = apt.install_apt_pkgs(pkgs)
            assert result is True
            mock_sudo.assert_called_once_with(["apt", "install", "-y", "test-pkg"])

    def test_install_apt_pkg_unless_found_already_installed(self):
        apt = AptInstaller(make_log(), make_runner({"apt": "/usr/bin/apt"}))
        with patch.object(apt, "is_apt_pkg_installed", return_value=True):
            pkg = {"name": "test", "apt": "test-pkg"}
            result = apt.install_apt_pkg_unless_found(pkg)
            assert result is True


class TestPipInstaller:

    def test_has_pip_true(self):
        pip = PipInstaller(make_log(), make_runner({"pip3": "/usr/bin/pip3"}))
        assert pip.has_pip is True

    def test_has_pip_false(self):
        pip = PipInstaller(make_log(), make_runner({}))
        assert pip.has_pip is False

    def test_can_use_pip_no_pip_key(self):
        pip = PipInstaller(make_log(), make_runner({"pip3": "/usr/bin/pip3"}))
        pkg = {"name": "test", "apt": "test"}
        assert pip.can_use_pip(pkg) is False

    def test_can_use_pip_with_pip_key(self):
        pip = PipInstaller(make_log(), make_runner({"pip3": "/usr/bin/pip3"}))
        pkg = {"name": "test", "pip": "test"}
        assert pip.can_use_pip(pkg) is True

    def test_get_pip_pkgs(self):
        pip = PipInstaller(make_log(), make_runner({"pip3": "/usr/bin/pip3"}))
        pkgs = [
            {"name": "a", "apt": "a"},
            {"name": "b", "pip": "b"},
        ]
        result = pip.get_pip_pkgs(pkgs)
        assert len(result) == 1
        assert result[0]["name"] == "b"

    def test_pip_namespace(self):
        pip = PipInstaller(make_log(), make_runner({"pip3": "/usr/bin/pip3"}))
        ns = pip.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_pip_pkg_returns_value(self):
        runner = make_runner({"pip3": "/usr/bin/pip3"})
        pip = PipInstaller(make_log(), runner)
        with patch.object(runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "pip": "test-pkg"}
            result = pip.install_pip_pkg(pkg)
            assert result is True


class TestBrewInstaller:

    def test_has_brew_true(self):
        brew = BrewInstaller(make_log(), make_runner({"brew": "/usr/local/bin/brew"}))
        assert brew.has_brew is True

    def test_has_brew_false(self):
        brew = BrewInstaller(make_log(), make_runner({}))
        assert brew.has_brew is False

    def test_can_use_brew_no_brew_key(self):
        brew = BrewInstaller(make_log(), make_runner({"brew": "/usr/local/bin/brew"}))
        pkg = {"name": "test", "apt": "test"}
        assert brew.can_use_brew(pkg) is False

    def test_can_use_brew_with_brew_key(self):
        brew = BrewInstaller(make_log(), make_runner({"brew": "/usr/local/bin/brew"}))
        pkg = {"name": "test", "brew": "test"}
        assert brew.can_use_brew(pkg) is True

    def test_brew_namespace(self):
        brew = BrewInstaller(make_log(), make_runner({"brew": "/usr/local/bin/brew"}))
        ns = brew.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_brew_pkg_returns_value(self):
        runner = make_runner({"brew": "/usr/local/bin/brew"})
        brew = BrewInstaller(make_log(), runner)
        with patch.object(runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "brew": "test-pkg"}
            result = brew.install_brew_pkg(pkg)
            assert result is True


class TestCargoInstaller:

    def test_has_cargo_true(self):
        cargo = CargoInstaller(make_log(), make_runner({"cargo": "/usr/bin/cargo"}))
        assert cargo.has_cargo is True

    def test_has_cargo_false(self):
        cargo = CargoInstaller(make_log(), make_runner({}))
        assert cargo.has_cargo is False

    def test_can_use_cargo_no_cargo_key(self):
        cargo = CargoInstaller(make_log(), make_runner({"cargo": "/usr/bin/cargo"}))
        pkg = {"name": "test", "apt": "test"}
        assert cargo.can_use_cargo(pkg) is False

    def test_can_use_cargo_with_cargo_key(self):
        cargo = CargoInstaller(make_log(), make_runner({"cargo": "/usr/bin/cargo"}))
        pkg = {"name": "test", "cargo": "test"}
        assert cargo.can_use_cargo(pkg) is True

    def test_cargo_namespace(self):
        cargo = CargoInstaller(make_log(), make_runner({"cargo": "/usr/bin/cargo"}))
        ns = cargo.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_cargo_pkg_returns_value(self):
        runner = make_runner({"cargo": "/usr/bin/cargo"})
        cargo = CargoInstaller(make_log(), runner)
        with patch.object(runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "cargo": "test-pkg"}
            result = cargo.install_cargo_pkg(pkg)
            assert result is True


class TestWingetInstaller:

    def test_has_winget_true(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        assert winget.has_winget is True

    def test_has_winget_false(self):
        winget = WingetInstaller(make_log(), make_runner({}))
        assert winget.has_winget is False

    def test_has_winget_cached(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = WingetInstaller(make_log(), runner)
        _ = winget.has_winget
        runner.which = lambda cmd: None
        assert winget.has_winget is True

    def test_can_use_winget_no_winget_key(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        pkg = {"name": "test", "apt": "test"}
        assert winget.can_use_winget(pkg) is False

    def test_can_use_winget_with_winget_key(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        pkg = {"name": "test", "winget": "Test.App"}
        assert winget.can_use_winget(pkg) is True

    def test_can_use_winget_no_pkg(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        assert winget.can_use_winget() is True

    def test_get_winget_pkgs(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        pkgs = [
            {"name": "a", "winget": "A.App"},
            {"name": "b", "apt": "b"},
            {"name": "c", "winget": "C.App", "apt": "c"},
        ]
        result = winget.get_winget_pkgs(pkgs)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "c"

    def test_is_winget_pkg_installed_no_winget(self):
        winget = WingetInstaller(make_log(), make_runner({}))
        pkg = {"name": "test", "winget": "Test.App"}
        assert winget.is_winget_pkg_installed(pkg) is False

    def test_is_winget_pkg_installed_found(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = WingetInstaller(make_log(), runner)
        pkg = {"name": "test", "winget": "Test.App"}
        with patch.object(runner, "run",
                          return_value=subprocess.CompletedProcess(
                              args=[], returncode=0,
                              stdout=b"Name   Id        Version\n"
                                     b"----------------------------\n"
                                     b"Test   Test.App  1.2.3\n",
                              stderr=b"")):
            assert winget.is_winget_pkg_installed(pkg) is True

    def test_is_winget_pkg_installed_not_found(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = WingetInstaller(make_log(), runner)
        pkg = {"name": "test", "winget": "Test.App"}
        with patch.object(runner, "run",
                          return_value=subprocess.CompletedProcess(
                              args=[], returncode=0,
                              stdout=b"No installed package found matching input criteria.\n",
                              stderr=b"")):
            assert winget.is_winget_pkg_installed(pkg) is False

    def test_winget_namespace(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        ns = winget.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")
        assert hasattr(ns, "update")

    def test_install_winget_pkg_returns_value(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = WingetInstaller(make_log(), runner)
        with patch.object(runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "winget": "Test.App"}
            result = winget.install_winget_pkg(pkg)
            assert result is True

    def test_install_winget_pkg_unless_found_already_installed(self):
        winget = WingetInstaller(make_log(), make_runner({"winget": "C:\\winget.exe"}))
        with patch.object(winget, "is_winget_pkg_installed", return_value=True):
            pkg = {"name": "test", "winget": "Test.App"}
            result = winget.install_winget_pkg_unless_found(pkg)
            assert result is True


class TestInstallerRegistration:

    def test_all_default_backends_registered(self):
        installer = make_installer(which_returns={})
        assert "apt" in installer._backends
        assert "brew" in installer._backends
        assert "cargo" in installer._backends
        assert "pip" in installer._backends
        assert "winget" in installer._backends

    def test_registered_backends_count(self):
        installer = make_installer(which_returns={})
        assert len(installer._backends) == 5

    def test_get_backend_returns_instance(self):
        installer = make_installer(which_returns={})
        assert isinstance(installer.get_backend("apt"), AptInstaller)
        assert isinstance(installer.get_backend("brew"), BrewInstaller)
        assert isinstance(installer.get_backend("cargo"), CargoInstaller)
        assert isinstance(installer.get_backend("pip"), PipInstaller)
        assert isinstance(installer.get_backend("winget"), WingetInstaller)

    def test_get_backend_not_found(self):
        installer = make_installer(which_returns={})
        with pytest.raises(ValueError):
            installer.get_backend("nonexistent")

    def test_register_custom_installer(self):
        installer = make_installer(which_returns={})

        class CustomInstaller:
            INSTALLER_NAME = "custom"

            @property
            def namespace(self):
                class Namespace:
                    @staticmethod
                    def can_install(pkg=None):
                        return False

                    @staticmethod
                    def install(pkgs):
                        return False

                    @staticmethod
                    def is_installed(pkg):
                        return False

                    @staticmethod
                    def update():
                        return False
                return Namespace()

        installer.register_installer(CustomInstaller())
        assert "custom" in installer._backends
        assert len(installer._backends) == 6

    def test_register_override_existing(self):
        installer = make_installer(which_returns={})
        original_apt = installer.get_backend("apt")

        class CustomApt:
            INSTALLER_NAME = "apt"

            @property
            def namespace(self):
                class Namespace:
                    @staticmethod
                    def can_install(pkg=None):
                        return False

                    @staticmethod
                    def install(pkgs):
                        return False

                    @staticmethod
                    def is_installed(pkg):
                        return False

                    @staticmethod
                    def update():
                        return False
                return Namespace()

        installer.register_installer(CustomApt())
        assert installer.get_backend("apt") is not original_apt
        assert isinstance(installer.get_backend("apt"), CustomApt)


class TestInstallerOrchestration:

    def test_have_pkg_by_cmd(self):
        installer = make_installer(which_returns={"mycmd": "/usr/bin/mycmd"})
        pkg = {"name": "test", "cmd": "mycmd"}
        assert installer.have_pkg(pkg) is True

    def test_have_pkg_cmd_not_found(self):
        installer = make_installer(which_returns={})
        pkg = {"name": "test", "cmd": "mycmd"}
        assert installer.have_pkg(pkg) is False

    def test_get_missing_pkgs(self):
        installer = make_installer(which_returns={"existing": "/usr/bin/existing"})
        pkgs = [
            {"name": "found", "cmd": "existing"},
            {"name": "missing", "cmd": "notfound"},
        ]
        missing = installer.get_missing_pkgs(pkgs)
        assert len(missing) == 1
        assert missing[0]["name"] == "missing"

    def test_get_installer_with_apt(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        pkg = {"name": "test", "apt": "test"}
        result = installer.get_installer(pkg)
        assert result == "apt"

    def test_get_installer_with_preference(self):
        installer = make_installer(
            which_returns={"apt": "/usr/bin/apt", "cargo": "/usr/bin/cargo"}
        )
        pkg = {"name": "test", "apt": "test", "cargo": "test", "pref": ["cargo"]}
        result = installer.get_installer(pkg)
        assert result == "cargo"

    def test_get_installer_none_available(self):
        installer = make_installer(which_returns={})
        pkg = {"name": "test", "apt": "test"}
        result = installer.get_installer(pkg)
        assert result is None

    def test_install_pkgs_routes_correctly(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        with patch.object(installer.runner, "run_sudo",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkgs = [{"name": "test", "apt": "test-pkg", "cmd": "notfound"}]
            result = installer.install_pkgs(pkgs)
            assert result is True

    def test_install_pkg_delegates(self):
        installer = make_installer(which_returns={})
        with patch.object(installer, "install_pkgs", return_value=True) as mock:
            pkg = {"name": "test"}
            installer.install_pkg(pkg)
            mock.assert_called_once_with([pkg])


class TestPipInstallerWindowsSupport:

    def test_has_pip_fallback_to_pip(self):
        """When pip3 is not found, falls back to pip."""
        pip = PipInstaller(make_log(), make_runner({"pip": "/usr/bin/pip"}))
        assert pip.has_pip is True
        assert pip._pip_cmd == ["pip"]

    @patch("pyishlib.pip_installer.sys")
    def test_has_pip_windows_fallback_to_python_m_pip(self, mock_sys):
        """On Windows, falls back to python -m pip when pip is not on PATH."""
        mock_sys.platform = "win32"
        mock_sys.executable = "C:\\Python39\\python.exe"
        pip = PipInstaller(make_log(), make_runner({}))
        assert pip.has_pip is True
        assert pip._pip_cmd == ["C:\\Python39\\python.exe", "-m", "pip"]

    def test_pip_install_cmd_includes_user_flag(self):
        """pip install command always includes --user."""
        pip = PipInstaller(make_log(), make_runner({"pip3": "/usr/bin/pip3"}))
        cmd = pip.pip_install_cmd
        assert "--user" in cmd

    def test_has_pip_fallback_cached(self):
        """After fallback from pip3 to pip, result is cached."""
        runner = make_runner({"pip": "/usr/bin/pip"})
        pip = PipInstaller(make_log(), runner)
        _ = pip.has_pip
        # Change which to return None — but result should be cached
        runner.which = lambda cmd: None
        assert pip.has_pip is True
        assert pip._pip_cmd == ["pip"]


class TestCommandRunnerWindowsSupport:

    @patch("pyishlib.command_runner.sys")
    def test_run_sudo_raises_on_windows(self, mock_sys):
        """run_sudo raises OSError on Windows."""
        mock_sys.platform = "win32"
        runner = CommandRunner(dry_run=True)
        with pytest.raises(OSError, match="sudo is not available on Windows"):
            runner.run_sudo(["apt", "update"])

    @patch("pyishlib.command_runner.sys")
    def test_on_ubuntu_false_on_windows(self, mock_sys):
        """on_ubuntu() returns False on Windows without calling uname."""
        mock_sys.platform = "win32"
        runner = CommandRunner(dry_run=True)
        assert runner.on_ubuntu() is False

    @patch("pyishlib.command_runner.sys")
    def test_on_ubuntu_desktop_false_on_windows(self, mock_sys):
        """on_ubuntu_desktop() returns False on Windows."""
        mock_sys.platform = "win32"
        runner = CommandRunner(dry_run=True)
        assert runner.on_ubuntu_desktop() is False

    def test_on_ubuntu_dry_run_no_type_error(self):
        """on_ubuntu() handles dry-run mode without TypeError from bytes/str mismatch."""
        runner = CommandRunner(dry_run=True)
        # In dry-run mode, run() returns stdout=b"", which must not cause
        # a TypeError when checking 'in' against a string.
        result = runner.on_ubuntu()
        assert result is False


class TestInstallerConfigIntegration:

    def test_installer_config_on_ubuntu_check(self):
        """Test that on_ubuntu in InstallerConfig uses the correct cached field."""
        from pyishlib.installer_config import InstallerConfig

        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        # Manually set _on_ubuntu to test the caching logic
        ic._on_ubuntu = True
        assert ic.on_ubuntu is True

    def test_installer_config_get_pkg(self):
        from pyishlib.installer_config import InstallerConfig

        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        pkg = ic.get_pkg("pkg1")
        assert pkg["apt"] == "pkg1"
        assert pkg["name"] == "pkg1"

    def test_installer_config_get_pkg_not_found(self):
        from pyishlib.installer_config import InstallerConfig

        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        with pytest.raises(ValueError):
            ic.get_pkg("nonexistent")

    def test_installer_config_get_pkgs_filters_ubuntu(self):
        from pyishlib.installer_config import InstallerConfig

        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2", "ubuntu": True},
        }
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        ic._on_ubuntu = False
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "pkg1"

    @patch("pyishlib.installer_config.sys")
    def test_installer_config_on_windows(self, mock_sys):
        """Test that on_windows is detected and cached correctly."""
        from pyishlib.installer_config import InstallerConfig

        mock_sys.platform = "win32"
        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        assert ic.on_windows is True
        # Verify caching: change platform, should still return cached value
        mock_sys.platform = "linux"
        assert ic.on_windows is True

    @patch("pyishlib.installer_config.sys")
    def test_installer_config_not_on_windows(self, mock_sys):
        """Test that on_windows is False on Linux."""
        from pyishlib.installer_config import InstallerConfig

        mock_sys.platform = "linux"
        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        assert ic.on_windows is False

    def test_installer_config_get_pkgs_filters_gnome(self):
        from pyishlib.installer_config import InstallerConfig

        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2", "gnome": True},
        }
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        ic._on_gnome = False
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "pkg1"


if __name__ == "__main__":
    pytest.main()
