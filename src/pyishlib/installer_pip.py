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
from typing import Any, Optional, Iterable, Mapping
from .command_runner import CommandRunner

log = logging.getLogger(__name__)


class InstallerPip:
    """Helper class for managing python packages via pip"""

    INSTALLER_NAME: str = "pip"

    PIP_UPDATE_PKG: Mapping[str, str] = {
        "name": "pip",
        "pip": "pip",
    }

    def __init__(self, runner: CommandRunner) -> None:
        self.runner: CommandRunner = runner
        self._pip_checked: bool = False
        self._has_pip: bool = False
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

    @property
    def pip_install_cmd(self) -> Iterable[str]:
        """Get the pip install command for the current platform"""
        return list(self._pip_cmd) + ["install", "--user"]

    @property
    def has_pip(self) -> bool:
        """Check if pip is available"""

        if not self._pip_checked:
            if len(self._pip_cmd) == 1:
                self._has_pip = self.runner.which(self._pip_cmd[0]) is not None
                if not self._has_pip and self._pip_cmd == ["pip3"]:
                    # Fallback: try "pip" if "pip3" is not found
                    self._has_pip = self.runner.which("pip") is not None
                    if self._has_pip:
                        self._pip_cmd = ["pip"]
                if not self._has_pip and sys.platform == "win32":
                    # Fallback: try "python -m pip" on Windows
                    self._pip_cmd = [sys.executable, "-m", "pip"]
                    self._has_pip = True
            else:
                # Already set to a multi-element command (e.g. python -m pip)
                self._has_pip = True
            self._pip_checked = True
        return self._has_pip

    @property
    def namespace(self):
        """Get the common Namespace for installer commands"""

        # pylint: disable=R0903
        class Namespace:
            """Namespace for pip commands"""

            can_install = self.can_use_pip
            install = self.install_pip_pkgs
            install_unless_found = self.install_pip_pkg_unless_found
            is_installed = self.is_pip_pkg_installed
            update = self.update_pip_pkgs
            update_and_install_all = self.update_and_install_pip_pkgs

        return Namespace()

    def can_use_pip(self, pkg: Optional[Any] = None) -> bool:
        """Check if pip is available, and optionally, if pkg can use it"""

        if pkg is not None and "pip" not in pkg:
            return False
        return self.has_pip

    def get_pip_pkgs(self, pkgs) -> Iterable[dict]:
        """Get the pip packages from a list of packages"""
        return [pkg for pkg in pkgs if self.can_use_pip(pkg)]

    def is_pip_pkg_installed(self, pkg) -> bool:
        """Check if a pip package is installed"""

        if not self.can_use_pip():
            log.debug("Pip not available")
            return False
        if not self.can_use_pip(pkg):
            log.debug("Pip pkg not available for %s", pkg["name"])
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

    def install_pip_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of pip packages"""

        assert isinstance(pkgs, Iterable) and all(
            isinstance(pkg, dict) for pkg in pkgs
        ), "pkgs should be an iterable of dictionaries"
        assert all(self.can_use_pip(p) for p in pkgs)

        pkg_list: Iterable[str] = [pkg["pip"] for pkg in pkgs]

        log.info("Installing with pip: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(
                list(self.pip_install_cmd) + pkg_list
            )
            return res.returncode == 0
        except CalledProcessError as e:
            log.critical("Pip error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def install_pip_pkg(self, pkg) -> bool:
        """Install a pip package"""
        return self.install_pip_pkgs([pkg])

    def install_pip_pkg_unless_found(self, pkg) -> bool:
        """Install a pip package unless it is already installed"""

        if not self.is_pip_pkg_installed(pkg):
            return self.install_pip_pkg(pkg)
        return True

    def update_pip_pkgs(self) -> bool:
        """Update all installed pip packages"""
        assert self.can_use_pip()

        self.install_pip_pkg_unless_found(self.PIP_UPDATE_PKG)
        self.runner.run(list(self._pip_cmd) + ["install", "--upgrade", "pip"])
        log.warning("pip update not implemented (only updates pip itself)")
        return True

    def update_and_install_pip_pkgs(self, pkgs):
        """Update python, pip and pip packages, then install new pip pkgs"""
        assert self.can_use_pip()

        self.update_pip_pkgs()
        self.install_pip_pkgs(pkgs)
