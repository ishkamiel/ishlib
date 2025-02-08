# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from pyishlib.installer_config import InstallerConfig, InstallerConfigJSON
import sys


class TestInstallerConfigSimple(unittest.TestCase):
    real_open = open

    DUMMY_CONFIG_FN = "/fake/path/to/config"
    DUMMY_CONFIG = """\
{
  "apt-file": {
    "apt": "apt-file"
  }
}
"""

    def mock_open_side_effect(file, mode="r", *args, **kwargs):
        if file == TestInstallerConfigSimple.DUMMY_CONFIG_FN:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = (
                TestInstallerConfigSimple.DUMMY_CONFIG
            )
            return mock_file
        else:
            return TestInstallerConfigSimple.real_open(file, mode, *args, **kwargs)

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_read(self, mock_open):
        config = InstallerConfigJSON(TestInstallerConfigSimple.DUMMY_CONFIG_FN)
        mock_open.assert_any_call(
            TestInstallerConfigSimple.DUMMY_CONFIG_FN, "r", encoding="utf-8"
        )


class TestInstallerConfigFull(unittest.TestCase):
    real_open = open

    DUMMY_CONFIG_FN = "/fake/path/to/config"
    DUMMY_CONFIG = """\
{
  "apt-file": {
    "apt": "apt-file",
    "cmd": "apt-file"
  },
  "build-essential": {
    "apt": "build-essential"
  },
  "cargo-update": {
    "cargo": "cargo-update"
  },
  "du-dust": {
    "cargo": "du-dust",
    "cmd": "dust"
  },
  "python-is-python3": {
    "apt": "python-is-python3",
    "ubuntu": true
  },
  "python3-toml": {
    "apt": "python3-toml",
    "pip": "toml",
    "type": "python_pkg"
  }
}
"""

    def mock_open_side_effect(file, mode="r", *args, **kwargs):
        if file == TestInstallerConfigFull.DUMMY_CONFIG_FN:
            mock_file = MagicMock()
            mock_file.__enter__.return_value.read.return_value = (
                TestInstallerConfigFull.DUMMY_CONFIG
            )
            return mock_file
        else:
            return TestInstallerConfigFull.real_open(file, mode, *args, **kwargs)

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_read(self, mock_open):
        config = InstallerConfigJSON(TestInstallerConfigFull.DUMMY_CONFIG_FN)
        mock_open.assert_any_call(
            TestInstallerConfigFull.DUMMY_CONFIG_FN, "r", encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
