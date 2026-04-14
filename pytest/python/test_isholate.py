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
    _check_incus_available,
    _host_base_name,
    _image_tag,
    _project_base_name,
    _project_hash,
    ensure_host_base,
    ensure_project_base,
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
_FAKE_BASE_NAME = _host_base_name(_FAKE_USER, _FAKE_IMAGE)
_FAKE_PBASE_NAME = _project_base_name(_FAKE_USER, Path("/work/myproject"))


def _fake_user_info():
    return (_FAKE_USER, _FAKE_HOME, _FAKE_CWD)


def _make_args(**overrides):
    """Build a minimal args namespace for launch_and_exec."""
    defaults = {
        "name": "test-container",
        "image": _FAKE_IMAGE,
        "shell": _FAKE_SHELL,
        "rw_cwd": False,
        "ro_cwd": False,
        "no_host_ishfiles": False,
        "no_project_ishfiles": False,
        "no_cache": False,
        "rebuild_base": False,
        "rebuild_project_base": False,
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
    # git commands for _source_fingerprint
    if "git" in cmd:
        return SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr="")
    return SimpleNamespace(returncode=0, stdout="", stderr="")


# ---------------------------------------------------------------------------
# Naming helpers
# ---------------------------------------------------------------------------


class TestNamingHelpers:
    def test_image_tag_strips_scheme(self):
        assert _image_tag("images:ubuntu/24.04") == "ubuntu-24-04"

    def test_image_tag_truncates(self):
        long_image = "images:" + "x" * 50
        assert len(_image_tag(long_image)) <= 30

    def test_project_hash_is_deterministic(self):
        p = Path("/work/myproject")
        assert _project_hash(p) == _project_hash(p)

    def test_project_hash_differs_for_different_paths(self):
        assert _project_hash(Path("/a")) != _project_hash(Path("/b"))

    def test_host_base_name_includes_user_and_image(self):
        name = _host_base_name("alice", "images:ubuntu/24.04")
        assert "alice" in name
        assert "ubuntu" in name
        assert name.startswith("isholate-base-")

    def test_project_base_name_starts_with_pbase(self):
        name = _project_base_name("alice", Path("/some/project"))
        assert name.startswith("isholate-pbase-")


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
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in name)


# ---------------------------------------------------------------------------
# purge_containers
# ---------------------------------------------------------------------------


class TestPurgeContainers:
    def _run_purge(self, username, existing_containers, *, include_bases=False):
        """Helper: run purge_containers with a mocked container list."""
        run_calls = []

        def fake_run(cmd, **kwargs):
            run_calls.append(cmd)
            return SimpleNamespace(returncode=0)

        def fake_subprocess_run(cmd, **kwargs):
            import json

            return SimpleNamespace(
                returncode=0, stdout=json.dumps(existing_containers), stderr=""
            )

        with patch("pyishlib.isholate.container._run", side_effect=fake_run):
            with patch(
                "pyishlib.isholate.container.subprocess.run",
                side_effect=fake_subprocess_run,
            ):
                rc = purge_containers(
                    username, quiet=True, include_bases=include_bases
                )
        return rc, run_calls

    def test_prefix_matches_sanitised_username(self):
        """purge must sanitise the username the same way generate_name does."""
        username = "john_doe"
        existing = [
            {"name": generate_name(username)},
            {"name": generate_name(username)},
            {"name": "isholate-other-abc123"},  # different user, not purged
        ]
        rc, run_calls = self._run_purge(username, existing)
        deleted = [c for c in run_calls if c[:2] == ["incus", "delete"]]
        deleted_names = [c[2] for c in deleted]

        assert rc == 0
        assert len(deleted) == 2
        for name in deleted_names:
            assert name.startswith("isholate-john-doe-")
            assert "isholate-other-" not in name

    def test_bases_preserved_by_default(self):
        """Default purge must NOT delete host-base or pbase containers."""
        username = "alice"
        ephemeral = generate_name(username)
        host_base = _host_base_name(username, _FAKE_IMAGE)
        pbase = _project_base_name(username, Path("/proj"))
        existing = [
            {"name": ephemeral},
            {"name": host_base},
            {"name": pbase},
        ]
        rc, run_calls = self._run_purge(username, existing, include_bases=False)
        deleted_names = [c[2] for c in run_calls if c[:2] == ["incus", "delete"]]

        assert rc == 0
        assert ephemeral in deleted_names
        assert host_base not in deleted_names
        assert pbase not in deleted_names

    def test_include_bases_deletes_base_containers(self):
        """With include_bases=True, bases are also deleted."""
        username = "alice"
        ephemeral = generate_name(username)
        host_base = _host_base_name(username, _FAKE_IMAGE)
        pbase = _project_base_name(username, Path("/proj"))
        existing = [
            {"name": ephemeral},
            {"name": host_base},
            {"name": pbase},
        ]
        rc, run_calls = self._run_purge(username, existing, include_bases=True)
        deleted_names = [c[2] for c in run_calls if c[:2] == ["incus", "delete"]]

        assert rc == 0
        assert ephemeral in deleted_names
        assert host_base in deleted_names
        assert pbase in deleted_names

    def test_no_containers_returns_zero(self):
        rc, _ = self._run_purge("nobody", [])
        assert rc == 0


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
# launch_and_exec — no-source path (one-shot, original behaviour)
# ---------------------------------------------------------------------------


