# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

from typing import Any, Optional, Iterable, Mapping
from .command_runner import CommandRunner
from .ish_comp import IshComp
from .cargo_installer import CargoInstaller
from .apt_installer import AptInstaller
from .pip_installer import PipInstaller
from .brew_installer import BrewInstaller


class Installer(IshComp):
    """Installer class for installing packages."""

    def __init__(self, runner: Optional[CommandRunner] = None, **kwargs: Any) -> None:
        IshComp.__init__(self, **kwargs)
        self._backends: dict = {}
        self.runner: CommandRunner = (
            runner
            if runner is not None
            else CommandRunner(
                args=self._args,
                conf=self._conf,
                dry_run=self._dry_run,
            )
        )
        self.register_installer(AptInstaller(self.log, self.runner))
        self.register_installer(CargoInstaller(self.log, self.runner))
        self.register_installer(PipInstaller(self.log, self.runner))
        self.register_installer(BrewInstaller(self.log, self.runner))

    def register_installer(self, backend: Any) -> None:
        """Register an installer backend.

        The backend must have an INSTALLER_NAME class attribute and a
        namespace property exposing can_install, install, is_installed,
        and update methods.  Registering a backend with a name that
        already exists replaces the previous one.
        """
        name = backend.INSTALLER_NAME
        self._backends[name] = backend

    def get_backend(self, name: str) -> Any:
        """Get an installer backend instance by name."""
        if name not in self._backends:
            self.log.critical("Installer backend %s not found", name)
            raise ValueError(f"Installer backend {name} not found")
        return self._backends[name]

    def installer(self, name: str) -> Any:
        """Get an installer namespace by name."""
        return self.get_backend(name).namespace

    def get_installer(self, pkg: dict) -> Optional[str]:
        """Get the installer for a package."""

        # See if the package has a preferred installer
        if "pref" in pkg:
            for i in pkg["pref"]:
                if self.installer(i).can_install(pkg):
                    return i
        # Otherwise use the first installer that can install the package
        for i in self._backends:
            if self.installer(i).can_install(pkg):
                return i
        self.log.debug("No installer found for %s", pkg["name"])
        return None

    def install_pkgs(self, pkgs: Iterable[Mapping]) -> bool:
        """Install all packages."""

        # Get the packages that are missing
        missing_packages: Iterable[dict] = self.get_missing_pkgs(pkgs)

        # Then sort them by installer
        to_install: Mapping[str, list] = {i: [] for i in self._backends}
        for pkg in missing_packages:
            installer: Optional[str] = self.get_installer(pkg)
            if installer is not None:
                to_install[installer].append(pkg)
                continue
            self.log.error("No installer found for %s", pkg["name"])

        # Finally, install the packages
        for i, i_pkgs in to_install.items():
            if len(i_pkgs) == 0:
                continue
            self.installer(i).install(i_pkgs)
        return True

    def have_pkg(self, package: dict) -> bool:
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
        for i in self._backends:
            ns = self.installer(i)
            if ns.can_install(package):
                found_checker = True
                if ns.is_installed(package):
                    self.log.debug("Package %s installed with %s", package["name"], i)
                    return True
                self.log.debug("Package %s not installed with %s", package["name"], i)

        if not found_checker:
            self.log.error("Cannot check if %s is installed", package["name"])
        return False

    def install_pkg(self, pkg: dict) -> bool:
        """Install a package"""
        return self.install_pkgs([pkg])

    def get_missing_pkgs(self, pkgs: Iterable[dict]) -> Iterable[dict]:
        """Check if a list of commands are available."""
        return [p for p in pkgs if not self.have_pkg(p)]
