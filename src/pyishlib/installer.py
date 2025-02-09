# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

from typing import Any, Optional, Iterable
from .command_runner import CommandRunner
from .ish_comp import IshComp
from .cargo_installer import CargoInstaller
from .apt_installer import AptInstaller


class Installer(IshComp, CargoInstaller, AptInstaller):
    """Installer class for installing packages."""

    INSTALLERS: list[list[str]] = [
        ["apt", "apt"],
        ["cargo", "cargo"],
        # ["pip", "pip3"],
    ]

    def __init__(self, runner: Optional[CommandRunner] = None, **kwargs: Any) -> None:
        self.runner: CommandRunner = (
            runner
            if runner is not None
            else CommandRunner(
                args=self._args,
                conf=self._conf,
                dry_run=self._dry_run,
            )
        )
        IshComp.__init__(self, **kwargs)
        CargoInstaller.__init__(self)
        AptInstaller.__init__(self)

    def installer(self, installer: str) -> Any:
        """Get an installer."""
        if not hasattr(self, installer):
            self.log.critical("Installer %s not found", installer)
            raise ValueError(f"Installer {installer} not found")
        return getattr(self, installer)

    def get_installer(self, pkg: dict) -> str | None:
        """Get the installer for a package."""

        # See if the package has a preferred installer
        if "pref" in pkg:
            for i in pkg["pref"]:
                if self.installer(i).can_install(pkg):
                    return i
        # Otherwise use the first installer that can install the package
        for i, _ in self.INSTALLERS:
            if self.installer(i).can_install(pkg):
                return i
        self.log.debug("No installer found for %s", pkg["name"])
        return None

    def install_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install all packages."""

        # Get the packages that are missing
        missing_packages: Iterable[dict] = self.get_missing_pkgs(pkgs)

        # Then sort them by installer
        to_install: dict[str, list] = {
            "apt": [],
            "cargo": [],
            "pip": [],
        }
        for pkg in missing_packages:
            installer: str | None = self.get_installer(pkg)
            if installer is not None:
                to_install[installer].append(pkg)
                continue
            self.log.error("No installer found for %s", pkg["name"])

        # Finallyh, install the packages
        for i, i_pkgs in to_install.items():
            if len(i_pkgs) == 0:
                continue
            self.installer(i).install(i_pkgs)
        return True

    def have_pkg(self, package: dict[Any]) -> bool:
        """Check if a package is installed."""
        found_checker = False
        if "cmd" in package:
            found_checker = True
            if self.runner.which(package["cmd"]) is not None:
                self.log.debug(
                    "Package %s installed, found command %s",
                    package["name"],
                    package["cmd"],
                )
                return True
            self.log.debug("Did not find %s with which", package["cmd"])
        if self.can_use_apt(package):
            found_checker = True
            if self.is_apt_pkg_installed(package):
                self.log.debug("Package %s installed with apt", package["name"])
                return True
            self.log.debug("Package %s not installed with apt", package["name"])
        if self.can_use_cargo(package):
            found_checker = True
            if self.is_cargo_pkg_installed(package):
                self.log.debug("Package %s installed with cargo", package["name"])
                return True
            self.log.debug("Package %s not installed with cargo", package["name"])
        # if "pip" in package and shutil.which("pip3") is not None:
        #     self.log.debug("Checking if %s is installed with pip", package["name"])
        #     try:
        #         result: subprocess.CompletedProcess = self.runner.run(
        #             ["pip3", "show", package["pip"]],
        #             check=True,
        #             stdout=subprocess.PIPE,
        #             stderr=subprocess.PIPE,
        #         )
        #         if
        #         return package["pip"] in result.stdout.decode("utf-8")
        #     except subprocess.CalledProcessError as e:
        #         self.log.error(
        #             "Error checking if %s is installed: %s", package["name"], e
        #         )
        #         raise e

        if not found_checker:
            self.log.error("Cannot check if %s is installed", package["name"])
        return False

    def install_pkg(self, pkg: dict) -> bool:
        """Install a package"""
        return self.install_pkgs([pkg])

    def get_missing_pkgs(self, pkgs: Iterable[dict]) -> Iterable[dict]:
        """Check if a list of commands are available."""
        return [p for p in pkgs if not self.have_pkg(p)]
