# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

import subprocess
from subprocess import CompletedProcess, CalledProcessError
from typing import Any, Optional, Iterable
from .command_runner import CommandRunner
from .ish_comp import IshComp


class CargoInstaller:
    """Helper class for managing rust and cargo packages"""

    CARGO_UPDATE_PKG: dict[str, str] = {
        "name": "cargo-update",
        "cargo": "cargo-update",
    }

    # The --locked flags forces cargo to use the pkg-specific versions of deps
    CARGO_INSTALL_CMD: list[str] = ["cargo", "install", "--locked"]

    def __init__(self) -> None:
        self._cargo_checked: bool = False
        self._has_cargo: bool = False
        assert isinstance(self, IshComp)
        self.log = getattr(self, "log", None)
        self.runner: CommandRunner = getattr(self, "runner", None)

    @property
    def has_cargo(self) -> bool:
        """Check if cargo is available"""
        if not self._cargo_checked:
            self._has_cargo = self.runner.which("cargo") is not None
            self._cargo_checked = True
        return self._has_cargo

    @property
    def cargo(self) -> bool:
        """Get the common Namespace for installer commands"""

        # pylint: disable=R0903
        class Namespace:
            """Namespace for cargo commands"""

            can_install = self.can_use_cargo
            install = self.install_cargo_pkgs
            install_unless_found = self.install_cargo_pkg_unless_found
            is_installed = self.is_cargo_pkg_installed
            update = self.update_cargo_pkgs
            update_and_install_all = self.update_and_install_all

        return Namespace

    def can_use_cargo(self, pkg: Optional[Any] = None) -> bool:
        """Check if cargo is available, and optionally, if pkg can use it"""
        if pkg is not None and "cargo" not in pkg:
            return False
        return self.has_cargo

    def get_cargo_pkgs(self, pkgs) -> list[dict]:
        """Get the cargo packages from a list of packages"""
        return [pkg for pkg in pkgs if self.can_use_cargo(pkg)]

    def is_cargo_pkg_installed(self, pkg) -> bool:
        """Check if a cargo package is installed"""
        if not self.can_use_cargo():
            self.log.debug("Cargo not available")
            return False
        if not self.can_use_cargo(pkg):
            self.log.debug("Cargo pkg not available for %s", pkg["name"])
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
            self.log.critical("Cargo error checking %s: %s", pkg["name"], e)
            raise e

    def install_cargo_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install a list of cargo packages"""
        assert isinstance(pkgs, Iterable) and all(
            isinstance(pkg, dict) for pkg in pkgs
        ), "pkgs should be an iterable of dictionaries"
        assert all(self.can_use_cargo(p) for p in pkgs)

        pkg_list: list[str] = [pkg["cargo"] for pkg in pkgs]

        self.log.info("Installing with cargo: %s", " ".join(pkg_list))
        try:
            res: CompletedProcess = self.runner.run(self.CARGO_INSTALL_CMD + pkg_list)
            return res.returncode == 0
        except CalledProcessError as e:
            self.log.critical("Cargo error installing %s: %s", " ".join(pkg_list), e)
            raise e

    def install_cargo_pkg(self, pkg) -> bool:
        """Install a cargo package"""
        self.install_cargo_pkgs([pkg])

    def install_cargo_pkg_unless_found(self, pkg) -> bool:
        """Install a cargo package unless it is already installed"""
        if not self.is_cargo_pkg_installed(pkg):
            self.install_cargo_pkg(pkg)

    def update_cargo_pkgs(self) -> bool:
        """Update all installed cargo packages"""
        assert self.can_use_cargo()

        self.install_cargo_pkg_unless_found(self.CARGO_UPDATE_PKG)
        self.runner.run(["cargo", "install-update", "-a", "-q"])

    def update_or_install_rust(self) -> bool:
        """Update rustup and install stable if needed"""
        assert self.runner.which("rustup") is not None
        q: bool = not getattr(self, "verbose", False)

        try:
            res: CompletedProcess = self.runner.run(
                ["rustup", "toolchain", "list"], capture_output=True, text=True
            )
            if res.stdout.find("stable.*(default)") == -1:
                self.runner.run(["rustup", "install", "stable"], quiet=q)
                self.runner.run(["rustup", "install", "stable"], quiet=q)
            self.runner.run(["rustup", "install", "stable"], quiet=q)
        except CalledProcessError as e:
            self.log.critical("Rustup error: %s", e)
            raise e

    def update_and_install_all(self, pkgs):
        """Update rust, cargo and cargo packages, then install new cargo pkgs"""
        self.update_or_install_rust()
        self.update_cargo_pkgs()
        self.install_cargo_pkgs(pkgs)
