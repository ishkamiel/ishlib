#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Base file preprocessing: directive handling, variable substitution, metadata stripping.

Provides the core preprocessing pipeline used by both :class:`DotFilePreprocessor`
(for dotfile installation) and :class:`DotfileScript` (for executable scripts).

The pipeline processes a text file through four stages:

1. **Extract metadata** -- read ``__ISH__`` metadata blocks.
2. **Strip metadata** -- remove the metadata blocks from the output.
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

Supported directives:

- ``set <name>=<value>`` -- define a preprocessing variable.
- ``if <expr>`` -- begin a conditional block; *expr* is evaluated as
  Python with the :class:`DotfileContext` available as ``ish``.
- ``elif <expr>`` -- else-if branch.
- ``else`` -- fallback branch.
- ``fi`` -- end a conditional block.

Variable substitution
---------------------

Variable references use the syntax ``${__ish_<name>}``.  The ``__ish_``
prefix ensures no collision with real environment variables.

Variables are resolved in order of precedence (highest first):

1. ``#@ish set`` directives in the file itself
2. Variables passed programmatically (e.g. from CLI or config)
3. The ``[vars]`` section of embedded ``__ISH__`` metadata
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .dotfile_context import DotfileContext
from .ish_metadata import read_metadata, remove_metadata_blocks

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


# ---------------------------------------------------------------------------
# Helpers (kept module-level for testability)
# ---------------------------------------------------------------------------


def _parse_set_directive(command: str) -> Optional[tuple]:
    """Parse ``set name=value``.  Returns *(name, value)* or *None*."""
    m = re.match(r"set\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*)", command)
    if m:
        return m.group(1), m.group(2).strip()
    return None


def _parse_prompt_directive(command: str) -> Optional[tuple]:
    """Parse ``prompt key "message" ["default"]``.

    Returns *(key, message, default)* or *None*.  The message and optional
    default must be double-quoted strings.

    Examples::

        prompt machineType "Machine type (min/def/personal)" "def"
        prompt email "Email address"
    """
    m = re.match(
        r'prompt\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+"([^"]*)"(?:\s+"([^"]*)")?',
        command,
    )
    if m:
        return m.group(1), m.group(2), m.group(3) or ""
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
# Conditional block tracking
# ---------------------------------------------------------------------------


class _CondFrame:
    """Tracks state for one if/elif/else/fi block.

    Attributes:
        satisfied: True once any branch has been taken.
        active: True if the *current* branch is emitting lines.
    """

    __slots__ = ("satisfied", "active")

    def __init__(self, active: bool) -> None:
        self.satisfied: bool = active
        self.active: bool = active


# ---------------------------------------------------------------------------
# FilePreprocessor
# ---------------------------------------------------------------------------


