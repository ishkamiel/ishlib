# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

#
# Tests for the isholate tool (CLI and container lifecycle)

import logging
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
    resolve_default_shell,
)
from pyishlib.container.incus import check_incus_available
from pyishlib.isholate.claude import (
    _CLAUDE_ALLOW_DOMAINS,
    _CLAUDE_DNS_UPSTREAM,
    _CLAUDE_FIREWALL_APPLY_SCRIPT,
    _CLAUDE_FIREWALL_SYSTEMD_UNIT,
    _CLAUDE_IPSET_NAME,
    _CLAUDE_IPTABLES_CHAIN,
    _CLAUDE_NETWORK_NAME,
    _apply_network_restrictions,
    _build_claude_firewall_install_script,
    _build_claude_raw_dnsmasq,
    _build_minimal_claude_json,
    _claude_firewall_rules_in_place,
    _ensure_claude_network,
    _install_claude_firewall,
    _preflight_claude_host_tools,
)
from pyishlib.isholate.container import (
    _META_SOURCE_HASH,
    _assert_no_isholate_devices,
    _find_isholate_containers,
    _host_base_name,
    _image_tag,
    _list_isholate_devices,
    _project_base_name,
    _project_hash,
    _remove_isholate_devices,
    _source_fingerprint,
    ensure_host_base,
    ensure_project_base,
    generate_name,
    get_host_user_info,
    launch_and_exec,
    list_containers,
    purge_containers,
    stop_containers,
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
        "claude": False,
        "claude_base": False,
        "no_network": False,
        "no_host_ishfiles": False,
        "no_project_ishfiles": False,
        "no_cache": False,
        "rebuild_base": False,
        "rebuild_project_base": False,
        "verbose": False,
        "debug": False,
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
# _source_fingerprint
# ---------------------------------------------------------------------------


class TestSourceFingerprint:
    """Tests for _source_fingerprint's path-scoped git fingerprinting.

    These tests guard against the regression where an active project's
    unrelated repo-wide churn (commits or dirty files outside the overlay)
    invalidated the project-base cache.  The fingerprint must reflect only
    state of files under the given source path.
    """

    _FAKE_SOURCE = Path("/work/myproject/.ishlib/ishfiles")

    def _fake_git_runner(self, *, log_stdout="cafebabe", status_stdout=""):
        """Return (fake_run, calls) where fake_run records git invocations."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if not cmd or cmd[0] != "git":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            # Match on the git subcommand following "-C <path>".
            if "log" in cmd:
                return SimpleNamespace(
                    returncode=0, stdout=f"{log_stdout}\n", stderr=""
                )
            if "status" in cmd:
                return SimpleNamespace(returncode=0, stdout=status_stdout, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return fake_run, calls

    def test_scopes_git_log_to_path(self):
        fake_run, calls = self._fake_git_runner()
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run):
            _source_fingerprint(self._FAKE_SOURCE)

        log_calls = [c for c in calls if "log" in c]
        assert log_calls, "expected at least one 'git log' call"
        for c in log_calls:
            # Must be scoped with '-- .' pathspec so state outside the source
            # tree does not contribute to the fingerprint.
            assert "--" in c and c[-1] == ".", f"git log must be path-scoped, got: {c}"
            assert "-C" in c and str(self._FAKE_SOURCE) in c

    def test_scopes_git_status_to_path(self):
        fake_run, calls = self._fake_git_runner()
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run):
            _source_fingerprint(self._FAKE_SOURCE)

        status_calls = [c for c in calls if "status" in c]
        assert status_calls, "expected at least one 'git status' call"
        for c in status_calls:
            assert "--porcelain" in c
            assert "--" in c and c[-1] == ".", (
                f"git status must be path-scoped, got: {c}"
            )

    def test_stable_across_unrelated_repo_activity(self):
        """Same path-scoped state → same fingerprint, regardless of other repo churn."""
        fake_run_a, _ = self._fake_git_runner(
            log_stdout="deadbeef", status_stdout=" M foo\n"
        )
        fake_run_b, _ = self._fake_git_runner(
            log_stdout="deadbeef", status_stdout=" M foo\n"
        )
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run_a):
            fp_a = _source_fingerprint(self._FAKE_SOURCE)
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run_b):
            fp_b = _source_fingerprint(self._FAKE_SOURCE)
        assert fp_a == fp_b

    def test_changes_when_scoped_history_changes(self):
        fake_run_a, _ = self._fake_git_runner(log_stdout="aaaaaaaa")
        fake_run_b, _ = self._fake_git_runner(log_stdout="bbbbbbbb")
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run_a):
            fp_a = _source_fingerprint(self._FAKE_SOURCE)
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run_b):
            fp_b = _source_fingerprint(self._FAKE_SOURCE)
        assert fp_a != fp_b

    def test_changes_when_scoped_status_changes(self):
        fake_run_a, _ = self._fake_git_runner(status_stdout="")
        fake_run_b, _ = self._fake_git_runner(status_stdout="?? newfile\n")
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run_a):
            fp_a = _source_fingerprint(self._FAKE_SOURCE)
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run_b):
            fp_b = _source_fingerprint(self._FAKE_SOURCE)
        assert fp_a != fp_b

    def test_falls_back_when_no_committed_history(self, tmp_path):
        """Empty 'git log' output → content-hash fallback engages."""
        src = tmp_path / "overlay"
        src.mkdir()
        (src / "a.txt").write_text("hello")

        fake_run, calls = self._fake_git_runner(log_stdout="")  # empty
        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run):
            fp = _source_fingerprint(src)

        # Status must NOT have been called — we bailed out of the git branch.
        assert not any("status" in c for c in calls), (
            "status must not run when git log reports no history"
        )
        # Fingerprint is a 16-char hex digest from the content hash fallback.
        assert len(fp) == 16 and all(ch in "0123456789abcdef" for ch in fp)

    def test_falls_back_when_git_unavailable(self, tmp_path):
        """FileNotFoundError for git → content-hash fallback engages."""
        src = tmp_path / "overlay"
        src.mkdir()
        (src / "a.txt").write_text("hello")

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("git not found")

        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run):
            fp = _source_fingerprint(src)
        assert len(fp) == 16

    def test_falls_back_on_git_error(self, tmp_path):
        """CalledProcessError from git → content-hash fallback engages."""
        src = tmp_path / "overlay"
        src.mkdir()
        (src / "a.txt").write_text("hello")

        import subprocess as _sp

        def fake_run(cmd, **kwargs):
            raise _sp.CalledProcessError(128, cmd)

        with patch("pyishlib.isholate.container.subprocess.run", side_effect=fake_run):
            fp = _source_fingerprint(src)
        assert len(fp) == 16


# ---------------------------------------------------------------------------
# purge_containers
# ---------------------------------------------------------------------------


class TestDeviceHelpers:
    """Tests for _list_isholate_devices, _remove_isholate_devices, and
    _assert_no_isholate_devices.

    incus config device list outputs plain text (one name per line), not JSON.
    These tests verify the helpers parse that format correctly.
    """

    def _fake_run_for_list(self, stdout, returncode=0):
        """Return a fake_run that echoes *stdout* for device list commands."""

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        return fake_run

    def test_list_returns_only_isholate_prefix(self):
        plain_output = "eth0\nisholate-ishlib\nroot\nisholate-ishconf\n"
        with patch(
            "pyishlib.container.incus._run",
            side_effect=self._fake_run_for_list(plain_output),
        ):
            result = _list_isholate_devices("mycontainer")
        assert result == ["isholate-ishlib", "isholate-ishconf"]

    def test_list_returns_empty_when_no_isholate_devices(self):
        plain_output = "eth0\nroot\n"
        with patch(
            "pyishlib.container.incus._run",
            side_effect=self._fake_run_for_list(plain_output),
        ):
            result = _list_isholate_devices("mycontainer")
        assert result == []

    def test_list_returns_empty_on_command_failure(self):
        with patch(
            "pyishlib.container.incus._run",
            side_effect=self._fake_run_for_list("", returncode=1),
        ):
            result = _list_isholate_devices("mycontainer")
        assert result == []

    def test_remove_only_strips_isholate_devices(self):
        plain_output = "eth0\nisholate-ishlib\nroot\nisholate-ishsrc\n"
        removed = []

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout=plain_output, stderr="")
            if cmd[:4] == ["incus", "config", "device", "remove"]:
                removed.append(cmd[5])  # device name is 6th token
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            _remove_isholate_devices("mycontainer")

        assert set(removed) == {"isholate-ishlib", "isholate-ishsrc"}

    def test_remove_is_noop_when_no_isholate_devices(self):
        plain_output = "eth0\nroot\n"
        removed = []

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout=plain_output, stderr="")
            if cmd[:4] == ["incus", "config", "device", "remove"]:
                removed.append(cmd[5])
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            _remove_isholate_devices("mycontainer")

        assert removed == []

    def test_assert_raises_when_isholate_devices_remain(self):
        plain_output = "eth0\nisholate-ishlib\nroot\n"
        with patch(
            "pyishlib.container.incus._run",
            side_effect=self._fake_run_for_list(plain_output),
        ):
            with pytest.raises(RuntimeError, match="isholate-ishlib"):
                _assert_no_isholate_devices("mycontainer")

    def test_assert_passes_when_clean(self):
        plain_output = "eth0\nroot\n"
        with patch(
            "pyishlib.container.incus._run",
            side_effect=self._fake_run_for_list(plain_output),
        ):
            _assert_no_isholate_devices("mycontainer")  # must not raise

    def test_assert_raises_on_command_failure(self):
        """Strict: non-zero exit from device-list must raise, not silently pass.

        Regression guard — a prior refactor routed the assert through the
        lenient list helper, which returns [] on failure and let a poisoned
        base slip past verification.
        """

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr="incus: not logged in"
                )
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="exited with 1"):
                _assert_no_isholate_devices("mycontainer")


class TestPurgeContainers:
    def _run_purge(self, username, existing_containers, *, include_bases=False):
        """Helper: run purge_containers with a mocked container list."""
        import json

        run_calls = []
        listing_json = json.dumps(existing_containers)

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["incus", "list", "--format=json"]:
                return SimpleNamespace(returncode=0, stdout=listing_json, stderr="")
            run_calls.append(cmd)
            return SimpleNamespace(returncode=0)

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            rc = purge_containers(username, quiet=True, include_bases=include_bases)
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
# _find_isholate_containers
# ---------------------------------------------------------------------------


def _fake_incus_list(containers):
    """Return a fake subprocess.run replacement yielding *containers* as JSON."""

    def _inner(cmd, **kwargs):
        import json as _json

        return SimpleNamespace(returncode=0, stdout=_json.dumps(containers), stderr="")

    return _inner


class TestFindIsholateContainers:
    def test_filters_by_user(self):
        username = "alice"
        existing = [
            {"name": generate_name(username), "status": "Running"},
            {"name": generate_name("bob"), "status": "Running"},
            {"name": "not-an-isholate-container", "status": "Running"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            entries = _find_isholate_containers(username)

        names = [e["name"] for e in entries]
        assert len(entries) == 1
        assert names[0].startswith("isholate-alice-")
        assert entries[0]["kind"] == "ephemeral"
        assert entries[0]["status"] == "Running"
        assert entries[0]["owner"] == "alice"

    def test_include_bases_false_hides_bases(self):
        username = "alice"
        existing = [
            {"name": generate_name(username), "status": "Running"},
            {"name": _host_base_name(username, _FAKE_IMAGE), "status": "Stopped"},
            {"name": _project_base_name(username, Path("/p")), "status": "Stopped"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            entries = _find_isholate_containers(username, include_bases=False)

        assert len(entries) == 1
        assert entries[0]["kind"] == "ephemeral"

    def test_include_bases_true_shows_bases(self):
        username = "alice"
        host_base = _host_base_name(username, _FAKE_IMAGE)
        pbase = _project_base_name(username, Path("/p"))
        existing = [
            {"name": generate_name(username), "status": "Running"},
            {"name": host_base, "status": "Stopped"},
            {"name": pbase, "status": "Stopped"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            entries = _find_isholate_containers(username, include_bases=True)

        kinds = {e["kind"] for e in entries}
        assert kinds == {"ephemeral", "host-base", "project-base"}

    def test_all_users_skips_user_filter(self):
        existing = [
            {"name": generate_name("alice"), "status": "Running"},
            {"name": generate_name("bob"), "status": "Stopped"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            entries = _find_isholate_containers("carol", all_users=True)

        owners = {e["owner"] for e in entries}
        assert owners == {"alice", "bob"}
        assert all(e["kind"] == "ephemeral" for e in entries)

    def test_non_isholate_names_are_skipped(self):
        existing = [
            {"name": "other-container", "status": "Running"},
            {"name": "isholate-", "status": "Running"},  # malformed
            {"name": "isholate", "status": "Running"},  # also malformed
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            entries = _find_isholate_containers("alice", all_users=True)

        assert entries == []

    def test_entries_sorted_by_name(self):
        username = "alice"
        # Craft names with predictable ordering.
        existing = [
            {"name": f"isholate-{username}-zzz", "status": "Running"},
            {"name": f"isholate-{username}-aaa", "status": "Running"},
            {"name": f"isholate-{username}-mmm", "status": "Running"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            entries = _find_isholate_containers(username)

        names = [e["name"] for e in entries]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# list_containers
# ---------------------------------------------------------------------------


class TestListContainers:
    def test_empty_returns_zero_and_no_stdout(self, capsys):
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list([]),
        ):
            rc = list_containers("alice")
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_prints_table_with_headers(self, capsys):
        username = "alice"
        ephemeral = generate_name(username)
        existing = [
            {"name": ephemeral, "status": "Running"},
            {"name": _host_base_name(username, _FAKE_IMAGE), "status": "Stopped"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            rc = list_containers(username)
        assert rc == 0
        out = capsys.readouterr().out
        assert "NAME" in out
        assert "STATE" in out
        assert "KIND" in out
        assert ephemeral in out
        assert "ephemeral" in out
        assert "host-base" in out
        assert "Running" in out
        assert "Stopped" in out

    def test_running_only_filters(self, capsys):
        username = "alice"
        ephemeral_running = generate_name(username)
        ephemeral_stopped = generate_name(username)
        # generate_name is random, ensure the two names differ.
        if ephemeral_running == ephemeral_stopped:
            ephemeral_stopped = ephemeral_stopped + "2"
        existing = [
            {"name": ephemeral_running, "status": "Running"},
            {"name": ephemeral_stopped, "status": "Stopped"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            rc = list_containers(username, running_only=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert ephemeral_running in out
        assert ephemeral_stopped not in out

    def test_no_bases_hides_bases(self, capsys):
        username = "alice"
        ephemeral = generate_name(username)
        host_base = _host_base_name(username, _FAKE_IMAGE)
        existing = [
            {"name": ephemeral, "status": "Running"},
            {"name": host_base, "status": "Stopped"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            list_containers(username, include_bases=False)
        out = capsys.readouterr().out
        assert ephemeral in out
        assert host_base not in out

    def test_all_users_adds_user_column(self, capsys):
        existing = [
            {"name": generate_name("alice"), "status": "Running"},
            {"name": generate_name("bob"), "status": "Running"},
        ]
        with patch(
            "pyishlib.container.incus.subprocess.run",
            side_effect=_fake_incus_list(existing),
        ):
            list_containers("carol", all_users=True)
        out = capsys.readouterr().out
        assert "USER" in out
        assert "alice" in out
        assert "bob" in out


# ---------------------------------------------------------------------------
# stop_containers
# ---------------------------------------------------------------------------


class TestStopContainers:
    def _run_stop(
        self, username, existing_containers, *, names=None, include_bases=False
    ):
        """Invoke stop_containers with mocked incus list + incus stop."""
        import json

        stop_calls = []
        listing_json = json.dumps(existing_containers)

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["incus", "list", "--format=json"]:
                return SimpleNamespace(returncode=0, stdout=listing_json, stderr="")
            stop_calls.append(list(cmd))
            return SimpleNamespace(returncode=0)

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            rc = stop_containers(username, names=names, include_bases=include_bases)
        return rc, stop_calls

    def test_no_names_stops_all_running_ephemerals(self):
        username = "alice"
        running = generate_name(username)
        stopped = generate_name(username)
        if stopped == running:
            stopped = stopped + "2"
        host_base = _host_base_name(username, _FAKE_IMAGE)
        existing = [
            {"name": running, "status": "Running"},
            {"name": stopped, "status": "Stopped"},
            {"name": host_base, "status": "Running"},
        ]
        rc, calls = self._run_stop(username, existing)
        assert rc == 0
        stopped_names = [c[2] for c in calls if c[:2] == ["incus", "stop"]]
        assert running in stopped_names
        assert stopped not in stopped_names
        # Bases are NOT stopped without --all.
        assert host_base not in stopped_names

    def test_no_names_no_running_returns_zero(self):
        username = "alice"
        existing = [{"name": generate_name(username), "status": "Stopped"}]
        rc, calls = self._run_stop(username, existing)
        assert rc == 0
        stopped = [c for c in calls if c[:2] == ["incus", "stop"]]
        assert stopped == []

    def test_include_bases_also_stops_running_bases(self):
        username = "alice"
        ephemeral = generate_name(username)
        host_base = _host_base_name(username, _FAKE_IMAGE)
        existing = [
            {"name": ephemeral, "status": "Running"},
            {"name": host_base, "status": "Running"},
        ]
        rc, calls = self._run_stop(username, existing, include_bases=True)
        assert rc == 0
        stopped_names = [c[2] for c in calls if c[:2] == ["incus", "stop"]]
        assert ephemeral in stopped_names
        assert host_base in stopped_names

    def test_explicit_name_running(self):
        username = "alice"
        name = generate_name(username)
        existing = [{"name": name, "status": "Running"}]
        rc, calls = self._run_stop(username, existing, names=[name])
        assert rc == 0
        stopped_names = [c[2] for c in calls if c[:2] == ["incus", "stop"]]
        assert stopped_names == [name]

    def test_explicit_name_already_stopped_skipped(self):
        username = "alice"
        name = generate_name(username)
        existing = [{"name": name, "status": "Stopped"}]
        rc, calls = self._run_stop(username, existing, names=[name])
        assert rc == 0
        stopped = [c for c in calls if c[:2] == ["incus", "stop"]]
        assert stopped == []

    def test_unknown_name_returns_one(self):
        username = "alice"
        existing = [{"name": generate_name(username), "status": "Running"}]
        rc, calls = self._run_stop(username, existing, names=["bogus-name"])
        assert rc == 1
        stopped = [c for c in calls if c[:2] == ["incus", "stop"]]
        assert stopped == []

    def test_stop_failure_returns_one(self):
        import json

        username = "alice"
        name = generate_name(username)
        existing = [{"name": name, "status": "Running"}]
        listing_json = json.dumps(existing)

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["incus", "list", "--format=json"]:
                return SimpleNamespace(returncode=0, stdout=listing_json, stderr="")
            return SimpleNamespace(returncode=1)

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            rc = stop_containers(username, names=[name])
        assert rc == 1


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
                "pyishlib.container.incus._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.container.incus.subprocess.run",
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

        # Must create container first (without starting), with nesting enabled
        init_cmd = next(
            (
                c
                for c in cmds
                if c[:4] == ["incus", "init", _FAKE_IMAGE, "test-container"]
            ),
            None,
        )
        assert init_cmd is not None, "incus init not found in commands"
        assert "--config" in init_cmd, "incus init missing --config flag"
        assert "security.nesting=true" in init_cmd, (
            "incus init missing security.nesting=true"
        )

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
        # _FAKE_SHELL is /bin/bash which is in the login-flag allowlist,
        # so it should be invoked as a login shell (``-l``) so profile
        # files are sourced on container entry.
        assert exec_cmd[-2:] == [_FAKE_SHELL, "-l"]

    def test_exec_unknown_shell_no_login_flag(self):
        """Shells not in the login-flag allowlist are invoked bare so they
        don't bail out on an unsupported ``-l`` flag."""
        args = _make_args(command=[], shell="/bin/dash")
        calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        exec_cmd = next(c for c in cmds if "exec" in c and "--user" in c)
        assert exec_cmd[-1] == "/bin/dash"
        assert "-l" not in exec_cmd

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

    def test_claude_adds_mounts_when_host_config_present(self):
        """--claude mounts ~/.claude and ~/.claude.json into the container."""
        args = _make_args(claude=True)

        def fake_is_dir(self):
            return str(self) == str(_FAKE_HOME / ".claude")

        def fake_is_file(self):
            return str(self) == str(_FAKE_HOME / ".claude.json")

        with patch.object(Path, "is_dir", fake_is_dir):
            with patch.object(Path, "is_file", fake_is_file):
                calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        # Expect two claude mounts, no cwd mount.
        sources = [next(p for p in c if p.startswith("source=")) for c in device_cmds]
        paths = [next(p for p in c if p.startswith("path=")) for c in device_cmds]
        assert f"source={_FAKE_HOME}/.claude" in sources
        assert f"source={_FAKE_HOME}/.claude.json" in sources
        assert f"path=/home/{_FAKE_USER}/.claude" in paths
        assert f"path=/home/{_FAKE_USER}/.claude.json" in paths
        # All claude mounts use shift=true and are not readonly.
        for c in device_cmds:
            assert "shift=true" in c
            assert "readonly=true" not in c

    def test_claude_skips_mounts_when_host_config_absent(self):
        """--claude is a no-op when neither ~/.claude nor ~/.claude.json exist."""
        args = _make_args(claude=True)

        with patch.object(Path, "is_dir", lambda self: False):
            with patch.object(Path, "is_file", lambda self: False):
                calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert device_cmds == []

    def test_claude_base_adds_credentials_mount_when_present(self):
        """--claude-base mounts ~/.claude/.credentials.json even with no host
        ~/.claude.json (push of synthetic .claude.json is skipped with a warn).
        """
        args = _make_args(claude_base=True)
        cred_path = _FAKE_HOME / ".claude" / ".credentials.json"

        with patch.object(Path, "is_file", lambda self: str(self) == str(cred_path)):
            with patch.object(Path, "is_dir", lambda self: False):
                calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1
        cmd = device_cmds[0]
        assert cmd[5] == "isholate-claude-cred"
        assert f"source={cred_path}" in cmd
        assert f"path=/home/{_FAKE_USER}/.claude/.credentials.json" in cmd
        assert "shift=true" in cmd
        assert "readonly=true" not in cmd

        # No synthetic .claude.json push happens when host config is missing.
        push_cmds = [c for c in cmds if c[:3] == ["incus", "file", "push"]]
        assert push_cmds == []

    def test_claude_base_is_noop_when_credentials_absent(self):
        """--claude-base is a no-op when ~/.claude/.credentials.json does not exist."""
        args = _make_args(claude_base=True)

        with patch.object(Path, "is_file", lambda self: False):
            with patch.object(Path, "is_dir", lambda self: False):
                calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert device_cmds == []
        push_cmds = [c for c in cmds if c[:3] == ["incus", "file", "push"]]
        assert push_cmds == []

    def test_claude_base_pushes_synthetic_claude_json(self):
        """When host has usable ~/.claude.json, --claude-base mounts credentials
        and pushes a synthetic ~/.claude.json into the container."""
        args = _make_args(claude_base=True)
        cred_path = _FAKE_HOME / ".claude" / ".credentials.json"

        synthetic = {
            "hasCompletedOnboarding": True,
            "oauthAccount": {"emailAddress": "test@example.com"},
        }

        with patch.object(Path, "is_file", lambda self: str(self) == str(cred_path)):
            with patch.object(Path, "is_dir", lambda self: False):
                with patch(
                    "pyishlib.isholate.claude._build_minimal_claude_json",
                    return_value=synthetic,
                ):
                    calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1
        assert device_cmds[0][5] == "isholate-claude-cred"

        push_cmds = [c for c in cmds if c[:3] == ["incus", "file", "push"]]
        assert len(push_cmds) == 1
        push = push_cmds[0]
        assert "--uid" in push
        assert push[push.index("--uid") + 1] == str(_FAKE_CONTAINER_UID)
        assert "--gid" in push
        assert push[push.index("--gid") + 1] == str(_FAKE_CONTAINER_UID)
        assert "--mode" in push
        assert push[push.index("--mode") + 1] == "600"
        assert push[-1] == f"test-container/home/{_FAKE_USER}/.claude.json"

    def test_claude_base_skips_push_when_no_oauth_account(self):
        """No synthetic .claude.json is pushed when host config lacks oauthAccount."""
        args = _make_args(claude_base=True)
        cred_path = _FAKE_HOME / ".claude" / ".credentials.json"

        with patch.object(Path, "is_file", lambda self: str(self) == str(cred_path)):
            with patch.object(Path, "is_dir", lambda self: False):
                with patch(
                    "pyishlib.isholate.claude._build_minimal_claude_json",
                    return_value=None,
                ):
                    calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1  # credentials mount only
        push_cmds = [c for c in cmds if c[:3] == ["incus", "file", "push"]]
        assert push_cmds == []

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
                "pyishlib.container.incus._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.container.incus.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    rc = launch_and_exec(_make_args())

                assert rc == 1
                cmds = [c.args[0] for c in mock_run.call_args_list]
                assert any(c[:3] == ["incus", "stop", "test-container"] for c in cmds)

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
        import logging
        from pyishlib.ish_logging import setup_logging

        setup_logging(logging.INFO)
        args = _make_args()
        self._run_with_mocks(args)
        err = capsys.readouterr().err
        # Progress messages now go through logging at INFO level with [--] prefix.
        assert "creating container" in err
        assert "starting container" in err
        assert "creating user" in err

    def test_quiet_suppresses_progress_messages(self, capsys):
        import logging
        from pyishlib.ish_logging import setup_logging

        setup_logging(logging.WARNING)
        args = _make_args(quiet=True)
        self._run_with_mocks(args)
        err = capsys.readouterr().err
        # INFO-level progress messages should not appear at WARNING level.
        assert "creating container" not in err


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
            # device list returns valid (empty) JSON so the strict
            # _assert_no_isholate_devices check passes.
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return default

        project_root = overlay.parent.parent if overlay is not None else None

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.container.incus._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.container.incus.subprocess.run",
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

    def test_bootstrap_base_packages(self):
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        # Package install step: python3, sudo, bubblewrap, socat must all be present
        assert any(
            all(pkg in c[-1] for pkg in ("python3", "sudo", "bubblewrap", "socat"))
            for c in sh_cmds
        )
        # npm sandbox-runtime installed as a separate step
        assert any("sandbox-runtime" in c[-1] for c in sh_cmds)
        # The legacy in-container firewall packages must no longer appear
        # in the base bootstrap — restriction is applied via the
        # isholate-claude bridge at the Incus layer.
        pkg_install_scripts = " ".join(
            c[-1] for c in sh_cmds if "apt-get install" in c[-1]
        )
        assert "iptables" not in pkg_install_scripts
        assert "ipset" not in pkg_install_scripts
        assert "dnsmasq" not in pkg_install_scripts

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
        args = _make_args(verbose=True)
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        sh_cmds = [c for c in cmds if "/bin/sh" in c]
        script = sh_cmds[1][-1]
        assert "-qq" not in script

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert any("-v" in c for c in apply_cmds)

    def test_debug_passes_debug_to_ishfiles(self):
        args = _make_args(debug=True)
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert any("--debug" in c for c in apply_cmds)

    def _run_cached_with_claude(self, args, *, claude_dir_exists, claude_json_exists):
        """Run launch_and_exec through the cached path with fine-grained host FS mocks.

        Always marks ``host_ishfiles_source`` as an existing dir (so the cached
        path is actually exercised), and toggles the existence of the host's
        ``~/.claude`` directory and ``~/.claude.json`` file independently.
        """
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            # device list returns valid (empty) JSON so the strict
            # _assert_no_isholate_devices check passes.
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return default

        claude_dir = _FAKE_HOME / ".claude"
        claude_json = _FAKE_HOME / ".claude.json"

        def fake_is_dir(self):
            if self == claude_dir:
                return claude_dir_exists
            return True

        def fake_is_file(self):
            if self == claude_json:
                return claude_json_exists
            return True

        host_source = _FAKE_HOME / ".local" / "share" / "ishfiles"
        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.container.incus._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.container.incus.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    with patch.object(Path, "is_dir", fake_is_dir):
                        with patch.object(Path, "is_file", fake_is_file):
                            launch_and_exec(args, host_ishfiles_source=host_source)
                            return mock_run.call_args_list

    def test_claude_adds_mounts_on_cached_path(self):
        """--claude wires the claude mounts when launching from a cached base."""
        args = _make_args(claude=True)
        calls = self._run_cached_with_claude(
            args, claude_dir_exists=True, claude_json_exists=True
        )
        cmds = self._cmds(calls)

        # The cached path uses `incus copy` (not `incus init`) to clone the base.
        assert any(c[:2] == ["incus", "copy"] for c in cmds)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        device_names = [c[5] for c in device_adds]
        assert "isholate-claude" in device_names
        assert "isholate-claude-json" in device_names

        claude_cmd = next(c for c in device_adds if c[5] == "isholate-claude")
        assert f"source={_FAKE_HOME}/.claude" in claude_cmd
        assert f"path=/home/{_FAKE_USER}/.claude" in claude_cmd
        assert "shift=true" in claude_cmd
        assert "readonly=true" not in claude_cmd

        json_cmd = next(c for c in device_adds if c[5] == "isholate-claude-json")
        assert f"source={_FAKE_HOME}/.claude.json" in json_cmd
        assert f"path=/home/{_FAKE_USER}/.claude.json" in json_cmd
        assert "shift=true" in json_cmd
        assert "readonly=true" not in json_cmd

    def test_claude_cached_path_skips_mounts_when_host_config_absent(self):
        """--claude is a no-op on the cached path when no host claude config exists."""
        args = _make_args(claude=True)
        calls = self._run_cached_with_claude(
            args, claude_dir_exists=False, claude_json_exists=False
        )
        cmds = self._cmds(calls)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        device_names = [c[5] for c in device_adds]
        assert "isholate-claude" not in device_names
        assert "isholate-claude-json" not in device_names

    def test_claude_cached_path_skips_mounts_when_claude_flag_absent(self):
        """Without --claude, no claude mounts are added on the cached path."""
        args = _make_args(claude=False)
        calls = self._run_cached_with_claude(
            args, claude_dir_exists=True, claude_json_exists=True
        )
        cmds = self._cmds(calls)

        device_adds = [c for c in cmds if "device" in c and "add" in c]
        device_names = [c[5] for c in device_adds]
        assert "isholate-claude" not in device_names
        assert "isholate-claude-json" not in device_names

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

    def test_custom_username_passed_to_ishfiles(self):
        """ishfiles apply receives --custom-username <host_user> during provisioning."""
        args = _make_args()
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        calls, _ = self._run_with_mocks(args, host_source=fake_src)
        cmds = self._cmds(calls)

        apply_cmds = [c for c in cmds if "ishfiles" in str(c) and "apply" in c]
        assert len(apply_cmds) >= 1
        for cmd in apply_cmds:
            assert "--custom-username" in cmd, (
                f"--custom-username missing from ishfiles apply command: {cmd}"
            )
            idx = cmd.index("--custom-username")
            assert cmd[idx + 1] == _FAKE_USER, (
                f"Expected username {_FAKE_USER!r}, got {cmd[idx + 1]!r}"
            )


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
        log_level=logging.WARNING,
        quiet=True,
    ):
        """Run ensure_host_base with mocked Incus calls."""
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            # Return the stored fingerprint for config get of source_hash
            if cmd[:3] == ["incus", "config", "get"] and _META_SOURCE_HASH in cmd:
                fp = stored_fp or ""
                return SimpleNamespace(returncode=0, stdout=fp, stderr="")
            # incus info returns success iff container_exists
            if cmd[:2] == ["incus", "info"]:
                rc = 0 if container_exists else 1
                return SimpleNamespace(returncode=rc, stdout="", stderr="")
            # device list returns a valid (empty) JSON object so the strict
            # _assert_no_isholate_devices check passes.
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return default

        calls = []

        def recording_run(cmd, **kwargs):
            calls.append(cmd)
            return fake_run(cmd, **kwargs)

        with patch("pyishlib.container.incus._run", side_effect=recording_run):
            with patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ):
                with patch.object(Path, "is_dir", return_value=True):
                    with patch(
                        "pyishlib.isholate.container._host_base_fingerprint",
                        return_value="COMPUTED",
                    ):
                        name = ensure_host_base(
                            _FAKE_IMAGE,
                            _FAKE_USER,
                            host_source,
                            None,
                            _FAKE_SHELL,
                            log_level=log_level,
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
        # Must delete the stale base and create a new one with nesting enabled
        assert any(c[:2] == ["incus", "delete"] for c in cmds)
        init_cmd = next((c for c in cmds if c[:2] == ["incus", "init"]), None)
        assert init_cmd is not None
        assert "--config" in init_cmd and "security.nesting=true" in init_cmd

    def test_creates_base_when_it_does_not_exist(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(
            fake_src, stored_fp=None, container_exists=False
        )
        cmds = calls
        init_cmd = next((c for c in cmds if c[:2] == ["incus", "init"]), None)
        assert init_cmd is not None
        assert "--config" in init_cmd and "security.nesting=true" in init_cmd
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
        init_cmd = next((c for c in cmds if c[:2] == ["incus", "init"]), None)
        assert init_cmd is not None
        assert "--config" in init_cmd and "security.nesting=true" in init_cmd

    def test_base_is_stopped_after_creation(self):
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        name, calls = self._run_ensure_host_base(fake_src, container_exists=False)
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
            # device list returns valid (empty) JSON so the strict
            # _assert_no_isholate_devices check passes.
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return default

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch("pyishlib.container.incus._run", side_effect=fake_run):
                with patch(
                    "pyishlib.container.incus.subprocess.run",
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
# Stale device cleanup (regression: "The device already exists")
# ---------------------------------------------------------------------------


class TestStaleDeviceHandling:
    """Regression tests for stale isholate-* device cleanup on base containers.

    ``incus config device list`` prints one device name per line (plain text).
    Mocks must use that format, not JSON.
    """

    # Plain-text output as returned by ``incus config device list``.
    _STALE_OUTPUT = "isholate-ishlib\n"

    def _make_pbase_run(self, *, stale_output=None):
        """Return a (fake_run, calls) pair for ensure_project_base.

        Mocks _container_exists (no pbase), fingerprint lookups, and
        optionally returns stale plain-text output on the first device list
        call (subsequent calls return empty, simulating successful removal).
        """
        default = SimpleNamespace(returncode=0, stdout="", stderr="")
        calls = []
        device_list_count = [0]

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["incus", "info"]:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr=""
                )  # pbase absent
            if cmd[:3] == ["incus", "config", "get"] and "source_hash" in str(cmd):
                # host_base fingerprint lookup
                if _FAKE_BASE_NAME in cmd:
                    return SimpleNamespace(returncode=0, stdout="HOST_FP\n", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[:4] == ["incus", "config", "device", "list"]:
                device_list_count[0] += 1
                if device_list_count[0] == 1 and stale_output:
                    return SimpleNamespace(returncode=0, stdout=stale_output, stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return default

        return fake_run, calls

    def test_pbase_strips_inherited_devices_before_start(self):
        """ensure_project_base must remove inherited isholate-* devices before incus start."""
        fake_run, calls = self._make_pbase_run(stale_output=self._STALE_OUTPUT)

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            with patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ):
                with patch(
                    "pyishlib.isholate.container._source_fingerprint",
                    return_value="OVERLAY_FP",
                ):
                    ensure_project_base(
                        _FAKE_BASE_NAME,
                        _FAKE_USER,
                        _FAKE_CWD / ".ishlib" / "ishfiles",
                        project_root=_FAKE_CWD,
                        quiet=True,
                    )

        pbase_name = _FAKE_PBASE_NAME
        remove_idx = next(
            (
                i
                for i, c in enumerate(calls)
                if c[:4] == ["incus", "config", "device", "remove"]
                and pbase_name in c
                and "isholate-ishlib" in c
            ),
            None,
        )
        start_idx = next(
            (
                i
                for i, c in enumerate(calls)
                if c[:2] == ["incus", "start"] and pbase_name in c
            ),
            None,
        )

        assert remove_idx is not None, "expected device remove for isholate-ishlib"
        assert start_idx is not None, "expected incus start for pbase"
        assert remove_idx < start_idx, "device remove must precede incus start"

    def test_host_base_reuse_scrubs_stale_devices(self):
        """ensure_host_base must remove stale devices from a reused (cached) base."""
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        default = SimpleNamespace(returncode=0, stdout="", stderr="")
        calls = []
        # Simulate: first list call returns stale, subsequent calls return
        # clean (device removal succeeded).
        device_list_count = [0]

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["incus", "info"]:
                return SimpleNamespace(
                    returncode=0, stdout="", stderr=""
                )  # base exists
            if cmd[:3] == ["incus", "config", "get"] and "source_hash" in str(cmd):
                return SimpleNamespace(returncode=0, stdout="COMPUTED\n", stderr="")
            if cmd[:4] == ["incus", "config", "device", "list"]:
                device_list_count[0] += 1
                if device_list_count[0] == 1:
                    return SimpleNamespace(
                        returncode=0, stdout=self._STALE_OUTPUT, stderr=""
                    )
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return default

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            with patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ):
                with patch.object(Path, "is_dir", return_value=True):
                    with patch(
                        "pyishlib.isholate.container._host_base_fingerprint",
                        return_value="COMPUTED",
                    ):
                        ensure_host_base(
                            _FAKE_IMAGE,
                            _FAKE_USER,
                            fake_src,
                            None,
                            _FAKE_SHELL,
                            quiet=True,
                        )

        remove_calls = [
            c
            for c in calls
            if c[:4] == ["incus", "config", "device", "remove"]
            and "isholate-ishlib" in c
        ]
        assert remove_calls, "expected device remove for stale isholate-ishlib on reuse"

    def test_host_base_new_build_raises_if_devices_remain(self):
        """ensure_host_base raises when device removal silently fails during new build."""
        fake_src = Path("/home/testuser/.local/share/ishfiles")
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["incus", "info"]:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr=""
                )  # base absent
            # device list always returns a stale entry (simulate failed removal)
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(
                    returncode=0, stdout=self._STALE_OUTPUT, stderr=""
                )
            return default

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            with patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ):
                with patch.object(Path, "is_dir", return_value=True):
                    with patch(
                        "pyishlib.isholate.container._host_base_fingerprint",
                        return_value="COMPUTED",
                    ):
                        with pytest.raises(RuntimeError, match="isholate-ishlib"):
                            ensure_host_base(
                                _FAKE_IMAGE,
                                _FAKE_USER,
                                fake_src,
                                None,
                                _FAKE_SHELL,
                                quiet=True,
                            )


