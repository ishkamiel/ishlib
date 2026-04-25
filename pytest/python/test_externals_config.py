# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for ishfiles.externals_config."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.externals_config import (
    load_externals,
    parse_refresh_period,
)


def _make_cfg(tmp_dir: str) -> SimpleNamespace:
    """Minimal config-like object pointing source at *tmp_dir*."""
    return SimpleNamespace(
        get_opt=lambda name, default=None: {
            "source": tmp_dir,
            "config_dir": "ishconfig",
            "externals_config_file": "externals.toml",
        }.get(name, default)
    )


def _write_toml(tmp_dir: str, content: str) -> None:
    config_dir = Path(tmp_dir) / "ishconfig"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "externals.toml").write_text(content, encoding="utf-8")


class TestParseRefreshPeriod(unittest.TestCase):
    def test_hours(self):
        assert parse_refresh_period("168h") == 168 * 3600

    def test_days(self):
        assert parse_refresh_period("7d") == 7 * 86400

    def test_minutes(self):
        assert parse_refresh_period("30m") == 30 * 60

    def test_seconds(self):
        assert parse_refresh_period("3600s") == 3600

    def test_weeks(self):
        assert parse_refresh_period("2w") == 2 * 604800

    def test_bare_number_treated_as_seconds(self):
        assert parse_refresh_period("60") == 60

    def test_empty_returns_none(self):
        assert parse_refresh_period("") is None

    def test_none_returns_none(self):
        assert parse_refresh_period(None) is None

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_refresh_period("abc")


class TestLoadExternals(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert specs == []

    def test_four_entry_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
refresh_period = "168h"

[".oh-my-zsh"]
url = "https://github.com/ohmyzsh/ohmyzsh.git"
revision = "master"

[".pyenv"]
url = "https://github.com/pyenv/pyenv.git"
revision = "v2.5.5"

[".tmux/plugins/tpm"]
url = "https://github.com/tmux-plugins/tpm.git"
revision = "master"
""",
            )
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert len(specs) == 4
            paths = [s.path for s in specs]
            assert ".fzf" in paths
            assert ".oh-my-zsh" in paths
            assert ".pyenv" in paths
            assert ".tmux/plugins/tpm" in paths

    def test_refresh_period_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
refresh_period = "168h"
""",
            )
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert specs[0].refresh_period == 168 * 3600

    def test_camlecase_alias_accepted(self):
        """refreshPeriod (chezmoi name) is accepted as an alias."""
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
refreshPeriod = "24h"
""",
            )
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert specs[0].refresh_period == 24 * 3600

    def test_missing_url_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
revision = "v0.62.0"
""",
            )
            cfg = _make_cfg(tmp)
            with self.assertLogs(level="WARNING"):
                specs = load_externals(cfg)
            assert specs == []

    def test_missing_revision_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
""",
            )
            cfg = _make_cfg(tmp)
            with self.assertLogs(level="WARNING"):
                specs = load_externals(cfg)
            assert specs == []

    def test_unknown_type_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
type = "archive"
""",
            )
            cfg = _make_cfg(tmp)
            with self.assertLogs(level="WARNING"):
                specs = load_externals(cfg)
            assert specs == []

    def test_include_exclude_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
include = ["bin/*"]
exclude = ["*.md"]
""",
            )
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert specs[0].include == ["bin/*"]
            assert specs[0].exclude == ["*.md"]

    def test_strip_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
strip_prefix = "subdir"
""",
            )
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert specs[0].strip_prefix == "subdir"

    def test_default_type_is_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
""",
            )
            cfg = _make_cfg(tmp)
            specs = load_externals(cfg)
            assert specs[0].type == "git-repo"

    def test_invalid_include_type_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_toml(
                tmp,
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"
include = "not-a-list"
""",
            )
            cfg = _make_cfg(tmp)
            with self.assertLogs(level="WARNING"):
                specs = load_externals(cfg)
            assert specs == []


if __name__ == "__main__":
    unittest.main()
