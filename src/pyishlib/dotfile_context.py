#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Dotfile context for preprocessing variable tracking and expression evaluation.

Provides the :class:`DotfileContext` object that is exposed as ``ish`` inside
``@ish if`` expressions and tracks all preprocessing variables.

An :class:`~pyishlib.environment.EnvironmentNamespace` is available as
``ish.env``, giving expressions access to environment checks such as
``ish.env.is_linux()``, ``ish.env.is_macos()``, etc.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .environment import EnvironmentNamespace
from .userio import normalise_bool, prompt_bool as _io_prompt_bool
from .userio import prompt_string as _io_prompt_string

log = logging.getLogger(__name__)


class DotfileContext:
    """Context object for dotfile preprocessing.

    Tracks variables available for ``${__ish_<name>}`` substitution and
    is exposed as ``ish`` inside ``@ish if`` expression evaluation.

    Variables can be accessed as attributes (``ish.hostname``) or via
    dict-style lookup (``ish["hostname"]``).  Missing attributes return
    an empty string rather than raising ``AttributeError``, making
    conditional expressions forgiving.

    An :attr:`env` attribute provides an
    :class:`~pyishlib.environment.EnvironmentNamespace` for live
    platform checks (e.g. ``ish.env.is_linux()``).

    The context is built in layers (lowest to highest precedence):

    1. Common variables (platform info, etc. -- added by the caller).
    2. Metadata ``[vars]`` section from the ``__ISH__`` block.
    3. Variables passed programmatically (CLI, config).
    4. ``#@ish set`` directives encountered during preprocessing.

    Args:
        variables: Optional initial variable mapping.
    """

    _vars: Dict[str, str]

    def __init__(self, variables: Optional[Dict[str, str]] = None) -> None:
        # Use object.__setattr__ to avoid triggering our custom __setattr__
        # before _vars exists.
        object.__setattr__(self, "_vars", dict(variables) if variables else {})
        object.__setattr__(self, "env", EnvironmentNamespace())

    # -- dict-style access ---------------------------------------------------

    def __getitem__(self, key: str) -> str:
        return self._vars[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._vars[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._vars

    # -- attribute-style access (ish.hostname in expressions) ----------------

    def __getattr__(self, name: str) -> str:
        # Only called when normal attribute lookup fails.
        if name.startswith("_"):
            raise AttributeError(name)
        return self._vars.get(name, "")

    def __setattr__(self, name: str, value: str) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._vars[name] = value

    # -- bulk operations -----------------------------------------------------

    def get(self, key: str, default: str = "") -> str:
        """Return the value for *key*, or *default* if not set."""
        return self._vars.get(key, default)

    def set(self, key: str, value: str) -> None:
        """Set a variable."""
        self._vars[key] = value

    def update(self, mapping: Dict[str, Any]) -> None:
        """Merge a mapping into the context, converting values to strings."""
        for key, val in mapping.items():
            self._vars[key] = str(val)

    def update_defaults(self, mapping: Dict[str, Any]) -> None:
        """Merge a mapping, but only for keys not already set."""
        for key, val in mapping.items():
            if key not in self._vars:
                self._vars[key] = str(val)

    def prompt(self, key: str, message: str, default: str = "") -> str:
        """Return the stored value for *key*, or prompt the user interactively.

        If *key* is already set and non-empty, returns the stored value without
        prompting.  Delegates all I/O to :func:`~pyishlib.userio.prompt_string`.

        This method is accessible as ``ish.prompt(key, message, default)``
        inside ``@ish if`` expressions and from the ``@ish prompt`` directive.
        """
        existing = self._vars.get(key)
        if existing:
            return existing
        value = _io_prompt_string(message, default, name=key)
        self._vars[key] = value
        return value

    def prompt_bool(self, key: str, message: str, default: bool = False) -> str:
        """Return the stored value for *key*, or prompt the user for a yes/no answer.

        If *key* is already set and non-empty, normalises the stored value via
        :func:`~pyishlib.userio.normalise_bool` and returns the canonical
        ``"true"`` or ``"false"`` string.  Otherwise delegates I/O to
        :func:`~pyishlib.userio.prompt_bool`.
        """
        existing = self._vars.get(key)
        if existing:
            normalised = normalise_bool(existing) or ("true" if existing else "false")
            self._vars[key] = normalised
            return normalised
        result = _io_prompt_bool(message, default, name=key)
        value = "true" if result else "false"
        self._vars[key] = value
        return value

    def as_dict(self) -> Dict[str, str]:
        """Return a plain dict copy of all variables."""
        return dict(self._vars)

    def __repr__(self) -> str:
        return f"DotfileContext({self._vars!r})"
