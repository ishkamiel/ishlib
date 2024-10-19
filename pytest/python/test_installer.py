# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from pyishlib.installer import Installer, InstallerConfig
from pyishlib.command_runner import CommandRunner


class TestInstaller(unittest.TestCase):

    @patch("pyishlib.installer.shutil.which", return_value=None)
    @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    def test_apt_install_unless_cmd(self, mock_run, mock_which):
        runner = CommandRunner(dry_run=True)
        installer = Installer(runner=runner)
        packages = [{"command": "fakecmd", "package": "fakepkg"}]

        installer.install_apt_unless_cmd(*packages)

        mock_which.assert_called_once_with("fakecmd")
        mock_run.assert_called_once_with(["apt", "install", "fakepkg"], sudo=True)

    @patch("pyishlib.installer.shutil.which", return_value=None)
    @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    def test_cargo_install_unless_cmd(self, mock_run, mock_which):
        runner = CommandRunner(dry_run=True)
        installer = Installer(runner=runner)
        packages = [{"command": "fakecmd", "package": "fakepkg"}]

        installer.install_cargo_unless_cmd(*packages)

        mock_which.assert_called_once_with("fakecmd")
        mock_run.assert_called_once_with(["cargo", "install", "fakepkg"])

    @patch("pyishlib.installer.shutil.which", return_value=None)
    @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    def test_install_apt(self, mock_run, mock_which):
        runner = CommandRunner(dry_run=True)
        installer = Installer(runner=runner)

        installer.install_apt("fakepkg")

        mock_run.assert_called_once_with(["apt", "install", "fakepkg"], sudo=True)

    @patch("pyishlib.installer.CommandRunner.run", return_value=True)
    def test_install_cargo(self, mock_run):
        runner = CommandRunner(dry_run=True)
        installer = Installer(runner=runner)

        installer.install_cargo("fakepkg")

        mock_run.assert_called_once_with(["cargo", "install", "fakepkg"])


if __name__ == "__main__":
    unittest.main()
