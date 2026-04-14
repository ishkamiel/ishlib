#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for :mod:`pyishlib.ishfiles.default_shell` (apply Phase 6)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles import default_shell as ds  # noqa: E402
from pyishlib.userio import Choice  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cfg(
    *,
    default_shell=None,
    dry_run=False,
    quiet=False,
    yes=False,
):
    opts = {
        "default_shell": default_shell,
        "yes": yes,
    }
    return SimpleNamespace(
        dry_run=dry_run,
        quiet=quiet,
        verbose=False,
        get_opt=lambda name, default=None: opts.get(name, default),
    )


def _ok_completed(args=None):
    return subprocess.CompletedProcess(
        args=args or ["chsh"], returncode=0, stdout=b"", stderr=b""
    )


def _fail_completed(rc=1):
    return subprocess.CompletedProcess(
        args=["chsh"], returncode=rc, stdout=b"", stderr=b""
    )


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------


class TestNoOps(unittest.TestCase):
    def test_unset_is_noop(self):
        cfg = _make_cfg(default_shell=None)
        with patch.object(ds, "CommandRunner") as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_empty_string_is_noop(self):
        cfg = _make_cfg(default_shell="")
        with patch.object(ds, "CommandRunner") as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_whitespace_string_is_noop(self):
        cfg = _make_cfg(default_shell="   ")
        with patch.object(ds, "CommandRunner") as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_windows_noop(self):
        cfg = _make_cfg(default_shell="zsh")
        with patch.object(ds, "is_windows", return_value=True), patch.object(
            ds, "CommandRunner"
        ) as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Already matches -> skip
# ---------------------------------------------------------------------------


class TestAlreadyMatching(unittest.TestCase):
    def test_already_matching_basename(self):
        cfg = _make_cfg(default_shell="zsh")
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/zsh"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            ds, "CommandRunner"
        ) as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_already_matching_absolute(self):
        cfg = _make_cfg(default_shell="/usr/bin/zsh")
        with patch.object(
            ds, "_current_login_shell", return_value="/usr/bin/zsh"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            ds, "CommandRunner"
        ) as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_already_matching_basename_cross_dir(self):
        # Configured bare name, current is /usr/local/bin/zsh -- still matches.
        cfg = _make_cfg(default_shell="zsh")
        with patch.object(
            ds, "_current_login_shell", return_value="/usr/local/bin/zsh"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            ds, "CommandRunner"
        ) as runner_cls:
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Resolution + execution
# ---------------------------------------------------------------------------


class TestExecution(unittest.TestCase):
    def test_bare_name_resolved(self):
        cfg = _make_cfg(default_shell="zsh")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            ds, "shutil"
        ) as sh_mock, patch.object(
            ds, "CommandRunner", return_value=runner
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ):
            sh_mock.which.return_value = "/usr/bin/zsh"
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh"], check=False
            )

    def test_absolute_safe_no_prompt(self):
        cfg = _make_cfg(default_shell="/usr/bin/fish")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "prompt_yes_no_always"
        ) as prompt_mock, patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            prompt_mock.assert_not_called()
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/fish"], check=False
            )

    def test_etc_shells_whitelist(self):
        # Non-standard dir but listed in /etc/shells -> no prompt.
        cfg = _make_cfg(default_shell="/opt/mystuff/bin/zsh")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=["/opt/mystuff/bin/zsh"]
        ), patch.object(
            ds, "prompt_yes_no_always"
        ) as prompt_mock, patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            prompt_mock.assert_not_called()
            runner.run.assert_called_once()


# ---------------------------------------------------------------------------
# Fishy-path confirmation flow
# ---------------------------------------------------------------------------


class TestFishyPathPrompt(unittest.TestCase):
    def test_fishy_path_prompt_yes(self):
        cfg = _make_cfg(default_shell="/home/u/.nix/bin/zsh")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "prompt_yes_no_always", return_value=Choice.YES
        ) as prompt_mock, patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            prompt_mock.assert_called_once()
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/home/u/.nix/bin/zsh"], check=False
            )

    def test_fishy_path_prompt_no(self):
        cfg = _make_cfg(default_shell="/home/u/.nix/bin/zsh")
        runner = MagicMock()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "prompt_yes_no_always", return_value=Choice.NO
        ), patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_not_called()

    def test_yes_mode_skips_prompt(self):
        cfg = _make_cfg(default_shell="/home/u/.nix/bin/zsh", yes=True)
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "prompt_yes_no_always"
        ) as prompt_mock, patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            prompt_mock.assert_not_called()
            runner.run.assert_called_once()


