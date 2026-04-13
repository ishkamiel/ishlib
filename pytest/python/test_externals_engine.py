#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for ishfiles.externals (engine — offline helpers and mocked git ops)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.externals import (
    ExternalsEngine,
    FetchResult,
    ApplyResult,
    copy_tree_nondestructive,
    _parse_remote_tags,
    _pick_latest_tag,
    _tag_tuple,
    _tree_hash,
)
from pyishlib.ishfiles.externals_config import ExternalSpec
from pyishlib.ishfiles.externals_state import ExternalsState
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig


def _make_cfg(source: str, target: str) -> SimpleNamespace:
    return SimpleNamespace(
        dry_run=False,
        get_opt=lambda name, default=None: {
            "source": source,
            "target": target,
            "externals_cache_dir": str(Path(source) / ".cache" / "externals"),
            "externals_state_filename": "externals-state.json",
        }.get(name, default),
    )


def _make_spec(path=".fzf", url="https://example.com/fzf.git", revision="v1.0.0", **kw):
    return ExternalSpec(path=path, url=url, revision=revision, **kw)


def _make_runner(dry_run=False):
    ish_cfg = IshConfig()
    ish_cfg.dry_run = dry_run
    return CommandRunner(cfg=ish_cfg)


# ---------------------------------------------------------------------------
# copy_tree_nondestructive
# ---------------------------------------------------------------------------


class TestCopyTreeNondestructive(unittest.TestCase):
    def _setup_src(self, tmp: str) -> Path:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "file1.txt").write_text("hello", encoding="utf-8")
        subdir = src / "sub"
        subdir.mkdir()
        (subdir / "file2.txt").write_text("world", encoding="utf-8")
        return src

    def test_copies_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._setup_src(tmp)
            dst = Path(tmp) / "dst"
            runner = _make_runner()
            result = copy_tree_nondestructive(src, dst, runner)
            assert (dst / "file1.txt").read_text() == "hello"
            assert (dst / "sub" / "file2.txt").read_text() == "world"
            assert result.copied == 2
            assert result.skipped == 0

    def test_leaves_extra_files_in_dst(self):
        """Non-destructive: extra files in dst must survive."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._setup_src(tmp)
            dst = Path(tmp) / "dst"
            dst.mkdir()
            extra = dst / "extra.txt"
            extra.write_text("do not delete", encoding="utf-8")

            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner)

            assert extra.exists()
            assert extra.read_text() == "do not delete"

    def test_idempotent_second_run(self):
        """Re-running should skip all files (hash match)."""
        with tempfile.TemporaryDirectory() as tmp:
            src = self._setup_src(tmp)
            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner)
            result2 = copy_tree_nondestructive(src, dst, runner)
            assert result2.copied == 0
            assert result2.skipped == 2

    def test_git_dir_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            git_dir = src / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
            (src / "real.txt").write_text("keep", encoding="utf-8")

            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner)

            assert not (dst / ".git").exists()
            assert (dst / "real.txt").exists()

    def test_exclude_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "keep.txt").write_text("yes", encoding="utf-8")
            (src / "ignore.md").write_text("no", encoding="utf-8")

            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner, exclude=["*.md"])

            assert (dst / "keep.txt").exists()
            assert not (dst / "ignore.md").exists()

    def test_include_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "main.py").write_text("code", encoding="utf-8")
            (src / "README.md").write_text("docs", encoding="utf-8")

            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner, include=["*.py"])

            assert (dst / "main.py").exists()
            assert not (dst / "README.md").exists()

    def test_pyc_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "module.py").write_text("x = 1", encoding="utf-8")
            (src / "module.pyc").write_bytes(b"\x00compiled")

            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner)

            assert (dst / "module.py").exists()
            assert not (dst / "module.pyc").exists()

    def test_nonexistent_src_returns_empty_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "dst"
            runner = _make_runner()
            with self.assertLogs(level="WARNING"):
                result = copy_tree_nondestructive(Path(tmp) / "missing", dst, runner)
            assert result.copied == 0

    def test_symlink_recreated(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            target_file = src / "real.txt"
            target_file.write_text("data", encoding="utf-8")
            link = src / "link.txt"
            os.symlink("real.txt", link)

            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner)

            assert (dst / "link.txt").is_symlink()
            assert os.readlink(dst / "link.txt") == "real.txt"

    def test_symlink_skipped_if_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            src.mkdir()
            (src / "real.txt").write_text("data", encoding="utf-8")
            os.symlink("real.txt", src / "link.txt")

            dst = Path(tmp) / "dst"
            runner = _make_runner()
            copy_tree_nondestructive(src, dst, runner)  # first run
            result2 = copy_tree_nondestructive(src, dst, runner)  # second
            # The symlink should be skipped on second run
            assert result2.skipped >= 1


# ---------------------------------------------------------------------------
# _pick_latest_tag / _tag_tuple
# ---------------------------------------------------------------------------


class TestPickLatestTag(unittest.TestCase):
    def test_empty_returns_none(self):
        assert _pick_latest_tag([]) is None

    def test_single_tag(self):
        assert _pick_latest_tag(["v1.0.0"]) == "v1.0.0"

    def test_semver_sort(self):
        tags = ["v1.0.0", "v1.2.0", "v0.9.0", "v1.10.0"]
        assert _pick_latest_tag(tags) == "v1.10.0"

    def test_no_leading_v(self):
        tags = ["0.9.0", "1.0.0", "0.10.0"]
        assert _pick_latest_tag(tags) == "1.0.0"

    def test_prerelease_filter_in_parse_remote_tags(self):
        """_pick_latest_tag works on pre-filtered lists."""
        # After filtering pre-releases, the latest stable should win.
        tags = ["v1.0.0", "v1.1.0"]
        assert _pick_latest_tag(tags) == "v1.1.0"


class TestTagTuple(unittest.TestCase):
    def test_basic(self):
        assert _tag_tuple("v1.2.3") == ((0, 1), (0, 2), (0, 3))

    def test_no_v(self):
        assert _tag_tuple("2.0") == ((0, 2), (0, 0))

    def test_extra_string_part_makes_longer_tuple(self):
        # v1.0.0-rc1 has an extra segment; note pre-release filtering in
        # check_update means the tuple ordering for rc tags is handled by
        # excluding them before comparison, not by tuple comparison alone.
        t_release = _tag_tuple("v1.0.0")
        t_rc = _tag_tuple("v1.0.0-rc1")
        # Both start with the same numeric prefix
        assert t_release[:3] == t_rc[:3]
        # The rc version has an extra component
        assert len(t_rc) > len(t_release)


# ---------------------------------------------------------------------------
# _parse_remote_tags
# ---------------------------------------------------------------------------


class TestParseRemoteTags(unittest.TestCase):
    LS_REMOTE_OUTPUT = """\
