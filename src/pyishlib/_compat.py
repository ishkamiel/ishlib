# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Compatibility shims for optional dependencies."""

import logging
import sys
from pathlib import Path
from typing import Any, Mapping

if sys.version_info >= (3, 11):
    import tomllib  # noqa: F401

    HAS_TOML = True
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]  # noqa: F401

        HAS_TOML = True
    except ImportError:
        tomllib = None  # type: ignore[assignment]
        HAS_TOML = False


log = logging.getLogger(__name__)


def load_toml_file(
    path: Path,
    *,
    default: Any = None,
    warn_missing_toml: bool = False,
) -> Any:
    """Load a TOML file, returning *default* on any failure.

    - Missing file -> *default* (silent).
    - ``tomllib`` unavailable -> *default*; a warning is emitted only when
      *warn_missing_toml* is ``True``.
    - Decode / I/O error -> log a warning, return *default*.

    Callers own schema interpretation after the load (e.g. picking a
    sub-table, coercing types).
    """
    if tomllib is None:
        if warn_missing_toml:
            log.warning(
                "TOML support unavailable (need Python 3.11+ or 'tomli'); ignoring %s",
                path,
            )
        return default
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("Failed to read TOML file %s: %s", path, exc)
        return default


def load_toml_file_strict(path: Path) -> Mapping[str, Any]:
    """Load a TOML file, raising on failure.

    Raises:
        ImportError: if ``tomllib`` is unavailable.
        ValueError: if the file cannot be parsed as TOML.
        OSError: if the file cannot be opened.
    """
    if tomllib is None or not HAS_TOML:
        raise ImportError(
            "TOML support requires Python 3.11+ (tomllib) "
            "or the 'tomli' package for older Python versions"
        )
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Config file is not valid TOML: {exc}") from exc
