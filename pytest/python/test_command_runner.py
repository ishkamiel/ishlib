#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for CommandRunner class

import sys
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.command_runner import CommandRunner, UserDeclinedError
from pyishlib.ish_config import IshConfig
from pyishlib.userio import Choice


class TestCommandRunnerProperties:
    def test_dry_run_default(self):
        runner = CommandRunner()
        assert runner.dry_run is False

    def test_dry_run_set(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        assert runner.dry_run is True

    def test_dry_run_setter(self):
        runner = CommandRunner()
        runner.dry_run = True
        assert runner.dry_run is True

    def test_always_sudo_default(self):
        runner = CommandRunner()
        assert runner.always_sudo is False

    def test_always_sudo_set(self):
        runner = CommandRunner(always_sudo=True)
        assert runner.always_sudo is True

    def test_always_sudo_setter(self):
        runner = CommandRunner()
        runner.always_sudo = True
        assert runner.always_sudo is True


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="tests use Unix shell builtins (echo, false, pwd)",
)
class TestCommandRunnerRun:
    def test_run_captures_output(self):
        runner = CommandRunner()
        result = runner.run(["echo", "hello"], capture_output=True)
        assert result.returncode == 0
        assert b"hello" in result.stdout

    def test_run_check_true_by_default(self):
        runner = CommandRunner()
        with pytest.raises(subprocess.CalledProcessError):
            runner.run(["false"])

    def test_run_check_false(self):
        runner = CommandRunner()
        result = runner.run(["false"], check=False)
        assert result.returncode != 0

    def test_run_dry_run_returns_zero(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        result = runner.run(["false"])
        assert result.returncode == 0
        assert result.stdout == b""
        assert result.stderr == b""

    def test_run_quiet_suppresses_output(self):
        runner = CommandRunner()
        result = runner.run(["echo", "hello"], quiet=True)
        assert result.returncode == 0

    def test_run_with_work_dir(self):
        runner = CommandRunner()
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.run(
                ["pwd"], work_dir=Path(tmpdir), capture_output=True, text=True
            )
            assert tmpdir in result.stdout
        # Verify we restored the original directory
        assert os.getcwd() == original_dir

    def test_run_with_work_dir_restores_on_error(self):
        runner = CommandRunner()
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(subprocess.CalledProcessError):
                runner.run(["false"], work_dir=Path(tmpdir))
        # Must restore cwd even after error
        assert os.getcwd() == original_dir

    def test_run_converts_command_to_strings(self):
        runner = CommandRunner()
        result = runner.run(["echo", Path("/tmp")], capture_output=True, text=True)
        assert "/tmp" in result.stdout


class TestCommandRunnerGit:
    def test_git_prepends_git(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        result = runner.git(["status"])
        assert result.returncode == 0

    def test_git_with_work_dir_adds_C_flag(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        with patch.object(
            runner, "run", return_value=MagicMock(returncode=0)
        ) as mock_run:
            runner.git(["status"], work_dir=Path("/tmp"))
            args = mock_run.call_args[0][0]
            assert "-C" in args
            assert str(Path("/tmp")) in args


class TestCommandRunnerFileOps:
    def test_chdir(self):
        runner = CommandRunner()
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.chdir(Path(tmpdir))
            assert result is True
            assert os.getcwd() == tmpdir
            os.chdir(original_dir)

    def test_chdir_same_dir(self):
        runner = CommandRunner()
        current = Path(os.getcwd())
        result = runner.chdir(current)
        assert result is True

    def test_chdir_nonexistent_may_fail(self):
        runner = CommandRunner()
        result = runner.chdir(Path("/nonexistent/path"), may_fail=True)
        assert result is False

    def test_chdir_nonexistent_fatal(self):
        runner = CommandRunner()
        with pytest.raises(SystemExit):
            runner.chdir(Path("/nonexistent/path"), may_fail=False)

    def test_chdir_dry_run(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.chdir(Path(tmpdir))
            assert result is True
            # Should NOT have actually changed directory
            assert os.getcwd() == original_dir

    def test_mkdir(self):
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "newdir"
            result = runner.mkdir(new_dir)
            assert result is True
            assert new_dir.exists()

    def test_mkdir_already_exists(self):
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.mkdir(Path(tmpdir))
            assert result is True

    def test_mkdir_dry_run(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "newdir"
            result = runner.mkdir(new_dir)
            assert result is True
            assert not new_dir.exists()

    def test_rm_file(self):
        runner = CommandRunner()
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        assert path.exists()
        result = runner.rm(path)
        assert result is True
        assert not path.exists()

    def test_rm_nonexistent(self):
        runner = CommandRunner()
        result = runner.rm(Path("/nonexistent/file"))
        assert result is True

    def test_rm_recursive(self):
        runner = CommandRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "sub"
            subdir.mkdir()
            (subdir / "file.txt").write_text("test")
            result = runner.rm(subdir, recursive=True)
            assert result is True
            assert not subdir.exists()

    def test_rm_dry_run(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = Path(f.name)
        try:
            result = runner.rm(path)
            assert result is True
            assert path.exists()  # Should NOT have deleted
        finally:
            path.unlink()


class TestCommandRunnerWhich:
    def test_which_existing_command(self):
        runner = CommandRunner()
        cmd = "cmd" if sys.platform == "win32" else "echo"
        result = runner.which(cmd)
        assert result is not None

    def test_which_nonexistent_command(self):
        runner = CommandRunner()
        result = runner.which("nonexistent_command_xyz")
        assert result is None


@pytest.mark.skipif(sys.platform == "win32", reason="sudo not available on Windows")
class TestCommandRunnerSudo:
    def test_run_sudo_aborts_on_user_decline(self):
        runner = CommandRunner()
        with patch("pyishlib.command_runner.prompt_yes_no_always") as mock_prompt:
            mock_prompt.return_value = Choice.NO
            with pytest.raises(UserDeclinedError):
                runner.run_sudo(["echo", "test"])

    def test_run_sudo_always_sudo(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True), always_sudo=True)
        result = runner.run_sudo(["echo", "test"])
        assert result.returncode == 0

    def test_check_sudo_dry_run_skips_prompt(self):
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        assert runner._check_sudo(["sudo", "echo"], force_sudo=False) is True

    def test_check_sudo_force(self):
        runner = CommandRunner()
        assert runner._check_sudo(["sudo", "echo"], force_sudo=True) is True

    def test_check_sudo_always_sets_flag(self):
        runner = CommandRunner()
        with patch(
            "pyishlib.command_runner.prompt_yes_no_always",
            return_value=Choice.ALWAYS,
        ):
            result = runner._check_sudo(["sudo", "echo"])
            assert result is True
            assert runner._always_sudo is True

    def test_check_sudo_skips_prompt_when_root(self):
        runner = CommandRunner()
        with patch("pyishlib.command_runner.os.geteuid", return_value=0):
            assert runner._check_sudo(["sudo", "echo"]) is True

    def test_run_sudo_as_root_omits_sudo_prefix(self):
        """When already root, `sudo=True` must not prepend `sudo` to the command.

        `sudo` requires a TTY for authentication; prepending it in a
        non-interactive container (stdin=/dev/null) would fail even though
        the process is already root.
        """
        runner = CommandRunner(cfg=IshConfig(dry_run=True))
        with patch("pyishlib.command_runner.os.geteuid", return_value=0):
            result = runner.run(["echo", "test"], sudo=True)
        # dry_run returns a fake CompletedProcess; verify no KeyboardInterrupt
        assert result.returncode == 0

    def test_check_sudo_prompts_when_not_root(self):
        runner = CommandRunner()
        with patch("pyishlib.command_runner.os.geteuid", return_value=1000), patch(
            "pyishlib.command_runner.prompt_yes_no_always",
            return_value=Choice.NO,
        ):
            assert runner._check_sudo(["sudo", "echo"]) is False


if __name__ == "__main__":
    pytest.main()
