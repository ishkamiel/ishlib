#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Classes to manage installer configuration"""

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Iterable, Optional

from .environment import should_skip_for_os
from .schema_validation import validate_packages
from .userio import normalise_bool, normalise_str

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from ._compat import HAS_TOML, tomllib  # HAS_TOML re-exported for callers

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

    def _ctx_get(self, key: str, default: str = "") -> str:
        """Get a value from the IshConfig context, or return *default*."""
        if self._cfg is not None and hasattr(self._cfg, "context"):
            return self._cfg.context.get(key, default)
        return default

    def _passes_tag_filter(self, pkg: dict) -> bool:
        """Return True if *pkg* should be included given its tags.

        Tag semantics are derived entirely from ``cfg.data_template`` — no
        tag names are hard-coded here.  Supported patterns:

        - ``<var>``   — where ``var`` is a ``bool`` key: include when truthy.
        - ``!<var>``  — negation of the above.
        - ``<val>``   — where ``val`` appears in a ``tags`` variable's
                        ``values`` list: include when the variable == val.
        - ``<val>``   — where ``val`` appears in an ``ordered_tags`` variable's
                        ``values`` list: include when the variable's index ≥ val's.

        Packages without tags are always included.
        """
        tags = pkg.get("tags", []) or []
        if not tags:
            return True

        template: dict = {}
        if self._cfg is not None:
            template = getattr(self._cfg, "data_template", None) or {}

        for tag in tags:
            negated = tag.startswith("!")
            name = tag[1:] if negated else tag
            matched = self._tag_matches(name, template, pkg)
            if negated:
                matched = not matched
            if not matched:
                return False
        return True

    def _tag_matches(self, tag: str, template: dict, pkg: dict) -> bool:
        """Return True if *tag* is satisfied by the current context and template."""
        ntag = normalise_str(tag)

        # 1. tag == a bool variable name
        for var, vspec in template.items():
            if normalise_str(var) == ntag and vspec.get("type") == "bool":
                return normalise_bool(self._ctx_get(var)) == "true"

        # 2. tag is a value declared in a tags / ordered_tags variable
        for var, vspec in template.items():
            t = vspec.get("type")
            if t not in ("tags", "ordered_tags"):
                continue
            nvalues = [normalise_str(v) for v in vspec.get("values", [])]
            if ntag not in nvalues:
                continue
            ncurrent = normalise_str(self._ctx_get(var))
            if t == "tags":
                return ncurrent == ntag
            # ordered_tags: current index must be >= tag index (higher implies lower)
            if ncurrent not in nvalues:
                return False
            return nvalues.index(ncurrent) >= nvalues.index(ntag)

        log.warning("Unknown package tag %r on %s", tag, pkg.get("name"))
        return False

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

        super().__init__(config=config, config_fn=config_fn, cfg=cfg, **kwargs)