# ---------------------------------------------------------------------------
# Parallel-safety: base-build locking
# ---------------------------------------------------------------------------


class TestBaseBuildLocking:
    """Verify that concurrent invocations against the same base serialize,
    while parallel ephemeral launches from an already-valid base do not.
    """

    @staticmethod
    def _redirect_lock_dir(monkeypatch, tmp_path):
        """Point the base-build lock directory at a per-test tmp path.

        LOCKS_STATE_DIR is patched to an absolute path; ``Path.home() /
        <absolute>`` yields the absolute path on POSIX, bypassing $HOME and
        keeping parallel pytest-xdist workers isolated from one another.
        """
        import pyishlib.isholate.locks as locks_mod

        monkeypatch.setattr(locks_mod, "LOCKS_STATE_DIR", tmp_path / "locks")
        # Short poll interval keeps the test snappy.
        monkeypatch.setattr(locks_mod, "_POLL_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(locks_mod, "_WAIT_LOG_AFTER_SECONDS", 0.05)

    def test_concurrent_host_base_builds_serialize(self, tmp_path, monkeypatch):
        """Two threads building the same host base: exactly one ``incus init``
        call; the waiter observes the peer's finished base and returns it."""
        import threading
        import time

        self._redirect_lock_dir(monkeypatch, tmp_path)

        state = {"exists": False, "fingerprint": ""}
        init_calls = []
        init_entered = threading.Event()
        release_init = threading.Event()
        state_lock = threading.Lock()

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["incus", "info"]:
                with state_lock:
                    rc = 0 if state["exists"] else 1
                return SimpleNamespace(returncode=rc, stdout="", stderr="")
            if cmd[:3] == ["incus", "config", "get"] and _META_SOURCE_HASH in cmd:
                with state_lock:
                    fp = state["fingerprint"]
                return SimpleNamespace(returncode=0, stdout=fp, stderr="")
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            if cmd[:2] == ["incus", "init"]:
                init_calls.append(list(cmd))
                init_entered.set()
                # Block until the main thread has confirmed the second
                # worker is queued on the lock.
                assert release_init.wait(timeout=5.0)
                with state_lock:
                    state["exists"] = True
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if (
                cmd[:3] == ["incus", "config", "set"]
                and len(cmd) >= 6
                and cmd[4] == _META_SOURCE_HASH
            ):
                # The build writes the fingerprint last; that is what the
                # waiter observes via the re-check under the lock.
                with state_lock:
                    state["fingerprint"] = cmd[5]
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        results = {}
        errors = {}

        def worker(idx):
            try:
                results[idx] = ensure_host_base(
                    _FAKE_IMAGE,
                    _FAKE_USER,
                    Path("/fake/src"),
                    None,
                    _FAKE_SHELL,
                    quiet=True,
                )
            except Exception as exc:  # pragma: no cover - surfaced via assert
                errors[idx] = exc

        # Patches applied once outside the threads — unittest.mock.patch is
        # not thread-safe, and both workers must see the same mocked state.
        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ), \
            patch.object(Path, "is_dir", return_value=True), \
            patch(
                "pyishlib.isholate.container._host_base_fingerprint",
                return_value="COMPUTED",
            ):
            t1 = threading.Thread(target=worker, args=(1,))
            t2 = threading.Thread(target=worker, args=(2,))
            t1.start()
            # Wait for thread 1 to be blocked inside incus init (i.e. it
            # holds the lock).
            assert init_entered.wait(timeout=5.0), "worker 1 never entered init"
            t2.start()
            # Give t2 time to reach the flock() and block on it.
            time.sleep(0.2)
            # Release t1's init; it finishes, releases the lock; t2 wakes
            # and observes the now-valid base via its locked re-check.
            release_init.set()
            t1.join(timeout=5.0)
            t2.join(timeout=5.0)

        assert not errors, f"worker errors: {errors}"
        assert len(init_calls) == 1, (
            f"expected exactly one incus init under lock, got {len(init_calls)}"
        )
        assert results[1] == results[2] == _FAKE_BASE_NAME

    def test_concurrent_project_base_builds_serialize(self, tmp_path, monkeypatch):
        """Two threads building the same project base: exactly one ``incus
        copy <host_base> <pbase>``; waiter returns the peer's result."""
        import threading
        import time

        self._redirect_lock_dir(monkeypatch, tmp_path)

        # Map container-name -> (exists, fingerprint).  The host base starts
        # out "already built" with a known fingerprint; the project base is
        # initially absent.
        state = {
            _FAKE_BASE_NAME: {"exists": True, "fp": "HOSTFP"},
            _FAKE_PBASE_NAME: {"exists": False, "fp": ""},
        }
        copy_calls = []
        copy_entered = threading.Event()
        release_copy = threading.Event()
        state_lock = threading.Lock()

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["incus", "info"] and len(cmd) >= 3:
                target = cmd[2]
                with state_lock:
                    rc = 0 if state.get(target, {}).get("exists") else 1
                return SimpleNamespace(returncode=rc, stdout="", stderr="")
            if (
                cmd[:3] == ["incus", "config", "get"]
                and _META_SOURCE_HASH in cmd
                and len(cmd) >= 4
            ):
                target = cmd[3]
                with state_lock:
                    fp = state.get(target, {}).get("fp", "")
                return SimpleNamespace(returncode=0, stdout=fp, stderr="")
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            if cmd[:2] == ["incus", "copy"] and len(cmd) >= 4:
                copy_calls.append(list(cmd))
                copy_entered.set()
                assert release_copy.wait(timeout=5.0)
                target = cmd[3]
                with state_lock:
                    state[target] = {"exists": True, "fp": ""}
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if (
                cmd[:3] == ["incus", "config", "set"]
                and len(cmd) >= 6
                and cmd[4] == _META_SOURCE_HASH
            ):
                target = cmd[3]
                with state_lock:
                    state.setdefault(target, {"exists": True, "fp": ""})["fp"] = cmd[5]
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        results = {}
        errors = {}

        def worker(idx):
            try:
                results[idx] = ensure_project_base(
                    _FAKE_BASE_NAME,
                    _FAKE_USER,
                    Path("/fake/overlay"),
                    project_root=Path("/work/myproject"),
                    quiet=True,
                )
            except Exception as exc:  # pragma: no cover
                errors[idx] = exc

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ), \
            patch.object(Path, "is_dir", return_value=True), \
            patch(
                "pyishlib.isholate.container._source_fingerprint",
                return_value="OVERLAYFP",
            ):
            t1 = threading.Thread(target=worker, args=(1,))
            t2 = threading.Thread(target=worker, args=(2,))
            t1.start()
            assert copy_entered.wait(timeout=5.0), "worker 1 never entered copy"
            t2.start()
            time.sleep(0.2)
            release_copy.set()
            t1.join(timeout=5.0)
            t2.join(timeout=5.0)

        assert not errors, f"worker errors: {errors}"
        # Exactly one incus copy <host_base> <pbase> — the waiter must have
        # observed the finished pbase and returned without a second copy.
        pbase_copies = [
            c
            for c in copy_calls
            if len(c) >= 4 and c[2] == _FAKE_BASE_NAME and c[3] == _FAKE_PBASE_NAME
        ]
        assert len(pbase_copies) == 1, (
            f"expected exactly one project-base copy, got {len(pbase_copies)}"
        )
        assert results[1] == results[2] == _FAKE_PBASE_NAME

    def test_parallel_ephemeral_launches_do_not_serialize(self, tmp_path, monkeypatch):
        """Two ensure_host_base calls where the base is already valid must
        not queue on the base-build lock.  Both workers must be able to pass
        through the fast path concurrently."""
        import threading

        self._redirect_lock_dir(monkeypatch, tmp_path)

        in_fast_path = threading.Barrier(2, timeout=5.0)

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["incus", "info"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[:3] == ["incus", "config", "get"] and _META_SOURCE_HASH in cmd:
                # Synchronise both threads inside the fast-path check.  If
                # one were holding the base-build lock, the other could
                # never reach this point — the barrier would time out.
                in_fast_path.wait()
                return SimpleNamespace(returncode=0, stdout="COMPUTED", stderr="")
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        results = {}
        errors = {}

        def worker(idx):
            try:
                results[idx] = ensure_host_base(
                    _FAKE_IMAGE,
                    _FAKE_USER,
                    Path("/fake/src"),
                    None,
                    _FAKE_SHELL,
                    quiet=True,
                )
            except Exception as exc:  # pragma: no cover
                errors[idx] = exc

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ), \
            patch.object(Path, "is_dir", return_value=True), \
            patch(
                "pyishlib.isholate.container._host_base_fingerprint",
                return_value="COMPUTED",
            ):
            t1 = threading.Thread(target=worker, args=(1,))
            t2 = threading.Thread(target=worker, args=(2,))
            t1.start()
            t2.start()
            t1.join(timeout=5.0)
            t2.join(timeout=5.0)

        assert not errors, f"worker errors: {errors}"
        assert results[1] == results[2] == _FAKE_BASE_NAME

    def test_double_check_elides_redundant_rebuild(self, tmp_path, monkeypatch):
        """A single caller with an up-to-date base issues no incus init or
        incus delete — proves the double-checked fast path still works after
        the locking refactor."""
        self._redirect_lock_dir(monkeypatch, tmp_path)

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["incus", "info"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[:3] == ["incus", "config", "get"] and _META_SOURCE_HASH in cmd:
                return SimpleNamespace(returncode=0, stdout="COMPUTED", stderr="")
            if cmd[:4] == ["incus", "config", "device", "list"]:
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            with patch(
                "pyishlib.container.incus.subprocess.run",
                side_effect=_fake_subprocess_run,
            ):
                with patch.object(Path, "is_dir", return_value=True):
                    with patch(
                        "pyishlib.isholate.container._host_base_fingerprint",
                        return_value="COMPUTED",
                    ):
                        name = ensure_host_base(
                            _FAKE_IMAGE,
                            _FAKE_USER,
                            Path("/fake/src"),
                            None,
                            _FAKE_SHELL,
                            quiet=True,
                        )

        assert name == _FAKE_BASE_NAME
        assert not any(c[:2] == ["incus", "init"] for c in calls)
        assert not any(c[:2] == ["incus", "delete"] for c in calls)


# ---------------------------------------------------------------------------
# Network pre-flight
# ---------------------------------------------------------------------------


class TestNetworkPreflight:
    """Tests for _network_preflight behaviour in launch_and_exec."""

    def _run_with_mocks_custom(self, args, fake_run_fn, host_source=None):
        """Like TestProvisioning._run_with_mocks but accepts a custom fake_run."""

        def wrapped_run(cmd, **kwargs):
            # device list returns valid (empty) JSON so the strict
            # _assert_no_isholate_devices check passes, unless the custom
            # fake_run handles the call itself.
            if cmd[:4] == ["incus", "config", "device", "list"]:
                result = fake_run_fn(cmd, **kwargs)
                if not getattr(result, "stdout", "").strip():
                    return SimpleNamespace(returncode=0, stdout="{}", stderr="")
                return result
            return fake_run_fn(cmd, **kwargs)

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.container.incus._run", side_effect=wrapped_run
            ) as mock_run:
                with patch(
                    "pyishlib.container.incus.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    with patch.object(Path, "is_dir", return_value=True):
                        rc = launch_and_exec(args, host_ishfiles_source=host_source)
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
        with patch("pyishlib.isholate.cli.check_incus_available", return_value=None):
            yield

    def test_subcommand_is_required(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_bare_isholate_dispatches_to_run(self):
        """Running `isholate` with no arguments should open a shell via `run`."""
        with patch(
            "pyishlib.isholate.commands.run.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.run._run_subcommand", return_value=0
            ) as mock_run:
                assert cli_main([]) == 0
        args = mock_run.call_args.args[0]
        assert args.subcommand == "run"
        assert args.command == []

    def test_run_defaults(self):
        from pyishlib.isholate.cli import DEFAULT_IMAGE, DEFAULT_SHELL

        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.subcommand == "run"
        assert args.image == DEFAULT_IMAGE
        assert args.shell == DEFAULT_SHELL
        assert args.rw_cwd is False
        assert args.ro_cwd is False
        assert args.claude is False
        assert args.no_host_ishfiles is False
        assert args.no_project_ishfiles is False
        assert args.no_cache is False
        assert args.rebuild is False
        assert args.rebuild_base is False
        assert args.rebuild_project_base is False
        assert args.verbose == 0
        assert args.quiet is False
        assert args.command == []

    def test_claude_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--claude"])
        assert args.claude is True

    def test_rw_cwd_and_ro_cwd_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--rw-cwd", "--ro-cwd"])

    def test_custom_image(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--image", "images:ubuntu/22.04"])
        assert args.image == "images:ubuntu/22.04"

    def test_no_host_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-host-ishfiles"])
        assert args.no_host_ishfiles is True

    def test_no_project_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-project-ishfiles"])
        assert args.no_project_ishfiles is True

    def test_no_ishfiles_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-ishfiles"])
        assert args.no_ishfiles is True

    def test_no_cache_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-cache"])
        assert args.no_cache is True

    def test_rebuild_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--rebuild"])
        assert args.rebuild is True

    def test_rebuild_base_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--rebuild-base"])
        assert args.rebuild_base is True

    def test_rebuild_project_base_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--rebuild-project-base"])
        assert args.rebuild_project_base is True

    def test_rebuild_flags_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--rebuild", "--rebuild-base"])

    def test_purge_flags_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["purge", "--bases", "--all"])

    def test_purge_bases_flag(self):
        parser = build_parser()
        args = parser.parse_args(["purge", "--bases"])
        assert args.subcommand == "purge"
        assert args.bases is True
        assert args.bases_alias is False

    def test_purge_all_flag(self):
        parser = build_parser()
        args = parser.parse_args(["purge", "--all"])
        assert args.subcommand == "purge"
        assert args.bases is False
        assert args.bases_alias is True

    def test_purge_plain(self):
        parser = build_parser()
        args = parser.parse_args(["purge"])
        assert args.subcommand == "purge"
        assert args.bases is False
        assert args.bases_alias is False

    def test_list_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["list"])
        assert args.subcommand == "list"
        assert args.running is False
        assert args.all_users is False
        assert args.no_bases is False

    def test_list_flags(self):
        parser = build_parser()
        args = parser.parse_args(["list", "--running", "--all-users", "--no-bases"])
        assert args.running is True
        assert args.all_users is True
        assert args.no_bases is True

    def test_stop_no_names(self):
        parser = build_parser()
        args = parser.parse_args(["stop"])
        assert args.subcommand == "stop"
        assert args.names == []
        assert args.include_bases is False

    def test_stop_with_names(self):
        parser = build_parser()
        args = parser.parse_args(["stop", "foo", "bar"])
        assert args.names == ["foo", "bar"]

    def test_stop_all(self):
        parser = build_parser()
        args = parser.parse_args(["stop", "--all"])
        assert args.include_bases is True

    def test_no_ishfiles_suppresses_provisioning(self):
        """--no-ishfiles must pass None for both sources to launch_and_exec."""
        with patch("pyishlib.isholate.commands.run.discover_project_overlay", return_value=None):
            with patch(
                "pyishlib.isholate.commands.run.get_host_user_info",
                return_value=_fake_user_info(),
            ):
                with patch(
                    "pyishlib.isholate.commands.run.discover_host_ishfiles_source",
                    return_value=Path("/some/ishfiles"),
                ):
                    with patch(
                        "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
                    ) as mock_launch:
                        cli_main(["run", "--no-ishfiles"])
                        _, kwargs = mock_launch.call_args
                        assert kwargs["host_ishfiles_source"] is None
                        assert kwargs["project_overlay"] is None

    def test_command_passthrough(self):
        parser = build_parser()
        args = parser.parse_args(["run", "ls"])
        assert args.command == ["ls"]

    def test_command_passthrough_with_flags(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--", "ls", "-la"])
        assert args.command == ["--", "ls", "-la"]

    def test_verbose_flag(self):
        parser = build_parser()
        assert parser.parse_args(["run"]).verbose is False
        assert parser.parse_args(["run"]).debug is False
        assert parser.parse_args(["run", "-v"]).verbose is True
        assert parser.parse_args(["run", "--verbose"]).verbose is True
        assert parser.parse_args(["run", "--debug"]).debug is True
        # -v/--debug/-q are available on every subcommand.
        assert parser.parse_args(["purge", "-v"]).verbose is True
        assert parser.parse_args(["list", "-v"]).verbose is True
        assert parser.parse_args(["stop", "-v"]).verbose is True
        assert parser.parse_args(["purge", "--debug"]).debug is True

    def test_quiet_flag(self):
        parser = build_parser()
        args = parser.parse_args(["run", "-q"])
        assert args.quiet is True
        args = parser.parse_args(["run", "--quiet"])
        assert args.quiet is True
        # -q works on every subcommand.
        assert parser.parse_args(["purge", "-q"]).quiet is True

    def test_main_rejects_non_linux(self):
        with patch("sys.platform", "darwin"):
            rc = cli_main(["run"])
        assert rc == 1

    def test_purge_bases_calls_purge_with_include_bases(self):
        """`purge --bases` must call purge_containers with include_bases=True."""
        with patch(
            "pyishlib.isholate.commands.purge.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.purge.purge_containers", return_value=0
            ) as mock_purge:
                cli_main(["purge", "--bases"])
                _, kwargs = mock_purge.call_args
                assert kwargs.get("include_bases") is True

    def test_purge_all_calls_purge_with_include_bases(self):
        """`purge --all` must also call purge_containers with include_bases=True."""
        with patch(
            "pyishlib.isholate.commands.purge.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.purge.purge_containers", return_value=0
            ) as mock_purge:
                cli_main(["purge", "--all"])
                _, kwargs = mock_purge.call_args
                assert kwargs.get("include_bases") is True

    def test_purge_does_not_include_bases(self):
        """Plain `purge` must NOT pass include_bases=True."""
        with patch(
            "pyishlib.isholate.commands.purge.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.purge.purge_containers", return_value=0
            ) as mock_purge:
                cli_main(["purge"])
                _, kwargs = mock_purge.call_args
                assert not kwargs.get("include_bases", False)

    def test_list_dispatch(self):
        """`list` subcommand dispatches to list_containers with the right kwargs."""
        with patch(
            "pyishlib.isholate.commands.list.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.list.list_containers", return_value=0
            ) as mock_list:
                cli_main(["list"])
                _, kwargs = mock_list.call_args
                assert kwargs == {
                    "all_users": False,
                    "running_only": False,
                    "include_bases": True,
                }

    def test_list_dispatch_flags(self):
        with patch(
            "pyishlib.isholate.commands.list.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.list.list_containers", return_value=0
            ) as mock_list:
                cli_main(["list", "--running", "--all-users", "--no-bases"])
                _, kwargs = mock_list.call_args
                assert kwargs == {
                    "all_users": True,
                    "running_only": True,
                    "include_bases": False,
                }

    def test_stop_dispatch_no_names(self):
        with patch(
            "pyishlib.isholate.commands.stop.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.stop.stop_containers", return_value=0
            ) as mock_stop:
                cli_main(["stop"])
                _, kwargs = mock_stop.call_args
                assert kwargs == {"names": None, "include_bases": False}

    def test_stop_dispatch_with_names(self):
        with patch(
            "pyishlib.isholate.commands.stop.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.stop.stop_containers", return_value=0
            ) as mock_stop:
                cli_main(["stop", "a", "b"])
                _, kwargs = mock_stop.call_args
                assert kwargs == {"names": ["a", "b"], "include_bases": False}

    def test_stop_dispatch_all(self):
        with patch(
            "pyishlib.isholate.commands.stop.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.isholate.commands.stop.stop_containers", return_value=0
            ) as mock_stop:
                cli_main(["stop", "--all"])
                _, kwargs = mock_stop.call_args
                assert kwargs == {"names": None, "include_bases": True}

    def test_list_does_not_call_launch_and_exec(self):
        with patch(
            "pyishlib.isholate.commands.list.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch("pyishlib.isholate.commands.list.list_containers", return_value=0):
                with patch(
                    "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
                ) as mock_launch:
                    cli_main(["list"])
                    mock_launch.assert_not_called()

    def test_project_config_overrides_image_default(self, tmp_path):
        """Image from .ishlib/isholate/config.toml becomes the argparse default."""
        overlay = tmp_path / ".ishlib" / "ishfiles"
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        (tmp_path / ".ishlib" / "isholate" / "config.toml").write_text(
            'image = "images:debian/12"\n'
        )
        with patch(
            "pyishlib.isholate.commands.run.discover_project_overlay", return_value=overlay
        ):
            with patch(
                "pyishlib.isholate.commands.run.load_project_config",
                return_value={"image": "images:debian/12"},
            ):
                with patch(
                    "pyishlib.isholate.commands.run.get_host_user_info",
                    return_value=_fake_user_info(),
                ):
                    with patch(
                        "pyishlib.isholate.commands.run.discover_host_ishfiles_source",
                        return_value=None,
                    ):
                        with patch(
                            "pyishlib.isholate.commands.run.launch_and_exec",
                            return_value=0,
                        ) as mock_launch:
                            cli_main(["run"])
                            called_args = mock_launch.call_args[0][0]
                            assert called_args.image == "images:debian/12"

    def test_cli_image_flag_overrides_project_config(self, tmp_path):
        """--image CLI flag takes priority over .ishlib/isholate/config.toml."""
        with patch("pyishlib.isholate.commands.run.discover_project_overlay", return_value=None):
            with patch(
                "pyishlib.isholate.commands.run.get_host_user_info",
                return_value=_fake_user_info(),
            ):
                with patch(
                    "pyishlib.isholate.commands.run.discover_host_ishfiles_source",
                    return_value=None,
                ):
                    with patch(
                        "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
                    ) as mock_launch:
                        cli_main(["run", "--image", "images:ubuntu/22.04"])
                        called_args = mock_launch.call_args[0][0]
                        assert called_args.image == "images:ubuntu/22.04"

    def test_rebuild_wires_flags_to_launch_and_exec(self):
        """--rebuild must set rebuild_base=True and rebuild_project_base=True on args."""
        with patch("pyishlib.isholate.commands.run.discover_project_overlay", return_value=None):
            with patch(
                "pyishlib.isholate.commands.run.get_host_user_info",
                return_value=_fake_user_info(),
            ):
                with patch(
                    "pyishlib.isholate.commands.run.discover_host_ishfiles_source",
                    return_value=None,
                ):
                    with patch(
                        "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
                    ) as mock_launch:
                        cli_main(["run", "--rebuild"])
                        called_args = mock_launch.call_args[0][0]
                        assert called_args.rebuild_base is True
                        assert called_args.rebuild_project_base is True

    def test_project_root_picks_up_overlay_outside_cwd(self, tmp_path):
        """--project-root causes overlay discovery to use the given dir, not cwd."""
        overlay = tmp_path / ".ishlib" / "ishfiles"
        overlay.mkdir(parents=True)
        other_cwd = tmp_path / "other"
        other_cwd.mkdir()

        # cwd has no overlay; only the explicit project root does.
        _, home, _ = _fake_user_info()
        with patch(
            "pyishlib.isholate.commands.run.get_host_user_info",
            return_value=("testuser", home, other_cwd),
        ):
            with patch(
                "pyishlib.isholate.commands.run.discover_host_ishfiles_source",
                return_value=None,
            ):
                with patch(
                    "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
                ) as mock_launch:
                    result = cli_main(["run", "--project-root", str(tmp_path)])
                    assert result == 0
                    _, kwargs = mock_launch.call_args
                    assert kwargs["project_overlay"] == overlay
                    assert kwargs["project_root"] == tmp_path.resolve()

    def test_project_root_picks_up_config_outside_cwd(self, tmp_path):
        """--project-root causes project config to load from the given dir."""
        (tmp_path / ".ishlib" / "isholate").mkdir(parents=True)
        (tmp_path / ".ishlib" / "isholate" / "config.toml").write_text(
            'image = "images:debian/12"\n'
        )
        other_cwd = tmp_path / "other"
        other_cwd.mkdir()

        _, home, _ = _fake_user_info()
        with patch(
            "pyishlib.isholate.commands.run.get_host_user_info",
            return_value=("testuser", home, other_cwd),
        ):
            with patch(
                "pyishlib.isholate.commands.run.discover_host_ishfiles_source",
                return_value=None,
            ):
                with patch(
                    "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
                ) as mock_launch:
                    result = cli_main(["run", "--project-root", str(tmp_path)])
                    assert result == 0
                    called_args = mock_launch.call_args[0][0]
                    assert called_args.image == "images:debian/12"

    def test_project_root_nonexistent_exits_2(self, tmp_path):
        """--project-root with a non-existent path must exit with code 2."""
        nonexistent = tmp_path / "does-not-exist"
        with patch(
            "pyishlib.isholate.commands.run.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            result = cli_main(["run", "--project-root", str(nonexistent)])
            assert result == 2

    def test_project_root_file_not_directory_exits_2(self, tmp_path):
        """--project-root with a file path (not a dir) must exit with code 2."""
        a_file = tmp_path / "somefile"
        a_file.write_text("hi")
        with patch(
            "pyishlib.isholate.commands.run.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            result = cli_main(["run", "--project-root", str(a_file)])
            assert result == 2


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

    def test_reads_source_from_ishfiles_section(self, tmp_path):
        """Schema-compliant config nests source under [ishfiles]."""
        src = tmp_path / "mysource"
        src.mkdir()
        config_dir = tmp_path / ".config" / "ishfiles"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(f'[ishfiles]\nsource = "{src}"\n')
        result = discover_host_ishfiles_source(tmp_path)
        assert result == src

    def test_ishfiles_section_beats_top_level(self, tmp_path):
        """[ishfiles].source takes precedence over a top-level source key."""
        nested_src = tmp_path / "nested"
        nested_src.mkdir()
        top_src = tmp_path / "top"
        top_src.mkdir()
        config_dir = tmp_path / ".config" / "ishfiles"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text(
            f'source = "{top_src}"\n[ishfiles]\nsource = "{nested_src}"\n'
        )
        result = discover_host_ishfiles_source(tmp_path)
        assert result == nested_src

    def test_falls_back_to_default_path(self, tmp_path):
        default_src = tmp_path / ".local" / "share" / "ishfiles"
        default_src.mkdir(parents=True)
        result = discover_host_ishfiles_source(tmp_path)
        assert result == default_src

    def test_source_from_config_must_exist(self, tmp_path):
        config_dir = tmp_path / ".config" / "ishfiles"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('source = "/nonexistent/path"\n')
        result = discover_host_ishfiles_source(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# resolve_default_shell — ishfiles default_shell resolution
# ---------------------------------------------------------------------------


class TestResolveDefaultShell:
    """Tests for resolve_default_shell()."""

    def _write_ishfiles_config(self, path, default_shell):
        """Write a minimal ishfiles config.toml with default_shell."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'[ishfiles]\ndefault_shell = "{default_shell}"\n')

    def test_returns_none_when_nothing_configured(self, tmp_path):
        result = resolve_default_shell(tmp_path, None, None)
        assert result is None

    def test_reads_from_host_user_config(self, tmp_path):
        self._write_ishfiles_config(
            tmp_path / ".config" / "ishfiles" / "config.toml", "/bin/zsh"
        )
        result = resolve_default_shell(tmp_path, None, None)
        assert result == "/bin/zsh"

    def test_reads_from_host_repo_config(self, tmp_path):
        host_src = tmp_path / "ishfiles-src"
        self._write_ishfiles_config(host_src / "ishconfig" / "config.toml", "/bin/fish")
        result = resolve_default_shell(tmp_path, host_src, None)
        assert result == "/bin/fish"

    def test_host_user_config_beats_host_repo_config(self, tmp_path):
        self._write_ishfiles_config(
            tmp_path / ".config" / "ishfiles" / "config.toml", "/bin/zsh"
        )
        host_src = tmp_path / "ishfiles-src"
        self._write_ishfiles_config(host_src / "ishconfig" / "config.toml", "/bin/fish")
        result = resolve_default_shell(tmp_path, host_src, None)
        assert result == "/bin/zsh"

    def test_project_overlay_beats_host_user_config(self, tmp_path):
        self._write_ishfiles_config(
            tmp_path / ".config" / "ishfiles" / "config.toml", "/bin/zsh"
        )
        overlay = tmp_path / "project" / ".ishlib" / "ishfiles"
        self._write_ishfiles_config(overlay / "ishconfig" / "config.toml", "/bin/fish")
        result = resolve_default_shell(tmp_path, None, overlay)
        assert result == "/bin/fish"

    def test_basename_normalised_to_absolute(self, tmp_path):
        self._write_ishfiles_config(
            tmp_path / ".config" / "ishfiles" / "config.toml", "zsh"
        )
        result = resolve_default_shell(tmp_path, None, None)
        assert result == "/bin/zsh"

    def test_absolute_path_passed_through(self, tmp_path):
        self._write_ishfiles_config(
            tmp_path / ".config" / "ishfiles" / "config.toml", "/usr/bin/zsh"
        )
        result = resolve_default_shell(tmp_path, None, None)
        assert result == "/usr/bin/zsh"

    def test_empty_value_returns_none(self, tmp_path):
        cfg = tmp_path / ".config" / "ishfiles" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[ishfiles]\ndefault_shell = ""\n')
        result = resolve_default_shell(tmp_path, None, None)
        assert result is None

    def test_missing_ishfiles_section_returns_none(self, tmp_path):
        cfg = tmp_path / ".config" / "ishfiles" / "config.toml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('source = "/some/path"\n')
        result = resolve_default_shell(tmp_path, None, None)
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
            "pyishlib.container.incus.subprocess.run",
            return_value=result,
        )

    def test_missing_binary_debian(self):
        with patch("pyishlib.container.incus.shutil.which", return_value=None):
            with patch("pyishlib.container.incus.detect_distro", return_value="debian"):
                msg = check_incus_available()
        assert msg is not None
        assert "not found on PATH" in msg
        assert "apt install incus" in msg

    def test_missing_binary_fedora(self):
        with patch("pyishlib.container.incus.shutil.which", return_value=None):
            with patch("pyishlib.container.incus.detect_distro", return_value="fedora"):
                msg = check_incus_available()
        assert msg is not None
        assert "dnf install incus" in msg

    def test_missing_binary_unknown_distro(self):
        with patch("pyishlib.container.incus.shutil.which", return_value=None):
            with patch("pyishlib.container.incus.detect_distro", return_value=None):
                msg = check_incus_available()
        assert msg is not None
        # Match on the path substring rather than a full hostname so the
        # test doesn't look like URL-origin validation to static analysers.
        assert "linuxcontainers" in msg

    def test_healthy_returns_none(self):
        with patch(
            "pyishlib.container.incus.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(0):
                assert check_incus_available() is None

    def test_permission_denied(self):
        with patch(
            "pyishlib.container.incus.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                1, stderr="Error: permission denied on /var/lib/incus/unix.socket"
            ):
                msg = check_incus_available()
        assert msg is not None
        assert "permission denied" in msg.lower()
        assert "usermod -aG incus-admin" in msg
        assert "newgrp incus-admin" in msg

    def test_daemon_not_initialized(self):
        with patch(
            "pyishlib.container.incus.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                1, stderr="Error: Daemon is not initialized, run 'incus admin init'"
            ):
                msg = check_incus_available()
        assert msg is not None
        assert "incus admin init" in msg

    def test_connection_refused(self):
        with patch(
            "pyishlib.container.incus.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                1,
                stderr="dial unix /var/lib/incus/unix.socket: connect: connection refused",
            ):
                msg = check_incus_available()
        assert msg is not None
        assert "daemon is not ready" in msg.lower()
        assert "systemctl" in msg

    def test_unknown_failure_surfaces_stderr(self):
        with patch(
            "pyishlib.container.incus.shutil.which", return_value="/usr/bin/incus"
        ):
            with self._patch_incus_info(
                2, stderr="Error: something surprising went wrong"
            ):
                msg = check_incus_available()
        assert msg is not None
        assert "something surprising went wrong" in msg
        assert "exit 2" in msg


class TestCliIncusPreflight:
    """The CLI should bail out with a helpful message when incus isn't usable."""

    def test_main_returns_1_and_prints_guidance(self, capsys):
        with patch(
            "pyishlib.isholate.cli.check_incus_available",
            return_value="isholate: error: TEST GUIDANCE",
        ):
            rc = cli_main(["run"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "TEST GUIDANCE" in captured.err

    def test_help_works_without_incus(self, capsys):
        """`--help` must still print usage on hosts without a healthy incus."""
        with patch(
            "pyishlib.isholate.cli.check_incus_available",
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


# ---------------------------------------------------------------------------
# --no-network flag and _apply_network_restrictions helper
# ---------------------------------------------------------------------------


class TestClaudeCliFlags:
    """--claude and --claude-base flags parse correctly and are mutually exclusive."""

    def test_claude_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.claude is False

    def test_claude_base_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.claude_base is False

    def test_claude_sets_true(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--claude"])
        assert args.claude is True
        assert args.claude_base is False

    def test_claude_base_sets_true(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--claude-base"])
        assert args.claude_base is True
        assert args.claude is False

    def test_claude_and_claude_base_are_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run", "--claude", "--claude-base"])


class TestNoNetworkCliFlag:
    """The --no-network flag parses and stacks with --claude / --claude-base."""

    def test_flag_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.no_network is False

    def test_flag_sets_true(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-network"])
        assert args.no_network is True

    def test_flag_stacks_with_claude(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-network", "--claude"])
        assert args.no_network is True
        assert args.claude is True

    def test_flag_stacks_with_claude_base(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-network", "--claude-base"])
        assert args.no_network is True
        assert args.claude_base is True


class TestClaudeBaseMountsInLaunch:
    """--claude-base wires the credentials mount and the allow_claude bridge."""

    def _run_with_mocks(self, args):
        default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            return default

        with patch(
            "pyishlib.isholate.container.get_host_user_info",
            return_value=_fake_user_info(),
        ):
            with patch(
                "pyishlib.container.incus._run", side_effect=fake_run
            ) as mock_run:
                with patch(
                    "pyishlib.container.incus.subprocess.run",
                    side_effect=_fake_subprocess_run,
                ):
                    rc = launch_and_exec(args)
                    return mock_run.call_args_list, rc

    @staticmethod
    def _cmds(calls):
        return [c.args[0] for c in calls]

    def test_claude_base_adds_credentials_mount_on_launch(self):
        """--claude-base passes the credentials mount through launch_and_exec."""
        args = _make_args(claude_base=True)
        cred_path = _FAKE_HOME / ".claude" / ".credentials.json"

        with patch.object(Path, "is_file", lambda self: str(self) == str(cred_path)):
            with patch.object(Path, "is_dir", lambda self: False):
                calls, _ = self._run_with_mocks(args)
        cmds = self._cmds(calls)

        device_cmds = [c for c in cmds if "device" in c and "add" in c]
        assert len(device_cmds) == 1
        cmd = device_cmds[0]
        assert cmd[5] == "isholate-claude-cred"
        assert f"source={cred_path}" in cmd
        assert "shift=true" in cmd
        assert "readonly=true" not in cmd

    def test_no_network_with_claude_base_uses_allow_claude_bridge(self):
        """--claude-base --no-network passes allow_claude=True to network restrictions."""
        args = _make_args(claude_base=True, no_network=True)
        cred_path = _FAKE_HOME / ".claude" / ".credentials.json"

        with patch(
            "pyishlib.isholate.container._apply_network_restrictions"
        ) as mock_net:
            with patch.object(
                Path, "is_file", lambda self: str(self) == str(cred_path)
            ):
                with patch.object(Path, "is_dir", lambda self: False):
                    self._run_with_mocks(args)

        assert mock_net.called
        _, kwargs = mock_net.call_args
        assert kwargs.get("allow_claude") is True


class TestApplyNetworkRestrictions:
    """Unit tests for _apply_network_restrictions command sequencing."""

    @staticmethod
    def _collect_cmds(calls):
        """Flatten Mock call() objects into their cmd argv lists."""
        cmds = []
        for c in calls:
            if c.args:
                cmds.append(list(c.args[0]))
            elif "cmd" in c.kwargs:
                cmds.append(list(c.kwargs["cmd"]))
        return cmds

    def test_no_claude_detaches_eth0_device(self):
        """Without --claude we remove eth0 at the Incus layer; no iptables."""
        with patch("pyishlib.container.incus._run") as mock_run, \
            patch("pyishlib.container.incus._run_checked") as mock_checked:
            mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
            mock_checked.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            _apply_network_restrictions("ctr", allow_claude=False)

        run_cmds = self._collect_cmds(mock_run.call_args_list)
        checked_cmds = self._collect_cmds(mock_checked.call_args_list)
        all_cmds = run_cmds + checked_cmds

        # A best-effort device-remove is attempted first (via _run, not
        # _run_checked) so the subsequent add succeeds even when eth0 already
        # exists at the instance level.
        remove = [
            cmd
            for cmd in run_cmds
            if cmd == ["incus", "config", "device", "remove", "ctr", "eth0"]
        ]
        assert len(remove) == 1, (
            f"expected one best-effort device-remove call, got {run_cmds}"
        )

        # eth0 is detached via an Incus device-override (not ip link down).
        detach = [
            cmd
            for cmd in checked_cmds
            if cmd == ["incus", "config", "device", "add", "ctr", "eth0", "none"]
        ]
        assert len(detach) == 1, (
            f"expected one Incus device-override call, got {checked_cmds}"
        )

        # The old in-container approach (ip link / sysctl) must NOT appear.
        for cmd in all_cmds:
            joined = " ".join(cmd)
            assert "ip link" not in joined
            assert "disable_ipv6" not in joined

        # No iptables or apt machinery on the no-claude path.
        for cmd in all_cmds:
            joined = " ".join(cmd)
            assert "iptables" not in joined
            assert "apt-get" not in joined

    def test_claude_switches_to_isholate_bridge(self):
        """With --claude we ensure the bridge, ensure host rules, and attach eth0.

        No in-container changes: nothing runs via incus exec inside the
        ephemeral container.  Host-side rules are installed via
        ``_install_claude_firewall`` when not already present; the firewall
        helpers are mocked here and covered by their own suites.
        """
        with patch(
                "pyishlib.isholate.claude._ensure_claude_network",
                return_value=_CLAUDE_NETWORK_NAME,
            ) as mock_ensure, \
            patch(
                "pyishlib.isholate.claude._claude_firewall_rules_in_place",
                return_value=True,
            ) as mock_in_place, \
            patch("pyishlib.isholate.claude._install_claude_firewall") as mock_install, \
            patch("pyishlib.container.incus._run") as mock_run, \
            patch("pyishlib.container.incus._run_checked") as mock_checked:
            mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
            mock_checked.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            _apply_network_restrictions("ctr", allow_claude=True)

        # The bridge is ensured exactly once.
        assert mock_ensure.call_count == 1
        # Firewall state is probed; rules are in place so install is skipped.
        assert mock_in_place.call_count == 1
        assert mock_install.call_count == 0

        run_cmds = self._collect_cmds(mock_run.call_args_list)
        checked_cmds = self._collect_cmds(mock_checked.call_args_list)
        all_cmds = run_cmds + checked_cmds

        # Best-effort device-remove so the subsequent add cannot collide with
        # an existing instance-level override.
        remove = [
            cmd
            for cmd in run_cmds
            if cmd == ["incus", "config", "device", "remove", "ctr", "eth0"]
        ]
        assert len(remove) == 1, (
            f"expected one best-effort device-remove call, got {run_cmds}"
        )

        # eth0 is attached as a nic device on the isholate-claude bridge.
        add_nic = [
            cmd
            for cmd in checked_cmds
            if cmd
            == [
                "incus",
                "config",
                "device",
                "add",
                "ctr",
                "eth0",
                "nic",
                f"network={_CLAUDE_NETWORK_NAME}",
                "name=eth0",
            ]
        ]
        assert len(add_nic) == 1, (
            f"expected one nic device-add call, got {checked_cmds}"
        )

        # No in-container changes: no incus exec calls at all.
        for cmd in all_cmds:
            assert cmd[:2] != ["incus", "exec"], (
                f"no in-container changes expected, got {cmd!r}"
            )

        # The old in-container machinery must NOT appear in _apply_network_*
        # invocations (sudo/iptables are only in _install_claude_firewall,
        # which is mocked out here).
        for cmd in all_cmds:
            joined = " ".join(cmd)
            assert "sudo" not in joined
            assert "iptables" not in joined
            assert "chattr" not in joined
            assert "resolv.conf" not in joined
            assert "disable_ipv6" not in joined

    def test_claude_installs_firewall_when_rules_missing(self):
        """If _claude_firewall_rules_in_place is False, install is invoked."""
        with patch(
                "pyishlib.isholate.claude._ensure_claude_network",
                return_value=_CLAUDE_NETWORK_NAME,
            ), \
            patch(
                "pyishlib.isholate.claude._claude_firewall_rules_in_place",
                return_value=False,
            ), \
            patch("pyishlib.isholate.claude._install_claude_firewall") as mock_install, \
            patch("pyishlib.container.incus._run") as mock_run, \
            patch("pyishlib.container.incus._run_checked") as mock_checked:
            mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
            mock_checked.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            _apply_network_restrictions("ctr", allow_claude=True)

        assert mock_install.call_count == 1


# ---------------------------------------------------------------------------
# _ensure_claude_network and _build_claude_raw_dnsmasq
# ---------------------------------------------------------------------------


class TestBuildClaudeRawDnsmasq:
    """The raw.dnsmasq string must encode the allowlist correctly."""

    def test_contains_catch_all(self):
        """local=/#/ is the NXDOMAIN catch-all for non-allowlisted domains."""
        assert "local=/#/" in _build_claude_raw_dnsmasq()

    def test_contains_server_line_per_domain(self):
        """Every allowlisted domain gets a server= forwarding rule."""
        raw = _build_claude_raw_dnsmasq()
        for domain in _CLAUDE_ALLOW_DOMAINS:
            assert f"server=/{domain}/{_CLAUDE_DNS_UPSTREAM}" in raw, (
                f"missing forward for {domain!r}"
            )

    def test_contains_ipset_directive(self):
        """ipset= populates the host ipset so iptables can match on it."""
        raw = _build_claude_raw_dnsmasq()
        # ipset= takes a slash-separated domain list followed by the set name.
        expected_suffix = f"/{_CLAUDE_IPSET_NAME}"
        ipset_lines = [line for line in raw.split("\n") if line.startswith("ipset=")]
        assert len(ipset_lines) == 1, f"expected one ipset= line, got {ipset_lines!r}"
        line = ipset_lines[0]
        assert line.endswith(expected_suffix)
        for domain in _CLAUDE_ALLOW_DOMAINS:
            assert f"/{domain}" in line, f"ipset= missing domain {domain!r}"

    def test_is_newline_joined(self):
        """Value is one directive per line so Incus writes a valid config."""
        lines = _build_claude_raw_dnsmasq().split("\n")
        # One catch-all + one server= per domain + one ipset= line.
        assert len(lines) == 1 + len(_CLAUDE_ALLOW_DOMAINS) + 1


class TestEnsureClaudeNetwork:
    """The isholate-claude managed network is created once and kept current."""

    @staticmethod
    def _collect_cmds(calls):
        cmds = []
        for c in calls:
            if c.args:
                cmds.append(list(c.args[0]))
            elif "cmd" in c.kwargs:
                cmds.append(list(c.kwargs["cmd"]))
        return cmds

    def test_creates_network_when_absent(self):
        """incus network show non-zero -> create with our flags, then set both
        raw.dnsmasq and ipv4.firewall=false."""

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["incus", "network", "show"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="not found")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run) as mock_run, \
            patch("pyishlib.container.incus._run_checked") as mock_checked:
            mock_checked.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            result = _ensure_claude_network()

        assert result == _CLAUDE_NETWORK_NAME

        run_cmds = self._collect_cmds(mock_run.call_args_list)
        checked_cmds = self._collect_cmds(mock_checked.call_args_list)

        # Existence probe happened.
        assert [
            "incus",
            "network",
            "show",
            _CLAUDE_NETWORK_NAME,
        ] in run_cmds

        # Create call with all expected flags including ipv4.firewall=false
        # so Incus leaves our FORWARD rules alone.
        create_cmds = [
            cmd for cmd in checked_cmds if cmd[:3] == ["incus", "network", "create"]
        ]
        assert len(create_cmds) == 1
        create = create_cmds[0]
        assert _CLAUDE_NETWORK_NAME in create
        assert "ipv4.address=auto" in create
        assert "ipv4.nat=true" in create
        assert "ipv4.firewall=false" in create
        assert "ipv6.address=none" in create

        # Three set calls: raw.dnsmasq, ipv4.firewall=false, and ipv4.nat=true
        # (re-applied even on create so any isholate upgrade that changes them
        # converges).  Key is cmd[4], value is cmd[5] (separate args).
        set_cmds = [
            cmd for cmd in checked_cmds if cmd[:3] == ["incus", "network", "set"]
        ]
        assert len(set_cmds) == 3
        set_keys = {cmd[4] for cmd in set_cmds}
        assert "raw.dnsmasq" in set_keys
        assert "ipv4.firewall" in set_keys
        assert "ipv4.nat" in set_keys

    def test_reuses_existing_network(self):
        """incus network show returns 0 -> skip create, still set both configs."""

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch("pyishlib.container.incus._run_checked") as mock_checked:
            mock_checked.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            _ensure_claude_network()

        checked_cmds = self._collect_cmds(mock_checked.call_args_list)

        # No create call on reuse.
        create_cmds = [
            cmd for cmd in checked_cmds if cmd[:3] == ["incus", "network", "create"]
        ]
        assert create_cmds == []

        # All three set calls still happen so config converges on isholate
        # upgrades.  Key is cmd[4], value is cmd[5] (separate args).
        set_cmds = [
            cmd for cmd in checked_cmds if cmd[:3] == ["incus", "network", "set"]
        ]
        assert len(set_cmds) == 3
        set_keys = {cmd[4] for cmd in set_cmds}
        assert "raw.dnsmasq" in set_keys
        assert "ipv4.firewall" in set_keys
        assert "ipv4.nat" in set_keys

    def test_raw_dnsmasq_value_includes_all_domains_and_ipset(self):
        """The raw.dnsmasq set call carries the full allowlist and ipset= line."""

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch("pyishlib.container.incus._run_checked") as mock_checked:
            mock_checked.return_value = SimpleNamespace(
                returncode=0, stdout="", stderr=""
            )
            _ensure_claude_network()

        raw_sets = [
            cmd
            for cmd in self._collect_cmds(mock_checked.call_args_list)
            if cmd[:3] == ["incus", "network", "set"] and cmd[4] == "raw.dnsmasq"
        ]
        assert len(raw_sets) == 1
        value = raw_sets[0][5]  # key=cmd[4], value=cmd[5] (separate args)
        assert "local=/#/" in value
        for domain in _CLAUDE_ALLOW_DOMAINS:
            assert f"server=/{domain}/{_CLAUDE_DNS_UPSTREAM}" in value
        assert f"/{_CLAUDE_IPSET_NAME}" in value


# ---------------------------------------------------------------------------
# Host firewall: _claude_firewall_rules_in_place / _install_claude_firewall
# ---------------------------------------------------------------------------


class TestClaudeFirewallRulesInPlace:
    """Idempotent check that must not require sudo."""

    def test_returns_true_when_on_disk_matches_and_unit_enabled(self):
        """On-disk content matches + systemd unit enabled -> True."""

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "is-enabled"]:
                return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.isholate.claude._claude_firewall_on_disk_matches",
                return_value=True,
            ):
            assert _claude_firewall_rules_in_place() is True

    def test_returns_false_when_systemd_unit_disabled(self):
        """Unit installed but disabled -> False (reboot would leave host unprotected)."""

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "is-enabled"]:
                return SimpleNamespace(returncode=1, stdout="disabled\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.isholate.claude._claude_firewall_on_disk_matches",
                return_value=True,
            ):
            assert _claude_firewall_rules_in_place() is False

    def test_returns_false_when_on_disk_content_drifts(self):
        """Unit enabled but apply script / unit file stale -> False.

        An isholate upgrade that changes the embedded apply script content
        must trigger a reinstall, otherwise the stale on-disk script would
        restore the old rules on the next reboot.
        """

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.isholate.claude._claude_firewall_on_disk_matches",
                return_value=False,
            ):
            assert _claude_firewall_rules_in_place() is False

    def test_returns_false_when_systemctl_missing(self):
        """FileNotFoundError from missing systemctl -> False, not a traceback."""

        def fake_run(cmd, **kwargs):
            if cmd[:1] == ["systemctl"]:
                raise FileNotFoundError(2, "No such file or directory", "systemctl")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.isholate.claude._claude_firewall_on_disk_matches",
                return_value=True,
            ):
            assert _claude_firewall_rules_in_place() is False

    def test_does_not_invoke_sudo_or_netfilter_tools(self):
        """The check must never spawn sudo, ipset, or iptables.

        Those need root on every modern distro; calling them here would
        either force a sudo prompt on every run (defeating the purpose of
        the check) or always return non-zero and always reinstall.
        """
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")

        with patch("pyishlib.container.incus._run", side_effect=fake_run), \
            patch(
                "pyishlib.isholate.claude._claude_firewall_on_disk_matches",
                return_value=True,
            ):
            _claude_firewall_rules_in_place()

        forbidden = {"sudo", "ipset", "iptables"}
        for cmd in calls:
            assert cmd[0] not in forbidden, (
                f"_claude_firewall_rules_in_place ran forbidden tool: {cmd}"
            )


class TestClaudeFirewallOnDiskMatches:
    """Drift detection: on-disk apply script + systemd unit match embedded."""

    def test_returns_true_when_both_files_match(self, tmp_path):
        """Both files present and identical to the embedded content -> True."""
        from pyishlib.isholate import claude

        apply_path = tmp_path / "apply.sh"
        unit_path = tmp_path / "unit.service"
        apply_path.write_text(claude._CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT)
        unit_path.write_text(claude._CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT)
        with patch.object(claude, "_CLAUDE_FIREWALL_APPLY_SCRIPT", str(apply_path)), \
            patch.object(claude, "_CLAUDE_FIREWALL_SYSTEMD_UNIT", str(unit_path)):
            assert claude._claude_firewall_on_disk_matches() is True

    def test_returns_false_when_apply_script_missing(self, tmp_path):
        """Missing apply script file -> False."""
        from pyishlib.isholate import claude

        unit_path = tmp_path / "unit.service"
        unit_path.write_text(claude._CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT)
        with patch.object(
                claude, "_CLAUDE_FIREWALL_APPLY_SCRIPT", str(tmp_path / "missing.sh")
            ), \
            patch.object(claude, "_CLAUDE_FIREWALL_SYSTEMD_UNIT", str(unit_path)):
            assert claude._claude_firewall_on_disk_matches() is False

    def test_returns_false_when_unit_missing(self, tmp_path):
        """Missing systemd unit file -> False."""
        from pyishlib.isholate import claude

        apply_path = tmp_path / "apply.sh"
        apply_path.write_text(claude._CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT)
        with patch.object(claude, "_CLAUDE_FIREWALL_APPLY_SCRIPT", str(apply_path)), \
            patch.object(
                claude,
                "_CLAUDE_FIREWALL_SYSTEMD_UNIT",
                str(tmp_path / "missing.service"),
            ):
            assert claude._claude_firewall_on_disk_matches() is False

    def test_returns_false_when_apply_script_stale(self, tmp_path):
        """Apply script content drifted from embedded -> False (triggers reinstall)."""
        from pyishlib.isholate import claude

        apply_path = tmp_path / "apply.sh"
        unit_path = tmp_path / "unit.service"
        apply_path.write_text("# stale content from previous isholate version\n")
        unit_path.write_text(claude._CLAUDE_FIREWALL_SYSTEMD_UNIT_CONTENT)
        with patch.object(claude, "_CLAUDE_FIREWALL_APPLY_SCRIPT", str(apply_path)), \
            patch.object(claude, "_CLAUDE_FIREWALL_SYSTEMD_UNIT", str(unit_path)):
            assert claude._claude_firewall_on_disk_matches() is False

    def test_returns_false_when_unit_stale(self, tmp_path):
        """Unit content drifted from embedded -> False."""
        from pyishlib.isholate import claude

        apply_path = tmp_path / "apply.sh"
        unit_path = tmp_path / "unit.service"
        apply_path.write_text(claude._CLAUDE_FIREWALL_APPLY_SCRIPT_CONTENT)
        unit_path.write_text("# stale unit content\n")
        with patch.object(claude, "_CLAUDE_FIREWALL_APPLY_SCRIPT", str(apply_path)), \
            patch.object(claude, "_CLAUDE_FIREWALL_SYSTEMD_UNIT", str(unit_path)):
            assert claude._claude_firewall_on_disk_matches() is False


class TestBuildClaudeFirewallInstallScript:
    """The install script content must encode all the required state."""

    def test_script_writes_apply_script(self):
        """The install script writes the persistent apply helper."""
        script = _build_claude_firewall_install_script()
        assert f"cat > {_CLAUDE_FIREWALL_APPLY_SCRIPT} <<" in script
        assert f"chmod +x {_CLAUDE_FIREWALL_APPLY_SCRIPT}" in script

    def test_script_writes_systemd_unit(self):
        """The install script writes the systemd unit file."""
        script = _build_claude_firewall_install_script()
        assert f"cat > {_CLAUDE_FIREWALL_SYSTEMD_UNIT} <<" in script
        assert "systemctl daemon-reload" in script
        assert "systemctl enable isholate-claude-firewall.service" in script

    def test_script_runs_apply_after_install(self):
        """Rules come into effect immediately, not only after reboot."""
        script = _build_claude_firewall_install_script()
        # The apply script path appears as a standalone command line near the
        # end of the install script.
        lines = script.splitlines()
        assert any(line.strip() == _CLAUDE_FIREWALL_APPLY_SCRIPT for line in lines), (
            "install script must run the apply helper once"
        )

    def test_apply_script_references_ipset_and_chain(self):
        """The embedded apply script must actually configure our set + chain."""
        script = _build_claude_firewall_install_script()
        # These values live inside the heredoc so only need a substring match.
        assert _CLAUDE_IPSET_NAME in script
        assert _CLAUDE_IPTABLES_CHAIN in script
        assert _CLAUDE_NETWORK_NAME in script
        # Core rules we expect to be applied.
        assert "ipset create" in script
        assert "--match-set" in script
        assert "--dport 443" in script


class TestInstallClaudeFirewall:
    """_install_claude_firewall runs the script under sudo and surfaces errors."""

    # All host tools (ipset, iptables, systemctl, sudo) must be present
    # for the sudo invocation to be reached.  ``_all_tools_present`` is
    # the common fake_which used by the happy-path and sudo-failure tests.
    @staticmethod
    def _all_tools_present(tool):
        return f"/usr/bin/{tool}"

    def test_invokes_sudo_with_install_script(self):
        """Install must run sudo /bin/sh -c <install script>."""

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch(
                "pyishlib.isholate.claude.shutil.which",
                side_effect=self._all_tools_present,
            ), \
            patch("pyishlib.container.incus._run", side_effect=fake_run) as mock_run:
            _install_claude_firewall()

        # One _run call, and it's the sudo invocation.
        assert mock_run.call_count == 1
        cmd = mock_run.call_args_list[0].args[0]
        assert cmd[:3] == ["sudo", "/bin/sh", "-c"]
        # The script argument carries the heredoc contents.
        assert _CLAUDE_FIREWALL_APPLY_SCRIPT in cmd[3]

    def test_raises_if_ipset_missing(self):
        """ipset not on PATH -> targeted RuntimeError mentioning ipset."""

        def fake_which(tool):
            return None if tool == "ipset" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            with pytest.raises(RuntimeError) as excinfo:
                _install_claude_firewall()
        msg = str(excinfo.value)
        assert "missing host tools" in msg
        assert "ipset" in msg

    def test_raises_if_iptables_missing(self):
        """iptables not on PATH -> targeted RuntimeError mentioning iptables."""

        def fake_which(tool):
            return None if tool == "iptables" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            with pytest.raises(RuntimeError) as excinfo:
                _install_claude_firewall()
        msg = str(excinfo.value)
        assert "missing host tools" in msg
        assert "iptables" in msg

    def test_raises_if_systemctl_missing(self):
        """systemctl not on PATH -> targeted RuntimeError mentioning systemd."""

        def fake_which(tool):
            return None if tool == "systemctl" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            with pytest.raises(RuntimeError) as excinfo:
                _install_claude_firewall()
        msg = str(excinfo.value)
        assert "missing host tools" in msg
        assert "systemctl" in msg

    def test_raises_if_sudo_missing(self):
        """No sudo on PATH (but host tools present) -> RuntimeError."""

        def fake_which(tool):
            return None if tool == "sudo" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            with pytest.raises(RuntimeError, match="sudo not found"):
                _install_claude_firewall()

    def test_preflight_lists_all_missing_tools(self):
        """Multiple missing tools are reported in a single error."""

        def fake_which(tool):
            # Only systemctl is present; ipset and iptables are missing.
            return "/usr/bin/systemctl" if tool == "systemctl" else None

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            with pytest.raises(RuntimeError) as excinfo:
                _install_claude_firewall()
        msg = str(excinfo.value)
        assert "ipset" in msg
        assert "iptables" in msg

    def test_raises_if_sudo_fails(self):
        """sudo exit != 0 -> RuntimeError."""

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="denied")

        with patch(
                "pyishlib.isholate.claude.shutil.which",
                side_effect=self._all_tools_present,
            ), \
            patch("pyishlib.container.incus._run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="failed to install"):
                _install_claude_firewall()


# ---------------------------------------------------------------------------
# _preflight_claude_host_tools
# ---------------------------------------------------------------------------


class TestPreflightClaudeHostTools:
    """_preflight_claude_host_tools returns None when all tools present,
    or a user-facing message listing each missing tool."""

    @staticmethod
    def _all_present(tool):
        return f"/usr/bin/{tool}"

    def test_returns_none_when_all_tools_present(self):
        """All tools on PATH -> None (no error)."""
        with patch(
            "pyishlib.isholate.claude.shutil.which",
            side_effect=self._all_present,
        ):
            assert _preflight_claude_host_tools() is None

    def test_returns_message_when_ipset_missing(self):
        """Missing ipset -> message mentioning 'ipset'."""

        def fake_which(tool):
            return None if tool == "ipset" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            msg = _preflight_claude_host_tools()
        assert msg is not None
        assert "ipset" in msg

    def test_returns_message_when_iptables_missing(self):
        """Missing iptables -> message mentioning 'iptables'."""

        def fake_which(tool):
            return None if tool == "iptables" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            msg = _preflight_claude_host_tools()
        assert msg is not None
        assert "iptables" in msg

    def test_returns_message_when_systemctl_missing(self):
        """Missing systemctl -> message mentioning 'systemctl'."""

        def fake_which(tool):
            return None if tool == "systemctl" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            msg = _preflight_claude_host_tools()
        assert msg is not None
        assert "systemctl" in msg

    def test_returns_message_when_sudo_missing(self):
        """All firewall tools present but sudo absent -> message mentioning 'sudo'."""

        def fake_which(tool):
            return None if tool == "sudo" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            msg = _preflight_claude_host_tools()
        assert msg is not None
        assert "sudo" in msg

    def test_lists_multiple_missing_tools(self):
        """Multiple missing tools appear together in one message."""

        def fake_which(tool):
            return "/usr/bin/systemctl" if tool == "systemctl" else None

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which):
            msg = _preflight_claude_host_tools()
        assert msg is not None
        assert "ipset" in msg
        assert "iptables" in msg


# ---------------------------------------------------------------------------
# CLI preflight: --no-network --claude fails fast before any container work
# ---------------------------------------------------------------------------


class TestCliPreflightClaudeHostTools:
    """cli.main() checks host tools before launching anything when
    --no-network --claude is requested."""

    def test_returns_error_before_launch_when_tool_missing(self, tmp_path):
        """Missing ipset -> exit 1 without calling launch_and_exec."""

        def fake_which(tool):
            return None if tool == "ipset" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which), \
            patch("pyishlib.isholate.cli.is_linux", return_value=True), \
            patch("pyishlib.isholate.cli.check_incus_available", return_value=None), \
            patch(
                "pyishlib.isholate.commands.run.get_host_user_info",
                return_value=("testuser", tmp_path, tmp_path),
            ), \
            patch("pyishlib.isholate.commands.run.launch_and_exec") as mock_launch:
            rc = cli_main(["run", "--no-network", "--claude"])

        assert rc == 1
        mock_launch.assert_not_called()

    def test_proceeds_when_all_tools_present(self, tmp_path):
        """All tools available -> launch_and_exec is reached."""

        def fake_which(tool):
            return f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which), \
            patch("pyishlib.isholate.cli.is_linux", return_value=True), \
            patch("pyishlib.isholate.cli.check_incus_available", return_value=None), \
            patch(
                "pyishlib.isholate.commands.run.get_host_user_info",
                return_value=("testuser", tmp_path, tmp_path),
            ), \
            patch(
                "pyishlib.isholate.commands.run.discover_host_ishfiles_source", return_value=None
            ), \
            patch("pyishlib.isholate.commands.run.discover_project_overlay", return_value=None), \
            patch("pyishlib.isholate.commands.run.load_project_config", return_value={}), \
            patch("pyishlib.isholate.commands.run.resolve_default_shell", return_value=None), \
            patch(
                "pyishlib.isholate.commands.run.launch_and_exec", return_value=0
            ) as mock_launch:
            rc = cli_main(["run", "--no-network", "--claude"])

        assert rc == 0
        mock_launch.assert_called_once()

    def test_claude_base_also_triggers_preflight(self, tmp_path):
        """--no-network --claude-base gets the same preflight as --claude."""

        def fake_which(tool):
            return None if tool == "ipset" else f"/usr/bin/{tool}"

        with patch("pyishlib.isholate.claude.shutil.which", side_effect=fake_which), \
            patch("pyishlib.isholate.cli.is_linux", return_value=True), \
            patch("pyishlib.isholate.cli.check_incus_available", return_value=None), \
            patch(
                "pyishlib.isholate.commands.run.get_host_user_info",
                return_value=("testuser", tmp_path, tmp_path),
            ), \
            patch("pyishlib.isholate.commands.run.launch_and_exec") as mock_launch:
            rc = cli_main(["run", "--no-network", "--claude-base"])

        assert rc == 1
        mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# _build_minimal_claude_json — pure function tests
# ---------------------------------------------------------------------------


class TestBuildMinimalClaudeJson:
    """Verify the allowlist-only synthesis used by --claude-base."""

    def test_returns_none_when_file_missing(self, tmp_path):
        assert _build_minimal_claude_json(tmp_path) is None

    def test_returns_none_on_invalid_json(self, tmp_path):
        (tmp_path / ".claude.json").write_text("{not json", encoding="utf-8")
        assert _build_minimal_claude_json(tmp_path) is None

    def test_returns_none_without_oauth_account(self, tmp_path):
        import json as _json

        (tmp_path / ".claude.json").write_text(
            _json.dumps({"userID": "abc", "firstStartTime": "t0"}),
            encoding="utf-8",
        )
        assert _build_minimal_claude_json(tmp_path) is None

    def test_returns_none_when_oauth_account_not_dict(self, tmp_path):
        import json as _json

        (tmp_path / ".claude.json").write_text(
            _json.dumps({"oauthAccount": "not a dict"}),
            encoding="utf-8",
        )
        assert _build_minimal_claude_json(tmp_path) is None

    def test_happy_path_copies_allowlisted_fields_only(self, tmp_path):
        import json as _json

        host = {
            "oauthAccount": {"emailAddress": "me@example.com", "accountUuid": "u"},
            "userID": "abc123",
            "firstStartTime": "2026-01-01T00:00:00Z",
            # Fields that must NOT be copied:
            "projects": {"secret-project": {"foo": "bar"}},
            "mcpServers": {"x": {}},
            "promptQueueLog": ["sensitive"],
            "cachedGrowthBookFeatures": {"flag": True},
            "cachedExtraUsageDisabledReason": "something",
        }
        (tmp_path / ".claude.json").write_text(_json.dumps(host), encoding="utf-8")

        out = _build_minimal_claude_json(tmp_path)
        assert out is not None
        # Allowlisted fields are copied verbatim.
        assert out["oauthAccount"] == host["oauthAccount"]
        assert out["userID"] == "abc123"
        assert out["firstStartTime"] == "2026-01-01T00:00:00Z"
        # hasCompletedOnboarding is always True, independent of host.
        assert out["hasCompletedOnboarding"] is True
        # Non-allowlisted fields are dropped.
        for forbidden in (
            "projects",
            "mcpServers",
            "promptQueueLog",
            "cachedGrowthBookFeatures",
            "cachedExtraUsageDisabledReason",
        ):
            assert forbidden not in out

    def test_missing_optional_allowlist_keys_are_dropped(self, tmp_path):
        """userID/firstStartTime are optional — only oauthAccount is required."""
        import json as _json

        (tmp_path / ".claude.json").write_text(
            _json.dumps({"oauthAccount": {"emailAddress": "m@e.com"}}),
            encoding="utf-8",
        )
        out = _build_minimal_claude_json(tmp_path)
        assert out is not None
        assert out == {
            "hasCompletedOnboarding": True,
            "oauthAccount": {"emailAddress": "m@e.com"},
        }
