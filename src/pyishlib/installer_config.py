# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Classes to manage installer configuration"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Iterable

try:
    import cerberus

    HAS_CERBERUS = True
except ImportError:
    HAS_CERBERUS = False

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import tomllib  # Python 3.11+

    HAS_TOML = True
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # Fallback for Python < 3.11

        HAS_TOML = True
    except ImportError:
        HAS_TOML = False

log = logging.getLogger(__name__)


class InstallerConfig:
    """Class for handling installer configuration"""

    SCHEMA: Path = (
        Path(__file__).parent.parent / "schema" / "installer_config_cerberus.json"
    )

    def __init__(self, config: Mapping[str, Any], config_fn: Path) -> None:
        self._config_file: Path = config_fn

        if HAS_CERBERUS:
            # Load the schema file (JSON format, use yaml.safe_load if available
            # for tolerance of comments/trailing commas, otherwise json.load)
            with open(InstallerConfig.SCHEMA, "r", encoding="utf-8") as schema_fh:
                if HAS_YAML:
                    schema = yaml.safe_load(schema_fh)
                else:
                    schema = json.load(schema_fh)

            validator = cerberus.Validator(schema)
            if not validator.validate({"config": config}):
                raise ValueError(f"Config data does not validate: {validator.errors}")
        else:
            log.debug(
                "cerberus not available, skipping config validation for %s",
                config_fn,
            )

        for name, pkg in config.items():
            pkg["name"] = name

        self._config: Mapping[str, Any] = config
        self._on_gnome = None
        self._on_ubuntu = None
        self._on_windows = None

    @property
    def config_file(self) -> Path:
        """Get the configuration file name"""
        return self._config_file

    @property
    def on_windows(self):
        """True if running on Windows"""
        if self._on_windows is None:
            self._on_windows = sys.platform == "win32"
        return self._on_windows

    @property
    def on_gnome(self):
        """True if running Gnome"""
        if self._on_gnome is None:
            cur_desk = os.environ.get("XDG_CURRENT_DESKTOP")
            self._on_gnome = cur_desk is not None and cur_desk.lower() == "gnome"
        return self._on_gnome

    @property
    def on_ubuntu(self):
        """True if on Ubuntu"""
        if self._on_ubuntu is None:
            try:
                with open("/etc/os-release", "r", encoding="utf-8") as f:
                    self._on_ubuntu = "ubuntu" in f.read().lower()
            except FileNotFoundError:
                self._on_ubuntu = False
        return self._on_ubuntu

    def get_pkgs(self) -> Iterable[dict]:
        """Get the packages from the configuration"""
        all_pkgs = []
        for p in self._config.values():
            if "ubuntu" in p and p["ubuntu"] and not self.on_ubuntu:
                continue
            if "gnome" in p and p["gnome"] and not self.on_gnome:
                continue
            all_pkgs.append(p)
        return all_pkgs

    def get_pkg(self, name: str) -> dict:
        """Get a package by name"""
        if name not in self._config:
            raise ValueError(f"Package {name} not found in config")
        return self._config[name]


class InstallerConfigJSON(InstallerConfig):
    """Class for handling installer configuration from a JSON file"""

    SCHEMA: Path = (
        Path(__file__).parent.parent / "schema" / "installer_config_json.json"
    )

    def __init__(self, config_fn: Path, **kwargs) -> None:
        # Load JSON config
        try:
            with open(config_fn, "r", encoding="utf-8") as config_fh:
                config: Mapping[str, Any] = json.load(config_fh)
        except json.decoder.JSONDecodeError as e:
            raise ValueError(f"Config file is not valid JSON: {e}") from e

        # Validate the JSON file based on the schema
        if HAS_JSONSCHEMA:
            try:
                with open(
                    InstallerConfigJSON.SCHEMA, "r", encoding="utf-8"
                ) as schema_fh:
                    schema = json.load(schema_fh)
                    jsonschema.validate(config, schema)
            except json.decoder.JSONDecodeError as e:
                raise ValueError(f"Failed to load JSON schema\n{e}") from e
            except jsonschema.exceptions.ValidationError as e:
                raise ValueError(f"Config file does not match schema: {e}") from e
        else:
            log.debug(
                "jsonschema not available, skipping JSON schema validation for %s",
                config_fn,
            )

        super().__init__(config=config, config_fn=config_fn, **kwargs)


class InstallerConfigTOML(InstallerConfig):
    """Class for handling installer configuration from a TOML file"""

    def __init__(self, config_fn: Path, **kwargs) -> None:
        if not HAS_TOML:
            raise ImportError(
                "TOML support requires Python 3.11+ (tomllib) "
                "or the 'tomli' package for older Python versions"
            )

        # Load TOML config
        try:
            with open(config_fn, "rb") as config_fh:
                config: Mapping[str, Any] = tomllib.load(config_fh)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(f"Config file is not valid TOML: {e}") from e

        # Cerberus validation is handled by the parent class
        super().__init__(config=config, config_fn=config_fn, **kwargs)
