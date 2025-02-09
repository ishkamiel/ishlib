# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from pyishlib.installer import Installer
from pyishlib.command_runner import CommandRunner
import logging
import subprocess


class TestInstaller(unittest.TestCase):

    @patch("pyishlib.installer.CommandRunner.which", return_value="fakecmd")
    # @patch("pyishlib.installer.CommandRunner.run", return_value=subprocess.CompletedProcess(args=[], returncode=0))
    def test_is_installed(self, mock_which):
        runner = CommandRunner(dry_run=True)
        installer = Installer(runner=runner)
        # installer.set_log_level(logging.DEBUG)

        pkg_config = {"name": "fakepkg", "apt": "fakepkg", "cmd": "fakecmd"}

        have_pkg_result: bool = installer.have_pkg(pkg_config)

        mock_which.assert_any_call("fakecmd")
        assert have_pkg_result

    def mock_which(cmd, *args, **kwargs):
        if cmd == "apt":
            return "apt"
        return None

    # @patch("pyishlib.installer.AptInstaller.can_use_apt", return_value=True)
    @patch("pyishlib.installer.CommandRunner.which", side_effect=mock_which)
    @patch(
        "pyishlib.installer.CommandRunner.run_sudo",
        return_value=subprocess.CompletedProcess(args=[], returncode=0),
    )
    def test_apt(self, mock_run, mock_which):
        runner = CommandRunner(dry_run=True)
        installer = Installer(runner=runner)
        installer.set_log_level(logging.DEBUG)

        pkg_config = {"name": "fakepkg", "apt": "fakepkg", "cmd": "fakecmd"}
        install_package_result: bool = installer.install_pkg(pkg_config)

        # mock_which.assert_called_once_with("fakecmd")
        mock_run.assert_any_call(["apt", "install", "-y", "fakepkg"])
        assert install_package_result

    # @patch("pyishlib.installer.shutil.which", return_value=None)
    # @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    # def test_cargo_install_unless_cmd(self, mock_run, mock_which):
    #     runner = CommandRunner(dry_run=True)
    #     installer = Installer(runner=runner)
    #     packages = [{"command": "fakecmd", "package": "fakepkg"}]

    #     installer.install_cargo_unless_cmd(*packages)

    #     mock_which.assert_called_once_with("fakecmd")
    #     mock_run.assert_called_once_with(["cargo", "install", "fakepkg"])

    # @patch("pyishlib.installer.shutil.which", return_value=None)
    # @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    # def test_install_apt(self, mock_run, mock_which):
    #     runner = CommandRunner(dry_run=True)
    #     installer = Installer(runner=runner)

    #     installer.install_apt("fakepkg")

    #     mock_run.assert_called_once_with(["apt", "install", "fakepkg"], sudo=True)

    # @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    # def test_install_cargo(self, mock_run):
    #     runner = CommandRunner(dry_run=True)
    #     installer = Installer(runner=runner)

    #     installer.install_cargo("fakepkg")

    #     mock_run.assert_called_once_with(["cargo", "install", "fakepkg"])


if __name__ == "__main__":
    unittest.main()
