# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for package installing tasks"""

# Standard imports
from pathlib import Path
from typing import Any, Optional
import json
import shutil
import toml
import yaml
from cerberus import Validator
from .ish_comp import IshComp
from .command_runner import CommandRunner

INSTALLER_CONFIG: Path = Path(__file__).parent / "schema" / "installer_config.toml"


class PackageInfo:
    """Class for handling package information"""

    def __init__(self, command: str, conf: "InstallerConfig") -> None:
        self._command: str = command
        self._cargo_pkg: str | None = conf.get_cargo_pkg(command)
        self._apt_pkg: str | None = conf.get_apt_pkg(command)

    def __repr__(self) -> str:
        return json.dumps(self.__dict__)

    def __str__(self) -> str:
        return self.command

    @property
    def command(self) -> str:
        """Get the command"""
        return self._command

    @property
    def cargo_pkg(self) -> Optional[str]:
        """Get the cargo package that provides the command"""
        return self._cargo_pkg

    @property
    def apt_pkg(self) -> Optional[str]:
        """Get the cargo package that provides the command"""
        return self._apt_pkg


class InstallerConfig:
    """Class for handling installer configuration"""

    def __init__(self, config_file: Path, schema_file=INSTALLER_CONFIG) -> None:
        self._config_file: Path = config_file

        # Read the TOML file
        assert config_file.exists() and config_file.name.endswith(".toml")
        with open(config_file, "r", encoding="utf-8") as config_fh:
            self._config: dict[str, Any] = toml.load(config_fh)

        # Load the schema from a YAML file
        assert schema_file.exists() and config_file.name.endswith(".yaml")
        with open(schema_file, "r", encoding="utf-8") as schema_fh:
            schema = yaml.safe_load(schema_fh)

        if not Validator(schema).validate(self._config):
            raise ValueError("Config file does not match schema")

    @property
    def config_file(self) -> Path:
        """Get the configuration file name"""
        return self._config_file

    def get_pkg_info(self, command: str) -> PackageInfo:
        """Get information for package that provides command"""
        return PackageInfo(command, self)

    def get_cargo_pkg(self, cmd: str) -> str | None:
        """Get the cargo package that provides a command"""
        if cmd in self._config["cargo_packages"]:
            return self._config["cargo_packages"][cmd]
        return None

    def get_apt_pkg(self, cmd: str) -> str | None:
        """Get the apt package that provides a command"""
        if cmd in self._config["apt_packages"]:
            return self._config["apt_packages"][cmd]
        return None


class Installer(IshComp):
    """Installer class for installing packages."""

    def __init__(self, runner: Optional[CommandRunner] = None, **kwargs: Any) -> None:
        self._runner: CommandRunner | None = runner
        super().__init__(**kwargs)

    @property
    def runner(self) -> CommandRunner:
        """Get the command runner."""
        if self._runner is None:
            self._runner = CommandRunner(
                args=self._args,
                conf=self._conf,
                dry_run=self._dry_run,
                quiet=self._quiet,
            )
        return self._runner

    def check_command(self, command: str) -> bool:
        """Check if a command is available."""
        return shutil.which(command) is not None

    def _get_not_found_pkgs(self, *commands: str) -> list[str]:
        """Check if a list of commands are available."""
        return [
            pkg["package"] for pkg in commands if shutil.which(pkg["command"]) is None
        ]

    def install_unless_cmd(self, *packages: list[dict[str:str]], **kwargs) -> bool:
        """Install a package unless the command is available."""
        return self.install(*self._get_not_found_pkgs(*packages), **kwargs)

    def install(self, *packages) -> bool:
        """Install a package."""
        packages: list[str] = self._get_not_found_pkgs(*packages)
        self.log_info(f"Need to install packages for {packages}")
        assert False, "Not implemented"

    def install_apt_unless_cmd(self, *packages: list[str], **kwargs) -> bool:
        """Install a package using apt unless the command is available."""
        return self.install_apt(*self._get_not_found_pkgs(*packages), **kwargs)

    def install_apt(self, *packages, sudo: Optional[bool] = True, **kwargs) -> bool:
        """Install a package using apt."""
        return self.runner.run(["apt", "install", *packages], sudo=sudo, **kwargs)

    def install_cargo_unless_cmd(self, *packages: list[str], **kwargs) -> bool:
        """Install a package using cargo unless the command is available."""
        return self.install_cargo(*self._get_not_found_pkgs(*packages), **kwargs)

    def install_cargo(self, *packages: list[str], **kwargs) -> bool:
        """Install a package using cargo."""
        return self.runner.run(["cargo", "install", *packages], **kwargs)
