# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for package installing tasks"""

import logging
import subprocess
from subprocess import CalledProcessError
from typing import Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerWinget(InstallerBase):
    """Helper class for managing packages via winget (Windows Package Manager)"""

    INSTALLER_NAME: str = "winget"

    def _tool_cmd(self) -> str:
        return "winget"

    def _pkg_key(self) -> str:
        return "winget"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a winget package is installed"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("winget not available for %s", pkg.get("name"))
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["winget", "list", "--id", pkg["winget"], "--exact"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output = result.stdout
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return pkg["winget"] in output
        except CalledProcessError as e:
            log.debug("winget error checking %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of winget packages"""
        self._validate_pkgs(pkgs)

        for pkg in pkgs:
            pkg_id: str = pkg["winget"]
            log.info("Installing with winget: %s", pkg_id)
            # _run_cmd uses CommandRunner.run with check=True, so a
            # non-zero exit raises CalledProcessError and propagates.
            self._run_cmd(
                [
                    "winget",
                    "install",
                    "--id",
                    pkg_id,
                    "--exact",
                    "--accept-source-agreements",
                    "--accept-package-agreements",
                ],
                action="installing",
            )
        return True

    def update_pkgs(self) -> bool:
        """Update all installed winget packages"""
        self._require_available()

        self._run_cmd(
            [
                "winget",
                "upgrade",
                "--all",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ],
            action="updating",
        )
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update winget packages, then install new winget pkgs"""
        self._require_available()

        self.update_pkgs()
        self.install_pkgs(pkgs)
