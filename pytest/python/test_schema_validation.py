# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

#
# Tests for shared schema validation.

import sys
import os
import tempfile
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.schema_validation import (
    validate_packages,
    validate_metadata,
    load_packages_schema,
    load_metadata_schema,
    HAS_CERBERUS,
)

# Skip all tests if cerberus is not available
pytestmark = pytest.mark.skipif(not HAS_CERBERUS, reason="cerberus not installed")


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


class TestSchemaLoading:
    def test_load_packages_schema(self):
        schema = load_packages_schema()
        assert "keysrules" in schema
        assert "valuesrules" in schema
        # Verify it has expected package fields
        pkg_schema = schema["valuesrules"]["schema"]
        assert "apt" in pkg_schema
        assert "brew" in pkg_schema
        assert "pref" in pkg_schema

    def test_load_metadata_schema(self):
        schema = load_metadata_schema()
        assert "metadata" in schema
        meta_schema = schema["metadata"]["schema"]
        assert "only_on" in meta_schema
        assert "ignore_on" in meta_schema
        assert "vars" in meta_schema
        assert "packages" in meta_schema


# ---------------------------------------------------------------------------
# validate_packages
# ---------------------------------------------------------------------------


class TestValidatePackages:
    def test_valid_empty(self):
        assert validate_packages({}) is None

    def test_valid_simple(self):
        assert validate_packages({"vim": {}, "git": {}}) is None

    def test_valid_with_attributes(self):
        packages = {
            "vim": {"pref": ["apt"]},
            "ripgrep": {"cargo": "ripgrep", "apt": "ripgrep"},
        }
        assert validate_packages(packages) is None

    def test_valid_all_fields(self):
        packages = {
            "mypackage": {
                "apt": "my-pkg",
                "brew": "my-pkg",
                "cargo": "my-pkg",
                "cmd": "install my-pkg",
                "custom": "myscript",
                "dnf": "my-pkg",
                "ignore_on": ["windows"],
                "only_on": ["linux"],
                "optional": True,
                "pip": "my-pkg",
                "pref": ["apt", "brew"],
                "tags": ["build_tools"],
                "type": "system",
                "winget": "Publisher.MyPkg",
            }
        }
        assert validate_packages(packages) is None

    def test_invalid_wrong_type_for_apt(self):
        packages = {"vim": {"apt": 123}}
        err = validate_packages(packages)
        assert err is not None
        assert "validation failed" in err.lower() or "Package" in err

    def test_invalid_wrong_type_for_optional(self):
        packages = {"vim": {"apt": "vim", "optional": "yes"}}
        err = validate_packages(packages)
        assert err is not None

    def test_source_label_in_error(self):
        err = validate_packages({"bad": {"apt": 42}}, source="test.toml")
        assert err is not None
        assert "test.toml" in err


# ---------------------------------------------------------------------------
# validate_metadata
# ---------------------------------------------------------------------------


class TestValidateMetadata:
    def test_valid_empty(self):
        assert validate_metadata({}) is None

    def test_valid_only_on(self):
        assert validate_metadata({"only_on": ["linux", "macos"]}) is None

    def test_valid_ignore_on(self):
        assert validate_metadata({"ignore_on": ["windows"]}) is None

    def test_valid_vars(self):
        assert validate_metadata({"vars": {"editor": "vim"}}) is None

    def test_valid_packages(self):
        metadata = {"packages": {"vim": {}, "git": {"pref": ["apt"]}}}
        assert validate_metadata(metadata) is None

    def test_valid_full_metadata(self):
        metadata = {
            "only_on": ["linux"],
            "ignore_on": ["windows"],
            "vars": {"editor": "vim", "shell": "bash"},
            "packages": {"vim": {"apt": "vim-nox"}, "git": {}},
        }
        assert validate_metadata(metadata) is None

    def test_invalid_only_on_type(self):
        err = validate_metadata({"only_on": "linux"})
        assert err is not None

    def test_invalid_ignore_on_type(self):
        err = validate_metadata({"ignore_on": "windows"})
        assert err is not None

    def test_invalid_vars_type(self):
        err = validate_metadata({"vars": "not a dict"})
        assert err is not None

    def test_invalid_packages_sub_schema(self):
        metadata = {"packages": {"vim": {"apt": 123}}}
        err = validate_metadata(metadata)
        assert err is not None

    def test_allows_unknown_top_level_keys(self):
        # The metadata schema uses allow_unknown=true so custom keys are OK
        assert validate_metadata({"custom_key": "value"}) is None

    def test_source_label_in_error(self):
        err = validate_metadata({"only_on": "bad"}, source="myfile.sh")
        assert err is not None
        assert "myfile.sh" in err


# ---------------------------------------------------------------------------
# Integration: read_metadata validates
# ---------------------------------------------------------------------------


class TestReadMetadataValidation:
    def test_valid_metadata_no_warning(self, caplog):
        from pyishlib.ish_metadata import read_metadata

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.sh"
            p.write_text(
                ": <<'__ISH__'\n"
                'only_on = ["linux"]\n'
                "[packages]\n"
                "vim = {}\n"
                "__ISH__\n"
                "echo hello\n"
            )
            import logging

            with caplog.at_level(logging.WARNING):
                meta = read_metadata(p)
            assert meta is not None
            assert "validation failed" not in caplog.text.lower()

    def test_invalid_metadata_logs_warning(self, caplog):
        from pyishlib.ish_metadata import read_metadata

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.sh"
            p.write_text(
                ": <<'__ISH__'\nonly_on = \"not_a_list\"\n__ISH__\necho hello\n"
            )
            import logging

            with caplog.at_level(logging.WARNING):
                meta = read_metadata(p)
            # Metadata is still returned despite validation warning
            assert meta is not None
            assert "validation failed" in caplog.text.lower()

    def test_skip_validation(self, caplog):
        from pyishlib.ish_metadata import read_metadata

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.sh"
            p.write_text(
                ": <<'__ISH__'\nonly_on = \"not_a_list\"\n__ISH__\necho hello\n"
            )
            import logging

            with caplog.at_level(logging.WARNING):
                meta = read_metadata(p, validate=False)
            assert meta is not None
            assert "validation failed" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# InstallerConfig uses shared validation
# ---------------------------------------------------------------------------


class TestInstallerConfigSharedValidation:
    def test_valid_config(self):
        from pyishlib.installer_config import InstallerConfig

        config = {"vim": {"apt": "vim"}, "git": {}}
        with tempfile.NamedTemporaryFile(suffix=".toml") as f:
            ic = InstallerConfig(config, Path(f.name))
            pkgs = list(ic.get_pkgs())
            assert len(pkgs) == 2

    def test_invalid_config_raises(self):
        from pyishlib.installer_config import InstallerConfig

        config = {"vim": {"apt": 123}}
        with tempfile.NamedTemporaryFile(suffix=".toml") as f:
            with pytest.raises(ValueError, match="validation failed"):
                InstallerConfig(config, Path(f.name))


if __name__ == "__main__":
    pytest.main()
