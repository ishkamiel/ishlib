# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.ishfiles.default_shell` (apply Phase 6)."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles import default_shell as ds  # noqa: E402
from pyishlib.userio import Choice  # noqa: E402

# Phase 6 (default_shell) is a POSIX-only feature: the production code
# returns early via ``is_windows()`` and never touches chsh, /etc/shells,
# or /etc/passwd on Windows.  These tests mock ``is_windows()`` to False
# and exercise POSIX path behaviour (absolute-path detection, parent-dir
# stringification against ``_SAFE_DIRS``), which behaves differently on
# WindowsPath.  Skip the whole module on Windows rather than building a
# cross-platform harness for code that never runs there.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="default_shell stage is a no-op on Windows (see is_windows() guard)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_cfg(
    *,
    default_shell=None,
    dry_run=False,
    quiet=False,
    yes=False,
    custom_username=None,
):
    opts = {
        "default_shell": default_shell,
        "yes": yes,
        "custom_username": custom_username,
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


def _enter_all(stack, *cms):
    """Enter every context manager in *cms* via *stack*.

    Returns the list of enter results.  Used instead of the
    parenthesized multi-with syntax (Python 3.10+) so tests remain
    compatible with Python 3.8-3.9 CI.
    """
    return [stack.enter_context(cm) for cm in cms]


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
        with ExitStack() as stack:
            _, runner_cls = _enter_all(
                stack,
                patch.object(ds, "is_windows", return_value=True),
                patch.object(ds, "CommandRunner"),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Already matches -> skip
# ---------------------------------------------------------------------------


class TestAlreadyMatching(unittest.TestCase):
    def _run_already_matches(self, desired, current):
        cfg = _make_cfg(default_shell=desired)
        with ExitStack() as stack:
            _, _, runner_cls = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value=current),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(ds, "CommandRunner"),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_already_matching_basename(self):
        self._run_already_matches(desired="zsh", current="/bin/zsh")

    def test_already_matching_absolute(self):
        self._run_already_matches(desired="/usr/bin/zsh", current="/usr/bin/zsh")

    def test_already_matching_basename_cross_dir(self):
        # Configured bare name, current is /usr/local/bin/zsh -- still matches.
        self._run_already_matches(desired="zsh", current="/usr/local/bin/zsh")


# ---------------------------------------------------------------------------
# Resolution + execution
# ---------------------------------------------------------------------------


class TestExecution(unittest.TestCase):
    def test_bare_name_resolved(self):
        cfg = _make_cfg(default_shell="zsh")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _, _, sh_mock, _, _ = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(ds, "shutil"),
                patch.object(ds, "CommandRunner", return_value=runner),
                patch.object(ds, "_read_etc_shells", return_value=[]),
            )
            sh_mock.which.return_value = "/usr/bin/zsh"
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh"], check=False, quiet=False
            )

    def test_absolute_safe_no_prompt(self):
        cfg = _make_cfg(default_shell="/usr/bin/fish")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _, _, _, _, prompt_mock, _ = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "prompt_yes_no_always"),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            prompt_mock.assert_not_called()
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/fish"], check=False, quiet=False
            )

    def test_etc_shells_whitelist(self):
        # Non-standard dir but listed in /etc/shells -> no prompt.
        cfg = _make_cfg(default_shell="/opt/mystuff/bin/zsh")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _, _, _, _, prompt_mock, _ = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(
                    ds, "_read_etc_shells", return_value=["/opt/mystuff/bin/zsh"]
                ),
                patch.object(ds, "prompt_yes_no_always"),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
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
        with ExitStack() as stack:
            _, _, _, _, prompt_mock, _ = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "prompt_yes_no_always", return_value=Choice.YES),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            prompt_mock.assert_called_once()
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/home/u/.nix/bin/zsh"], check=False, quiet=False
            )

    def test_fishy_path_prompt_no(self):
        cfg = _make_cfg(default_shell="/home/u/.nix/bin/zsh")
        runner = MagicMock()
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "prompt_yes_no_always", return_value=Choice.NO),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_not_called()

    def test_yes_mode_skips_prompt(self):
        cfg = _make_cfg(default_shell="/home/u/.nix/bin/zsh", yes=True)
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _, _, _, _, prompt_mock, _ = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "prompt_yes_no_always"),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
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
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(ds.shutil, "which", return_value=None),
                patch.object(ds, "CommandRunner", runner_cls),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_absolute_missing_binary_is_noop(self):
        cfg = _make_cfg(default_shell="/nonexistent/bin/zsh")
        runner_cls = MagicMock()
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=False),
                patch.object(ds, "CommandRunner", runner_cls),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner_cls.assert_not_called()

    def test_missing_chsh_binary(self):
        cfg = _make_cfg(default_shell="/usr/bin/zsh")
        runner = MagicMock()
        runner.run.side_effect = FileNotFoundError("chsh: not found")
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
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
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh"], check=False, quiet=False
            )

    def test_quiet_propagates_to_runner(self):
        cfg = _make_cfg(default_shell="/usr/bin/zsh", quiet=True)
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh"], check=False, quiet=True
            )

    def test_absolute_missing_path_log_message(self):
        # Absolute path that doesn't exist -> log should say "does not exist".
        cfg = _make_cfg(default_shell="/nonexistent/bin/zsh")
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=False),
            )
            with self.assertLogs(
                "pyishlib.ishfiles.default_shell", level="INFO"
            ) as cm:
                self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
        self.assertTrue(
            any("does not exist" in m for m in cm.output),
            f"expected 'does not exist' log, got {cm.output}",
        )

    def test_bare_name_missing_log_message(self):
        # Bare name that which() can't find -> log should say "not found on PATH".
        cfg = _make_cfg(default_shell="notashell")
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(ds.shutil, "which", return_value=None),
            )
            with self.assertLogs(
                "pyishlib.ishfiles.default_shell", level="INFO"
            ) as cm:
                self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
        self.assertTrue(
            any("not found on PATH" in m for m in cm.output),
            f"expected 'not found on PATH' log, got {cm.output}",
        )

    def test_chsh_fails(self):
        cfg = _make_cfg(default_shell="/usr/bin/zsh")
        runner = MagicMock()
        runner.run.return_value = _fail_completed(rc=1)
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
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
        with patch.object(ds, "_read_etc_shells", return_value=["/weird/path/zsh"]):
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
            self.assertEqual(ds._resolve_target_shell("zsh"), Path("/usr/bin/zsh"))

    def test_resolve_target_shell_bare_name_missing(self):
        with patch.object(ds.shutil, "which", return_value=None):
            self.assertIsNone(ds._resolve_target_shell("nope"))

    def test_resolve_target_shell_empty(self):
        self.assertIsNone(ds._resolve_target_shell(""))
        self.assertIsNone(ds._resolve_target_shell("   "))


