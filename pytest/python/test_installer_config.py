#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

import pytest

try:
    import cerberus
    import jsonschema
    import yaml

    HAS_VALIDATION_DEPS = True
except ImportError:
    HAS_VALIDATION_DEPS = False

from pyishlib.installer_config import (
    InstallerConfig,
    InstallerConfigJSON,
    InstallerConfigTOML,
    HAS_TOML,
)


@pytest.mark.skipif(
    not HAS_VALIDATION_DEPS,
    reason="cerberus/jsonschema/pyyaml not installed",
)
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


@pytest.mark.skipif(
    not HAS_VALIDATION_DEPS,
    reason="cerberus/jsonschema/pyyaml not installed",
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


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestInstallerConfigTOMLSimple(unittest.TestCase):
    real_open = open

    DUMMY_CONFIG_FN = "/fake/path/to/config.toml"
    DUMMY_CONFIG = b"""\
[apt-file]
apt = "apt-file"
"""

    def mock_open_side_effect(file, mode="r", *args, **kwargs):
        if file == TestInstallerConfigTOMLSimple.DUMMY_CONFIG_FN:
            import io

            return io.BytesIO(TestInstallerConfigTOMLSimple.DUMMY_CONFIG)
        else:
            return TestInstallerConfigTOMLSimple.real_open(file, mode, *args, **kwargs)

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_read(self, mock_open):
        config = InstallerConfigTOML(TestInstallerConfigTOMLSimple.DUMMY_CONFIG_FN)
        mock_open.assert_any_call(TestInstallerConfigTOMLSimple.DUMMY_CONFIG_FN, "rb")

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_pkgs(self, mock_open):
        config = InstallerConfigTOML(TestInstallerConfigTOMLSimple.DUMMY_CONFIG_FN)
        pkgs = config.get_pkgs()
        assert len(pkgs) == 1
        assert pkgs[0]["name"] == "apt-file"
        assert pkgs[0]["apt"] == "apt-file"


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestInstallerConfigTOMLFull(unittest.TestCase):
    real_open = open

    DUMMY_CONFIG_FN = "/fake/path/to/config.toml"
    DUMMY_CONFIG = b"""\
[apt-file]
apt = "apt-file"
cmd = "apt-file"

[build-essential]
apt = "build-essential"

[cargo-update]
cargo = "cargo-update"

[du-dust]
cargo = "du-dust"
cmd = "dust"

[python-is-python3]
apt = "python-is-python3"
ubuntu = true

[python3-toml]
apt = "python3-toml"
pip = "toml"
type = "python_pkg"
"""

    def mock_open_side_effect(file, mode="r", *args, **kwargs):
        if file == TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN:
            import io

            return io.BytesIO(TestInstallerConfigTOMLFull.DUMMY_CONFIG)
        else:
            return TestInstallerConfigTOMLFull.real_open(file, mode, *args, **kwargs)

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_read(self, mock_open):
        config = InstallerConfigTOML(TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN)
        mock_open.assert_any_call(TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN, "rb")

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_pkgs(self, mock_open):
        config = InstallerConfigTOML(TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN)
        pkgs = config.get_pkgs()
        names = [p["name"] for p in pkgs]
        assert "apt-file" in names
        assert "cargo-update" in names
        assert "du-dust" in names

    @patch("builtins.open", side_effect=mock_open_side_effect)
    def test_config_invalid_toml(self, mock_open):
        """Test that invalid TOML raises ValueError"""
        import io

        mock_open.side_effect = lambda file, mode="r", *a, **kw: (
            io.BytesIO(b"[invalid\nthis is not valid toml")
            if file == TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN
            else TestInstallerConfigTOMLFull.real_open(file, mode, *a, **kw)
        )
        with self.assertRaises(ValueError):
            InstallerConfigTOML(TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN)


if __name__ == "__main__":
    unittest.main()
