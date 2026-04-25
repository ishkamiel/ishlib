# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

#
# Tests for installer backend classes (InstallerApt, InstallerPip, etc.)

import sys
import os
import subprocess
import logging
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.installer import Installer
from pyishlib.installer_apt import (
    InstallerApt,
    _parse_reverse_provides,
    _showpkg_has_versions_or_providers,
)
from pyishlib.installer_brew import InstallerBrew
from pyishlib.installer_cargo import InstallerCargo
from pyishlib.installer_custom import InstallerCustom
from pyishlib.installer_dnf import InstallerDnf
from pyishlib.installer_pip import InstallerPip
from pyishlib.installer_winget import InstallerWinget
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig


def make_runner(which_returns=None):
    """Create a CommandRunner with a mocked which method."""
    runner = CommandRunner(cfg=IshConfig(dry_run=True))

    def mock_which(cmd):
        if which_returns is None:
            return None
        return which_returns.get(cmd, None)

    runner.which = mock_which
    return runner


def make_installer(which_returns=None):
    """Create an Installer with a mocked runner."""
    runner = make_runner(which_returns)
    cfg = IshConfig(dry_run=True, log_level=logging.DEBUG)
    installer = Installer(cfg=cfg, runner=runner)
    return installer


class TestInstallerApt:
    def test_available_true(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        assert apt.available is True

    def test_available_false(self):
        apt = InstallerApt(make_runner({}))
        assert apt.available is False

    def test_available_cached(self):
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        _ = apt.available
        # Change which to return None — but result should be cached
        runner.which = lambda cmd: None
        assert apt.available is True

    def test_can_install_no_apt_key(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        pkg = {"name": "test", "pip": "test"}
        assert apt.can_install(pkg) is False

    def test_can_install_with_apt_key(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        pkg = {"name": "test", "apt": "test"}
        assert apt.can_install(pkg) is True

    def test_can_install_no_pkg(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        assert apt.can_install() is True

    def test_is_pkg_installed_no_apt(self):
        apt = InstallerApt(make_runner({}))
        pkg = {"name": "test", "apt": "test"}
        assert apt.is_pkg_installed(pkg) is False

    def test_apt_namespace(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        ns = apt.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")
        assert hasattr(ns, "update")

    def test_install_pkgs_dry_run(self):
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ) as mock_run:
            pkgs = [{"name": "test", "apt": "test-pkg"}]
            result = apt.install_pkgs(pkgs)
            assert result is True
            mock_run.assert_called_once_with(
                ["apt", "install", "-y", "test-pkg"], sudo=True
            )

    def test_install_pkg_unless_found_already_installed(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        with patch.object(apt, "is_pkg_installed", return_value=True):
            pkg = {"name": "test", "apt": "test-pkg"}
            result = apt.install_pkg_unless_found(pkg)
            assert result is True

    def test_is_pkg_installed_transitional_via_provider(self):
        """is_pkg_installed returns True when a provider package is installed."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "virtual-pkg", "apt": "virtual-pkg"}
        dpkg_not_installed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        )
        dpkg_provider_installed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"install ok installed\n",
            stderr=b"",
        )
        showpkg_output = (
            b"Package: virtual-pkg\n"
            b"Versions: \n\n"
            b"Reverse Depends: \n\n"
            b"Dependencies\n\n"
            b"Provides: \n\n"
            b"Reverse Provides:\n"
            b"real-pkg 1.0\n\n"
        )
        showpkg_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=showpkg_output, stderr=b""
        )

        call_count = [0]

        def mock_run(cmd, **kwargs):
            call_count[0] += 1
            if cmd[0] == "dpkg-query" and "virtual-pkg" in cmd:
                return dpkg_not_installed
            if cmd[0] == "apt-cache":
                return showpkg_result
            if cmd[0] == "dpkg-query" and "real-pkg" in cmd:
                return dpkg_provider_installed
            return dpkg_not_installed

        runner.run = mock_run
        assert apt.is_pkg_installed(pkg) is True

    def test_is_pkg_installed_literal_package(self):
        """is_pkg_installed returns True when dpkg finds the package directly."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "real-pkg", "apt": "real-pkg"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"install ok installed\n", stderr=b""
            ),
        ):
            assert apt.is_pkg_installed(pkg) is True

    def test_is_pkg_available_known_package(self):
        """is_pkg_available returns True when showpkg shows version entries."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "tldr", "apt": "tldr"}
        showpkg_out = b"Package: tldr\nVersions: \n0.5.0-1 (/var/lib/apt/lists/...)\n\n"
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=showpkg_out, stderr=b""
            ),
        ):
            assert apt.is_pkg_available(pkg) is True

    def test_is_pkg_available_virtual_package(self):
        """is_pkg_available returns True when showpkg shows reverse provides."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "gnome-ext", "apt": "gnome-extensions-app"}
        showpkg_out = (
            b"Package: gnome-extensions-app\nVersions: \n\n"
            b"Reverse Depends: \n\nDependencies\n\nProvides: \n\n"
            b"Reverse Provides:\ngnome-shell-extension-prefs 49.0\n\n"
        )
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=showpkg_out, stderr=b""
            ),
        ):
            assert apt.is_pkg_available(pkg) is True

    def test_is_pkg_available_unknown_package(self):
        """is_pkg_available returns False when showpkg shows no versions or provides."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "ulauncher", "apt": "ulauncher"}
        showpkg_out = (
            b"Package: ulauncher\nVersions: \n\n"
            b"Reverse Depends: \n\nDependencies\n\nProvides: \n\nReverse Provides: \n\n"
        )
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=showpkg_out, stderr=b""
            ),
        ):
            assert apt.is_pkg_available(pkg) is False

    def test_apt_namespace_has_is_pkg_available(self):
        apt = InstallerApt(make_runner({"apt": "/usr/bin/apt"}))
        ns = apt.namespace
        assert hasattr(ns, "is_pkg_available")

    def test_is_pkg_installed_min_version_ok(self):
        """Installed apt package whose version meets min_version → True."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "git", "apt": "git", "min_version": "2.30"}

        def mock_run(cmd, **kwargs):
            if cmd[0] == "dpkg-query" and "${Status}" in cmd[2]:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"install ok installed\n", stderr=b""
                )
            if cmd[0] == "dpkg-query" and "${Version}" in cmd[2]:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"1:2.40.1-1ubuntu1", stderr=b""
                )
            return subprocess.CompletedProcess(args=[], returncode=1)

        runner.run = mock_run
        assert apt.is_pkg_installed(pkg) is True

    def test_is_pkg_installed_min_version_too_low(self):
        """Installed apt package below min_version → False (so install runs)."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "git", "apt": "git", "min_version": "2.40"}

        def mock_run(cmd, **kwargs):
            if cmd[0] == "dpkg-query" and "${Status}" in cmd[2]:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"install ok installed\n", stderr=b""
                )
            if cmd[0] == "dpkg-query" and "${Version}" in cmd[2]:
                return subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"1:2.30.0-1ubuntu1", stderr=b""
                )
            return subprocess.CompletedProcess(args=[], returncode=1)

        runner.run = mock_run
        assert apt.is_pkg_installed(pkg) is False

    def test_is_pkg_installed_no_min_version_skips_version_query(self):
        """Without min_version, _dpkg_version is not consulted."""
        runner = make_runner({"apt": "/usr/bin/apt"})
        apt = InstallerApt(runner)
        pkg = {"name": "git", "apt": "git"}
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"install ok installed\n", stderr=b""
            )

        runner.run = mock_run
        assert apt.is_pkg_installed(pkg) is True
        # No call should ask for ${Version}
        assert not any("${Version}" in c[2] for c in calls if len(c) > 2)


class TestInstallerDnf:
    def test_is_pkg_available_true(self):
        runner = make_runner({"dnf": "/usr/bin/dnf"})
        dnf = InstallerDnf(runner)
        pkg = {"name": "tldr", "dnf": "tldr"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"", stderr=b""
            ),
        ):
            assert dnf.is_pkg_available(pkg) is True

    def test_is_pkg_available_false(self):
        runner = make_runner({"dnf": "/usr/bin/dnf"})
        dnf = InstallerDnf(runner)
        pkg = {"name": "ulauncher", "dnf": "ulauncher"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b"Error: No matching Packages\n",
                stderr=b"",
            ),
        ):
            assert dnf.is_pkg_available(pkg) is False

    def test_is_pkg_available_no_dnf(self):
        dnf = InstallerDnf(make_runner({}))
        pkg = {"name": "tldr", "dnf": "tldr"}
        assert dnf.is_pkg_available(pkg) is False

    def test_is_pkg_installed_min_version_ok(self):
        """Installed rpm whose %{VERSION} meets min_version → True."""
        runner = make_runner({"dnf": "/usr/bin/dnf"})
        dnf = InstallerDnf(runner)
        pkg = {"name": "git", "dnf": "git", "min_version": "2.30"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"2.40.1\n", stderr=b""
            ),
        ) as mock_run:
            assert dnf.is_pkg_installed(pkg) is True
            mock_run.assert_called_once()
            argv = mock_run.call_args.args[0]
            assert argv[:4] == ["rpm", "-q", "--qf", "%{VERSION}\n"]

    def test_is_pkg_installed_min_version_too_low(self):
        """Installed rpm below min_version → False."""
        runner = make_runner({"dnf": "/usr/bin/dnf"})
        dnf = InstallerDnf(runner)
        pkg = {"name": "git", "dnf": "git", "min_version": "2.40"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"2.30.0\n", stderr=b""
            ),
        ):
            assert dnf.is_pkg_installed(pkg) is False

    def test_is_pkg_installed_no_min_version(self):
        """Without min_version, returncode 0 alone is enough."""
        runner = make_runner({"dnf": "/usr/bin/dnf"})
        dnf = InstallerDnf(runner)
        pkg = {"name": "git", "dnf": "git"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"2.30.0\n", stderr=b""
            ),
        ):
            assert dnf.is_pkg_installed(pkg) is True


class TestParseReverseProvides:
    def test_single_provider(self):
        output = "Package: virt\nVersions: \n\nReverse Provides:\nreal-pkg 1.0\n\n"
        assert _parse_reverse_provides(output) == ["real-pkg"]

    def test_multiple_providers(self):
        output = (
            "Package: virt\nVersions: \n\nReverse Provides:\npkg-a 1.0\npkg-b 2.0\n\n"
        )
        assert _parse_reverse_provides(output) == ["pkg-a", "pkg-b"]

    def test_no_providers(self):
        output = "Package: real\nVersions: \n0.5.0\n\nReverse Provides: \n\n"
        assert _parse_reverse_provides(output) == []

    def test_provider_on_same_line(self):
        output = "Package: virt\nReverse Provides: real-pkg 1.0\n"
        assert _parse_reverse_provides(output) == ["real-pkg"]


class TestShowpkgHasVersionsOrProviders:
    def test_real_package_has_version(self):
        output = "Package: tldr\nVersions: \n0.5.0-1\n\nReverse Provides: \n\n"
        assert _showpkg_has_versions_or_providers(output) is True

    def test_virtual_package_has_provider(self):
        output = (
            "Package: gnome-extensions-app\nVersions: \n\n"
            "Reverse Provides:\ngnome-shell-extension-prefs 49.0\n\n"
        )
        assert _showpkg_has_versions_or_providers(output) is True

    def test_unknown_package_empty(self):
        output = "Package: unknown\nVersions: \n\nReverse Provides: \n\n"
        assert _showpkg_has_versions_or_providers(output) is False


class TestInstallerPip:
    def test_has_pip_true(self):
        pip = InstallerPip(make_runner({"pip3": "/usr/bin/pip3"}))
        assert pip.has_pip is True

    def test_has_pip_false(self):
        pip = InstallerPip(make_runner({}))
        if sys.platform == "win32":
            # Windows fallback always sets has_pip=True via python -m pip
            assert pip.has_pip is True
        else:
            assert pip.has_pip is False

    def test_can_install_no_pip_key(self):
        pip = InstallerPip(make_runner({"pip3": "/usr/bin/pip3"}))
        pkg = {"name": "test", "apt": "test"}
        assert pip.can_install(pkg) is False

    def test_can_install_with_pip_key(self):
        pip = InstallerPip(make_runner({"pip3": "/usr/bin/pip3"}))
        pkg = {"name": "test", "pip": "test"}
        assert pip.can_install(pkg) is True

    def test_pip_namespace(self):
        pip = InstallerPip(make_runner({"pip3": "/usr/bin/pip3"}))
        ns = pip.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_pip_pkg_returns_value(self):
        runner = make_runner({"pip3": "/usr/bin/pip3"})
        pip = InstallerPip(runner)
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ):
            pkg = {"name": "test", "pip": "test-pkg"}
            result = pip.install_pkg(pkg)
            assert result is True


class TestInstallerBrew:
    def test_available_true(self):
        brew = InstallerBrew(make_runner({"brew": "/usr/local/bin/brew"}))
        assert brew.available is True

    def test_available_false(self):
        brew = InstallerBrew(make_runner({}))
        assert brew.available is False

    def test_can_install_no_brew_key(self):
        brew = InstallerBrew(make_runner({"brew": "/usr/local/bin/brew"}))
        pkg = {"name": "test", "apt": "test"}
        assert brew.can_install(pkg) is False

    def test_can_install_with_brew_key(self):
        brew = InstallerBrew(make_runner({"brew": "/usr/local/bin/brew"}))
        pkg = {"name": "test", "brew": "test"}
        assert brew.can_install(pkg) is True

    def test_brew_namespace(self):
        brew = InstallerBrew(make_runner({"brew": "/usr/local/bin/brew"}))
        ns = brew.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_pkg_returns_value(self):
        runner = make_runner({"brew": "/usr/local/bin/brew"})
        brew = InstallerBrew(runner)
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ):
            pkg = {"name": "test", "brew": "test-pkg"}
            result = brew.install_pkg(pkg)
            assert result is True


class TestInstallerCargo:
    def test_available_true(self):
        cargo = InstallerCargo(make_runner({"cargo": "/usr/bin/cargo"}))
        assert cargo.available is True

    def test_available_false(self):
        cargo = InstallerCargo(make_runner({}))
        assert cargo.available is False

    def test_can_install_no_cargo_key(self):
        cargo = InstallerCargo(make_runner({"cargo": "/usr/bin/cargo"}))
        pkg = {"name": "test", "apt": "test"}
        assert cargo.can_install(pkg) is False

    def test_can_install_with_cargo_key(self):
        cargo = InstallerCargo(make_runner({"cargo": "/usr/bin/cargo"}))
        pkg = {"name": "test", "cargo": "test"}
        assert cargo.can_install(pkg) is True

    def test_cargo_namespace(self):
        cargo = InstallerCargo(make_runner({"cargo": "/usr/bin/cargo"}))
        ns = cargo.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")

    def test_install_pkg_returns_value(self):
        runner = make_runner({"cargo": "/usr/bin/cargo"})
        cargo = InstallerCargo(runner)
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ):
            pkg = {"name": "test", "cargo": "test-pkg"}
            result = cargo.install_pkg(pkg)
            assert result is True


class TestInstallerWinget:
    def test_available_true(self):
        winget = InstallerWinget(make_runner({"winget": "C:\\winget.exe"}))
        assert winget.available is True

    def test_available_false(self):
        winget = InstallerWinget(make_runner({}))
        assert winget.available is False

    def test_available_cached(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = InstallerWinget(runner)
        _ = winget.available
        runner.which = lambda cmd: None
        assert winget.available is True

    def test_can_install_no_winget_key(self):
        winget = InstallerWinget(make_runner({"winget": "C:\\winget.exe"}))
        pkg = {"name": "test", "apt": "test"}
        assert winget.can_install(pkg) is False

    def test_can_install_with_winget_key(self):
        winget = InstallerWinget(make_runner({"winget": "C:\\winget.exe"}))
        pkg = {"name": "test", "winget": "Test.App"}
        assert winget.can_install(pkg) is True

    def test_can_install_no_pkg(self):
        winget = InstallerWinget(make_runner({"winget": "C:\\winget.exe"}))
        assert winget.can_install() is True

    def test_is_pkg_installed_no_winget(self):
        winget = InstallerWinget(make_runner({}))
        pkg = {"name": "test", "winget": "Test.App"}
        assert winget.is_pkg_installed(pkg) is False

    def test_is_pkg_installed_found(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = InstallerWinget(runner)
        pkg = {"name": "test", "winget": "Test.App"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"Name   Id        Version\n"
                b"----------------------------\n"
                b"Test   Test.App  1.2.3\n",
                stderr=b"",
            ),
        ):
            assert winget.is_pkg_installed(pkg) is True

    def test_is_pkg_installed_not_found(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = InstallerWinget(runner)
        pkg = {"name": "test", "winget": "Test.App"}
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"No installed package found matching input criteria.\n",
                stderr=b"",
            ),
        ):
            assert winget.is_pkg_installed(pkg) is False

    def test_winget_namespace(self):
        winget = InstallerWinget(make_runner({"winget": "C:\\winget.exe"}))
        ns = winget.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")
        assert hasattr(ns, "update")

    def test_install_pkg_returns_value(self):
        runner = make_runner({"winget": "C:\\winget.exe"})
        winget = InstallerWinget(runner)
        with patch.object(
            runner,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0),
        ):
            pkg = {"name": "test", "winget": "Test.App"}
            result = winget.install_pkg(pkg)
            assert result is True

    def test_install_pkg_unless_found_already_installed(self):
        winget = InstallerWinget(make_runner({"winget": "C:\\winget.exe"}))
        with patch.object(winget, "is_pkg_installed", return_value=True):
            pkg = {"name": "test", "winget": "Test.App"}
            result = winget.install_pkg_unless_found(pkg)
            assert result is True


class TestInstallerRegistration:
    def test_all_default_backends_registered(self):
        installer = make_installer(which_returns={})
        assert "apt" in installer._backends
        assert "brew" in installer._backends
        assert "cargo" in installer._backends
        assert "custom" in installer._backends
        assert "pip" in installer._backends
        assert "winget" in installer._backends

    def test_registered_backends_count(self):
        installer = make_installer(which_returns={})
        assert (
            len(installer._backends) == 7
        )  # apt, dnf, cargo, pip, brew, winget, custom

    def test_get_backend_returns_instance(self):
        installer = make_installer(which_returns={})
        assert isinstance(installer.get_backend("apt"), InstallerApt)
        assert isinstance(installer.get_backend("brew"), InstallerBrew)
        assert isinstance(installer.get_backend("cargo"), InstallerCargo)
        assert isinstance(installer.get_backend("custom"), InstallerCustom)
        assert isinstance(installer.get_backend("pip"), InstallerPip)
        assert isinstance(installer.get_backend("winget"), InstallerWinget)

    def test_get_backend_not_found(self):
        installer = make_installer(which_returns={})
        with pytest.raises(ValueError):
            installer.get_backend("nonexistent")

    def test_register_extra_installer(self):
        installer = make_installer(which_returns={})

        class ExtraInstaller:
            INSTALLER_NAME = "extra"

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

        installer.register_installer(ExtraInstaller())
        assert "extra" in installer._backends
        assert len(installer._backends) == 8  # 7 built-in + 1 extra

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
        with patch.object(
            installer.runner,
            "run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout=b"", stderr=b""
            ),
        ):
            pkgs = [{"name": "test", "apt": "test-pkg", "cmd": "notfound"}]
            result = installer.install_pkgs(pkgs)
            assert result is True

    def test_install_pkg_delegates(self):
        installer = make_installer(which_returns={})
        with patch.object(installer, "install_pkgs", return_value=True) as mock:
            pkg = {"name": "test"}
            installer.install_pkg(pkg)
            mock.assert_called_once_with([pkg])

    def test_pkg_is_available_true(self):
        """pkg_is_available returns True when apt backend reports available."""
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        pkg = {"name": "tldr", "apt": "tldr"}
        apt_backend = installer.get_backend("apt")
        with patch.object(apt_backend, "is_pkg_available", return_value=True):
            assert installer.pkg_is_available(pkg) is True

    def test_pkg_is_available_false_no_backend(self):
        """pkg_is_available returns False when no backend can handle the package."""
        installer = make_installer(which_returns={})
        pkg = {"name": "unknown-tool", "apt": "unknown-tool"}
        assert installer.pkg_is_available(pkg) is False

    def test_pkg_is_available_false_backend_unavailable(self):
        """pkg_is_available returns False when backend reports unavailable."""
        installer = make_installer(which_returns={"apt": "/usr/bin/apt"})
        pkg = {"name": "ulauncher", "apt": "ulauncher"}
        apt_backend = installer.get_backend("apt")
        with patch.object(apt_backend, "is_pkg_available", return_value=False):
            assert installer.pkg_is_available(pkg) is False


class TestInstallerPipWindowsSupport:
    def test_has_pip_fallback_to_pip(self):
        """When pip3 is not found, falls back to pip."""
        pip = InstallerPip(make_runner({"pip": "/usr/bin/pip"}))
        assert pip.has_pip is True
        assert pip._pip_cmd == ["pip"]

    @patch("pyishlib.installer_pip.is_windows", return_value=True)
    @patch("pyishlib.installer_pip.sys")
    def test_has_pip_windows_fallback_to_python_m_pip(self, mock_sys, _mock_win):
        """On Windows, falls back to python -m pip when pip is not on PATH."""
        mock_sys.executable = "C:\\Python39\\python.exe"
        pip = InstallerPip(make_runner({}))
        assert pip.has_pip is True
        assert pip._pip_cmd == ["C:\\Python39\\python.exe", "-m", "pip"]

    def test_pip_install_cmd_includes_user_flag(self):
        """pip install command always includes --user."""
        pip = InstallerPip(make_runner({"pip3": "/usr/bin/pip3"}))
        cmd = pip.pip_install_cmd
        assert "--user" in cmd

    def test_has_pip_fallback_cached(self):
        """After fallback from pip3 to pip, result is cached."""
        runner = make_runner({"pip": "/usr/bin/pip"})
        pip = InstallerPip(runner)
        _ = pip.has_pip
        # Change which to return None — but result should be cached
        runner.which = lambda cmd: None
        assert pip.has_pip is True
        assert pip._pip_cmd == ["pip"]


class TestCommandRunnerWindowsSupport:
    @patch("pyishlib.command_runner.is_windows", return_value=True)
    def test_run_sudo_raises_on_windows(self, _mock):
        """run_sudo raises OSError on Windows."""
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        with pytest.raises(OSError, match="sudo is not available on Windows"):
            runner.run_sudo(["apt", "update"])


class TestInstallerConfigIntegration:
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

    @patch("pyishlib.installer_config.should_skip_for_os", return_value=False)
    def test_installer_config_get_pkgs_no_filter(self, _mock):
        """get_pkgs() includes packages when OS filter passes."""
        from pyishlib.installer_config import InstallerConfig

        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2"},
        }
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 2

    @patch("pyishlib.installer_config.should_skip_for_os")
    def test_installer_config_get_pkgs_filters_only_on(self, mock_skip):
        """get_pkgs() excludes packages when should_skip_for_os returns True."""
        from pyishlib.installer_config import InstallerConfig

        def skip_debian(only_on=None, ignore_on=None):
            return only_on == ["debian"]

        mock_skip.side_effect = skip_debian
        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2", "only_on": ["debian"]},
        }
        ic = InstallerConfig(config, config_fn=Path("/fake/path"))
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "pkg1"

    def test_installer_config_get_pkgs_filters_bool_tag(self):
        """get_pkgs() excludes bool-tagged packages when the flag is false."""
        from types import SimpleNamespace
        from pyishlib.installer_config import InstallerConfig
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext({"isGnome": "false"})
        cfg = SimpleNamespace(
            context=ctx,
            data_template={"isGnome": {"type": "bool"}},
        )
        config = {
            "pkg1": {"apt": "pkg1"},
            "pkg2": {"apt": "pkg2", "tags": ["isGnome"]},
        }
        ic = InstallerConfig(config, config_fn=Path("/fake/path"), cfg=cfg)
        pkgs = ic.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "pkg1"


if __name__ == "__main__":
    pytest.main()
