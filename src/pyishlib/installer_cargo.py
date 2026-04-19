# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for package installing tasks"""

from __future__ import annotations

import logging
import re
from subprocess import CalledProcessError, CompletedProcess
from typing import Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerCargo(InstallerBase):
    """Helper class for managing rust and cargo packages"""

    INSTALLER_NAME: str = "cargo"

    CARGO_UPDATE_PKG: dict[str, str] = {
        "name": "cargo-update",
        "cargo": "cargo-update",
    }

    def _tool_cmd(self) -> str:
        return "cargo"

    def _pkg_key(self) -> str:
        return "cargo"

    # The --locked flag forces cargo to use the pkg-specific versions of deps.
    def _install_flags(self) -> Sequence[str]:
        return ["install", "--locked"]

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a cargo package is installed"""
        return self._check_pkg_installed_by_output(pkg, ["cargo", "install", "--list"])

    def update_or_install_rust(self) -> bool:
        """Update rustup and install stable if needed"""
        if self.runner.which("rustup") is None:
            raise RuntimeError("cargo: rustup is required but was not found")
        q: bool = log.getEffectiveLevel() > logging.INFO

        try:
            res: CompletedProcess = self.runner.run(
                ["rustup", "toolchain", "list"], capture_output=True, text=True
            )
            if not re.search(r"stable.*\(default\)", res.stdout):
                self.runner.run(["rustup", "install", "stable"], quiet=q)
            self.runner.run(["rustup", "update", "stable"], quiet=q)
            return True
        except CalledProcessError as e:
            log.critical("Rustup error: %s", e)
            raise

    def update_pkgs(self) -> bool:
        """Update all installed cargo packages"""
        self._require_available()

        self.install_pkg_unless_found(self.CARGO_UPDATE_PKG)
        self._run_cmd(["cargo", "install-update", "-a", "-q"], action="updating")
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update rust, cargo and cargo packages, then install new cargo pkgs"""
        self.update_or_install_rust()
        self.update_pkgs()
        self.install_pkgs(pkgs)
