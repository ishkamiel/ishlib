# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

try:
    import cerberus  # noqa: F401
    import jsonschema  # noqa: F401
    import yaml  # noqa: F401

    HAS_VALIDATION_DEPS = True
except ImportError:
    HAS_VALIDATION_DEPS = False

from pyishlib.installer_config import (
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
        InstallerConfigJSON(TestInstallerConfigSimple.DUMMY_CONFIG_FN)
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
    "only_on": ["debian"]
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
        InstallerConfigJSON(TestInstallerConfigFull.DUMMY_CONFIG_FN)
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
        InstallerConfigTOML(TestInstallerConfigTOMLSimple.DUMMY_CONFIG_FN)
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
only_on = ["debian"]

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
        InstallerConfigTOML(TestInstallerConfigTOMLFull.DUMMY_CONFIG_FN)
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


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestInstallerConfigTagFilter(unittest.TestCase):
    """Tests for the generic tag-filter using cfg.data_template."""

    # Minimal data template used across tests
    TEMPLATE = {
        "machineType": {
            "type": "ordered_tags",
            "values": ["min", "def", "personal"],
        },
        "isWork": {"type": "bool"},
        "isGaming": {"type": "bool"},
        "needBuildTools": {"type": "bool"},
        "flavor": {
            "type": "tags",
            "values": ["vanilla", "chocolate"],
        },
    }

    def _make_cfg(self, context_vars: dict):
        """Return a minimal fake cfg object."""
        from types import SimpleNamespace
        from pyishlib.dotfile_context import DotfileContext

        ctx = DotfileContext(context_vars)
        ns = SimpleNamespace(context=ctx, data_template=self.TEMPLATE)
        return ns

    def _make_config(self, context_vars: dict, toml_bytes: bytes = b"[dummy]\n"):
        """Build an InstallerConfigTOML with a fake cfg."""
        import io
        from unittest.mock import patch

        cfg = self._make_cfg(context_vars)
        fn = "/fake/tags.toml"
        real_open = open

        def mock_open(file, mode="r", *a, **kw):
            if file == fn:
                return io.BytesIO(toml_bytes)
            return real_open(file, mode, *a, **kw)

        with patch("builtins.open", side_effect=mock_open):
            return InstallerConfigTOML(fn, cfg=cfg)  # type: ignore[arg-type]

    # ---- no tags → always included ----------------------------------------

    def test_no_tags_always_included(self):
        config = self._make_config(
            {"machineType": "min"},
            b'[pkg]\napt = "somepkg"\n',
        )
        pkgs = config.get_pkgs()
        assert any(p["name"] == "pkg" for p in pkgs)

    # ---- bool tags ---------------------------------------------------------

    def test_bool_tag_truthy_included(self):
        config = self._make_config(
            {"needBuildTools": "true"},
            b'[pkg]\napt = "build-pkg"\ntags = ["needBuildTools"]\n',
        )
        pkgs = config.get_pkgs()
        assert any(p["name"] == "pkg" for p in pkgs)

    def test_bool_tag_falsy_excluded(self):
        config = self._make_config(
            {"needBuildTools": "false"},
            b'[pkg]\napt = "build-pkg"\ntags = ["needBuildTools"]\n',
        )
        pkgs = config.get_pkgs()
        assert not any(p["name"] == "pkg" for p in pkgs)

    def test_negated_bool_tag(self):
        """!isWork is true when isWork is false."""
        config = self._make_config(
            {"isWork": "false"},
            b'[pkg]\napt = "personal-pkg"\ntags = ["!isWork"]\n',
        )
        pkgs = config.get_pkgs()
        assert any(p["name"] == "pkg" for p in pkgs)

    def test_negated_bool_tag_excluded_when_truthy(self):
        config = self._make_config(
            {"isWork": "true"},
            b'[pkg]\napt = "personal-pkg"\ntags = ["!isWork"]\n',
        )
        pkgs = config.get_pkgs()
        assert not any(p["name"] == "pkg" for p in pkgs)

    # ---- tags type ---------------------------------------------------------

    def test_tags_type_exact_match(self):
        config = self._make_config(
            {"flavor": "chocolate"},
            b'[pkg]\napt = "choc-pkg"\ntags = ["chocolate"]\n',
        )
        pkgs = config.get_pkgs()
        assert any(p["name"] == "pkg" for p in pkgs)

    def test_tags_type_no_match(self):
        config = self._make_config(
            {"flavor": "vanilla"},
            b'[pkg]\napt = "choc-pkg"\ntags = ["chocolate"]\n',
        )
        pkgs = config.get_pkgs()
        assert not any(p["name"] == "pkg" for p in pkgs)

    # ---- ordered_tags type -------------------------------------------------

    def test_ordered_tags_higher_implies_lower(self):
        """personal machine includes 'min' and 'def' tagged packages."""
        toml = b'[a]\napt="a"\ntags=["min"]\n[b]\napt="b"\ntags=["def"]\n[c]\napt="c"\ntags=["personal"]\n'
        config = self._make_config({"machineType": "personal"}, toml)
        names = [p["name"] for p in config.get_pkgs()]
        assert "a" in names
        assert "b" in names
        assert "c" in names

    def test_ordered_tags_lower_does_not_imply_higher(self):
        """min machine excludes 'def' and 'personal' tagged packages."""
        toml = b'[a]\napt="a"\ntags=["min"]\n[b]\napt="b"\ntags=["def"]\n[c]\napt="c"\ntags=["personal"]\n'
        config = self._make_config({"machineType": "min"}, toml)
        names = [p["name"] for p in config.get_pkgs()]
        assert "a" in names
        assert "b" not in names
        assert "c" not in names

    def test_ordered_tags_def_includes_min_excludes_personal(self):
        toml = b'[a]\napt="a"\ntags=["min"]\n[b]\napt="b"\ntags=["def"]\n[c]\napt="c"\ntags=["personal"]\n'
        config = self._make_config({"machineType": "def"}, toml)
        names = [p["name"] for p in config.get_pkgs()]
        assert "a" in names
        assert "b" in names
        assert "c" not in names

    # ---- unknown tag -------------------------------------------------------

    def test_unknown_tag_excluded_with_warning(self):
        config = self._make_config(
            {},
            b'[pkg]\napt = "p"\ntags = ["totally_unknown_tag"]\n',
        )
        with self.assertLogs("pyishlib.tag_filter", level="WARNING"):
            pkgs = config.get_pkgs()
        assert not any(p["name"] == "pkg" for p in pkgs)

    # ---- case-insensitive normalisation ------------------------------------

    def test_tag_case_insensitive(self):
        """Package tag 'Min' matches ordered_tags value 'min'."""
        config = self._make_config(
            {"machineType": "min"},
            b'[pkg]\napt = "p"\ntags = ["Min"]\n',
        )
        pkgs = config.get_pkgs()
        assert any(p["name"] == "pkg" for p in pkgs)

    def test_context_value_case_insensitive(self):
        """Context value 'Personal' matches tag 'personal'."""
        config = self._make_config(
            {"machineType": "Personal"},
            b'[pkg]\napt = "p"\ntags = ["personal"]\n',
        )
        pkgs = config.get_pkgs()
        assert any(p["name"] == "pkg" for p in pkgs)


if __name__ == "__main__":
    unittest.main()
