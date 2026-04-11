#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import logging
import subprocess
from subprocess import CompletedProcess, CalledProcessError
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
            try:
                res: CompletedProcess = self.runner.run(
                    [
                        "winget",
                        "install",
                        "--id",
                        pkg_id,
                        "--exact",
                        "--accept-source-agreements",
                        "--accept-package-agreements",
                    ]
                )
                if res.returncode != 0:
                    log.critical(
                        "winget error installing %s: returncode %d",
                        pkg_id,
                        res.returncode,
                    )
                    return False
            except CalledProcessError as e:
                log.critical("winget error installing %s: %s", pkg_id, e)
                raise e
        return True

    def update_pkgs(self) -> bool:
        """Update all installed winget packages"""
        assert self.can_install()

        self.runner.run(
            [
                "winget",
                "upgrade",
                "--all",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        )
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update winget packages, then install new winget pkgs"""
        assert self.can_install()

        self.update_pkgs()
        self.install_pkgs(pkgs)
