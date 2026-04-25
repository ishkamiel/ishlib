# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for ishfiles.commands.external and apply_externals_stage."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.commands.external import (
    apply_externals_stage,
    _seed_context,
)
from pyishlib.ishfiles.externals_config import ExternalSpec
from pyishlib.ish_config import IshConfig


def _make_cfg(source: str, target: str) -> IshConfig:
    """Build a minimal IshConfig pointing at temp dirs."""
    cfg = IshConfig()
    cfg.dry_run = False

    source_path = Path(source)
    target_path = Path(target)

    # Register the constants that load_config normally registers.
    cfg.set_constant("config_dir", "ishconfig")
    cfg.set_constant("externals_config_file", "externals.toml")
    cfg.set_constant("externals_cache_dir", str(source_path / ".cache" / "externals"))
    cfg.set_constant("externals_state_filename", "externals-state.json")
    cfg.set_default("source", str(source_path))
    cfg.set_default("target", str(target_path))
    return cfg


def _write_externals_toml(source: str, content: str) -> None:
    config_dir = Path(source) / "ishconfig"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "externals.toml").write_text(content, encoding="utf-8")


class TestSeedContext(unittest.TestCase):
    def test_sets_revision_and_sha(self):
        cfg = IshConfig()
        spec = ExternalSpec(path=".fzf", url="http://x", revision="v1.0.0")
        _seed_context(cfg, spec, "abc123")
        ctx = cfg.context.as_dict()
        assert ctx.get("ext_fzf_revision") == "v1.0.0"
        assert ctx.get("ext_fzf_commit_sha") == "abc123"

    def test_path_with_slashes_sanitized(self):
        cfg = IshConfig()
        spec = ExternalSpec(path=".tmux/plugins/tpm", url="http://x", revision="v3")
        _seed_context(cfg, spec, "sha1")
        ctx = cfg.context.as_dict()
        assert "ext_tmux_plugins_tpm_revision" in ctx

    def test_empty_sha_allowed(self):
        cfg = IshConfig()
        spec = ExternalSpec(path=".oh-my-zsh", url="http://x", revision="main")
        _seed_context(cfg, spec, "")
        ctx = cfg.context.as_dict()
        assert ctx.get("ext_oh_my_zsh_revision") == "main"


