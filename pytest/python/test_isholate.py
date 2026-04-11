#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for the isholate tool (CLI and container lifecycle)

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.isholate.cli import build_parser, main as cli_main
from pyishlib.isholate.container import (
    generate_name,
    get_host_user_info,
    launch_and_exec,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_USER = "testuser"
_FAKE_HOME = Path("/home/testuser")
_FAKE_CWD = Path("/work/myproject")
_FAKE_IMAGE = "images:ubuntu/24.04"
_FAKE_SHELL = "/bin/bash"
_FAKE_CONTAINER_UID = 1000


def _fake_user_info():
    return (_FAKE_USER, _FAKE_HOME, _FAKE_CWD)


def _make_args(**overrides):
    """Build a minimal args namespace for launch_and_exec."""
    defaults = {
        "name": "test-container",
        "image": _FAKE_IMAGE,
        "shell": _FAKE_SHELL,
        "ro_home": False,
        "rw_cwd": False,
        "ro_cwd": False,
        "command": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_subprocess_run(cmd, **kwargs):
    """Stand-in for subprocess.run for the 'id -u' lookup call."""
    if "id" in cmd and "-u" in cmd:
        return SimpleNamespace(
            returncode=0, stdout=f"{_FAKE_CONTAINER_UID}\n", stderr=""
        )
    return SimpleNamespace(returncode=0, stdout="", stderr="")


# ---------------------------------------------------------------------------
# generate_name
# ---------------------------------------------------------------------------


class TestGenerateName:
    def test_includes_username(self):
        name = generate_name("alice")
        assert name.startswith("isholate-alice-")

    def test_is_unique(self):
        names = {generate_name("bob") for _ in range(20)}
        assert len(names) > 1

    def test_valid_chars(self):
        name = generate_name("alice")
        # Container names must use only lowercase letters, digits, and hyphens
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name)


# ---------------------------------------------------------------------------
# get_host_user_info
# ---------------------------------------------------------------------------


class TestGetHostUserInfo:
    def test_returns_tuple(self):
        username, home, cwd = get_host_user_info()
        assert isinstance(username, str)
        assert isinstance(home, Path)
        assert isinstance(cwd, Path)


# ---------------------------------------------------------------------------
# launch_and_exec -- command sequence
# ---------------------------------------------------------------------------


class TestLaunchAndExec:
    def _run_with_mocks(self, args, fake_run_returns=None):
        """Run launch_and_exec with _run and subprocess.run mocked.

        Returns (all_calls, returncode).
        """
        side_effects = fake_run_returns or []
        default = SimpleNamespace(returncode=0)

        call_count = [0]

        def fake_run(cmd, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(side_effects):
                return side_effects[idx]
            return default

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.container._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.isholate.container.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    rc = launch_and_exec(args)
                    return mock_run.call_args_list, rc

    def _cmds(self, calls):
        """Extract just the cmd lists from call_args_list."""
        return [c.args[0] for c in calls]

    def test_basic_launch_sequence(self):
        args = _make_args()
        calls, rc = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        # Must create container first (without starting)
        assert ["incus", "init", _FAKE_IMAGE, "test-container"] in cmds

        # Must start the container
        assert ["incus", "start", "test-container"] in cmds

        # Must remove the default ubuntu user
        assert any("userdel" in c for c in cmds)

        # Must create the user
        assert any("useradd" in c for c in cmds)

        # Must stop at the end
        assert any(c[:3] == ["incus", "stop", "test-container"] for c in cmds)

    def test_exec_uses_container_uid(self):
        args = _make_args()
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        uid_idx = exec_cmd.index("--user") + 1
        assert exec_cmd[uid_idx] == str(_FAKE_CONTAINER_UID)

    def test_exec_default_shell(self):
        args = _make_args(command=[])
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        assert exec_cmd[-1] == _FAKE_SHELL

    def test_exec_custom_command(self):
        # No '--' prefix here, so it's passed directly
        args = _make_args(command=["ls", "-la"])
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        assert exec_cmd[-2:] == ["ls", "-la"]

    def test_exec_strips_double_dash_from_remainder(self):
        # argparse.REMAINDER keeps '--'; container.py must strip it so the
        # command ends up as [incus, exec, ..., --, ls, -la], not [... --, --, ls, -la]
        args = _make_args(command=["--", "ls", "-la"])
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        # Only one '--' separator (the incus exec one), not two
        assert exec_cmd.count("--") == 1
        assert exec_cmd[-2:] == ["ls", "-la"]

    def test_no_disk_devices_by_default(self):
        args = _make_args()
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert device_cmds == []

    def test_ro_home_adds_readonly_device(self):
        args = _make_args(ro_home=True)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1
        cmd = device_cmds[0]
        assert f"source={_FAKE_HOME}" in cmd
        assert f"path=/home/{_FAKE_USER}" in cmd
        assert "readonly=true" in cmd
        assert "shift=true" in cmd

    def test_rw_cwd_adds_device_without_readonly(self):
        args = _make_args(rw_cwd=True)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1
        cmd = device_cmds[0]
        assert f"source={_FAKE_CWD}" in cmd
        assert "readonly=true" not in cmd
        assert "shift=true" in cmd

    def test_ro_cwd_adds_readonly_device(self):
        args = _make_args(ro_cwd=True)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1
        cmd = device_cmds[0]
        assert f"source={_FAKE_CWD}" in cmd
        assert "readonly=true" in cmd
        assert "shift=true" in cmd

    def test_ro_home_and_rw_cwd_together(self):
        args = _make_args(ro_home=True, rw_cwd=True)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 2

    def test_stop_called_even_if_exec_raises(self):
        """incus stop must be called in the finally block."""
        import subprocess

        def fake_run(cmd, **kwargs):
            if "--user" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            return SimpleNamespace(returncode=0)

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.container._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.isholate.container.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    with pytest.raises(Exception):
                        launch_and_exec(_make_args())

                    cmds = [c.args[0] for c in mock_run.call_args_list]
                    assert any(
                        c[:3] == ["incus", "stop", "test-container"] for c in cmds
                    )

    def test_auto_generated_name_when_none(self):
        args = _make_args(name=None)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        init_cmd = next(c for c in cmds if c[:2] == ["incus", "init"])
        container_name = init_cmd[3]
        assert container_name.startswith(f"isholate-{_FAKE_USER}-")

    def test_rw_cwd_sets_cwd_as_workdir(self):
        args = _make_args(rw_cwd=True)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        cwd_idx = exec_cmd.index("--cwd") + 1
        assert exec_cmd[cwd_idx] == str(_FAKE_CWD)

    def test_ro_cwd_sets_cwd_as_workdir(self):
        args = _make_args(ro_cwd=True)
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        cwd_idx = exec_cmd.index("--cwd") + 1
        assert exec_cmd[cwd_idx] == str(_FAKE_CWD)

    def test_default_cwd_is_home(self):
        args = _make_args()
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        cwd_idx = exec_cmd.index("--cwd") + 1
        assert exec_cmd[cwd_idx] == f"/home/{_FAKE_USER}"


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


class TestParser:
    def test_defaults(self):
        from pyishlib.isholate.cli import DEFAULT_IMAGE, DEFAULT_SHELL

        parser = build_parser()
        args = parser.parse_args([])
        assert args.image == DEFAULT_IMAGE
        assert args.shell == DEFAULT_SHELL
        assert args.ro_home is False
        assert args.rw_cwd is False
        assert args.ro_cwd is False
        assert args.command == []

    def test_rw_cwd_and_ro_cwd_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--rw-cwd", "--ro-cwd"])

    def test_ro_home_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--ro-home"])
        assert args.ro_home is True

    def test_custom_image(self):
        parser = build_parser()
        args = parser.parse_args(["--image", "images:ubuntu/22.04"])
        assert args.image == "images:ubuntu/22.04"

    def test_command_passthrough(self):
        parser = build_parser()
        args = parser.parse_args(["ls"])
        assert args.command == ["ls"]

    def test_command_passthrough_with_flags(self):
        parser = build_parser()
        # Commands with flags must follow -- to avoid argparse confusion.
        # argparse.REMAINDER keeps the '--' in the list; container.py strips it.
        args = parser.parse_args(["--", "ls", "-la"])
        assert args.command == ["--", "ls", "-la"]

    def test_purge_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--purge"])
        assert args.purge is True

    def test_main_rejects_non_linux(self):
        with patch("sys.platform", "darwin"):
            rc = cli_main([])
        assert rc == 1
