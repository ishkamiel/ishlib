# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Shared configuration for pyishlib components."""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IshConfig:
    """Shared configuration for all pyishlib components.

    Instead of threading ``args``, ``conf``, and ``dry_run`` through every
    constructor, create a single ``IshConfig`` and pass it around.  All
    components that share a config instance will see the same state.

    The optional *args* and *conf* objects are retained so that
    downstream code can look up arbitrary attributes via :meth:`get_opt`.

    Attributes:
        dry_run:   When *True*, commands are printed but not executed.
        log_level: The logging level (e.g. ``logging.DEBUG``).
        args:      Optional argparse namespace (highest priority in lookups).
        conf:      Optional configuration object (second priority).
    """

    dry_run: bool = False
    log_level: int = field(default=logging.WARNING)
    args: Any = field(default=None, repr=False, compare=False)
    conf: Any = field(default=None, repr=False, compare=False)
    defaults: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_args(
        cls,
        args: Any,
        conf: Any = None,
        defaults: Optional[dict] = None,
    ) -> "IshConfig":
        """Build an ``IshConfig`` from argparse / conf objects.

        The lookup priority is: *args* > *conf* > *defaults* > hardcoded
        fallback.

        All three objects are stored so :meth:`get_opt` and attribute
        access can resolve arbitrary names later.

        Args:
            args:     An argparse namespace (or similar object).
            conf:     A configuration object (e.g. from JSON/TOML).
            defaults: Optional dict of fallback values.
        """
        defs = defaults or {}
        dry_run = _resolve_opt("dry_run", args, conf, defs.get("dry_run", False))
        if _resolve_opt("debug", args, conf, defs.get("debug", False)):
            log_level = logging.DEBUG
        elif _resolve_opt("verbose", args, conf, defs.get("verbose", False)):
            log_level = logging.INFO
        elif _resolve_opt("quiet", args, conf, defs.get("quiet", False)):
            log_level = logging.ERROR
        else:
            log_level = logging.WARNING
        return cls(
            dry_run=dry_run, log_level=log_level, args=args, conf=conf, defaults=defs
        )

    def set_default(self, name: str, value: Any) -> None:
        """Set a single default value.

        Defaults have the lowest priority: args and conf attributes
        will still override them.
        """
        self.defaults[name] = value

    def __getattr__(self, name: str) -> Any:
        """Fall back to args -> conf -> defaults for unknown attributes.

        This lets ``IshConfig`` act as a drop-in for an argparse namespace::

            cfg = IshConfig.from_args(parsed_args)
            cfg.dry_run      # dataclass field  (direct)
            cfg.custom_opt   # from parsed_args (via __getattr__)
        """
        # Avoid infinite recursion: these are dataclass fields resolved via
        # __dict__ directly.  If we get here for them they truly don't exist
        # yet (e.g. during __init__), so bail out.
        if name in ("args", "conf", "defaults"):
            raise AttributeError(name)
        args = self.__dict__.get("args")
        conf = self.__dict__.get("conf")
        defaults = self.__dict__.get("defaults") or {}
        if args is not None and hasattr(args, name):
            return getattr(args, name)
        if conf is not None and hasattr(conf, name):
            return getattr(conf, name)
        if name in defaults:
            return defaults[name]
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def get_opt(self, name: str, default: Optional[Any] = None) -> Any:
        """Look up *name* with args -> conf -> defaults -> *default* priority.

        Unlike attribute access, this returns *default* instead of raising
        ``AttributeError`` when the name is not found.
        """
        val = _resolve_opt(name, self.args, self.conf)
        if val is not None:
            return val
        return self.defaults.get(name, default)

    # -- convenience properties ------------------------------------------------

    @property
    def debug(self) -> bool:
        """True when the log level is DEBUG or lower."""
        return self.log_level <= logging.DEBUG

    @property
    def verbose(self) -> bool:
        """True when the log level is INFO or lower."""
        return self.log_level <= logging.INFO

    @property
    def quiet(self) -> bool:
        """True when the log level is ERROR or higher."""
        return self.log_level >= logging.ERROR


def _resolve_opt(name: str, args: Any, conf: Any, default: Optional[Any] = None) -> Any:
    """Look up *name* in *args* then *conf*, falling back to *default*."""
    if args is not None and hasattr(args, name):
        return getattr(args, name)
    if conf is not None and hasattr(conf, name):
        return getattr(conf, name)
    return default
