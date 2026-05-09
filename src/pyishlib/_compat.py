# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Compatibility shims for optional dependencies."""

import logging
import os
import re
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


# TOML basic-string escapes per https://toml.io/en/v1.0.0#string.
# The spec forbids unescaped C0 control characters and requires
# backslash / double-quote to be escaped in basic strings.
_TOML_BASIC_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def toml_escape_basic_string(value: str) -> str:
    """Escape *value* for inclusion in a TOML basic string literal.

    Protects a generated config against input that contains quotes,
    backslashes, newlines, or other characters the TOML spec forbids
    inside basic strings (C0 control chars `< 0x20`, plus `DEL`
    (`U+007F`)).  ``tomllib`` round-trips the escape sequences back to
    the original string on the next load.
    """

    def _escape_char(ch: str) -> str:
        mapped = _TOML_BASIC_ESCAPES.get(ch)
        if mapped is not None:
            return mapped
        codepoint = ord(ch)
        if codepoint < 0x20 or codepoint == 0x7F:
            return f"\\u{codepoint:04x}"
        return ch

    return "".join(_escape_char(ch) for ch in value)


# TOML 1.0 bare-key grammar: ALPHA / DIGIT / "-" / "_" (one or more).
_TOML_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def is_toml_bare_key(name: str) -> bool:
    """Return True iff *name* is a valid TOML bare key.

    Matches the TOML 1.0 grammar:
    https://toml.io/en/v1.0.0#keys -- ``ALPHA / DIGIT / "-" / "_"``.
    Quoted keys (``"a key"`` / ``'a key'``) and dotted keys
    (``a.b.c``) are deliberately rejected.
    """
    return bool(_TOML_BARE_KEY_RE.match(name))


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically via a sibling tmp file.

    Uses ``os.replace`` so a signal or crash mid-write cannot leave
    *path* containing a truncated / half-populated document.
    """
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