# ---------------------------------------------------------------------------
# Missing binary / missing chsh
# ---------------------------------------------------------------------------


class TestMissingBinaries(unittest.TestCase):
    def test_missing_binary_is_noop(self):
        # which() returns None and the name isn't absolute either.
        cfg = _make_cfg(default_shell="notashell")
        runner_cls = MagicMock()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            ds.shutil, "which", return_value=None
        ), patch.object(
            ds, "CommandRunner", runner_cls
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_absolute_missing_binary_is_noop(self):
        cfg = _make_cfg(default_shell="/nonexistent/bin/zsh")
        runner_cls = MagicMock()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=False
        ), patch.object(
            ds, "CommandRunner", runner_cls
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_missing_chsh_binary(self):
        cfg = _make_cfg(default_shell="/usr/bin/zsh")
        runner = MagicMock()
        runner.run.side_effect = FileNotFoundError("chsh: not found")
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)


# ---------------------------------------------------------------------------
# Dry-run and failures
# ---------------------------------------------------------------------------


class TestDryRunAndFailures(unittest.TestCase):
    def test_dry_run(self):
        # CommandRunner itself handles dry-run; we just assert it's called
        # and that rc 0 (the fake dry-run result) propagates.
        cfg = _make_cfg(default_shell="/usr/bin/zsh", dry_run=True)
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh"], check=False
            )

    def test_chsh_fails(self):
        cfg = _make_cfg(default_shell="/usr/bin/zsh")
        runner = MagicMock()
        runner.run.return_value = _fail_completed(rc=1)
        with patch.object(
            ds, "_current_login_shell", return_value="/bin/bash"
        ), patch.object(ds, "is_windows", return_value=False), patch.object(
            Path, "exists", return_value=True
        ), patch.object(
            ds, "_read_etc_shells", return_value=[]
        ), patch.object(
            ds, "CommandRunner", return_value=runner
        ):
            self.assertEqual(ds.apply_default_shell_stage(cfg), 1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    def test_read_etc_shells_missing_returns_empty(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertEqual(ds._read_etc_shells(), [])

    def test_read_etc_shells_strips_comments_and_blanks(self):
        sample = "\n# comment\n/bin/sh\n\n/bin/zsh  \n"
        with patch.object(Path, "read_text", return_value=sample):
            self.assertEqual(ds._read_etc_shells(), ["/bin/sh", "/bin/zsh"])

    def test_is_safe_location_standard_dir(self):
        with patch.object(ds, "_read_etc_shells", return_value=[]):
            self.assertTrue(ds._is_safe_location(Path("/usr/bin/zsh")))
            self.assertTrue(ds._is_safe_location(Path("/bin/sh")))
            self.assertTrue(ds._is_safe_location(Path("/opt/homebrew/bin/fish")))

    def test_is_safe_location_etc_shells(self):
        with patch.object(
            ds, "_read_etc_shells", return_value=["/weird/path/zsh"]
        ):
            self.assertTrue(ds._is_safe_location(Path("/weird/path/zsh")))

    def test_is_safe_location_fishy(self):
        with patch.object(ds, "_read_etc_shells", return_value=[]):
            self.assertFalse(ds._is_safe_location(Path("/home/u/.nix/bin/zsh")))
            self.assertFalse(ds._is_safe_location(Path("/tmp/zsh")))

    def test_resolve_target_shell_absolute_exists(self):
        with patch.object(Path, "exists", return_value=True):
            result = ds._resolve_target_shell("/usr/bin/zsh")
            self.assertEqual(result, Path("/usr/bin/zsh"))

    def test_resolve_target_shell_absolute_missing(self):
        with patch.object(Path, "exists", return_value=False):
            self.assertIsNone(ds._resolve_target_shell("/nope/zsh"))

    def test_resolve_target_shell_bare_name(self):
        with patch.object(ds.shutil, "which", return_value="/usr/bin/zsh"):
            self.assertEqual(
                ds._resolve_target_shell("zsh"), Path("/usr/bin/zsh")
            )

    def test_resolve_target_shell_bare_name_missing(self):
        with patch.object(ds.shutil, "which", return_value=None):
            self.assertIsNone(ds._resolve_target_shell("nope"))

    def test_resolve_target_shell_empty(self):
        self.assertIsNone(ds._resolve_target_shell(""))
        self.assertIsNone(ds._resolve_target_shell("   "))


if __name__ == "__main__":
    unittest.main()
