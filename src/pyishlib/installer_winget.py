# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for package installing tasks"""

import logging
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
        return self._check_pkg_installed_by_output(
            pkg,
            ["winget", "list", "--id", pkg["winget"], "--exact"],
            check=False,
        )

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of winget packages, one at a time."""
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
