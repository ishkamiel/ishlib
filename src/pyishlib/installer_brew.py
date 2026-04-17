# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for package installing tasks"""

import logging
import subprocess
from subprocess import CalledProcessError
from typing import Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerBrew(InstallerBase):
    """Helper class for managing packages via Homebrew"""

    INSTALLER_NAME: str = "brew"

    def _tool_cmd(self) -> str:
        return "brew"

    def _pkg_key(self) -> str:
        return "brew"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a Homebrew package is installed"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("Homebrew not available for %s", pkg.get("name"))
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["brew", "list", "--formula"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return pkg["brew"] in result.stdout.decode("utf-8")
        except CalledProcessError as e:
            log.debug("Homebrew error checking %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of Homebrew packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Sequence[str] = [pkg["brew"] for pkg in pkgs]

        log.info("Installing with Homebrew: %s", " ".join(pkg_list))
        res = self._run_cmd(["brew", "install", *pkg_list], action="installing")
        return res.returncode == 0

    def update_pkgs(self) -> bool:
        """Update all installed Homebrew packages"""
        self._require_available()

        self._run_cmd(["brew", "update"], action="updating")
        self._run_cmd(["brew", "upgrade"], action="updating")
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update Homebrew and Homebrew packages, then install new Homebrew pkgs"""
        self._require_available()

        self.update_pkgs()
        self.install_pkgs(pkgs)
