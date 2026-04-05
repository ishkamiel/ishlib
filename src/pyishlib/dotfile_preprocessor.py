# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Dotfile preprocessing: directive handling, variable substitution, metadata stripping.

Provides preprocessing for dotfiles managed by :class:`DotfileApplier`.
During the prepare stage, each source file is processed to:

1. **Extract metadata** -- read ``__ISH__`` metadata blocks and store them
   on the :class:`DotFile` object.
2. **Strip metadata** -- remove the metadata blocks from the output so the
   installed dotfile is clean.
3. **Process directives** -- handle single-line ``@ish`` directives embedded
   in language-appropriate comments (e.g. ``#@ish set name=value``).
4. **Substitute variables** -- replace ``${__ish_<name>}`` references with
   their values.

Directive syntax
----------------

Directives are single-line comments using the file's native comment prefix
followed immediately by ``@ish``::

    #@ish set editor=vim          (shell, python, yaml, ruby, ...)
    //@ish set editor=vim         (C, JS, Go, Rust, ...)
    --@ish set editor=vim         (SQL, Lua, Haskell, ...)
    ;@ish set editor=vim          (ini, lisp, ...)
    %@ish set editor=vim          (TeX, Matlab, ...)

Because the directive is a valid comment in every case, syntax checkers
and linters see nothing unusual.

Supported directives:

- ``set <name>=<value>`` -- define a preprocessing variable.

Variable substitution
---------------------

Variable references use the syntax ``${__ish_<name>}``.  In shell scripts
this looks like a normal variable expansion; in other file formats it is
a recognisable but harmless placeholder.  The ``__ish_`` prefix ensures
no collision with real environment variables.

Variables are resolved in order of precedence (highest first):

1. ``#@ish set`` directives in the file itself
2. Variables passed programmatically (e.g. from CLI or config)
3. The ``[vars]`` section of embedded ``__ISH__`` metadata
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

from .dotfile import DotFile
from .ish_metadata import read_metadata

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Directive line: <comment_prefix>@ish <command>
_RE_DIRECTIVE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<prefix>[#;%]|//|--)@ish\s+(?P<command>.+)$"
)

# Variable reference: ${__ish_<name>}
_RE_VAR_REF = re.compile(r"\$\{__ish_(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\}")

# Metadata block removal patterns -- mirror those in ish_metadata but
# designed for re.sub() removal rather than extraction.
_RE_REMOVE_SHELL_HEREDOC = re.compile(
    r"^[ \t]*:[ \t]+<<\s*['\"]?__ISH__['\"]?\s*$.*?^__ISH__[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

_RE_REMOVE_PYTHON_ASSIGN = re.compile(
    r"^__ish__\s*=\s*(?:\"{3}|\'{3}).*?(?:\"{3}|\'{3})[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

_RE_REMOVE_POWERSHELL_BLOCK = re.compile(
    r"<#__ISH__\s*?\r?\n.*?^__ISH__#>[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

_RE_REMOVE_COMMENT_BLOCK = re.compile(
    r"^(?P<prefix>[#;%]|//|--)[ \t]+__ISH__\s*$"
    r".*?"
    r"^(?P=prefix)[ \t]+__ISH__[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)

_METADATA_REMOVAL_PATTERNS = [
    _RE_REMOVE_SHELL_HEREDOC,
    _RE_REMOVE_PYTHON_ASSIGN,
    _RE_REMOVE_POWERSHELL_BLOCK,
    _RE_REMOVE_COMMENT_BLOCK,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _remove_metadata_blocks(text: str) -> str:
    """Remove all ``__ISH__`` metadata blocks from *text*."""
    for pattern in _METADATA_REMOVAL_PATTERNS:
        text = pattern.sub("", text)
    return text


def _parse_set_directive(command: str) -> Optional[tuple]:
    """Parse ``set name=value``.  Returns *(name, value)* or *None*."""
    m = re.match(r"set\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*)", command)
    if m:
        return m.group(1), m.group(2).strip()
    return None


def _substitute_variables(text: str, variables: Dict[str, str]) -> str:
    """Replace ``${__ish_<name>}`` references with variable values."""

    def _replacer(m: re.Match) -> str:
        name = m.group("name")
        if name in variables:
            return variables[name]
        log.warning("Undefined preprocessing variable: __ish_%s", name)
        return m.group(0)  # leave undefined references intact

    return _RE_VAR_REF.sub(_replacer, text)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def preprocess(
    dotfile: DotFile,
    variables: Optional[Dict[str, str]] = None,
) -> str:
    """Preprocess a single dotfile source.

    The processing pipeline:

    1. Read the source file as text.
    2. Extract ``__ISH__`` metadata and store on *dotfile.metadata*.
    3. Remove metadata blocks from the content.
    4. Scan for ``@ish`` directive lines, execute them, and remove them.
    5. Substitute ``${__ish_<name>}`` variable references.

    Args:
        dotfile: The :class:`DotFile` to preprocess.
        variables: Optional initial variable table (e.g. from CLI or
                   config).  These are overridden by ``set`` directives
                   in the file.

    Returns:
        The processed file content as a string.

    Raises:
        UnicodeDecodeError: If the file cannot be read as UTF-8 (the
            caller should fall back to a raw copy).
    """
    text = dotfile.source.read_text(encoding="utf-8")

    # 1. Extract metadata via the existing ish_metadata machinery
    meta = read_metadata(dotfile.source)
    if meta is not None:
        dotfile.metadata = meta

    # 2. Build the variable table (lowest to highest precedence)
    local_vars: Dict[str, str] = {}

    # Metadata [vars] section (lowest precedence)
    if meta and "vars" in meta:
        for key, val in meta["vars"].items():
            local_vars[key] = str(val)

    # Passed-in variables (middle precedence)
    if variables:
        local_vars.update(variables)

    # 3. Remove metadata blocks from content
    text = _remove_metadata_blocks(text)

    # 4. Process directive lines (highest precedence for set)
    lines = text.splitlines(True)
    output_lines: list = []
    for line in lines:
        m = _RE_DIRECTIVE.match(line.rstrip("\n\r"))
        if m:
            cmd = m.group("command").strip()
            parsed = _parse_set_directive(cmd)
            if parsed:
                local_vars[parsed[0]] = parsed[1]
            else:
                log.warning("Unknown @ish directive: %s", cmd)
            continue  # directive line is consumed
        output_lines.append(line)

    text = "".join(output_lines)

    # 5. Substitute variables
    text = _substitute_variables(text, local_vars)

    return text
