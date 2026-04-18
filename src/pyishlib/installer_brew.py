# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for package installing tasks"""

import logging
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

    def _install_flags(self) -> Sequence[str]:
        return ["install"]

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a Homebrew package is installed"""
        return self._check_pkg_installed_by_output(
            pkg, ["brew", "list", "--formula"]
        )

    def update_pkgs(self) -> bool:
        """Update all installed Homebrew packages"""
        self._require_available()

        self._run_cmd(["brew", "update"], action="updating")
        self._run_cmd(["brew", "upgrade"], action="updating")
        return True
