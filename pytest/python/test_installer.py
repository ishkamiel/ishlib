# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

import unittest
from unittest.mock import patch
from pyishlib.installer import Installer
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig
import logging
import subprocess


def _completed(stdout=b"", stderr=b"", returncode=0):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestInstaller(unittest.TestCase):
    @patch("pyishlib.installer.CommandRunner.which", return_value="fakecmd")
    # @patch("pyishlib.installer.CommandRunner.run", return_value=subprocess.CompletedProcess(args=[], returncode=0))
    def test_is_installed(self, mock_which):
        cfg = IshConfig(dry_run=True)
        runner = CommandRunner(cfg=cfg)
        installer = Installer(cfg=cfg, runner=runner)

        pkg_config = {"name": "fakepkg", "apt": "fakepkg", "cmd": "fakecmd"}

        have_pkg_result: bool = installer.have_pkg(pkg_config)

        mock_which.assert_any_call("fakecmd")
        assert have_pkg_result

    def mock_which(cmd, *args, **kwargs):
        if cmd == "apt":
            return "apt"
        return None

    # @patch("pyishlib.installer.InstallerApt.can_use_apt", return_value=True)
    @patch("pyishlib.installer.CommandRunner.which", side_effect=mock_which)
    @patch(
        "pyishlib.installer.CommandRunner.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        ),
    )
    def test_apt(self, mock_run, mock_which):
        cfg = IshConfig(dry_run=True, log_level=logging.DEBUG)
        runner = CommandRunner(cfg=cfg)
        installer = Installer(cfg=cfg, runner=runner)

        pkg_config = {"name": "fakepkg", "apt": "fakepkg", "cmd": "fakecmd"}
        install_package_result: bool = installer.install_pkg(pkg_config)

        # mock_which.assert_called_once_with("fakecmd")
        mock_run.assert_any_call(["apt", "install", "-y", "fakepkg"], sudo=True)
        assert install_package_result


class TestHavePkgVersionAware(unittest.TestCase):
    """Tests for Installer.have_pkg's min_version / command_version branch."""

    def _make(self):
        cfg = IshConfig(dry_run=True)
        runner = CommandRunner(cfg=cfg)
        return Installer(cfg=cfg, runner=runner)

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value="/usr/bin/rg")
    def test_min_version_ok(self, mock_which, mock_run):
        mock_run.return_value = _completed(stdout=b"ripgrep 14.1.0\n")
        installer = self._make()
        pkg = {"name": "rg", "cmd": "rg", "min_version": "13.0.0"}
        self.assertTrue(installer.have_pkg(pkg))
        # Probe ran with default `<cmd> --version` argv
        argv_calls = [c.args[0] for c in mock_run.call_args_list]
        self.assertIn(["rg", "--version"], argv_calls)

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value="/usr/bin/rg")
    def test_min_version_too_low(self, mock_which, mock_run):
        mock_run.return_value = _completed(stdout=b"ripgrep 12.0.0\n")
        installer = self._make()
        pkg = {"name": "rg", "cmd": "rg", "min_version": "13.0.0"}
        self.assertFalse(installer.have_pkg(pkg))

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value="/usr/bin/x")
    def test_min_version_unparsable_output(self, mock_which, mock_run):
        mock_run.return_value = _completed(stdout=b"hello\n")
        installer = self._make()
        pkg = {"name": "x", "cmd": "x", "min_version": "1.0"}
        self.assertFalse(installer.have_pkg(pkg))

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value=None)
    def test_min_version_command_not_on_path(self, mock_which, mock_run):
        installer = self._make()
        pkg = {"name": "rg", "cmd": "rg", "min_version": "1.0"}
        self.assertFalse(installer.have_pkg(pkg))
        # Probe is skipped when which() fails.
        mock_run.assert_not_called()

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value="/usr/bin/java")
    def test_min_version_with_custom_command_version(self, mock_which, mock_run):
        # java prints the version to stderr.
        mock_run.return_value = _completed(
            stderr=b'openjdk version "17.0.2" 2022-01-18\n'
        )
        installer = self._make()
        pkg = {
            "name": "java",
            "cmd": "java",
            "min_version": "17",
            "command_version": "java -version",
        }
        self.assertTrue(installer.have_pkg(pkg))
        argv_calls = [c.args[0] for c in mock_run.call_args_list]
        self.assertIn(["java", "-version"], argv_calls)

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value="/usr/bin/x")
    def test_min_version_probe_failure(self, mock_which, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, ["x", "--version"])
        installer = self._make()
        pkg = {"name": "x", "cmd": "x", "min_version": "1.0"}
        self.assertFalse(installer.have_pkg(pkg))

    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value="/usr/bin/rg")
    def test_cmd_only_no_min_version_unchanged(self, mock_which, mock_run):
        # Regression: cmd-only path must not invoke the probe.
        installer = self._make()
        pkg = {"name": "rg", "cmd": "rg"}
        self.assertTrue(installer.have_pkg(pkg))
        mock_run.assert_not_called()

    @patch("pyishlib.installer.InstallerApt.is_pkg_installed")
    @patch("pyishlib.installer.CommandRunner.run")
    @patch("pyishlib.installer.CommandRunner.which", return_value=None)
    def test_min_version_authoritative_skips_backends(
        self, mock_which, mock_run, mock_apt_is_installed
    ):
        # cmd not on PATH + min_version set → False without ever asking apt.
        installer = self._make()
        pkg = {"name": "rg", "cmd": "rg", "min_version": "1.0", "apt": "ripgrep"}
        self.assertFalse(installer.have_pkg(pkg))
        mock_apt_is_installed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
