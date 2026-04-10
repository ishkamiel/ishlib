#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Read embedded __ISH__ metadata from files.

Supports extracting TOML metadata embedded in files using the __ISH__ sentinel
convention. The metadata can be embedded in several ways depending on the file
type:

- **Shell (bash/zsh):** `: <<'__ISH__'` heredoc block
- **Python:** `__ish__ = \"\"\"...\"\"\"` assignment
- **PowerShell:** `<#__ISH__` ... `__ISH__#>` block comment
- **Text/config:** Comment-prefixed `# __ISH__` ... `# __ISH__` blocks
- **Sidecar:** `<filename>.ish` file containing raw TOML

The extracted text is parsed as TOML and returned as a dictionary.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

from ._compat import HAS_TOML, tomllib

_TOML_LOADS = tomllib.loads if HAS_TOML and tomllib is not None else None
_TOML_DECODE_ERROR = (
    tomllib.TOMLDecodeError if HAS_TOML and tomllib is not None else None
)

try:
    import tomli_w

    HAS_TOML_W = True
except ImportError:
    HAS_TOML_W = False

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata block patterns
#
# Each pattern matches a complete __ISH__ metadata block and captures the
# body content in a named ``body`` group.  The same compiled regex is used
# for both *extraction* (via ``m.group("body")``) and *removal* (via
# ``pattern.sub("", text)``).  Trailing horizontal whitespace and an
# optional newline are consumed so that removal leaves clean output.
# ---------------------------------------------------------------------------