# ---------------------------------------------------------------------------
# --custom-username flag
# ---------------------------------------------------------------------------


class TestCustomUsername(unittest.TestCase):
    def test_current_login_shell_by_name(self):
        """_current_login_shell passes username to getpwnam, not getpwuid."""
        import pwd

        fake_entry = pwd.struct_passwd(
            ("alice", "x", 1001, 1001, "", "/home/alice", "/usr/bin/zsh")
        )
        with patch.object(pwd, "getpwnam", return_value=fake_entry) as mock_getpwnam:
            with patch.object(pwd, "getpwuid") as mock_getpwuid:
                result = ds._current_login_shell("alice")
        mock_getpwnam.assert_called_once_with("alice")
        mock_getpwuid.assert_not_called()
        self.assertEqual(result, "/usr/bin/zsh")

    def test_current_login_shell_by_uid_when_no_username(self):
        """_current_login_shell falls back to getpwuid when username is None."""
        import pwd

        fake_entry = pwd.struct_passwd(
            ("root", "x", 0, 0, "", "/root", "/bin/bash")
        )
        with patch.object(pwd, "getpwuid", return_value=fake_entry) as mock_getpwuid:
            with patch.object(pwd, "getpwnam") as mock_getpwnam:
                result = ds._current_login_shell()
        mock_getpwuid.assert_called_once()
        mock_getpwnam.assert_not_called()
        self.assertEqual(result, "/bin/bash")

    def test_chsh_includes_username_flag(self):
        """chsh is called with -u <username> when custom_username is set."""
        cfg = _make_cfg(default_shell="/usr/bin/zsh", custom_username="alice")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh", "alice"],
                check=False,
                quiet=False,
            )

    def test_chsh_no_username_flag_by_default(self):
        """chsh is called WITHOUT -u when no custom_username is configured."""
        cfg = _make_cfg(default_shell="/usr/bin/zsh")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            self.assertEqual(ds.apply_default_shell_stage(cfg), 0)
            runner.run.assert_called_once_with(
                ["chsh", "-s", "/usr/bin/zsh"],
                check=False,
                quiet=False,
            )

    def test_current_login_shell_passed_username(self):
        """apply_default_shell_stage passes custom_username to _current_login_shell."""
        cfg = _make_cfg(default_shell="/usr/bin/zsh", custom_username="alice")
        runner = MagicMock()
        runner.run.return_value = _ok_completed()
        with ExitStack() as stack:
            shell_mock, _, _, _, _ = _enter_all(
                stack,
                patch.object(ds, "_current_login_shell", return_value="/bin/bash"),
                patch.object(ds, "is_windows", return_value=False),
                patch.object(Path, "exists", return_value=True),
                patch.object(ds, "_read_etc_shells", return_value=[]),
                patch.object(ds, "CommandRunner", return_value=runner),
            )
            ds.apply_default_shell_stage(cfg)
            shell_mock.assert_called_once_with("alice")


if __name__ == "__main__":
    unittest.main()