class TestLaunchAndExec:
    """Tests for the no-source / one-shot path through launch_and_exec.

    All tests call launch_and_exec with no host_ishfiles_source and no
    project_overlay, so they always go through the one-shot path regardless
    of caching flags.
    """

    def _run_with_mocks(self, args, fake_run_returns=None, **launch_kwargs):
        """Run launch_and_exec with _run and subprocess.run mocked.

        Returns (all_calls, returncode).
        """
        side_effects = fake_run_returns or []
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

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
        args = _make_args(command=["ls", "-la"])
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        assert exec_cmd[-2:] == ["ls", "-la"]

    def test_exec_strips_double_dash_from_remainder(self):
        args = _make_args(command=["--", "ls", "-la"])
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        assert exec_cmd.count("--") == 1
        assert exec_cmd[-2:] == ["ls", "-la"]

    def test_no_disk_devices_by_default(self):
        args = _make_args()
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert device_cmds == []

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
# launch_and_exec — cached path with sources
# ---------------------------------------------------------------------------


class TestProvisioning:
    """Tests for the ishfiles provisioning step.

    When host_ishfiles_source is supplied, launch_and_exec uses the
    three-tier cached path (ensure_host_base → ensure_project_base →
    _launch_ephemeral_from_base).  All Incus calls are captured via the
    _run mock so the provisioning assertions remain the same.
    """

    def _run_with_mocks(self, args, host_source=None, overlay=None):
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            return default

        project_root = overlay.parent.parent if overlay is not None else None

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
                    with patch.object(Path, "is_dir", return_value=True):
                        rc = launch_and_exec(
                            args,
                            host_ishfiles_source=host_source,
                            project_overlay=overlay,
                            project_root=project_root,
                        )
                        return mock_run.call_args_list, rc

    def _cmds(self, calls):
        return [c.args[0] for c in calls]

    def test_no_provisioning_when_no_sources(self):
        """With neither host source nor overlay, no provisioning calls occur."""
        args = _make_args()
        calls, _ = self._run_with_mocks(args, host_source=None, overlay=None)
        cmds = self._cmds(calls)

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

    def test_host_source_mounts_under_run_isholate(self):
        """The host source must be mounted under /run/isholate."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        ishsrc_cmd = next(c for c in device_adds if "isholate-ishsrc" in c)
        assert f"source={fake_src}" in ishsrc_cmd
        assert "path=/run/isholate/ishsrc" in ishsrc_cmd

    def test_host_source_runs_ishfiles_apply(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert len(apply_cmds) >= 1
        pass1 = apply_cmds[0]
        assert "-s" in pass1
        assert "/run/isholate/ishsrc" in pass1
        assert "--isholate" in pass1

    def test_overlay_only_falls_back_to_one_shot(self):
        """Overlay with no host source falls back to one-shot provisioning."""
        args = _make_args()
        fake_overlay = Path("/work/myproject/.ishlib/ishfiles")
        calls, _ = self._run_with_mocks(args, overlay=fake_overlay)
        cmds = self._cmds(calls)

        # One-shot path creates an ephemeral directly with incus init, not incus copy
        assert any(c[:2] == ["incus", "init"] for c in cmds)
        device_adds = [c for c in cmds if "device" in c and "add" in c]
        assert any("isholate-overlay" in c for c in device_adds)

    def test_overlay_runs_ishfiles_apply_with_source_flag(self):
        args = _make_args()
        fake_overlay = Path("/work/myproject/.ishlib/ishfiles")
        calls, _ = self._run_with_mocks(args, overlay=fake_overlay)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert len(apply_cmds) >= 1
        overlay_apply = apply_cmds[-1]
        assert "-s" in overlay_apply
        assert "/run/isholate/ishsrc-project" in overlay_apply
        assert "--isholate" in overlay_apply

    def test_both_sources_run_two_apply_passes(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        fake_overlay = Path("/work/myproject/.ishlib/ishfiles")
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
        script = sh_cmds[1][-1]
        assert "python3" in script
        assert "sudo" in script

    def test_forces_ipv4_before_apt(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        ipv4_script = sh_cmds[0][-1]
        assert "ForceIPv4" in ipv4_script
        assert "apt.conf.d" in ipv4_script

    def test_apt_bootstrap_is_noninteractive(self):
        """Regression: base-package install must not hang on debconf prompts."""
        import subprocess as _sp

        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)

        bootstrap_call = next(
            c
            for c in calls
            if "/bin/sh" in c.args[0] and "DEBIAN_FRONTEND=noninteractive" in c.args[0]
        )
        cmd = bootstrap_call.args[0]

        assert "--env" in cmd
        env_idx = cmd.index("--env")
        assert cmd[env_idx + 1] == "DEBIAN_FRONTEND=noninteractive"

        assert bootstrap_call.kwargs.get("stdin") is _sp.DEVNULL

    def test_verbose_drops_apt_qq_and_adds_ishfiles_verbose(self):
        args = _make_args(verbose=1)
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        script = sh_cmds[1][-1]
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
        script = sh_cmds[1][-1]
        assert "-qq" in script

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        for cmd in apply_cmds:
            assert "-v" not in cmd
            assert "--debug" not in cmd


# ---------------------------------------------------------------------------
# Cached path: ensure_host_base / ensure_project_base
# ---------------------------------------------------------------------------


class TestBaseManagement:
    """Tests for the persistent-base ensure_* functions."""

    def _run_ensure_host_base(
        self,
        host_source,
        *,
        stored_fp=None,
        container_exists=False,
        rebuild=False,
        verbose=0,
        quiet=True,
    ):
        """Run ensure_host_base with mocked Incus calls."""
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            # Return the stored fingerprint for config get of source_hash
            if (
                cmd[:3] == ["incus", "config", "get"]
                and "_META_SOURCE_HASH" not in str(cmd)
                and "source_hash" in str(cmd)
            ):
                fp = stored_fp or ""
                return SimpleNamespace(returncode=0, stdout=fp, stderr="")
            # incus info returns success iff container_exists
            if cmd[:2] == ["incus", "info"]:
                rc = 0 if container_exists else 1
                return SimpleNamespace(returncode=rc, stdout="", stderr="")
            return default

        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return fake_run(cmd, **kwargs)

        with patch("pyishlib.isholate.container._run", side_effect=recording_run):
            with patch(
                "pyishlib.isholate.container.subprocess.run",
                side_effect=_fake_subprocess_run,
            ):
                with patch.object(Path, "is_dir", return_value=True):
                    with patch(
                        "pyishlib.isholate.container._source_fingerprint",
                        return_value="COMPUTED",
                    ):
                        name = ensure_host_base(
                            _FAKE_IMAGE,
                            _FAKE_USER,
                            host_source,
                            None,
                            _FAKE_SHELL,
                            verbose=verbose,
                            quiet=quiet,
                            rebuild=rebuild,
                        )
        return name, calls

    def test_reuses_base_when_fingerprint_matches(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(
            fake_src, stored_fp="COMPUTED", container_exists=True
        )
        cmds = calls
        # Should not create a new container
        assert not any(c[:2] == ["incus", "init"] for c in cmds)
        assert not any(c[:2] == ["incus", "delete"] for c in cmds)
        assert name == _host_base_name(_FAKE_USER, _FAKE_IMAGE)

    def test_rebuilds_when_fingerprint_changes(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(
            fake_src, stored_fp="STALE", container_exists=True
        )
        cmds = calls
        # Must delete the stale base and create a new one
        assert any(c[:2] == ["incus", "delete"] for c in cmds)
        assert any(c[:2] == ["incus", "init"] for c in cmds)

    def test_creates_base_when_it_does_not_exist(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(
            fake_src, stored_fp=None, container_exists=False
        )
        cmds = calls
        assert any(c[:2] == ["incus", "init"] for c in cmds)
        assert any(c[:2] == ["incus", "start"] for c in cmds)

    def test_rebuild_flag_forces_rebuild(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(
            fake_src,
            stored_fp="COMPUTED",  # fingerprints match — but rebuild is forced
            container_exists=True,
            rebuild=True,
        )
        cmds = calls
        assert any(c[:2] == ["incus", "delete"] for c in cmds)
        assert any(c[:2] == ["incus", "init"] for c in cmds)

    def test_base_is_stopped_after_creation(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(
            fake_src, container_exists=False
        )
        cmds = calls
        stop_cmds = [c for c in cmds if c[:2] == ["incus", "stop"]]
        assert len(stop_cmds) >= 1

    def test_host_base_name_returned(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, _ = self._run_ensure_host_base(
            fake_src, stored_fp="COMPUTED", container_exists=True
        )
        assert name == _host_base_name(_FAKE_USER, _FAKE_IMAGE)

    def test_ephemeral_created_via_copy_not_init(self):
        """Cached path: ephemeral is incus copy, not incus init."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        default = SimpleNamespace(returncode=0, stdout="", stderr="")
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return default

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch("pyishlib.isholate.container._run", side_effect=fake_run):
                with patch(
                    "pyishlib.isholate.container.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    with patch.object(Path, "is_dir", return_value=True):
                        launch_and_exec(args, host_ishfiles_source=fake_src)

        cmds = calls
        # Base is created via incus init; ephemeral is cloned via incus copy
        assert any(c[:2] == ["incus", "copy"] for c in cmds)
        # The ephemeral should still be deleted at the end
        delete_cmds = [c for c in cmds if c[:2] == ["incus", "delete"]]
        # At least one delete (for the ephemeral; possibly one for a stale base)
        assert len(delete_cmds) >= 1


# ---------------------------------------------------------------------------
# Network pre-flight
# ---------------------------------------------------------------------------


class TestNetworkPreflight:
    """Tests for _network_preflight behaviour in launch_and_exec."""

    def _run_with_mocks_custom(self, args, fake_run_fn, host_source=None):
        """Like TestProvisioning._run_with_mocks but accepts a custom fake_run."""
        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.container._run", side_effect=fake_run_fn
            ) as mock_run:
                with patch(
                    "pyishlib.isholate.container.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    with patch.object(Path, "is_dir", return_value=True):
                        rc = launch_and_exec(
                            args, host_ishfiles_source=host_source
                        )
                        return mock_run.call_args_list, rc

    def _cmds(self, calls):
        return [c.args[0] for c in calls]

    def test_preflight_runs_before_apt(self):
        """Network probe must execute before apt-get update."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        calls, _ = self._run_with_mocks_custom(args, fake_run, host_source=fake_src)
        cmds = self._cmds(calls)

        curl_indices = [i for i, c in enumerate(cmds) if "1.1.1.1" in str(c)]
        apt_indices = [i for i, c in enumerate(cmds) if "apt-get" in str(c)]

        assert len(curl_indices) >= 1, "curl 1.1.1.1 probe not found"
        assert len(apt_indices) >= 1, "apt-get not found"
        assert curl_indices[0] < apt_indices[0], "preflight must run before apt"

    def test_preflight_failure_stops_container(self, capsys):
        """When the 1.1.1.1 probe fails, launch_and_exec returns non-zero and
        still stops the container (finally path)."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")

        def fake_run(cmd, **kwargs):
            if "1.1.1.1" in str(cmd):
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        calls, rc = self._run_with_mocks_custom(args, fake_run, host_source=fake_src)
        cmds = self._cmds(calls)

        assert rc != 0
        # The base container should be stopped (exact name is the host base)
        assert any(c[:2] == ["incus", "stop"] for c in cmds)

    def test_preflight_passes_continues_to_apt(self):
        """When probe passes, apt-get update still runs."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        calls, rc = self._run_with_mocks_custom(args, fake_run, host_source=fake_src)
        cmds = self._cmds(calls)

        assert any("apt-get" in str(c) for c in cmds), "apt-get must still run"
        assert rc == 0

    def test_preflight_error_message_mentions_ufw_firewalld_ip_forward(self, capsys):
        """Diagnostic A (bridge broken) must name all common root causes."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")

        def fake_run(cmd, **kwargs):
            if "1.1.1.1" in str(cmd):
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        self._run_with_mocks_custom(args, fake_run, host_source=fake_src)
        err = capsys.readouterr().err

        assert "ufw" in err
        assert "firewalld" in err
        assert "ip_forward" in err


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


