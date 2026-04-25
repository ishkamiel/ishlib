# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for dnf package installing tasks"""

import logging
import subprocess
from subprocess import CalledProcessError
from typing import Any, Optional, Sequence

from .installer_base import InstallerBase
from .version_check import meets_min_version

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
        """Check if a dnf package is installed via ``rpm -q``.

        When ``min_version`` is set on the package, the installed
        ``%{VERSION}`` is read in the same query and compared.  An
        installed package below ``min_version`` is reported as not
        installed so the caller proceeds to install a newer build.
        """
        if not self._guard_can_install(pkg):
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["rpm", "-q", "--qf", "%{VERSION}\n", pkg["dnf"]],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except CalledProcessError as e:
            log.debug("rpm -q non-zero exit for %s: %s", pkg["name"], e)
            return False
        if result.returncode != 0:
            return False
        min_version = pkg.get("min_version")
        if min_version is None:
            return True
        ver = result.stdout.decode("utf-8", errors="replace").strip()
        if meets_min_version(ver, min_version):
            return True
        log.debug(
            "Package %s installed at %s, below min_version %s",
            pkg["name"],
            ver,
            min_version,
        )
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