# Shell heredoc: : <<'__ISH__' ... __ISH__
_RE_SHELL_HEREDOC = re.compile(
    r"^[ \t]*:[ \t]+<<\s*['\"]?__ISH__['\"]?[ \t]*\n"
    r"(?P<body>.*?)"
    r"^__ISH__[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

# Python assignment: __ish__ = """..."""  or __ish__ = '''...'''
_RE_PYTHON_ASSIGN = re.compile(
    r"^__ish__\s*=\s*(?:\"{3}|'{3})(?P<body>.*?)(?:\"{3}|'{3})[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

# PowerShell block comment: <#__ISH__ ... __ISH__#>
_RE_POWERSHELL_BLOCK = re.compile(
    r"<#__ISH__\s*?\r?\n(?P<body>.*?)^__ISH__#>[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

# Comment-prefixed block: # __ISH__ ... # __ISH__
# Supports: #, //, --, ;, % prefixes
_RE_COMMENT_BLOCK = re.compile(
    r"^(?P<prefix>[#;%]|//|--)[ \t]+__ISH__[ \t]*\n"
    r"(?P<body>.*?)"
    r"^(?P=prefix)[ \t]+__ISH__[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

# Ordered list used by both extraction and removal.
_METADATA_PATTERNS = [
    _RE_SHELL_HEREDOC,
    _RE_PYTHON_ASSIGN,
    _RE_POWERSHELL_BLOCK,
    _RE_COMMENT_BLOCK,
]


def _parse_toml(text: str) -> Dict[str, Any]:
    """Parse a TOML string and return the resulting dictionary."""
    if not HAS_TOML or _TOML_LOADS is None:
        raise ImportError(
            "TOML support requires Python 3.11+ (tomllib) "
            "or the 'tomli' package for older versions"
        )
    try:
        return _TOML_LOADS(text)
    except _TOML_DECODE_ERROR as e:
        raise ValueError(f"Invalid TOML metadata: {e}") from e


def _strip_comment_prefix(body: str, prefix: str) -> str:
    """Strip a comment prefix from each line of a block."""
    lines = []
    for line in body.splitlines(True):
        stripped = line.lstrip()
        if stripped.startswith(prefix):
            after = stripped[len(prefix) :]
            # Remove exactly one leading space after the prefix if present
            if after.startswith(" "):
                after = after[1:]
            lines.append(after)
        else:
            # Empty or whitespace-only lines
            lines.append(line)
    return "".join(lines)


def _extract_embedded(text: str) -> Optional[str]:
    """Try to extract __ISH__ metadata from file text.

    Tries each embedding pattern in order and returns the first match,
    or None if no embedded metadata is found.
    """
    for pattern in _METADATA_PATTERNS:
        m = pattern.search(text)
        if m:
            body = m.group("body")
            # Comment-prefixed blocks need prefix stripping
            if "prefix" in m.groupdict():
                body = _strip_comment_prefix(body, m.group("prefix"))
            return body
    return None


def _read_sidecar(file_path: Path) -> Optional[str]:
    """Read the .ish sidecar file for a given path, if it exists."""
    sidecar = file_path.parent / (file_path.name + ".ish")
    if sidecar.is_file():
        return sidecar.read_text(encoding="utf-8")
    return None


def merge_metadata(
    base: Dict[str, Any],
    override: Dict[str, Any],
    base_label: str = "embedded",
    override_label: str = "sidecar",
) -> Tuple[Dict[str, Any], list]:
    """Deep-merge two metadata dicts, with *override* winning on conflicts.

    Returns the merged dict and a list of conflict descriptions (strings).
    Each conflict description notes the key path and differing values.
    This function can be reused wherever two metadata sources need merging.

    Args:
        base: The base metadata dictionary.
        override: The overriding metadata dictionary.
        base_label: Human-readable label for the base source.
        override_label: Human-readable label for the override source.

    Returns:
        A (merged_dict, conflicts) tuple.  *conflicts* is empty when the
        two dicts are compatible.
    """
    conflicts: list = []

    def _merge(dst, src, path=""):
        for key, val in src.items():
            key_path = f"{path}.{key}" if path else key
            if key not in dst:
                dst[key] = val
            elif isinstance(dst[key], dict) and isinstance(val, dict):
                _merge(dst[key], val, key_path)
            elif dst[key] != val:
                conflicts.append(
                    f"{key_path}: {base_label}={dst[key]!r} vs "
                    f"{override_label}={val!r} (using {override_label})"
                )
                dst[key] = val

    merged = json.loads(json.dumps(base))  # deep copy via JSON round-trip
    _merge(merged, override)
    return merged, conflicts


def extract_packages_from_metadata(
    packages_section: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Convert a ``[packages]`` metadata section to installer package dicts.

    The metadata ``[packages]`` section uses the same TOML table format as
    the main ``packages.toml``::

        [packages]
        vim = {}
        git = {pref = ["apt"]}

    This function converts each entry to a dict with a ``"name"`` key,
    matching the format expected by :class:`~pyishlib.installer.Installer`.

    Args:
        packages_section: The parsed ``[packages]`` dict from metadata.

    Returns:
        A list of package dicts, e.g. ``[{"name": "vim"}, ...]``.
    """
    result: List[Dict[str, Any]] = []
    for name, attrs in packages_section.items():
        pkg = dict(attrs) if isinstance(attrs, dict) else {}
        pkg["name"] = name
        result.append(pkg)
    return result


def collect_metadata_packages(
    metadata: Optional[Dict[str, Any]],
    source: str = "<unknown>",
) -> List[Dict[str, Any]]:
    """Safely extract packages from a metadata dict.

    Checks that *metadata* contains a ``packages`` key with a dict value,
    converts it to installer package dicts, and returns them.  Logs a
    warning and returns an empty list if the value is present but not a dict.

    Args:
        metadata: Parsed ``__ISH__`` metadata (may be *None*).
        source:   Human-readable label for warning messages.

    Returns:
        A list of package dicts, or an empty list.
    """
    if not metadata:
        return []
    meta_packages = metadata.get("packages")
    if isinstance(meta_packages, dict):
        return extract_packages_from_metadata(meta_packages)
    if meta_packages is not None:
        log.warning(
            "Ignoring invalid 'packages' in %s: expected dict, got %s",
            source,
            type(meta_packages).__name__,
        )
    return []


def remove_metadata_blocks(text: str) -> str:
    """Remove all ``__ISH__`` metadata blocks from *text*.

    Uses the same patterns as :func:`_extract_embedded` so that
    extraction and removal are always consistent.  The surrounding file
    content is left intact.

    Args:
        text: The full file content as a string.

    Returns:
        The text with all metadata blocks removed.
    """
    for pattern in _METADATA_PATTERNS:
        text = pattern.sub("", text)
    return text


def read_metadata(
    file_path: Union[str, Path],
    validate: bool = True,
) -> Optional[Dict[str, Any]]:
    """Read __ISH__ metadata from a file.

    Reads both embedded metadata and sidecar metadata when available.
    If both exist, they are merged with the sidecar taking precedence
    on conflicts (a warning is logged for each conflict).

    When *validate* is True (the default), the final metadata is checked
    against the ``__ISH__`` metadata schema.  Validation errors are logged
    as warnings but do **not** prevent the metadata from being returned.

    Args:
        file_path: Path to the file to read metadata from.
        validate:  Whether to validate the metadata against the schema.

    Returns:
        Parsed TOML metadata as a dictionary, or None if no metadata found.

    Raises:
        ImportError: If TOML support is not available.
        ValueError: If the embedded text is not valid TOML.
    """
    file_path = Path(file_path)

    # Try embedded metadata
    embedded = None
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = None

    if text is not None:
        raw = _extract_embedded(text)
        if raw is not None:
            embedded = _parse_toml(raw)

    # Try sidecar
    sidecar = None
    raw = _read_sidecar(file_path)
    if raw is not None:
        sidecar = _parse_toml(raw)

    # Merge or return whichever is available
    if embedded is not None and sidecar is not None:
        merged, conflicts = merge_metadata(embedded, sidecar)
        for conflict in conflicts:
            log.warning("%s: metadata conflict: %s", file_path, conflict)
        result = merged
    else:
        result = embedded if embedded is not None else sidecar

    if result is not None and validate:
        _validate_result(result, str(file_path))

    return result


def _validate_result(metadata: Dict[str, Any], source: str) -> None:
    """Validate metadata against the schema, logging warnings on failure."""
    # Import here to avoid circular imports
    from .schema_validation import validate_metadata  # pylint: disable=C0415

    err = validate_metadata(metadata, source=source)
    if err is not None:
        log.warning("%s", err)


def scan_directory(
    directory: Union[str, Path],
    extensions: Optional[Set[str]] = None,
    recursive: bool = True,
) -> Iterator[Tuple[Path, Dict[str, Any]]]:
    """Scan a directory for files with __ISH__ metadata.

    Args:
        directory: Directory to scan.
        extensions: If given, only consider files with these extensions
                    (e.g., {".sh", ".py"}).  Include the leading dot.
        recursive: Whether to recurse into subdirectories (default True).

    Yields:
        (path, metadata) tuples for each file that has __ISH__ metadata.
    """
    directory = Path(directory)
    walker = directory.rglob("*") if recursive else directory.glob("*")

    for path in walker:
        if not path.is_file():
            continue
        if extensions and path.suffix not in extensions:
            continue
        try:
            meta = read_metadata(path)
        except (ValueError, ImportError):
            log.warning("Failed to parse metadata from %s", path)
            continue
        if meta is not None:
            yield path, meta


def register_cli(subparsers: argparse._SubParsersAction) -> None:
    """Register metadata subcommands onto an existing subparsers group.

    This allows a parent CLI to embed the metadata commands as part of a
    larger tool, e.g.::

        parent_sub = parent_parser.add_subparsers(...)
        ish_metadata.register_cli(parent_sub)

    Args:
        subparsers: An ``argparse._SubParsersAction`` to add commands to.
    """
    # read subcommand
    read_parser = subparsers.add_parser(
        "meta-read", help="Read __ISH__ metadata from a file"
    )
    read_parser.add_argument("file", type=Path, help="File to read metadata from")
    read_parser.add_argument(
        "--format",
        choices=["json", "toml"],
        default="json",
        help="Output format (default: json)",
    )
    read_parser.set_defaults(func=_cmd_read)

    # scan subcommand
    scan_parser = subparsers.add_parser(
        "meta-scan", help="Scan a directory for files with __ISH__ metadata"
    )
    scan_parser.add_argument("directory", type=Path, help="Directory to scan")
    scan_parser.add_argument(
        "--ext",
        action="append",
        dest="extensions",
        help="File extensions to include (e.g., .sh .py)",
    )
    scan_parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not recurse into subdirectories",
    )
    scan_parser.add_argument(
        "--format",
        choices=["json", "toml"],
        default="json",
        help="Output format (default: json)",
    )
    scan_parser.set_defaults(func=_cmd_scan)


def _cmd_read(args: argparse.Namespace) -> int:
    """Handler for the meta-read subcommand."""
    meta = read_metadata(args.file)
    if meta is None:
        print(f"No __ISH__ metadata found in {args.file}")
        return 1
    _print_output(meta, args.format)
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    """Handler for the meta-scan subcommand."""
    exts = set(args.extensions) if args.extensions else None
    results = {
        str(path): meta
        for path, meta in scan_directory(
            args.directory,
            extensions=exts,
            recursive=not args.no_recursive,
        )
    }
    if not results:
        print("No files with __ISH__ metadata found.")
        return 1
    _print_output(results, args.format)
    return 0


def _cli_main(argv=None):
    """CLI entry point for standalone ish_metadata usage."""
    parser = argparse.ArgumentParser(
        prog="ish_metadata",
        description="Read __ISH__ metadata from files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_cli(subparsers)

    args = parser.parse_args(argv)
    return args.func(args)


def _print_output(data: Dict[str, Any], fmt: str) -> None:
    """Print metadata in the requested format."""
    if fmt == "toml" and HAS_TOML_W:
        print(tomli_w.dumps(data))  # pylint: disable=possibly-used-before-assignment
    else:
        if fmt == "toml":
            log.warning("tomli_w not installed, falling back to JSON output")
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    raise SystemExit(_cli_main())