class TestApplyExternalsStageNoConfig(unittest.TestCase):
    def test_returns_zero_when_no_externals_toml(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            cfg = _make_cfg(src, tgt)
            ret = apply_externals_stage(cfg)
            assert ret == 0

    def test_paths_filter_empty_list_warns_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            _write_externals_toml(src, """
[".fzf"]
url = "https://example.com/fzf.git"
revision = "v1.0.0"
""")
            cfg = _make_cfg(src, tgt)
            with self.assertLogs(level="WARNING"):
                ret = apply_externals_stage(cfg, paths=[".nonexistent"])
            assert ret == 0


class TestApplyExternalsStageMocked(unittest.TestCase):
    """apply_externals_stage with mocked ExternalsEngine."""

    def _run_stage(self, src, tgt, fetch_commit="abc123"):
        _write_externals_toml(src, """
[".fzf"]
url = "https://example.com/fzf.git"
revision = "v1.0.0"
""")
        cfg = _make_cfg(src, tgt)

        mock_fetch = MagicMock()
        mock_fetch.path = ".fzf"
        mock_fetch.commit_sha = fetch_commit
        mock_fetch.fetched = True
        mock_fetch.cache_dir = Path(src) / ".cache" / "externals" / ".fzf"

        mock_apply = MagicMock()
        mock_apply.copied = 3
        mock_apply.skipped = 1

        with patch(
            "pyishlib.ishfiles.commands.external.ExternalsEngine"
        ) as MockEngine:
            engine_instance = MockEngine.return_value
            engine_instance.fetch.return_value = mock_fetch
            engine_instance.apply.return_value = mock_apply
            ret = apply_externals_stage(cfg)

        return ret, cfg

    def test_returns_zero_on_success(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            ret, _ = self._run_stage(src, tgt)
            assert ret == 0

    def test_seeds_context_after_apply(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            _, cfg = self._run_stage(src, tgt, fetch_commit="deadbeef")
            ctx = cfg.context.as_dict()
            assert ctx.get("ext_fzf_revision") == "v1.0.0"
            assert ctx.get("ext_fzf_commit_sha") == "deadbeef"

    def test_path_filter_restricts_which_specs_are_processed(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            _write_externals_toml(src, """
[".fzf"]
url = "https://example.com/fzf.git"
revision = "v1.0.0"

[".pyenv"]
url = "https://example.com/pyenv.git"
revision = "v2.0.0"
""")
            cfg = _make_cfg(src, tgt)

            with patch(
                "pyishlib.ishfiles.commands.external.ExternalsEngine"
            ) as MockEngine:
                engine_instance = MockEngine.return_value
                mock_fetch = MagicMock()
                mock_fetch.commit_sha = "abc"
                engine_instance.fetch.return_value = mock_fetch
                engine_instance.apply.return_value = MagicMock(copied=0, skipped=0)
                apply_externals_stage(cfg, paths=[".fzf"])
                # Only one fetch call (for .fzf)
                assert engine_instance.fetch.call_count == 1

    def test_fetch_error_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            _write_externals_toml(src, """
[".fzf"]
url = "https://example.com/fzf.git"
revision = "v1.0.0"
""")
            cfg = _make_cfg(src, tgt)

            with patch(
                "pyishlib.ishfiles.commands.external.ExternalsEngine"
            ) as MockEngine:
                engine_instance = MockEngine.return_value
                engine_instance.fetch.side_effect = RuntimeError("network down")
                ret = apply_externals_stage(cfg)

            assert ret == 1


class TestRunUpdateYes(unittest.TestCase):
    """external update --yes rewrites revision and re-fetches."""

    def test_update_yes_rewrites_and_fetches(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            _write_externals_toml(src, """
[".fzf"]
url = "https://example.com/fzf.git"
revision = "v0.62.0"
""")
            cfg = _make_cfg(src, tgt)
            # Simulate CLI flag
            cfg.set_default("paths", [])
            cfg.set_default("update_yes", True)
            cfg.set_default("include_prereleases", False)

            from pyishlib.ishfiles.commands.external import run_update

            with patch(
                "pyishlib.ishfiles.commands.external.ExternalsEngine"
            ) as MockEngine:
                engine_instance = MockEngine.return_value

                from pyishlib.ishfiles.externals import UpdateCandidate
                engine_instance.check_update.return_value = UpdateCandidate(
                    path=".fzf",
                    current_rev="v0.62.0",
                    latest_tag="v0.99.0",
                )
                engine_instance.fetch.return_value = MagicMock(commit_sha="new_sha")

                ret = run_update(cfg)

            assert ret == 0
            engine_instance.rewrite_revision.assert_called_once()
            engine_instance.fetch.assert_called_once()

    def test_update_no_answer_leaves_config_unchanged(self):
        with tempfile.TemporaryDirectory() as src, \
             tempfile.TemporaryDirectory() as tgt:
            _write_externals_toml(src, """
[".fzf"]
url = "https://example.com/fzf.git"
revision = "v0.62.0"
""")
            cfg = _make_cfg(src, tgt)
            cfg.set_default("paths", [])
            cfg.set_default("update_yes", False)
            cfg.set_default("include_prereleases", False)

            from pyishlib.ishfiles.commands.external import run_update

            with patch(
                "pyishlib.ishfiles.commands.external.ExternalsEngine"
            ) as MockEngine, patch(
                "pyishlib.ishfiles.commands.external.prompt_yes_no_always"
            ) as mock_prompt:
                engine_instance = MockEngine.return_value

                from pyishlib.ishfiles.externals import UpdateCandidate

                no_response = MagicMock()
                no_response.yes = False
                no_response.always = False
                mock_prompt.return_value = no_response

                engine_instance.check_update.return_value = UpdateCandidate(
                    path=".fzf",
                    current_rev="v0.62.0",
                    latest_tag="v0.99.0",
                )

                run_update(cfg)

            engine_instance.rewrite_revision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
