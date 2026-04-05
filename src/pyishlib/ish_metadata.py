# -*- coding: utf-8 -*-
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

# Pattern: : <<'__ISH__' ... __ISH__
_RE_SHELL_HEREDOC = re.compile(
    r"""^[ \t]*:[ \t]+<<\s*['"]?__ISH__['"]?\s*$""" r"""(.*?)""" r"""^__ISH__\s*$""",
    re.MULTILINE | re.DOTALL,
)

# Pattern: __ish__ = """..."""  or __ish__ = '''...'''
_RE_PYTHON_ASSIGN = re.compile(
    r"""^__ish__\s*=\s*(?:"{3}|'{3})""" r"""(.*?)""" r"""(?:"{3}|'{3})""",
    re.MULTILINE | re.DOTALL,
)

# Pattern: <#__ISH__ ... __ISH__#>
_RE_POWERSHELL_BLOCK = re.compile(
    r"""<#__ISH__\s*?\r?\n""" r"""(.*?)""" r"""^__ISH__#>""",
    re.MULTILINE | re.DOTALL,
)

# Pattern: comment-prefixed block with any single-char or double-char prefix
# e.g., # __ISH__ / // __ISH__ / -- __ISH__ / ; __ISH__ / % __ISH__
_RE_COMMENT_BLOCK = re.compile(
    r"""^(?P<prefix>[#;%]|//|--)[ \t]+__ISH__\s*$"""
    r"""(?P<body>.*?)"""
    r"""^(?P=prefix)[ \t]+__ISH__\s*$""",
    re.MULTILINE | re.DOTALL,
)


def _parse_toml(text: str) -> Dict[str, Any]:
    """Parse a TOML string and return the resulting dictionary."""
    if not HAS_TOML:
        raise ImportError(
            "TOML support requires Python 3.11+ (tomllib) "
            "or the 'tomli' package for older Python versions"
        )
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
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


def read_metadata(file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """Read __ISH__ metadata from a file.

    Tries embedded metadata first, then falls back to a .ish sidecar file.

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
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = None

    if text is not None:
        raw = _extract_embedded(text)
        if raw is not None:
            return _parse_toml(raw)

    # Fall back to sidecar
    raw = _read_sidecar(file_path)
    if raw is not None:
        return _parse_toml(raw)

    return None


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


def _cli_main(argv=None):
    """CLI entry point for ish_metadata."""
    parser = argparse.ArgumentParser(
        prog="ish_metadata",
        description="Read __ISH__ metadata from files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # read subcommand
    read_parser = subparsers.add_parser("read", help="Read metadata from a file")
    read_parser.add_argument("file", type=Path, help="File to read metadata from")
    read_parser.add_argument(
        "--format",
        choices=["json", "toml"],
        default="json",
        help="Output format (default: json)",
    )

    # scan subcommand
    scan_parser = subparsers.add_parser(
        "scan", help="Scan a directory for files with metadata"
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

    args = parser.parse_args(argv)

    if args.command == "read":
        meta = read_metadata(args.file)
        if meta is None:
            print(f"No __ISH__ metadata found in {args.file}")
            return 1
        _print_output(meta, args.format)
        return 0

    if args.command == "scan":
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

    return 1


def _print_output(data: Dict[str, Any], fmt: str) -> None:
    """Print metadata in the requested format."""
    if fmt == "toml":
        try:
            import tomli_w

            print(tomli_w.dumps(data))
        except ImportError:
            print(json.dumps(data, indent=2))
            log.warning("tomli_w not installed, falling back to JSON output")
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    raise SystemExit(_cli_main())
