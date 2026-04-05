#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
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
- ``if <expr>`` -- begin a conditional block; *expr* is evaluated as
  Python with the :class:`DotfileContext` available as ``ish``.
- ``elif <expr>`` -- else-if branch.
- ``else`` -- fallback branch.
- ``fi`` -- end a conditional block.

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
from typing import Dict, List, Optional

from .dotfile import DotFile
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


class _CondFrame:  # pylint: disable=too-few-public-methods
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
# DotFilePreprocessor
# ---------------------------------------------------------------------------


class DotFilePreprocessor:
    """Stateful preprocessor for dotfile sources.

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

    def preprocess(self, dotfile: DotFile) -> str:
        """Preprocess a single dotfile source.

        The processing pipeline:

        1. Read the source file as text.
        2. Extract ``__ISH__`` metadata and store on *dotfile.metadata*.
        3. Remove metadata blocks from the content.
        4. Scan for ``@ish`` directive lines, execute them, and remove them.
        5. Substitute ``${__ish_<name>}`` variable references.

        Args:
            dotfile: The :class:`DotFile` to preprocess.

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

        # 2. Seed context from metadata [vars] (as defaults only)
        if meta and "vars" in meta:
            self._context.update_defaults(meta["vars"])

        # 3. Remove metadata blocks from content
        text = remove_metadata_blocks(text)

        # 4. Process directive lines and conditionals
        text = self._process_directives(text)

        # 5. Substitute variables
        text = _substitute_variables(text, self._context.as_dict())

        return text

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
            parsed = _parse_set_directive(command)
            if parsed:
                self._context.set(parsed[0], parsed[1])
            else:
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
            result = eval(  # pylint: disable=eval-used
                expr, {"__builtins__": {}}, {"ish": self._context}
            )
            return bool(result)
        except Exception as exc:  # pylint: disable=broad-except
            log.warning("Failed to evaluate @ish expression %r: %s", expr, exc)
            return False
