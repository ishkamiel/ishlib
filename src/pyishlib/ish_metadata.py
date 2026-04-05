#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
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
from typing import Any, Dict, Iterator, Optional, Set, Tuple, Union

from pyishlib.installer_config import HAS_TOML  # pylint: disable=duplicate-code

if HAS_TOML:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    _TOML_LOADS = tomllib.loads
    _TOML_DECODE_ERROR = tomllib.TOMLDecodeError
else:
    _TOML_LOADS = None
    _TOML_DECODE_ERROR = None

try:
    import tomli_w

    HAS_TOML_W = True
except ImportError:
    HAS_TOML_W = False

log = logging.getLogger(__name__)

# Pattern: : <<'__ISH__' ... __ISH__
_RE_SHELL_HEREDOC = re.compile(
    r"^[ \t]*:[ \t]+<<\s*['\"]?__ISH__['\"]?\s*$(.*?)^__ISH__\s*$",
    re.MULTILINE | re.DOTALL,
)

# Pattern: __ish__ = """..."""  or __ish__ = '''...'''
_RE_PYTHON_ASSIGN = re.compile(
    r"^__ish__\s*=\s*(?:\"{3}|'{3})(.*?)(?:\"{3}|'{3})",
    re.MULTILINE | re.DOTALL,
)

# Pattern: <#__ISH__ ... __ISH__#>
_RE_POWERSHELL_BLOCK = re.compile(
    r"<#__ISH__\s*?\r?\n(.*?)^__ISH__#>",
    re.MULTILINE | re.DOTALL,
)

# Pattern: comment-prefixed block with any single-char or double-char prefix
# e.g., # __ISH__ / // __ISH__ / -- __ISH__ / ; __ISH__ / % __ISH__
_RE_COMMENT_BLOCK = re.compile(
    r"^(?P<prefix>[#;%]|//|--)[ \t]+__ISH__\s*$(?P<body>.*?)^(?P=prefix)[ \t]+__ISH__\s*$",
    re.MULTILINE | re.DOTALL,
)


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
    # Shell heredoc
    m = _RE_SHELL_HEREDOC.search(text)
    if m:
        return m.group(1)

    # Python assignment
    m = _RE_PYTHON_ASSIGN.search(text)
    if m:
        return m.group(1)

    # PowerShell block comment
    m = _RE_POWERSHELL_BLOCK.search(text)
    if m:
        return m.group(1)

    # Comment-prefixed block
    m = _RE_COMMENT_BLOCK.search(text)
    if m:
        return _strip_comment_prefix(m.group("body"), m.group("prefix"))

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


def read_metadata(file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """Read __ISH__ metadata from a file.

    Reads both embedded metadata and sidecar metadata when available.
    If both exist, they are merged with the sidecar taking precedence
    on conflicts (a warning is logged for each conflict).

    Args:
        file_path: Path to the file to read metadata from.

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
        return merged

    return embedded if embedded is not None else sidecar


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
