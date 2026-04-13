#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for dnf package installing tasks"""

import logging
import subprocess
from subprocess import CalledProcessError
from typing import Any, Optional, Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerDnf(InstallerBase):
    """Helper class for managing dnf packages"""

    INSTALLER_NAME: str = "dnf"

    def _tool_cmd(self) -> str:
        return "dnf"

    def _pkg_key(self) -> str:
        return "dnf"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a dnf package is installed via rpm -q"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("dnf not available for %s", pkg.get("name"))
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["rpm", "-q", pkg["dnf"]],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return result.returncode == 0
        except CalledProcessError as e:
            log.debug("rpm -q non-zero exit for %s: %s", pkg["name"], e)
            return False

    def is_pkg_available(self, pkg: Optional[Any] = None) -> bool:
        """Return True if *pkg* is known to the local dnf repo index."""
        if pkg is None or not self.can_install() or not self.can_install(pkg):
            return False

        try:
            result = self.runner.run(
                ["dnf", "info", "--quiet", pkg["dnf"]],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return result.returncode == 0
        except Exception:
            return False

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of dnf packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Sequence[str] = [pkg["dnf"] for pkg in pkgs]

        log.info("Installing with dnf: %s", " ".join(pkg_list))
        res = self._run_cmd(
            ["dnf", "install", "-y", *pkg_list], sudo=True, action="installing"
        )
        return res.returncode == 0

    def update_pkgs(self) -> bool:
        """Update all installed dnf packages"""
        self._require_available()

        log.info("Updating dnf packages")
        self._run_cmd(["dnf", "upgrade", "-y"], sudo=True, action="updating")
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update dnf packages, then install new dnf pkgs"""
        self.update_pkgs()
        self.install_pkgs(pkgs)