abc123\trefs/tags/v0.9.0
def456\trefs/tags/v0.9.0^{}
ghi789\trefs/tags/v1.0.0
jkl012\trefs/tags/v1.0.0^{}
mno345\trefs/tags/v1.0.0-rc1
"""

    def test_strips_refs_tags_prefix(self):
        tags = _parse_remote_tags(self.LS_REMOTE_OUTPUT)
        assert "v1.0.0" in tags
        assert "v0.9.0" in tags

    def test_no_annotated_suffix(self):
        tags = _parse_remote_tags(self.LS_REMOTE_OUTPUT)
        assert "v1.0.0^{}" not in tags

    def test_dedup(self):
        tags = _parse_remote_tags(self.LS_REMOTE_OUTPUT)
        assert tags.count("v1.0.0") == 1

    def test_includes_prerelease(self):
        tags = _parse_remote_tags(self.LS_REMOTE_OUTPUT)
        assert "v1.0.0-rc1" in tags

    def test_empty_output(self):
        assert _parse_remote_tags("") == []


# ---------------------------------------------------------------------------
# _tree_hash
# ---------------------------------------------------------------------------


class TestTreeHash(unittest.TestCase):
    def test_stable_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "a.txt").write_text("hello", encoding="utf-8")
            (p / "b.txt").write_text("world", encoding="utf-8")
            h1 = _tree_hash(p)
            h2 = _tree_hash(p)
            assert h1 == h2

    def test_changes_when_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "a.txt").write_text("hello", encoding="utf-8")
            h1 = _tree_hash(p)
            (p / "a.txt").write_text("CHANGED", encoding="utf-8")
            h2 = _tree_hash(p)
            assert h1 != h2


# ---------------------------------------------------------------------------
# rewrite_revision
# ---------------------------------------------------------------------------


class TestRewriteRevision(unittest.TestCase):
    def _make_engine(self, source: str, target: str) -> ExternalsEngine:
        cfg = _make_cfg(source, target)
        runner = _make_runner()
        state = ExternalsState(Path(target) / "state.json")
        return ExternalsEngine(cfg, runner, state)

    def test_updates_matching_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "externals.toml"
            config_path.write_text(
                """
