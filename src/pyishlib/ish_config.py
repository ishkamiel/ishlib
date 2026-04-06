# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Shared configuration for pyishlib components."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

_log = logging.getLogger(__name__)

_MISSING = object()


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

    # -- TOML loading ----------------------------------------------------------

    @staticmethod
    def load_toml(
        path: Path,
        flatten: Optional[Dict[str, str]] = None,
    ) -> Optional[SimpleNamespace]:
        """Load a TOML file and return a :class:`SimpleNamespace`.

        The namespace can be used as the *conf* argument to
        :meth:`from_args`.

        Args:
            path:    Path to the TOML file.  Returns *None* when the
                     file does not exist or TOML support is unavailable.
            flatten: Optional mapping of ``section.key`` → ``attr_name``
                     used to flatten nested TOML sections into top-level
                     namespace attributes.  For example
                     ``{"ishfiles.source": "source"}`` maps
                     ``[ishfiles] source = …`` to ``ns.source``.
                     Keys without a dot are looked up at the top level.
        """
        if not path.is_file():
            _log.debug("Config file not found: %s", path)
            return None
        if tomllib is None:
            _log.warning(
                "TOML support unavailable (need Python 3.11+ or 'tomli'); "
                "ignoring %s",
                path,
            )
            return None

        with open(path, "rb") as fh:
            data = tomllib.load(fh)

        if not data:
            return None

        if flatten is None:
            return SimpleNamespace(**data)

        attrs: Dict[str, Any] = {}
        for toml_path, attr_name in flatten.items():
            parts = toml_path.split(".", 1)
            if len(parts) == 2:
                section, key = parts
                value = data.get(section, {}).get(key)
            else:
                value = data.get(parts[0])
            if value is not None:
                attrs[attr_name] = value
        return SimpleNamespace(**attrs) if attrs else None

    @classmethod
    def from_toml(
        cls,
        toml_path: Path,
        flatten: Optional[Dict[str, str]] = None,
        args: Optional[Any] = None,
        defaults: Optional[dict] = None,
    ) -> "IshConfig":
        """Build an ``IshConfig`` from a TOML file, args, and defaults.

        Convenience wrapper that calls :meth:`load_toml` and feeds the
        result into :meth:`from_args`.

        Args:
            toml_path: Path to the TOML configuration file.
            flatten:   Flattening map passed to :meth:`load_toml`.
            args:      Optional argparse namespace (highest priority).
            defaults:  Optional fallback dict (lowest priority).
        """
        conf = cls.load_toml(toml_path, flatten=flatten)
        return cls.from_args(args=args, conf=conf, defaults=defaults)

    # -- from_args -------------------------------------------------------------

    @classmethod
    def from_args(
        cls,
        args: Optional[Any] = None,
        conf: Optional[Any] = None,
        defaults: Optional[dict] = None,
    ) -> "IshConfig":
        """Build an ``IshConfig`` from argparse / conf objects.

        The lookup priority is: *args* > *conf* > *defaults* > hardcoded
        fallback.

        All three objects are stored so :meth:`get_opt` and attribute
        access can resolve arbitrary names later.

        Uses a temporary instance internally so that the full
        :meth:`get_opt` resolution chain is applied consistently.

        Args:
            args:     An argparse namespace (or similar object).
            conf:     A configuration object (e.g. from JSON/TOML).
            defaults: Optional dict of fallback values.
        """
        # Build a temporary instance to leverage get_opt for resolution.
        tmp = cls(args=args, conf=conf, defaults=defaults or {})

        dry_run = tmp.get_opt("dry_run", False)
        if tmp.get_opt("debug", False):
            log_level = logging.DEBUG
        elif tmp.get_opt("verbose", False):
            log_level = logging.INFO
        elif tmp.get_opt("quiet", False):
            log_level = logging.ERROR
        else:
            log_level = logging.WARNING

        tmp.dry_run = dry_run
        tmp.log_level = log_level
        return tmp

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

    def get_opt(self, name: str, default: Any = _MISSING) -> Any:
        """Look up *name* with args -> conf -> defaults -> *default* priority.

        Unlike attribute access, this returns *default* instead of raising
        ``AttributeError`` when the name is not found.  When no explicit
        *default* is given and the name is not found, returns ``None``.
        """
        if self.args is not None and hasattr(self.args, name):
            return getattr(self.args, name)
        if self.conf is not None and hasattr(self.conf, name):
            return getattr(self.conf, name)
        if name in self.defaults:
            return self.defaults[name]
        return None if default is _MISSING else default

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
