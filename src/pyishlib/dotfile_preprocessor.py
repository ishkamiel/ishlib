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

from typing import Dict, Optional

from .dotfile import DotFile
from .file_preprocessor import (  # pylint: disable=unused-import
    FilePreprocessor,
    _RE_DIRECTIVE,
    _RE_VAR_REF,
    _parse_set_directive,
    _substitute_variables,
)

# ---------------------------------------------------------------------------
# DotFilePreprocessor
# ---------------------------------------------------------------------------


class DotFilePreprocessor(FilePreprocessor):
    """Preprocessor specialised for :class:`DotFile` objects.

    Extends :class:`FilePreprocessor` to store extracted metadata back
    onto the :class:`DotFile` instance, which the dotfile applier uses
    for further processing.

    The preprocessor manages a :class:`DotfileContext` that is shared
    across all files processed by the same instance.  Per-file ``set``
    directives accumulate into the context, and the context object is
    available as ``ish`` inside ``if`` / ``elif`` expressions.

    Args:
        variables: Optional initial variable mapping.
    """

    def __init__(self, variables: Optional[Dict[str, str]] = None) -> None:
        super().__init__(variables=variables)

    # -- public API ----------------------------------------------------------

    def preprocess(self, dotfile: DotFile, metadata: Optional[dict] = None) -> str:
        """Preprocess a single dotfile source.

        The processing pipeline:

        1. Read the source file as text.
        2. Extract ``__ISH__`` metadata and store on *dotfile.metadata*.
        3. Remove metadata blocks from the content.
        4. Scan for ``@ish`` directive lines, execute them, and remove them.
        5. Substitute ``${__ish_<name>}`` variable references.

        Args:
            dotfile: The :class:`DotFile` to preprocess.
            metadata: Optional pre-extracted metadata dictionary.  When
                provided, the file is still read for content but metadata
                extraction is skipped (avoiding a redundant file read).

        Returns:
            The processed file content as a string.

        Raises:
            UnicodeDecodeError: If the file cannot be read as UTF-8 (the
                caller should fall back to a raw copy).
        """
        if metadata is not None:
            text = dotfile.source.read_text(encoding="utf-8")
            text = self.preprocess_text(text, meta=metadata)
            meta = metadata
        else:
            text, meta = self.preprocess_file(dotfile.source)

        if meta is not None:
            dotfile.metadata = meta

        return text
