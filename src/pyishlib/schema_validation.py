# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Shared schema validation for installer configs and ``__ISH__`` metadata.

Provides Cerberus-based validation helpers that load schema fragments from
``src/schema/`` and expose them to both :mod:`installer_config` (for
``packages.toml`` / ``packages.json``) and :mod:`ish_metadata` (for
``[packages]`` sections embedded in file metadata).

The package value schema is defined **once** in
``schema/packages_cerberus.json`` and consumed by both validation paths,
ensuring consistency between standalone package configs and metadata-embedded
package declarations.

When Cerberus is not available, all validation functions degrade gracefully
by logging a debug message and returning without error.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

try:
    import cerberus

    HAS_CERBERUS = True
except ImportError:
    HAS_CERBERUS = False

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# ---------------------------------------------------------------------------
# Schema directory
# ---------------------------------------------------------------------------

SCHEMA_DIR: Path = Path(__file__).parent.parent / "schema"


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=None)
def _load_schema(filename: str) -> Dict[str, Any]:
    """Load a JSON schema file from the schema directory.

    Results are cached so that schema files are read only once per process.

    Uses ``yaml.safe_load`` when available (tolerant of comments and
    trailing commas), otherwise falls back to ``json.load``.
    """
    path = SCHEMA_DIR / filename
    with open(path, "r", encoding="utf-8") as fh:
        if HAS_YAML:
            return yaml.safe_load(fh)
        return json.load(fh)


def load_packages_schema() -> Dict[str, Any]:
    """Load the shared packages Cerberus schema fragment.

    Returns the schema dict from ``schema/packages_cerberus.json``.
    This is the schema for a dict of ``{name: {attrs...}}`` package
    entries -- the same format used in both ``packages.toml`` and
    ``__ISH__`` metadata ``[packages]`` sections.

    The result is cached after first load.
    """
    return _load_schema("packages_cerberus.json")


def load_metadata_schema() -> Dict[str, Any]:
    """Load the ``__ISH__`` metadata Cerberus schema.

    Returns the schema dict from ``schema/ish_metadata_cerberus.json``.
    The ``packages`` key within it is validated separately via
    :func:`validate_packages`.

    The result is cached after first load.
    """
    return _load_schema("ish_metadata_cerberus.json")


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def validate_packages(
    packages: Dict[str, Any],
    source: str = "<unknown>",
) -> Optional[str]:
    """Validate a packages dict against the shared package schema.

    Args:
        packages: A dict of ``{name: {attrs...}}`` package entries.
        source:   Human-readable label for error messages (e.g. file path).

    Returns:
        *None* on success, or an error description string on failure.
        When Cerberus is unavailable, always returns *None*.
    """
    if not HAS_CERBERUS:
        log.debug("cerberus not available, skipping package validation for %s", source)
        return None

    schema = load_packages_schema()
    validator = cerberus.Validator({"packages": schema})
    if not validator.validate({"packages": packages}):
        return f"Package validation failed ({source}): {validator.errors}"
    return None


def validate_metadata(
    metadata: Dict[str, Any],
    source: str = "<unknown>",
) -> Optional[str]:
    """Validate an ``__ISH__`` metadata dict against the metadata schema.

    Validates the top-level metadata structure (``only_on``, ``ignore_on``,
    ``vars``, etc.) and, if a ``[packages]`` section is present, validates
    it against the shared package schema.

    Args:
        metadata: Parsed metadata dictionary.
        source:   Human-readable label for error messages.

    Returns:
        *None* on success, or an error description string on failure.
        When Cerberus is unavailable, always returns *None*.
    """
    if not HAS_CERBERUS:
        log.debug("cerberus not available, skipping metadata validation for %s", source)
        return None

    schema = load_metadata_schema()
    validator = cerberus.Validator({"metadata": schema["metadata"]})
    if not validator.validate({"metadata": metadata}):
        return f"Metadata validation failed ({source}): {validator.errors}"

    # Validate packages sub-section with the shared package schema
    if "packages" in metadata and isinstance(metadata["packages"], dict):
        pkg_err = validate_packages(metadata["packages"], source=source)
        if pkg_err is not None:
            return pkg_err

    return None
