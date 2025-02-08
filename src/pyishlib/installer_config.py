# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Classes to manage installer configuration"""

import json
from pathlib import Path
from typing import Any, Mapping, Iterable
import cerberus
import jsonschema
import yaml


class InstallerConfig:
    """Class for handling installer configuration"""

    SCHEMA: Path = (
        Path(__file__).parent.parent / "schema" / "installer_config_cerberus.json"
    )

    def __init__(self, config: Mapping[str, Any], config_fn: Path) -> None:
        self._config_file: Path = config_fn

        # Load the schema from a YAML file
        with open(InstallerConfig.SCHEMA, "r", encoding="utf-8") as schema_fh:
            schema = yaml.safe_load(schema_fh)

        validator = cerberus.Validator(schema)
        if not validator.validate({"config": config}):
            raise ValueError(f"Config data does not validate: {validator.errors}")

        for name, pkg in config.items():
            pkg["name"] = name

        self._config: Mapping[str, Any] = config

    @property
    def config_file(self) -> Path:
        """Get the configuration file name"""
        return self._config_file

    def get_pkgs(self) -> Iterable[dict]:
        """Get the packages from the configuration"""
        return self._config.values()


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

        # Validate the JSON file basedon the schema
        try:
            with open(InstallerConfigJSON.SCHEMA, "r", encoding="utf-8") as schema_fh:
                schema = json.load(schema_fh)
                jsonschema.validate(config, schema)
        except json.decoder.JSONDecodeError as e:
            raise ValueError(f"Failed to load JSON shcema\n{e}") from e
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Config file does not match schema: {e}") from e

        super().__init__(config=config, config_fn=config_fn, **kwargs)
