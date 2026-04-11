#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import logging
import subprocess
import sys
from subprocess import CompletedProcess, CalledProcessError
from typing import Iterable, Mapping, Sequence

from .command_runner import CommandRunner
from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerPip(InstallerBase):
    """Helper class for managing python packages via pip"""

    INSTALLER_NAME: str = "pip"

    PIP_UPDATE_PKG: Mapping[str, str] = {
        "name": "pip",
        "pip": "pip",
    }

    def __init__(self, runner: CommandRunner) -> None:
        super().__init__(runner)
        self._pip_cmd: Iterable[str] = self._detect_pip_cmd()

    def _detect_pip_cmd(self) -> Iterable[str]:
        """Detect the pip invocation for the current platform.

        On Windows, pip is often only available as ``python -m pip``
        rather than a standalone ``pip`` or ``pip3`` executable.  The
        detection order is: pip3, pip, then ``sys.executable -m pip``
        (the last one is only tried on Windows).
        """
        if sys.platform == "win32":
            return ["pip"]
        return ["pip3"]

    def _pkg_key(self) -> str:
        return "pip"

    @property
    def pip_install_cmd(self) -> Iterable[str]:
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
                if not self._tool_available and sys.platform == "win32":
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

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a pip package is installed"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("Pip not available for %s", pkg.get("name"))
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                list(self._pip_cmd) + ["list"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return pkg["pip"] in result.stdout.decode("utf-8")
        except CalledProcessError as e:
            log.debug("Pip error checking %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of pip packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Sequence[str] = [pkg["pip"] for pkg in pkgs]

        log.info("Installing with pip: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(
                list(self.pip_install_cmd) + pkg_list
            )
            return res.returncode == 0
        except CalledProcessError as e:
            log.critical("Pip error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def update_pkgs(self) -> bool:
        """Update all installed pip packages"""
        assert self.can_install()

        self.install_pkg_unless_found(self.PIP_UPDATE_PKG)
        self.runner.run(list(self._pip_cmd) + ["install", "--upgrade", "pip"])
        log.warning("pip update not implemented (only updates pip itself)")
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update python, pip and pip packages, then install new pip pkgs"""
        assert self.can_install()

        self.update_pkgs()
        self.install_pkgs(pkgs)
