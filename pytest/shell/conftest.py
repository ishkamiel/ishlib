# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Shell test configuration.

Automatically skips tests when the required shell or tool is not installed:

- Parametrized tests using a ``shell`` fixture value skip when that shell
  binary is absent from PATH.
- Shellcheck tests skip when ``shellcheck`` is not installed.
- The legacy ``prove`` test skips when ``zsh`` is absent (several of the
  legacy TAP tests require it).
"""

import shutil

import pytest

from . import get_src_files, poisix_only_shells, rel_path

_SHELLCHECK_AVAILABLE = bool(shutil.which("shellcheck"))
# Legacy TAP tests (run via prove) require zsh.
_ZSH_AVAILABLE = bool(shutil.which("zsh"))


def pytest_runtest_setup(item):
    """Skip tests for shells or tools that are not installed on this system."""
    params = item.callspec.params if hasattr(item, "callspec") else {}
    shell = params.get("shell")
    if shell and not shutil.which(shell):
        pytest.skip(f"shell not available: {shell}")
    if not _SHELLCHECK_AVAILABLE and "shellcheck" in item.nodeid:
        pytest.skip("shellcheck not installed")
    if not _ZSH_AVAILABLE and "prove" in item.nodeid:
        pytest.skip("zsh not available (required by legacy prove tests)")


@pytest.fixture(scope="session")
def all_src_files():
    return get_src_files()


@pytest.fixture
def project_root():
    return rel_path(".")


@pytest.fixture
def src_folder():
    return rel_path("src")


@pytest.fixture
def ishlib():
    return rel_path("ishlib.sh")


@pytest.fixture
def sh_only():
    return poisix_only_shells
