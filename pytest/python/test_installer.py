#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import unittest
from unittest.mock import patch
from pyishlib.installer import Installer
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig
import logging
import subprocess


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
        "pyishlib.installer.CommandRunner.run_sudo",
        return_value=subprocess.CompletedProcess(args=[], returncode=0),
    )
    def test_apt(self, mock_run, mock_which):
        cfg = IshConfig(dry_run=True, log_level=logging.DEBUG)
        runner = CommandRunner(cfg=cfg)
        installer = Installer(cfg=cfg, runner=runner)

        pkg_config = {"name": "fakepkg", "apt": "fakepkg", "cmd": "fakecmd"}
        install_package_result: bool = installer.install_pkg(pkg_config)

        # mock_which.assert_called_once_with("fakecmd")
        mock_run.assert_any_call(["apt", "install", "-y", "fakepkg"])
        assert install_package_result


if __name__ == "__main__":
    unittest.main()
