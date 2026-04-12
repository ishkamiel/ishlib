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

from .environment import should_skip_for_os, is_linux_desktop, is_gnome
from .schema_validation import validate_packages

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from ._compat import HAS_TOML, tomllib  # HAS_TOML re-exported for callers

log = logging.getLogger(__name__)

#: Known tags that map to runtime conditions rather than context variables.
_RUNTIME_TAGS = frozenset({"gui", "gnome"})

#: Tags that map to context variable names (value must be truthy).
_CTX_TRUTHY_TAGS: dict = {
    "build_tools": "needBuildTools",
    "work": "isWork",
    "gaming": "isGaming",
}

#: Tags that map to context variables that must NOT be truthy.
_CTX_FALSY_TAGS: dict = {
    "no_work": "isWork",
}


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

    def _ctx_truthy(self, key: str) -> bool:
        """Return True if the context variable *key* normalises to true."""
        from .userio import normalise_bool

        val = self._ctx_get(key)
        return normalise_bool(val) == "true"

    def _passes_tag_filter(self, pkg: dict) -> bool:
        """Return True if *pkg* should be included given its tags.

        Tags control which packages are selected based on user configuration
        and runtime environment:

        - ``min``         — always included
        - ``build_tools`` — only when ``needBuildTools`` is truthy in context
        - ``work``        — only when ``isWork`` is truthy
        - ``no_work``     — only when ``isWork`` is NOT truthy
        - ``gaming``      — only when ``isGaming`` is truthy
        - ``personal``    — only when ``machineType == "personal"``
        - ``gui``         — only when a Linux desktop session is detected
        - ``gnome``       — only when GNOME desktop is detected
        - *(no tags)*     — included unless ``machineType == "min"``
        """
        tags = pkg.get("tags", [])
        if not tags:
            # No tags: default packages, excluded on minimal installs
            return self._ctx_get("machineType") != "min"

        if "min" in tags:
            return True

        for tag in tags:
            if tag in _CTX_TRUTHY_TAGS:
                if not self._ctx_truthy(_CTX_TRUTHY_TAGS[tag]):
                    return False
            elif tag in _CTX_FALSY_TAGS:
                if self._ctx_truthy(_CTX_FALSY_TAGS[tag]):
                    return False
            elif tag == "personal":
                if self._ctx_get("machineType") != "personal":
                    return False
            elif tag == "gui":
                if not is_linux_desktop():
                    return False
            elif tag == "gnome":
                if not is_gnome():
                    return False
            else:
                log.warning("Unknown package tag %r on %s", tag, pkg.get("name"))

        return True

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
