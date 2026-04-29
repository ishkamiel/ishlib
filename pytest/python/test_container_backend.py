# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Tests for the pyishlib.container backend abstraction.

Covers the ABC contract (``ContainerBackend``), the Incus implementation
(``IncusBackend``), and the ``get_backend`` selection seam.  Subprocess
calls are mocked at the existing ``pyishlib.container.incus._run`` seam
that ``IncusContainer`` and the module-level helpers both go through.
"""

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.container import (  # noqa: E402
    Container,
    ContainerBackend,
    IncusBackend,
    IncusContainer,
    get_backend,
)


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class TestGetBackend:
    def test_default_returns_incus(self):
        backend = get_backend()
        assert isinstance(backend, IncusBackend)
        assert backend.name == "incus"

    def test_explicit_incus(self):
        assert isinstance(get_backend("incus"), IncusBackend)

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="unknown container backend"):
            get_backend("docker")

    def test_name_is_case_insensitive(self):
        assert isinstance(get_backend("INCUS"), IncusBackend)


class TestIncusBackendFactory:
    def test_container_returns_incus_container(self):
        c = IncusBackend().container("foo")
        assert isinstance(c, IncusContainer)
        assert isinstance(c, Container)
        assert c.name == "foo"

    def test_container_factory_is_pure(self):
        # No subprocess calls should happen for the factory; this would
        # raise StopIteration if anything reached for _run.
        with patch("pyishlib.container.incus._run", side_effect=AssertionError):
            IncusBackend().container("foo")


class TestIncusBackendCheckAvailable:
    def test_delegates_to_module_helper(self):
        # When incus reports OK, check_available returns None.
        with patch("pyishlib.container.incus.shutil.which", return_value="/usr/bin/incus"):
            with patch(
                "pyishlib.container.incus._run",
                return_value=_ok(returncode=0),
            ):
                assert IncusBackend().check_available() is None

    def test_returns_guidance_when_missing(self):
        with patch("pyishlib.container.incus.shutil.which", return_value=None):
            msg = IncusBackend().check_available()
            assert msg is not None
            assert "incus" in msg.lower()


class TestIncusBackendListContainers:
    def test_returns_parsed_json(self):
        payload = [
            {"name": "alpha", "status": "Running"},
            {"name": "beta", "status": "Stopped"},
        ]

        def fake_run(cmd, **kwargs):
            assert cmd == ["incus", "list", "--format=json"]
            return _ok(stdout=json.dumps(payload))

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            assert IncusBackend().list_containers() == payload


class TestIncusBackendManagedNetwork:
    def test_supports_managed_networks(self):
        assert IncusBackend().supports_managed_networks is True

    def test_creates_when_missing_and_applies_set_config(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            # First call is "show": pretend missing.
            if cmd[:3] == ["incus", "network", "show"]:
                return _ok(returncode=1, stderr="not found")
            return _ok(returncode=0)

        with patch("pyishlib.container.incus._run", side_effect=fake_run):
            IncusBackend().ensure_managed_network(
                "test-net",
                create_config=["ipv4.address=auto", "ipv4.nat=true"],
                set_config={"ipv4.firewall": "false"},
            )

        assert calls[0] == ["incus", "network", "show", "test-net"]
        assert calls[1] == [
            "incus",
            "network",
            "create",
            "test-net",
            "ipv4.address=auto",
            "ipv4.nat=true",
        ]
        assert calls[2] == [
            "incus",
            "network",
            "set",
            "test-net",
            "ipv4.firewall",
            "false",
        ]


class TestContainerBackendDefaults:
    """Default ABC behaviours for un-overridden methods."""

    class _Stub(ContainerBackend):
        name = "stub"

        def check_available(self):
            return None

        def container(self, name: str):
            raise NotImplementedError

        def list_containers(self):
            return []

    def test_supports_managed_networks_defaults_false(self):
        assert self._Stub().supports_managed_networks is False

    def test_ensure_managed_network_default_raises(self):
        with pytest.raises(NotImplementedError, match="managed networks"):
            self._Stub().ensure_managed_network(
                "x", create_config=[], set_config={}
            )

    def test_apply_no_network_default_raises(self):
        with pytest.raises(NotImplementedError, match="--no-network"):
            self._Stub().apply_no_network(object())  # type: ignore[arg-type]

    def test_apply_claude_default_raises(self):
        with pytest.raises(NotImplementedError, match="--claude"):
            self._Stub().apply_claude_network_isolation(
                object()  # type: ignore[arg-type]
            )