[".fzf"]
url = "https://github.com/junegunn/fzf.git"
revision = "v0.62.0"

[".pyenv"]
url = "https://github.com/pyenv/pyenv.git"
revision = "v2.5.5"
""",
                encoding="utf-8",
            )
            engine = self._make_engine(tmp, tmp)
            spec = _make_spec(path=".fzf", revision="v0.62.0")
            engine.rewrite_revision(spec, "v0.99.0", config_path)

            text = config_path.read_text(encoding="utf-8")
            assert 'revision = "v0.99.0"' in text
            # Pyenv revision unchanged
            assert 'revision = "v2.5.5"' in text

    def test_preserves_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "externals.toml"
            config_path.write_text(
                '# top comment\n[".fzf"]\n# inner comment\nurl = "x"\nrevision = "v1"\n',
                encoding="utf-8",
            )
            engine = self._make_engine(tmp, tmp)
            spec = _make_spec(path=".fzf", revision="v1")
            engine.rewrite_revision(spec, "v2", config_path)
            text = config_path.read_text(encoding="utf-8")
            assert "# top comment" in text
            assert "# inner comment" in text
            assert 'revision = "v2"' in text

    def test_section_not_found_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "externals.toml"
            config_path.write_text(
                '[".other"]\nurl = "x"\nrevision = "v1"\n',
                encoding="utf-8",
            )
            engine = self._make_engine(tmp, tmp)
            spec = _make_spec(path=".fzf", revision="v1")
            with self.assertLogs(level="WARNING"):
                engine.rewrite_revision(spec, "v2", config_path)
            # File unchanged
            assert 'revision = "v1"' in config_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ExternalsEngine.fetch (mocked git ops)
# ---------------------------------------------------------------------------


class TestFetchMocked(unittest.TestCase):
    def _make_engine(self, source: str, target: str):
        cfg = _make_cfg(source, target)
        runner = MagicMock(spec=CommandRunner)
        runner.dry_run = False

        # Simulate rev-parse returning a SHA
        rev_parse_result = MagicMock()
        rev_parse_result.stdout = "abc123def456abc123def456abc123def456abc12\n"

        def git_side_effect(args, **kwargs):
            if args[0] == "rev-parse":
                return rev_parse_result
            return MagicMock(returncode=0, stdout="", stderr="")

        runner.git.side_effect = git_side_effect

        state = ExternalsState(Path(target) / "state.json")
        return ExternalsEngine(cfg, runner, state), runner

    def test_clone_when_cache_missing(self):
        with tempfile.TemporaryDirectory() as tmp_src, \
             tempfile.TemporaryDirectory() as tmp_tgt:
            engine, runner = self._make_engine(tmp_src, tmp_tgt)
            spec = _make_spec()

            # Patch cache_dir to not exist
            cache_dir = Path(tmp_src) / ".cache" / "externals" / ".fzf"
            # cache_dir does not exist — engine should clone

            engine.fetch(spec)

            clone_call = [
                c for c in runner.git.call_args_list
                if c.args[0][0] == "clone"
            ]
            assert len(clone_call) == 1
            assert "--no-checkout" in clone_call[0].args[0]

    def test_no_clone_when_cache_exists(self):
        with tempfile.TemporaryDirectory() as tmp_src, \
             tempfile.TemporaryDirectory() as tmp_tgt:
            engine, runner = self._make_engine(tmp_src, tmp_tgt)
            spec = _make_spec()

            # Create the cache dir so engine thinks it's already cloned.
            cache_dir = Path(tmp_src) / ".cache" / "externals" / ".fzf"
            cache_dir.mkdir(parents=True)

            # State says fresh so no fetch needed (refresh period elapsed check).
            # Inject a fresh record so is_stale returns False for 168h period.
            engine._state.set(spec.path, spec.revision, "sha", spec.url,
                              last_fetched=time.time())

            spec.refresh_period = 168 * 3600  # 168h
            engine.fetch(spec)

            clone_calls = [
                c for c in runner.git.call_args_list
                if c.args[0][0] == "clone"
            ]
            assert len(clone_calls) == 0

    def test_checkout_always_called(self):
        with tempfile.TemporaryDirectory() as tmp_src, \
             tempfile.TemporaryDirectory() as tmp_tgt:
            engine, runner = self._make_engine(tmp_src, tmp_tgt)
            spec = _make_spec()
            cache_dir = Path(tmp_src) / ".cache" / "externals" / ".fzf"
            cache_dir.mkdir(parents=True)

            engine.fetch(spec)

            checkout_calls = [
                c for c in runner.git.call_args_list
                if c.args[0][0] == "checkout"
            ]
            assert len(checkout_calls) == 1
            assert spec.revision in checkout_calls[0].args[0]

    def test_force_bypasses_refresh_period(self):
        with tempfile.TemporaryDirectory() as tmp_src, \
             tempfile.TemporaryDirectory() as tmp_tgt:
            engine, runner = self._make_engine(tmp_src, tmp_tgt)
            spec = _make_spec(refresh_period=168 * 3600)

            cache_dir = Path(tmp_src) / ".cache" / "externals" / ".fzf"
            cache_dir.mkdir(parents=True)
            engine._state.set(spec.path, spec.revision, "sha", spec.url,
                              last_fetched=time.time())

            engine.fetch(spec, force=True)

            fetch_calls = [
                c for c in runner.git.call_args_list
                if c.args[0][0] == "fetch"
            ]
            assert len(fetch_calls) == 1


# ---------------------------------------------------------------------------
# ExternalsEngine.check_update (mocked)
# ---------------------------------------------------------------------------


LS_REMOTE_SAMPLE = """\
abc001\trefs/tags/v0.60.0
abc002\trefs/tags/v0.60.0^{}
abc003\trefs/tags/v0.61.0
abc004\trefs/tags/v0.61.0^{}
abc005\trefs/tags/v0.62.0
abc006\trefs/tags/v0.62.0^{}
abc007\trefs/tags/v0.62.0-rc1
"""


class TestCheckUpdateMocked(unittest.TestCase):
    def _make_engine_with_ls_remote(self, source, target, ls_output, returncode=0):
        cfg = _make_cfg(source, target)
        runner = MagicMock(spec=CommandRunner)
        runner.dry_run = False
        ls_result = MagicMock()
        ls_result.returncode = returncode
        ls_result.stdout = ls_output
        runner.git.return_value = ls_result
        state = ExternalsState(Path(target) / "state.json")
        return ExternalsEngine(cfg, runner, state)

    def test_returns_candidate_when_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine_with_ls_remote(tmp, tmp, LS_REMOTE_SAMPLE)
            spec = _make_spec(revision="v0.60.0")
            candidate = engine.check_update(spec)
            assert candidate is not None
            assert candidate.latest_tag == "v0.62.0"
            assert candidate.current_rev == "v0.60.0"

    def test_returns_none_when_already_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine_with_ls_remote(tmp, tmp, LS_REMOTE_SAMPLE)
            spec = _make_spec(revision="v0.62.0")
            candidate = engine.check_update(spec)
            assert candidate is None

    def test_prereleases_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine_with_ls_remote(tmp, tmp, LS_REMOTE_SAMPLE)
            spec = _make_spec(revision="v0.61.0")
            candidate = engine.check_update(spec)
            assert candidate is not None
            assert "rc" not in candidate.latest_tag

    def test_prereleases_included_when_flag_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Only rc tags available
            ls_output = "abc\trefs/tags/v1.0.0-rc1\n"
            engine = self._make_engine_with_ls_remote(tmp, tmp, ls_output)
            spec = _make_spec(revision="v0.9.0")
            candidate = engine.check_update(spec, include_prereleases=True)
            assert candidate is not None
            assert candidate.latest_tag == "v1.0.0-rc1"

    def test_returns_none_when_ls_remote_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine_with_ls_remote(tmp, tmp, "", returncode=128)
            spec = _make_spec(revision="v0.60.0")
            with self.assertLogs(level="WARNING"):
                candidate = engine.check_update(spec)
            assert candidate is None

    def test_returns_none_when_no_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine_with_ls_remote(tmp, tmp, "")
            spec = _make_spec(revision="v0.60.0")
            candidate = engine.check_update(spec)
            assert candidate is None


if __name__ == "__main__":
    unittest.main()
