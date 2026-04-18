# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for package installing tasks"""

from __future__ import annotations

import logging
import sys
from typing import Sequence

from .command_runner import CommandRunner
from .environment import is_windows
from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerPip(InstallerBase):
    """Helper class for managing python packages via pip"""

    INSTALLER_NAME: str = "pip"

    PIP_UPDATE_PKG: dict[str, str] = {
        "name": "pip",
        "pip": "pip",
    }

    def __init__(self, runner: CommandRunner) -> None:
        super().__init__(runner)
        self._pip_cmd: list[str] = self._detect_pip_cmd()

    def _detect_pip_cmd(self) -> list[str]:
        """Detect the pip invocation for the current platform.

        On Windows, pip is often only available as ``python -m pip``
        rather than a standalone ``pip`` or ``pip3`` executable.  The
        detection order is: pip3, pip, then ``sys.executable -m pip``
        (the last one is only tried on Windows).
        """
        if is_windows():
            return ["pip"]
        return ["pip3"]

    def _pkg_key(self) -> str:
        return "pip"

    @property
    def pip_install_cmd(self) -> list[str]:
        """Get the pip install command for the current platform"""
        return list(self._pip_cmd) + ["install", "--user"]

    @property
    def available(self) -> bool:
        """Check if pip is available (with platform-specific fallbacks)."""
        if not self._tool_checked:
            if len(self._pip_cmd) == 1:
                self._tool_available = self.runner.which(self._pip_cmd[0]) is not None
                if not self._tool_available and self._pip_cmd == ["pip3"]:
                    # Fallback: try "pip" if "pip3" is not found
                    self._tool_available = self.runner.which("pip") is not None
                    if self._tool_available:
                        self._pip_cmd = ["pip"]
                if not self._tool_available and is_windows():
                    # Fallback: try "python -m pip" on Windows
                    self._pip_cmd = [sys.executable, "-m", "pip"]
                    self._tool_available = True
            else:
                # Already set to a multi-element command (e.g. python -m pip)
                self._tool_available = True
            self._tool_checked = True
        return self._tool_available

    # Keep has_pip as an alias for backwards compatibility with tests/callers
    @property
    def has_pip(self) -> bool:
        """Alias for :attr:`available`."""
        return self.available

    def _build_install_cmd(self, pkg_names: Sequence[str]) -> Sequence[str]:
        """Pip's install invocation is ``[*pip_cmd, "install", "--user", ...]``."""
        return [*self.pip_install_cmd, *pkg_names]

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a pip package is installed"""
        return self._check_pkg_installed_by_output(
            pkg, [*self._pip_cmd, "list"]
        )

    def update_pkgs(self) -> bool:
        """Update all installed pip packages"""
        self._require_available()

        self.install_pkg_unless_found(self.PIP_UPDATE_PKG)
        self._run_cmd(
            [*self._pip_cmd, "install", "--upgrade", "pip"], action="updating"
        )
        log.warning("pip update not implemented (only updates pip itself)")
        return True
