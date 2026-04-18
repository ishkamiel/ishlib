# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
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

    def _install_flags(self) -> Sequence[str]:
        return ["install", "-y"]

    def _needs_sudo_for_install(self) -> bool:
        return True

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a dnf package is installed via rpm -q"""
        if not self._guard_can_install(pkg):
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

    def update_pkgs(self) -> bool:
        """Update all installed dnf packages"""
        self._require_available()

        log.info("Updating dnf packages")
        self._run_cmd(["dnf", "upgrade", "-y"], sudo=True, action="updating")
        return True
