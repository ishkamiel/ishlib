# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Classes to manage installer configuration"""

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Iterable, Optional

from .environment import should_skip_for_os
from .schema_validation import validate_packages

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from ._compat import HAS_TOML, load_toml_file_strict  # noqa: F401  # HAS_TOML re-exported for callers

log = logging.getLogger(__name__)


class InstallerConfig:
    """Class for handling installer configuration"""

    def __init__(
        self,
        config: Mapping[str, Any],
        config_fn: Path,
        cfg: Optional[Any] = None,
    ) -> None:
        self._config_file: Path = config_fn
        self._cfg = cfg  # IshConfig instance for tag/context filtering

        err = validate_packages(dict(config), source=str(config_fn))
        if err is not None:
            raise ValueError(err)

        for name, pkg in config.items():
            pkg["name"] = name

        self._config: Mapping[str, Any] = config

    @property
    def config_file(self) -> Path:
        """Get the configuration file name"""
        return self._config_file

    def _passes_tag_filter(self, pkg: dict) -> bool:
        """Return True if *pkg* should be included given its tags.

        Delegates to the shared :func:`~pyishlib.tag_filter.passes_tags`
        helper so that packages and scripts use identical semantics.

        Packages without tags are always included.
        """
        from .tag_filter import passes_tags

        tags = pkg.get("tags", []) or []
        return passes_tags(tags, self._cfg, label=pkg.get("name", ""))

    def get_pkgs(self) -> Iterable[dict]:
        """Get the packages from the configuration, applying OS and tag filters."""
        result = []
        for p in self._config.values():
            if should_skip_for_os(p.get("only_on"), p.get("ignore_on")):
                continue
            if not self._passes_tag_filter(p):
                continue
            result.append(p)
        return result

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

    def __init__(self, config_fn: Path, cfg: Optional[Any] = None, **kwargs) -> None:
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

        super().__init__(config=config, config_fn=config_fn, cfg=cfg, **kwargs)


class InstallerConfigTOML(InstallerConfig):
    """Class for handling installer configuration from a TOML file"""

    def __init__(self, config_fn: Path, cfg: Optional[Any] = None, **kwargs) -> None:
        config: Mapping[str, Any] = load_toml_file_strict(config_fn)
        super().__init__(config=config, config_fn=config_fn, cfg=cfg, **kwargs)
