#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import logging
import re
import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Iterable, Mapping

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerCargo(InstallerBase):
    """Helper class for managing rust and cargo packages"""

    INSTALLER_NAME: str = "cargo"

    CARGO_UPDATE_PKG: Mapping[str, str] = {
        "name": "cargo-update",
        "cargo": "cargo-update",
    }

    # The --locked flags forces cargo to use the pkg-specific versions of deps
    CARGO_INSTALL_CMD: Iterable[str] = ["cargo", "install", "--locked"]

    def _tool_cmd(self) -> str:
        return "cargo"

    def _pkg_key(self) -> str:
        return "cargo"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if a cargo package is installed"""
        if not self.can_install() or not self.can_install(pkg):
            log.debug("Cargo not available for %s", pkg.get("name"))
            return False

        try:
            result: subprocess.CompletedProcess = self.runner.run(
                ["cargo", "install", "--list"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return pkg["cargo"] in result.stdout.decode("utf-8")
        except CalledProcessError as e:
            log.debug("Cargo error checking %s: %s", pkg["name"], e)
            return False

    def install_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of cargo packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Iterable[str] = [pkg["cargo"] for pkg in pkgs]

        log.info("Installing with cargo: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(self.CARGO_INSTALL_CMD + pkg_list)
            return res.returncode == 0
        except CalledProcessError as e:
            log.critical("Cargo error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def update_or_install_rust(self) -> bool:
        """Update rustup and install stable if needed"""
        assert self.runner.which("rustup") is not None
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
            raise e

    def update_pkgs(self) -> bool:
        """Update all installed cargo packages"""
        assert self.can_install()

        self.install_pkg_unless_found(self.CARGO_UPDATE_PKG)
        self.runner.run(["cargo", "install-update", "-a", "-q"])
        return True

    def update_and_install_all(self, pkgs: Iterable[dict]) -> None:
        """Update rust, cargo and cargo packages, then install new cargo pkgs"""
        self.update_or_install_rust()
        self.update_pkgs()
        self.install_pkgs(pkgs)
