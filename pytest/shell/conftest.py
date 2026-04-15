#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
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
