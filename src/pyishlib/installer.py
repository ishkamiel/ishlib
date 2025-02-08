# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

# Standard imports
import shutil
import subprocess
from typing import Any, Literal, Optional, Iterable
from .command_runner import CommandRunner
from .ish_comp import IshComp


class Installer(IshComp):
    """Installer class for installing packages."""

    INSTALLERS: list[list[str]] = [
        ["apt", "apt"],
        ["cargo", "cargo"],
        ["pip", "pip3"],
    ]

    def __init__(self, runner: Optional[CommandRunner] = None, **kwargs: Any) -> None:
        self._runner: Optional[CommandRunner] = runner
        super().__init__(**kwargs)

    @property
    def runner(self) -> CommandRunner:
        """Get the command runner."""
        if self._runner is None:
            self._runner = CommandRunner(
                args=self._args,
                conf=self._conf,
                dry_run=self._dry_run,
            )
        return self._runner

    def install_all(self, pkgs: Iterable[dict]) -> None:
        """Install all packages."""
        for pkg in pkgs:
            if not self.is_installed(pkg):
                self.install_package(pkg)
            else:
                self.log.debug("%s is already installed", pkg["name"])

    def is_installed(self, package: str) -> bool:
        """Check if packageö is installed"""
        result: bool = self._is_installed(package)
        self.log.debug("%s is installed: %s", package["name"], result)
        return result

    def _is_installed(self, package: str) -> bool:
        if "cmd" in package:
            self.log.debug("Checking if %s is installed with cmd", package["name"])
            return self.have_cmd(package["cmd"])
        if "apt" in package and shutil.which("apt") is not None:
            self.log.debug("Checking if %s is installed with apt", package["name"])
            try:
                result: subprocess.CompletedProcess = self.runner.run(
                    ["dpkg", "-s", package["apt"]],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return "install ok installed" in result.stdout.decode("utf-8").lower()
            except subprocess.CalledProcessError as e:
                self.log.error(
                    "Error checking if %s is installed: %s", package["name"], e
                )
                raise e
        if "cargo" in package and shutil.which("cargo") is not None:
            self.log.debug("Checking if %s is installed with cargo", package["name"])
            try:
                result: subprocess.CompletedProcess = self.runner.run(
                    ["cargo", "install", "--list"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return package["cargo"] in result.stdout.decode("utf-8")
            except subprocess.CalledProcessError as e:
                self.log.error(
                    "Error checking if %s is installed: %s", package["name"], e
                )
                raise e
        if "pip" in package and shutil.which("pip3") is not None:
            self.log.debug("Checking if %s is installed with pip", package["name"])
            try:
                result: subprocess.CompletedProcess = self.runner.run(
                    ["pip3", "show", package["pip"]],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                return package["pip"] in result.stdout.decode("utf-8")
            except subprocess.CalledProcessError as e:
                self.log.error(
                    "Error checking if %s is installed: %s", package["name"], e
                )
                raise e

        self.log.warning("Cannot check if %s is installed", package["name"])
        return False

    def install_package(self, pkg) -> bool:
        """Install a package"""

        self.log.debug("Trying to find installer for %s", pkg["name"])

        if self.can_use(pkg, "apt"):
            self.log.info("Installing %s with apt", pkg["name"])
            return (
                self.runner.run(
                    ["apt", "install", pkg["apt"]], sudo=True, check=True
                ).returncode
                == 0
            )
        if self.can_use(pkg, "cargo"):
            self.log.info("Installing %s with cargo", pkg["name"])
            return (
                self.runner.run(
                    ["cargo", "install", pkg["cargo"]], check=True
                ).returncode
                == 0
            )
        if self.can_use(pkg, "pip"):
            self.log.info("Installing %s with pip", pkg["name"])
            return (
                self.runner.run(["pip3", "install", pkg["pip"]], check=True).returncode
                == 0
            )

        assert False, f"Cannot find installer for {pkg["name"]} not installed"

    def can_use(self, pkg, cmd: Literal["apt", "cargo", "pip"]) -> bool:
        """Check if a package can be installed with given installer."""
        for i in self.INSTALLERS:
            if i[0] != cmd:
                continue
            if not i[0] in pkg:
                self.log.debug("Cannot install %s with %s", pkg["name"], i[0])
                return False
            if not self.have_cmd(i[1]):
                self.log.debug("Cannot find {I[1]} command")
                return False
            self.log.debug("Can use %s to install %s", i[1], pkg["name"])
            return True
        self.die(f"Should never reach this point cmd={cmd}")

    def have_cmd(self, command: str) -> bool:
        """Check if a command is available."""
        return self.runner.which(command) is not None

    def _get_not_found_pkgs(self, *commands: str) -> Iterable[str]:
        """Check if a list of commands are available."""
        return [
            pkg["package"] for pkg in commands if shutil.which(pkg["command"]) is None
        ]