class TestParser:
    @pytest.fixture(autouse=True)
    def _mock_incus_preflight(self):
        """Bypass the incus availability check for CLI-dispatch tests.

        The check is covered by :class:`TestCheckIncusAvailable`; these tests
        exercise argparse wiring and dispatch, so we simulate a healthy host.
        """
        with patch("pyishlib.isholate.cli._check_incus_available", return_value=None):
            yield

    def test_defaults(self):
        from pyishlib.isholate.cli import DEFAULT_IMAGE, DEFAULT_SHELL

        parser = build_parser()
        args = parser.parse_args([])
        assert args.image == DEFAULT_IMAGE
        assert args.shell == DEFAULT_SHELL
        assert args.rw_cwd is False
        assert args.ro_cwd is False
        assert args.no_host_ishfiles is False
        assert args.no_project_ishfiles is False
        assert args.no_cache is False
        assert args.rebuild is False
        assert args.rebuild_base is False
        assert args.rebuild_project_base is False
        assert args.purge is False
        assert args.purge_bases is False
        assert args.purge_all is False
        assert args.verbose == 0
        assert args.quiet is False
        assert args.command == []

    def test_rw_cwd_and_ro_cwd_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--rw-cwd", "--ro-cwd"])

    def test_custom_image(self):
        parser = build_parser()
        args = parser.parse_args(["--image", "images:ubuntu/22.04"])
        assert args.image == "images:ubuntu/22.04"

    def test_no_host_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-host-ishfiles"])
        assert args.no_host_ishfiles is True

    def test_no_project_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-project-ishfiles"])
        assert args.no_project_ishfiles is True

    def test_no_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-ishfiles"])
        assert args.no_ishfiles is True

    def test_no_cache_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-cache"])
        assert args.no_cache is True

    def test_rebuild_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--rebuild"])
        assert args.rebuild is True

    def test_rebuild_base_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--rebuild-base"])
        assert args.rebuild_base is True

    def test_rebuild_project_base_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--rebuild-project-base"])
        assert args.rebuild_project_base is True

    def test_rebuild_flags_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--rebuild", "--rebuild-base"])

    def test_purge_flags_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--purge", "--purge-bases"])

    def test_purge_bases_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--purge-bases"])
        assert args.purge_bases is True

    def test_purge_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--purge-all"])
        assert args.purge_all is True

    def test_no_ishfiles_suppresses_provisioning(self):
        """--no-ishfiles must pass None for both sources to launch_and_exec."""
        with patch(
            "pyishlib.isholate.cli.discover_project_overlay", return_value=None
        ):
            with patch(
                "pyishlib.isholate.cli.get_host_user_info",
                return_value=_fake_user_info(),
            ):
                with patch(
                    "pyishlib.isholate.cli.discover_host_ishfiles_source",
                    return_value=Path("/some/ishfiles"),
                ):
                    with patch(
                        "pyishlib.isholate.cli.launch_and_exec", return_value=0
                    ) as mock_launch:
                        cli_main(["--no-ishfiles"])
                        _, kwargs = mock_launch.call_args
                        assert kwargs["host_ishfiles_source"] is None
                        assert kwargs["project_overlay"] is None

    def test_command_passthrough(self):
        parser = build_parser()
        args = parser.parse_args(["ls"])
        assert args.command == ["ls"]

    def test_command_passthrough_with_flags(self):
        parser = build_parser()
        args = parser.parse_args(["--", "ls", "-la"])
        assert args.command == ["--", "ls", "-la"]

    def test_run_default_is_none(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.run is None

    def test_run_long_flag_captures_command(self):
        parser = build_parser()
        args = parser.parse_args(["--run", "ls", "-la"])
        assert args.run == ["ls", "-la"]

    def test_run_short_flag_captures_command(self):
        parser = build_parser()
        args = parser.parse_args(["-r", "echo", "hello"])
        assert args.run == ["echo", "hello"]

    def test_run_captures_flags_that_follow(self):
        """Everything after --run is treated as the command, including flags."""
        parser = build_parser()
        args = parser.parse_args(["--quiet", "--run", "grep", "--color", "foo"])
        assert args.quiet is True
        assert args.run == ["grep", "--color", "foo"]

    def test_main_copies_run_into_command(self):
        """cli_main() must forward --run contents as args.command to launch_and_exec."""
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
                        cli_main(["--run", "ls", "-la"])
                        forwarded_args = mock_launch.call_args.args[0]
                        assert forwarded_args.command == ["ls", "-la"]

    def test_run_after_positional_is_absorbed_by_positional(self):
        """When a positional command comes first, REMAINDER absorbs --run.

        This documents the expected argparse behaviour: once the positional
        ``command`` starts consuming tokens, ``--run`` is treated as one of
        its arguments rather than as a separate option. ``--run`` therefore
        only has effect when it appears before any positional command.
        """
        parser = build_parser()
        args = parser.parse_args(["ls", "--run", "echo", "hi"])
        assert args.run is None
        assert args.command == ["ls", "--run", "echo", "hi"]

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

    def test_purge_bases_calls_purge_with_include_bases(self):
        """--purge-bases must call purge_containers with include_bases=True."""
        with patch(
            "pyishlib.isholate.cli.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.cli.purge_containers", return_value=0
            ) as mock_purge:
                cli_main(["--purge-bases"])
                _, kwargs = mock_purge.call_args
                assert kwargs.get("include_bases") is True

    def test_purge_all_calls_purge_with_include_bases(self):
        """--purge-all must also call purge_containers with include_bases=True."""
        with patch(
            "pyishlib.isholate.cli.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.cli.purge_containers", return_value=0
            ) as mock_purge:
                cli_main(["--purge-all"])
                _, kwargs = mock_purge.call_args
                assert kwargs.get("include_bases") is True

    def test_purge_does_not_include_bases(self):
        """Plain --purge must NOT pass include_bases=True."""
        with patch(
            "pyishlib.isholate.cli.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.cli.purge_containers", return_value=0
            ) as mock_purge:
                cli_main(["--purge"])
                _, kwargs = mock_purge.call_args
                assert not kwargs.get("include_bases", False)

    def test_project_config_overrides_image_default(self, tmp_path):
        """Image from .ishlib/isholate/config.toml becomes the argparse default."""
        overlay = tmp_path / ".ishlib" / "ishfiles"
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        (tmp_path / ".ishlib" / "isholate" / "config.toml").write_text(
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
        """--image CLI flag takes priority over .ishlib/isholate/config.toml."""
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

    def test_rebuild_wires_flags_to_launch_and_exec(self):
        """--rebuild must set rebuild_base=True and rebuild_project_base=True on args."""
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
                        cli_main(["--rebuild"])
                        called_args = mock_launch.call_args[0][0]
                        assert called_args.rebuild_base is True
                        assert called_args.rebuild_project_base is True


# ---------------------------------------------------------------------------
# config.py — discovery helpers
# ---------------------------------------------------------------------------


class TestDiscoverProjectOverlay:
    def test_finds_ishfiles_in_cwd(self, tmp_path):
        overlay = tmp_path / ".ishlib" / "ishfiles"
        overlay.mkdir(parents=True)
        result = discover_project_overlay(tmp_path)
        assert result == overlay

    def test_returns_none_when_not_found(self, tmp_path):
        result = discover_project_overlay(tmp_path)
        assert result is None

    def test_does_not_search_parent_dirs(self, tmp_path):
        (tmp_path / ".ishlib" / "ishfiles").mkdir(parents=True)
        subdir = tmp_path / "subdir" / "deep"
        subdir.mkdir(parents=True)
        result = discover_project_overlay(subdir)
        assert result is None

    def test_returns_none_when_only_isholate_dir_exists(self, tmp_path):
        """Overlay discovery is independent of the isholate config dir."""
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        result = discover_project_overlay(tmp_path)
        assert result is None


class TestLoadProjectConfig:
    def test_returns_empty_when_no_file(self, tmp_path):
        result = load_project_config(tmp_path)
        assert result == {}

    def test_reads_image_and_shell(self, tmp_path):
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        (tmp_path / ".ishlib" / "isholate" / "config.toml").write_text(
            'image = "images:ubuntu/22.04"\nshell = "/bin/zsh"\n'
        )
        result = load_project_config(tmp_path)
        assert result["image"] == "images:ubuntu/22.04"
        assert result["shell"] == "/bin/zsh"

    def test_returns_empty_for_empty_toml(self, tmp_path):
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        (tmp_path / ".ishlib" / "isholate" / "config.toml").write_text("")
        result = load_project_config(tmp_path)
        assert result == {}

    def test_reads_config_without_overlay(self, tmp_path):
        """Config loads even when the ishfiles overlay dir is absent."""
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        (tmp_path / ".ishlib" / "isholate" / "config.toml").write_text(
            'image = "images:debian/12"\n'
        )
        assert not (tmp_path / ".ishlib" / "ishfiles").exists()
        result = load_project_config(tmp_path)
        assert result["image"] == "images:debian/12"


class TestDiscoverHostIshfilesSource:
    def test_returns_none_when_source_does_not_exist(self, tmp_path):
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


# ---------------------------------------------------------------------------
# _check_incus_available — setup diagnostics
# ---------------------------------------------------------------------------


class TestCheckIncusAvailable:
    """Unit tests for the incus setup diagnostic helper."""

    def _patch_incus_info(self, returncode, stderr=""):
        """Return a patch context for subprocess.run that mimics incus info."""
        result = SimpleNamespace(returncode=returncode, stdout="", stderr=stderr)
        return patch(
            "pyishlib.isholate.container.subprocess.run",
            return_value=result,
        )

    def test_missing_binary_debian(self):
        with patch("pyishlib.isholate.container.shutil.which", return_value=None):
            with patch(
                "pyishlib.isholate.container.detect_distro", return_value="debian"
            ):
                msg = _check_incus_available()
        assert msg is not None
        assert "not found on PATH" in msg
        assert "apt install incus" in msg

    def test_missing_binary_fedora(self):
        with patch("pyishlib.isholate.container.shutil.which", return_value=None):
            with patch(
                "pyishlib.isholate.container.detect_distro", return_value="fedora"
            ):
                msg = _check_incus_available()
        assert msg is not None
        assert "dnf install incus" in msg

    def test_missing_binary_unknown_distro(self):
        with patch("pyishlib.isholate.container.shutil.which", return_value=None):
            with patch(
                "pyishlib.isholate.container.detect_distro", return_value=None
            ):
                msg = _check_incus_available()
        assert msg is not None
        # Match on the path substring rather than a full hostname so the
        # test doesn't look like URL-origin validation to static analysers.
        assert "linuxcontainers" in msg

    def test_healthy_returns_none(self):
        with patch(
            "pyishlib.isholate.container.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(0):
                assert _check_incus_available() is None

    def test_permission_denied(self):
        with patch(
            "pyishlib.isholate.container.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                1, stderr="Error: permission denied on /var/lib/incus/unix.socket"
            ):
                msg = _check_incus_available()
        assert msg is not None
        assert "permission denied" in msg.lower()
        assert "usermod -aG incus-admin" in msg
        assert "newgrp incus-admin" in msg

    def test_daemon_not_initialized(self):
        with patch(
            "pyishlib.isholate.container.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                1, stderr="Error: Daemon is not initialized, run 'incus admin init'"
            ):
                msg = _check_incus_available()
        assert msg is not None
        assert "incus admin init" in msg

    def test_connection_refused(self):
        with patch(
            "pyishlib.isholate.container.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                1, stderr="dial unix /var/lib/incus/unix.socket: connect: connection refused"
            ):
                msg = _check_incus_available()
        assert msg is not None
        assert "daemon is not ready" in msg.lower()
        assert "systemctl" in msg

    def test_unknown_failure_surfaces_stderr(self):
        with patch(
            "pyishlib.isholate.container.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                2, stderr="Error: something surprising went wrong"
            ):
                msg = _check_incus_available()
        assert msg is not None
        assert "something surprising went wrong" in msg
        assert "exit 2" in msg


class TestCliIncusPreflight:
    """The CLI should bail out with a helpful message when incus isn't usable."""

    def test_main_returns_1_and_prints_guidance(self, capsys):
        with patch(
            "pyishlib.isholate.cli._check_incus_available",
            return_value="isholate: error: TEST GUIDANCE",
        ):
            rc = cli_main([])
        captured = capsys.readouterr()
        assert rc == 1
        assert "TEST GUIDANCE" in captured.err

    def test_help_works_without_incus(self, capsys):
        """`--help` must still print usage on hosts without a healthy incus."""
        with patch(
            "pyishlib.isholate.cli._check_incus_available",
            return_value="isholate: error: SHOULD NOT BE PRINTED",
        ) as mock_check:
            with pytest.raises(SystemExit) as exc_info:
                cli_main(["--help"])
        captured = capsys.readouterr()
        # argparse exits 0 on --help.
        assert exc_info.value.code == 0
        # The preflight must not have run (argparse handled --help first).
        mock_check.assert_not_called()
        # Usage text reaches stdout; our guidance string does not.
        assert "usage" in captured.out.lower()
        assert "SHOULD NOT BE PRINTED" not in captured.err