class FilePreprocessor:
    """Base preprocessor for files with ``@ish`` directives.

    The preprocessor manages a :class:`DotfileContext` that is shared
    across all files processed by the same instance.  Per-file ``set``
    directives accumulate into the context, and the context object is
    available as ``ish`` inside ``if`` / ``elif`` expressions.

    Args:
        variables: Optional initial variable mapping.
    """

    def __init__(self, variables: Optional[Dict[str, str]] = None) -> None:
        self._context = DotfileContext(variables)

    @property
    def context(self) -> DotfileContext:
        """The preprocessing context."""
        return self._context

    # -- public API ----------------------------------------------------------

    def preprocess_file(self, path: Path) -> Tuple[str, Optional[dict]]:
        """Preprocess a file given its path.

        The processing pipeline:

        1. Read the source file as text.
        2. Extract ``__ISH__`` metadata.
        3. Remove metadata blocks from the content.
        4. Scan for ``@ish`` directive lines, execute them, and remove them.
        5. Substitute ``${__ish_<name>}`` variable references.

        Args:
            path: Path to the file to preprocess.

        Returns:
            A tuple of (processed_text, metadata_dict_or_None).

        Raises:
            UnicodeDecodeError: If the file cannot be read as UTF-8.
        """
        text = path.read_text(encoding="utf-8")
        meta = read_metadata(path)
        return self._preprocess_text_with_meta(text, meta)

    def preprocess_text(self, text: str, meta: Optional[dict] = None) -> str:
        """Preprocess text content directly.

        Args:
            text: The file content as a string.
            meta: Optional pre-extracted metadata dictionary.

        Returns:
            The processed text.
        """
        result, _ = self._preprocess_text_with_meta(text, meta)
        return result

    def _preprocess_text_with_meta(
        self, text: str, meta: Optional[dict]
    ) -> Tuple[str, Optional[dict]]:
        """Core preprocessing pipeline shared by all entry points."""
        # 1. Seed context from metadata [vars] (as defaults only)
        if meta and "vars" in meta:
            self._context.update_defaults(meta["vars"])

        # 2. Remove metadata blocks from content
        text = remove_metadata_blocks(text)

        # 3. Process directive lines and conditionals
        text = self._process_directives(text)

        # 4. Substitute variables
        text = _substitute_variables(text, self._context.as_dict())

        return text, meta

    # -- directive processing ------------------------------------------------

    def _process_directives(self, text: str) -> str:
        """Process all @ish directives in *text*, returning cleaned output."""
        lines = text.splitlines(True)
        output: List[str] = []
        cond_stack: List[_CondFrame] = []

        for line in lines:
            m = _RE_DIRECTIVE.match(line.rstrip("\n\r"))
            if m:
                self._handle_directive(m.group("command").strip(), cond_stack)
                continue  # directive line is consumed

            # Non-directive line: emit only if all enclosing conditions are active
            if self._is_emitting(cond_stack):
                output.append(line)

        if cond_stack:
            log.warning(
                "Unterminated @ish if block (%d level(s) deep)", len(cond_stack)
            )

        return "".join(output)

    def _handle_directive(self, command: str, cond_stack: List[_CondFrame]) -> None:
        """Dispatch a single directive command."""
        if self._handle_conditional(command, cond_stack):
            return

        # Non-conditional directives only execute in active branches
        if self._is_emitting(cond_stack):
            parsed_set = _parse_set_directive(command)
            if parsed_set:
                self._context.set(parsed_set[0], parsed_set[1])
                return
            parsed_prompt = _parse_prompt_directive(command)
            if parsed_prompt:
                self._context.prompt(
                    parsed_prompt[0], parsed_prompt[1], parsed_prompt[2]
                )
                return
            log.warning("Unknown @ish directive: %s", command)

    def _handle_conditional(self, command: str, cond_stack: List[_CondFrame]) -> bool:
        """Handle if/elif/else/fi directives.  Returns True if handled."""
        if command.startswith("if "):
            expr = command[3:].strip()
            if self._is_emitting(cond_stack):
                cond_stack.append(_CondFrame(active=self._eval_expr(expr)))
            else:
                # Nested if inside a suppressed branch: always inactive
                cond_stack.append(_CondFrame(active=False))
            return True

        if command.startswith("elif "):
            return self._handle_elif(command[5:].strip(), cond_stack)

        if command == "else":
            return self._handle_else(cond_stack)

        if command == "fi":
            if not cond_stack:
                log.warning("@ish fi without matching if")
            else:
                cond_stack.pop()
            return True

        return False

    def _handle_elif(self, expr: str, cond_stack: List[_CondFrame]) -> bool:
        """Process an elif directive."""
        if not cond_stack:
            log.warning("@ish elif without matching if")
            return True
        frame = cond_stack[-1]
        if frame.satisfied:
            frame.active = False
        else:
            result = self._eval_expr(expr)
            frame.active = result
            if result:
                frame.satisfied = True
        return True

    @staticmethod
    def _handle_else(cond_stack: List[_CondFrame]) -> bool:
        """Process an else directive."""
        if not cond_stack:
            log.warning("@ish else without matching if")
            return True
        frame = cond_stack[-1]
        frame.active = not frame.satisfied
        if frame.active:
            frame.satisfied = True
        return True

    @staticmethod
    def _is_emitting(cond_stack: List[_CondFrame]) -> bool:
        """True when all enclosing conditional frames are active."""
        return all(frame.active for frame in cond_stack)

    def _eval_expr(self, expr: str) -> bool:
        """Evaluate a Python expression with ``ish`` context in scope.

        The expression has access to the :class:`DotfileContext` as ``ish``.
        Only the ``ish`` name is exposed -- no builtins or other globals --
        to keep evaluation safe and predictable.
        """
        try:
            result = eval(expr, {"__builtins__": {}}, {"ish": self._context})
            return bool(result)
        except Exception as exc:
            log.warning("Failed to evaluate @ish expression %r: %s", expr, exc)
            return False
