#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

#
# Tests for the isholate tool (CLI and container lifecycle)

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="isholate requires Incus and Linux uid/gid mapping; Linux-only",
)

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.isholate.cli import build_parser, main as cli_main
from pyishlib.isholate.config import (
    discover_host_ishfiles_source,
    discover_project_overlay,
    load_project_config,
)
from pyishlib.isholate.container import (
    generate_name,
    get_host_user_info,
    launch_and_exec,
    purge_containers,
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
        "no_host_ishfiles": False,
        "no_project_overlay": False,
        "verbose": 0,
        "quiet": False,
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
# purge_containers
# ---------------------------------------------------------------------------


class TestPurgeContainers:
    def test_prefix_matches_sanitised_username(self):
        """purge must sanitise the username the same way generate_name does
        so that users like 'john_doe' (name -> 'isholate-john-doe-xxxxxx')
        still match the purge prefix."""
        username = "john_doe"
        # Containers a real run would have created for this user:
        existing = [
            {"name": generate_name(username)},
            {"name": generate_name(username)},
            {"name": "isholate-other-abc123"},  # different user, not purged
        ]
        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(cmd)
            return SimpleNamespace(returncode=0)

        def fake_subprocess_run(cmd, **kwargs):
            # The initial `incus list --format=json` lookup
            import json

            return SimpleNamespace(
                returncode=0, stdout=json.dumps(existing), stderr=""
            )

        with patch(
            "pyishlib.isholate.container._run", side_effect=fake_run
        ):
            with patch(
                "pyishlib.isholate.container.subprocess.run",
                side_effect=fake_subprocess_run,
            ):
                rc = purge_containers(username, quiet=True)

        assert rc == 0
        deleted = [c for c in run_calls if c[:2] == ["incus", "delete"]]
        deleted_names = [c[2] for c in deleted]
        # Both of the user's containers must be deleted; the other user's
        # container must not be touched.
        assert len(deleted) == 2
        for name in deleted_names:
            assert name.startswith("isholate-john-doe-")
            assert "isholate-other-" not in name


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
    def _run_with_mocks(self, args, fake_run_returns=None, **launch_kwargs):
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
                    rc = launch_and_exec(args, **launch_kwargs)
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

    def test_stop_called_even_if_exec_fails(self):
        """incus stop must be called in the finally block even when a step fails."""
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
                    rc = launch_and_exec(_make_args())

                assert rc == 1
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

    def test_progress_messages_on_stderr_by_default(self, capsys):
        args = _make_args()
        self._run_with_mocks(args)
        err = capsys.readouterr().err
        # Must announce each long-running stage so first-run does not
        # appear to hang.
        assert "isholate:" in err
        assert "creating container" in err
        assert "starting container" in err
        assert "creating user" in err

    def test_quiet_suppresses_progress_messages(self, capsys):
        args = _make_args(quiet=True)
        self._run_with_mocks(args)
        err = capsys.readouterr().err
        assert "isholate:" not in err


# ---------------------------------------------------------------------------
# launch_and_exec -- provisioning
# ---------------------------------------------------------------------------


class TestProvisioning:
    """Tests for the ishfiles provisioning step inside the container."""

    def _run_with_mocks(self, args, host_source=None, overlay=None):
        default = SimpleNamespace(returncode=0)

        def fake_run(cmd, **kwargs):
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
                    # host_config_dir.is_dir() is called inside _provision;
                    # patch Path.is_dir to return True for the fake config dir.
                    with patch.object(Path, "is_dir", return_value=True):
                        rc = launch_and_exec(
                            args,
                            host_ishfiles_source=host_source,
                            project_overlay=overlay,
                        )
                        return mock_run.call_args_list, rc

    def _cmds(self, calls):
        return [c.args[0] for c in calls]

    def test_no_provisioning_when_no_sources(self):
        """With neither host source nor overlay, no provisioning calls occur."""
        args = _make_args()
        calls, _ = self._run_with_mocks(args, host_source=None, overlay=None)
        cmds = self._cmds(calls)

        # No mkdir, no apt, no ishfiles apply, no chown for provisioning
        assert not any("/run/isholate" in str(c) for c in cmds)
        assert not any("ishfiles" in str(c) for c in cmds)
        assert not any("chown" in str(c) for c in cmds)

    def test_host_source_adds_ishlib_device(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        assert any("isholate-ishlib" in c for c in device_adds)

    def test_host_source_mounts_at_same_path(self):
        """The host source must be mounted at its own absolute path inside the
        container so the config file's `source = ...` entry resolves correctly."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        ishsrc_cmd = next(c for c in device_adds if "isholate-ishsrc" in c)
        assert f"source={fake_src}" in ishsrc_cmd
        assert f"path={fake_src}" in ishsrc_cmd

    def test_host_source_runs_ishfiles_apply(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert len(apply_cmds) >= 1
        # Pass 1 must NOT include an explicit -s override
        pass1 = apply_cmds[0]
        assert "-s" not in pass1
        # Must pass --isholate so data.toml overrides take effect
        assert "--isholate" in pass1

    def test_overlay_adds_project_device(self):
        args = _make_args()
        fake_overlay = Path("/work/myproject/.isholate")
        calls, _ = self._run_with_mocks(args, overlay=fake_overlay)
        cmds = self._cmds(calls)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        assert any("isholate-overlay" in c for c in device_adds)

    def test_overlay_runs_ishfiles_apply_with_source_flag(self):
        args = _make_args()
        fake_overlay = Path("/work/myproject/.isholate")
        calls, _ = self._run_with_mocks(args, overlay=fake_overlay)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert len(apply_cmds) >= 1
        # The overlay apply must use -s pointing at the mounted project source
        overlay_apply = apply_cmds[-1]
        assert "-s" in overlay_apply
        assert "/run/isholate/ishsrc-project" in overlay_apply
        # Must pass --isholate so data.toml overrides take effect
        assert "--isholate" in overlay_apply

    def test_both_sources_run_two_apply_passes(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        fake_overlay = Path("/work/myproject/.isholate")
        calls, _ = self._run_with_mocks(
            args, host_source=fake_src, overlay=fake_overlay
        )
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert len(apply_cmds) == 2

    def test_chown_called_after_provisioning(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        chown_cmds = [c for c in cmds if "chown" in c]
        assert len(chown_cmds) == 1
        chown_cmd = chown_cmds[0]
        assert f"{_FAKE_CONTAINER_UID}:{_FAKE_CONTAINER_UID}" in chown_cmd
        assert f"/home/{_FAKE_USER}" in chown_cmd

    def test_installs_python3_and_sudo(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        # Two /bin/sh calls: IPv4 force step + apt-get bootstrap
        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        assert len(sh_cmds) == 2
        # The bootstrap is the second sh call (after IPv4 forcing)
        script = sh_cmds[1][-1]  # the -c argument
        assert "python3" in script
        assert "sudo" in script

    def test_forces_ipv4_before_apt(self):
        """Provisioning writes a force-IPv4 apt config before running apt-get."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        ipv4_script = sh_cmds[0][-1]
        assert "ForceIPv4" in ipv4_script
        assert "apt.conf.d" in ipv4_script

    def test_apt_bootstrap_is_noninteractive(self):
        """Regression: base-package install must not hang on debconf prompts.

        The apt bootstrap in a fresh Ubuntu image pulls in tzdata (via
        python3), whose postinst invokes debconf.  Without
        DEBIAN_FRONTEND=noninteractive the container process would read
        from the user's tty and hang forever.  We also detach stdin from
        the controlling terminal as a belt-and-braces guard.
        """
        import subprocess as _sp

        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)

        # Find the apt-bootstrap call: the /bin/sh -c call that has DEBIAN_FRONTEND
        bootstrap_call = next(
            c
            for c in calls
            if "/bin/sh" in c.args[0] and "DEBIAN_FRONTEND=noninteractive" in c.args[0]
        )
        cmd = bootstrap_call.args[0]

        # DEBIAN_FRONTEND=noninteractive must be passed via `incus exec --env`.
        assert "--env" in cmd
        env_idx = cmd.index("--env")
        assert cmd[env_idx + 1] == "DEBIAN_FRONTEND=noninteractive"

        # stdin must be detached so debconf cannot read from the host tty.
        assert bootstrap_call.kwargs.get("stdin") is _sp.DEVNULL

    def test_verbose_drops_apt_qq_and_adds_ishfiles_verbose(self):
        args = _make_args(verbose=1)
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        script = sh_cmds[1][-1]  # bootstrap is the second sh call
        # -qq should not appear when verbose
        assert "-qq" not in script

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert any("-v" in c for c in apply_cmds)

    def test_vv_passes_debug_to_ishfiles(self):
        args = _make_args(verbose=2)
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert any("--debug" in c for c in apply_cmds)

    def test_default_keeps_apt_qq_and_no_ishfiles_verbose(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        script = sh_cmds[1][-1]  # bootstrap is the second sh call
        assert "-qq" in script

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        for cmd in apply_cmds:
            assert "-v" not in cmd
            assert "--debug" not in cmd


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
        assert args.no_host_ishfiles is False
        assert args.no_project_overlay is False
        assert args.verbose == 0
        assert args.quiet is False
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

    def test_no_host_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-host-ishfiles"])
        assert args.no_host_ishfiles is True

    def test_no_project_overlay_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-project-overlay"])
        assert args.no_project_overlay is True

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

    def test_verbose_flag_counts(self):
        parser = build_parser()
        assert parser.parse_args([]).verbose == 0
        assert parser.parse_args(["-v"]).verbose == 1
        assert parser.parse_args(["-vv"]).verbose == 2
        assert parser.parse_args(["--verbose"]).verbose == 1

    def test_quiet_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-q"])
        assert args.quiet is True
        args = parser.parse_args(["--quiet"])
        assert args.quiet is True

    def test_main_rejects_non_linux(self):
        with patch("sys.platform", "darwin"):
            rc = cli_main([])
        assert rc == 1

    def test_project_config_overrides_image_default(self, tmp_path):
        """Image from .isholate/ishconfig/isholate.toml becomes the argparse default."""
        overlay = tmp_path / ".isholate"
        (overlay / "ishconfig").mkdir(parents=True)
        (overlay / "ishconfig" / "isholate.toml").write_text(
            'image = "images:debian/12"\n'
        )
        with patch(
            "pyishlib.isholate.cli.discover_project_overlay", return_value=overlay
        ):
            with patch(
                "pyishlib.isholate.cli.load_project_config",
                return_value={"image": "images:debian/12"},
            ):
                with patch(
                    "pyishlib.isholate.cli.get_host_user_info",
                    return_value=_fake_user_info(),
                ):
                    with patch(
                        "pyishlib.isholate.cli.discover_host_ishfiles_source",
                        return_value=None,
                    ):
                        with patch(
                            "pyishlib.isholate.cli.launch_and_exec",
                            return_value=0,
                        ) as mock_launch:
                            cli_main([])
                            called_args = mock_launch.call_args[0][0]
                            assert called_args.image == "images:debian/12"

    def test_cli_image_flag_overrides_project_config(self, tmp_path):
        """--image CLI flag takes priority over .isholate/ishconfig/isholate.toml."""
        with patch(
            "pyishlib.isholate.cli.discover_project_overlay", return_value=None
        ):
            with patch(
                "pyishlib.isholate.cli.get_host_user_info",
                return_value=_fake_user_info(),
            ):
                with patch(
                    "pyishlib.isholate.cli.discover_host_ishfiles_source",
                    return_value=None,
                ):
                    with patch(
                        "pyishlib.isholate.cli.launch_and_exec", return_value=0
                    ) as mock_launch:
                        cli_main(["--image", "images:ubuntu/22.04"])
                        called_args = mock_launch.call_args[0][0]
                        assert called_args.image == "images:ubuntu/22.04"


# ---------------------------------------------------------------------------
# config.py — discovery helpers
# ---------------------------------------------------------------------------


class TestDiscoverProjectOverlay:
    def test_finds_isholate_in_cwd(self, tmp_path):
        overlay = tmp_path / ".isholate"
        overlay.mkdir()
        result = discover_project_overlay(tmp_path)
        assert result == overlay

    def test_finds_isholate_in_parent(self, tmp_path):
        overlay = tmp_path / ".isholate"
        overlay.mkdir()
        subdir = tmp_path / "subdir" / "deep"
        subdir.mkdir(parents=True)
        result = discover_project_overlay(subdir)
        assert result == overlay

    def test_returns_none_when_not_found(self, tmp_path):
        result = discover_project_overlay(tmp_path)
        assert result is None

    def test_stops_at_first_match(self, tmp_path):
        """Nested .isholate/ directories: the innermost (deepest) wins."""
        outer = tmp_path / ".isholate"
        outer.mkdir()
        inner_dir = tmp_path / "sub"
        inner_dir.mkdir()
        inner = inner_dir / ".isholate"
        inner.mkdir()
        result = discover_project_overlay(inner_dir)
        assert result == inner


class TestLoadProjectConfig:
    def test_returns_empty_when_no_file(self, tmp_path):
        overlay = tmp_path / ".isholate"
        overlay.mkdir()
        result = load_project_config(overlay)
        assert result == {}

    def test_reads_image_and_shell(self, tmp_path):
        overlay = tmp_path / ".isholate"
        (overlay / "ishconfig").mkdir(parents=True)
        (overlay / "ishconfig" / "isholate.toml").write_text(
            'image = "images:ubuntu/22.04"\nshell = "/bin/zsh"\n'
        )
        result = load_project_config(overlay)
        assert result["image"] == "images:ubuntu/22.04"
        assert result["shell"] == "/bin/zsh"

    def test_returns_empty_for_empty_toml(self, tmp_path):
        overlay = tmp_path / ".isholate"
        (overlay / "ishconfig").mkdir(parents=True)
        (overlay / "ishconfig" / "isholate.toml").write_text("")
        result = load_project_config(overlay)
        assert result == {}


class TestDiscoverHostIshfilesSource:
    def test_returns_none_when_source_does_not_exist(self, tmp_path):
        # Neither config file nor default source dir exists in tmp_path
        result = discover_host_ishfiles_source(tmp_path)
        assert result is None

    def test_reads_source_from_config(self, tmp_path):
        src = tmp_path / "mysource"
        src.mkdir()
        config_dir = tmp_path / ".config" / "ishfiles"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(f'source = "{src}"\n')
        result = discover_host_ishfiles_source(tmp_path)
        assert result == src

    def test_falls_back_to_default_path(self, tmp_path):
        default_src = tmp_path / ".local" / "share" / "ishfiles"
        default_src.mkdir(parents=True)
        result = discover_host_ishfiles_source(tmp_path)
        assert result == default_src

    def test_source_from_config_must_exist(self, tmp_path):
        config_dir = tmp_path / ".config" / "ishfiles"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            'source = "/nonexistent/path"\n'
        )
        result = discover_host_ishfiles_source(tmp_path)
        assert result is None
