# -*- coding: utf-8 -*-
#
# Tests for installer mixin classes (AptInstaller, PipInstaller, etc.)

import sys
import os
import subprocess
import logging
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.installer import Installer
from pyishlib.command_runner import CommandRunner


def make_installer(which_returns=None):
    """Create an Installer with a mocked runner."""
    runner = CommandRunner(dry_run=True)

    def mock_which(cmd):
        if which_returns is None:
            return None
        return which_returns.get(cmd, None)

    runner.which = mock_which
    installer = Installer(runner=runner, log_level=logging.DEBUG)
    return installer


class TestAptInstaller:

    def test_has_apt_true(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        assert installer.has_apt is True

    def test_has_apt_false(self):
        installer = make_installer(which_returns={})
        assert installer.has_apt is False

    def test_has_apt_cached(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        _ = installer.has_apt
        # Change which to return None — but result should be cached
        installer.runner.which = lambda cmd: None
        assert installer.has_apt is True

    def test_can_use_apt_no_apt_key(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        pkg = {"name": "test", "pip": "test"}
        assert installer.can_use_apt(pkg) is False

    def test_can_use_apt_with_apt_key(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        pkg = {"name": "test", "apt": "test"}
        assert installer.can_use_apt(pkg) is True

    def test_can_use_apt_no_pkg(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        assert installer.can_use_apt() is True

    def test_get_apt_pkgs(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        pkgs = [
            {"name": "a", "apt": "a"},
            {"name": "b", "pip": "b"},
            {"name": "c", "apt": "c", "pip": "c"},
        ]
        result = installer.get_apt_pkgs(pkgs)
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "c"

    def test_is_apt_pkg_installed_no_apt(self):
        installer = make_installer(which_returns={})
        pkg = {"name": "test", "apt": "test"}
        assert installer.is_apt_pkg_installed(pkg) is False

    def test_apt_namespace(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        ns = installer.apt
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")
        assert hasattr(ns, "update")

    def test_install_apt_pkgs_dry_run(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        with patch.object(installer.runner, "run_sudo",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)) as mock_sudo:
            pkgs = [{"name": "test", "apt": "test-pkg"}]
            result = installer.install_apt_pkgs(pkgs)
            assert result is True
            mock_sudo.assert_called_once_with(["apt", "install", "-y", "test-pkg"])

    def test_install_apt_pkg_unless_found_already_installed(self):
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        with patch.object(installer, "is_apt_pkg_installed", return_value=True):
            pkg = {"name": "test", "apt": "test-pkg"}
            result = installer.install_apt_pkg_unless_found(pkg)
            assert result is True


class TestPipInstaller:

    def test_has_pip_true(self):
        installer = make_installer(which_returns={"pip3": "/usr/bin/pip3"})
        assert installer.has_pip is True

    def test_has_pip_false(self):
        installer = make_installer(which_returns={})
        assert installer.has_pip is False

    def test_can_use_pip_no_pip_key(self):
        installer = make_installer(which_returns={"pip3": "/usr/bin/pip3"})
        pkg = {"name": "test", "apt": "test"}
        assert installer.can_use_pip(pkg) is False

    def test_can_use_pip_with_pip_key(self):
        installer = make_installer(which_returns={"pip3": "/usr/bin/pip3"})
        pkg = {"name": "test", "pip": "test"}
        assert installer.can_use_pip(pkg) is True

    def test_get_pip_pkgs(self):
        installer = make_installer(which_returns={"pip3": "/usr/bin/pip3"})
        pkgs = [
            {"name": "a", "apt": "a"},
            {"name": "b", "pip": "b"},
        ]
        result = installer.get_pip_pkgs(pkgs)
        assert len(result) == 1
        assert result[0]["name"] == "b"

    def test_pip_namespace(self):
        installer = make_installer(which_returns={"pip3": "/usr/bin/pip3"})
        ns = installer.pip
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_pip_pkg_returns_value(self):
        installer = make_installer(which_returns={"pip3": "/usr/bin/pip3"})
        with patch.object(installer.runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "pip": "test-pkg"}
            result = installer.install_pip_pkg(pkg)
            assert result is True


class TestBrewInstaller:

    def test_has_brew_true(self):
        installer = make_installer(which_returns={"brew": "/usr/local/bin/brew"})
        assert installer.has_brew is True

    def test_has_brew_false(self):
        installer = make_installer(which_returns={})
        assert installer.has_brew is False

    def test_can_use_brew_no_brew_key(self):
        installer = make_installer(which_returns={"brew": "/usr/local/bin/brew"})
        pkg = {"name": "test", "apt": "test"}
        assert installer.can_use_brew(pkg) is False

    def test_can_use_brew_with_brew_key(self):
        installer = make_installer(which_returns={"brew": "/usr/local/bin/brew"})
        pkg = {"name": "test", "brew": "test"}
        assert installer.can_use_brew(pkg) is True

    def test_brew_namespace(self):
        installer = make_installer(which_returns={"brew": "/usr/local/bin/brew"})
        ns = installer.brew
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_brew_pkg_returns_value(self):
        installer = make_installer(which_returns={"brew": "/usr/local/bin/brew"})
        with patch.object(installer.runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "brew": "test-pkg"}
            result = installer.install_brew_pkg(pkg)
            assert result is True


class TestCargoInstaller:

    def test_has_cargo_true(self):
        installer = make_installer(which_returns={"cargo": "/usr/bin/cargo"})
        assert installer.has_cargo is True

    def test_has_cargo_false(self):
        installer = make_installer(which_returns={})
        assert installer.has_cargo is False

    def test_can_use_cargo_no_cargo_key(self):
        installer = make_installer(which_returns={"cargo": "/usr/bin/cargo"})
        pkg = {"name": "test", "apt": "test"}
        assert installer.can_use_cargo(pkg) is False

    def test_can_use_cargo_with_cargo_key(self):
        installer = make_installer(which_returns={"cargo": "/usr/bin/cargo"})
        pkg = {"name": "test", "cargo": "test"}
        assert installer.can_use_cargo(pkg) is True

    def test_cargo_namespace(self):
        installer = make_installer(which_returns={"cargo": "/usr/bin/cargo"})
        ns = installer.cargo
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_cargo_pkg_returns_value(self):
        installer = make_installer(which_returns={"cargo": "/usr/bin/cargo"})
        with patch.object(installer.runner, "run",
                          return_value=subprocess.CompletedProcess(args=[], returncode=0)):
            pkg = {"name": "test", "cargo": "test-pkg"}
            result = installer.install_cargo_pkg(pkg)
            assert result is True


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


class TestInstallerConfigIntegration:

    def test_installer_config_on_ubuntu_check(self):
        """Test that on_ubuntu in InstallerConfig uses the correct cached field."""
        from pyishlib.installer_config import InstallerConfig

        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn="/fake/path")
        # Manually set _on_ubuntu to test the caching logic
        ic._on_ubuntu = True
        assert ic.on_ubuntu is True

    def test_installer_config_get_pkg(self):
        from pyishlib.installer_config import InstallerConfig

        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn="/fake/path")
        pkg = ic.get_pkg("pkg1")
        assert pkg["apt"] == "pkg1"
        assert pkg["name"] == "pkg1"

    def test_installer_config_get_pkg_not_found(self):
        from pyishlib.installer_config import InstallerConfig

        config = {"pkg1": {"apt": "pkg1"}}
        ic = InstallerConfig(config, config_fn="/fake/path")
        with pytest.raises(ValueError):
            ic.get_pkg("nonexistent")

    def test_installer_config_get_pkgs_filters_ubuntu(self):
        from pyishlib.installer_config import InstallerConfig

        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2", "ubuntu": True},
        }
        ic = InstallerConfig(config, config_fn="/fake/path")
        ic._on_ubuntu = False
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "pkg1"

    def test_installer_config_get_pkgs_filters_gnome(self):
        from pyishlib.installer_config import InstallerConfig

        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2", "gnome": True},
        }
        ic = InstallerConfig(config, config_fn="/fake/path")
        ic._on_gnome = False
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "pkg1"


if __name__ == "__main__":
    pytest.main()
