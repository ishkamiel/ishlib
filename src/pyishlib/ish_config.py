# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Shared configuration for pyishlib components."""

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Sequence, Tuple

from .dotfile_context import DotfileContext

from ._compat import atomic_write_text, load_toml_file, toml_escape_basic_string
from .userio import prompt_string

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
    repo_conf: Any = field(default=None, repr=False, compare=False)
    defaults: dict = field(default_factory=dict, repr=False, compare=False)
    constants: dict = field(default_factory=dict, repr=False, compare=False)
    context: DotfileContext = field(
        default_factory=DotfileContext, repr=False, compare=False
    )
    data_template: Dict[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )

    # -- TOML loading ----------------------------------------------------------

    @staticmethod
    def _flatten_from_schema(schema_path: Path) -> Dict[str, str]:
        """Derive a flatten map from a JSON Schema file.

        Walks the top-level ``properties`` of the schema.  For each
        nested object section, maps ``section.key`` → ``key``.  For
        top-level scalars, maps ``key`` → ``key``.
        """
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        flatten: Dict[str, str] = {}
        for section, sdef in schema.get("properties", {}).items():
            if sdef.get("type") == "object" and "properties" in sdef:
                for key in sdef["properties"]:
                    flatten[f"{section}.{key}"] = key
            else:
                flatten[section] = section
        return flatten

    @staticmethod
    def _validate_toml(data: dict, schema_path: Path) -> None:
        """Validate *data* against a JSON Schema file.

        Only checks for unknown top-level sections and unknown keys
        within known sections (mirrors ``additionalProperties: false``).
        """
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        allowed_sections = set(schema.get("properties", {}).keys())
        for key in data:
            if key not in allowed_sections:
                _log.warning("Unknown config section: %s", key)
                continue
            sdef = schema["properties"][key]
            if sdef.get("type") == "object" and "properties" in sdef:
                if not isinstance(data[key], dict):
                    _log.warning("Config section %r should be a table", key)
                    continue
                allowed_keys = set(sdef["properties"].keys())
                for subkey in data[key]:
                    if subkey not in allowed_keys:
                        _log.warning("Unknown config key: %s.%s", key, subkey)

    @staticmethod
    def load_toml(
        path: Path,
        schema: Optional[Path] = None,
    ) -> Optional[SimpleNamespace]:
        """Load a TOML file and return a :class:`SimpleNamespace`.

        The namespace can be used as the *conf* argument to
        :meth:`from_args`.

        When *schema* is given (path to a JSON Schema file), the loaded
        data is validated against it and the flatten map is derived
        automatically from the schema structure.  Nested TOML sections
        are flattened so that ``[section] key = …`` becomes ``ns.key``.

        Args:
            path:   Path to the TOML file.  Returns *None* when the
                    file does not exist or TOML support is unavailable.
            schema: Optional path to a JSON Schema file used for
                    validation and automatic flattening.
        """
        if not path.is_file():
            _log.debug("Config file not found: %s", path)
            return None

        data = load_toml_file(path, default=None, warn_missing_toml=True)
        if data is None:
            return None

        if schema is None:
            return SimpleNamespace(**data)

        IshConfig._validate_toml(data, schema)
        flatten = IshConfig._flatten_from_schema(schema)

        attrs: Dict[str, Any] = {}
        for toml_path, attr_name in flatten.items():
            parts = toml_path.split(".", 1)
            if len(parts) == 2:
                section, key = parts
                section_val = data.get(section)
                value = section_val.get(key) if isinstance(section_val, dict) else None
            else:
                value = data.get(parts[0])
            if value is not None:
                attrs[attr_name] = value
        return SimpleNamespace(**attrs) if attrs else None

    @classmethod
    def from_toml(
        cls,
        toml_path: Path,
        schema: Optional[Path] = None,
        args: Optional[Any] = None,
        defaults: Optional[dict] = None,
    ) -> "IshConfig":
        """Build an ``IshConfig`` from a TOML file, args, and defaults.

        Convenience wrapper that calls :meth:`load_toml` and feeds the
        result into :meth:`from_args`.

        Args:
            toml_path: Path to the TOML configuration file.
            schema:    Optional JSON Schema path for validation/flattening.
            args:      Optional argparse namespace (highest priority).
            defaults:  Optional fallback dict (lowest priority).
        """
        conf = cls.load_toml(toml_path, schema=schema)
        return cls.from_args(args=args, conf=conf, defaults=defaults)

    # -- bootstrap -------------------------------------------------------------

    @classmethod
    def bootstrap(
        cls,
        config_path: Path,
        *,
        section: str,
        prompts: Sequence[Tuple[str, str, str]],
        interactive: Optional[bool] = None,
    ) -> None:
        """Prompt for missing keys and write a TOML config at *config_path*.

        No-op when *config_path* already exists. Also a no-op on a
        non-interactive session (stdin is not a tty) with no file, so
        callers silently fall back to whatever ``defaults`` dict they
        pass into :meth:`from_toml` / :meth:`from_args`.

        Each entry in *prompts* is ``(key, message, default)``. On an
        interactive run the user is prompted once per key via
        :func:`pyishlib.userio.prompt_string`, then the file is written
        atomically with shape::

            [<section>]
            <key1> = "<value1>"
            <key2> = "<value2>"

        Values are escaped per the TOML basic-string grammar so a
        hazardous input (embedded quote, backslash, newline) produces a
        file that round-trips cleanly through :meth:`from_toml`.

        Args:
            config_path: Absolute path of the TOML file to create.
            section:     Name of the single ``[section]`` table written.
            prompts:     Ordered ``(key, message, default)`` tuples.
            interactive: Override TTY detection (mainly for testing).
        """
        if config_path.is_file():
            return
        if interactive is None:
            interactive = sys.stdin.isatty()
        if not interactive:
            _log.debug(
                "Non-interactive session and no %s; skipping bootstrap",
                config_path,
            )
            return

        print(
            f"\nNo config found at {config_path}.\n"
            f"Enter values for the [{section}] section; "
            "press Enter to accept the default.\n"
        )
        values: Dict[str, str] = {}
        for key, message, default in prompts:
            values[key] = prompt_string(message, default=default, name=key)

        config_path.parent.mkdir(parents=True, exist_ok=True)
        body_lines = [f"[{section}]"]
        for key, val in values.items():
            body_lines.append(f'{key} = "{toml_escape_basic_string(val)}"')
        atomic_write_text(config_path, "\n".join(body_lines) + "\n")
        print(f"Saved config to {config_path}")

    # -- from_args -------------------------------------------------------------

    @classmethod
    def from_args(
        cls,
        args: Optional[Any] = None,
        conf: Optional[Any] = None,
        repo_conf: Optional[Any] = None,
        defaults: Optional[dict] = None,
    ) -> "IshConfig":
        """Build an ``IshConfig`` from argparse / conf objects.

        The lookup priority is: *args* > *conf* > *repo_conf* > *defaults* >
        hardcoded fallback.

        All objects are stored so :meth:`get_opt` and attribute access can
        resolve arbitrary names later.

        Uses a temporary instance internally so that the full
        :meth:`get_opt` resolution chain is applied consistently.

        Args:
            args:      An argparse namespace (or similar object).
            conf:      A configuration object (e.g. from JSON/TOML).
            repo_conf: Optional repo-level config (lower priority than *conf*).
            defaults:  Optional dict of fallback values.
        """
        # Build a temporary instance to leverage get_opt for resolution.
        tmp = cls(args=args, conf=conf, repo_conf=repo_conf, defaults=defaults or {})

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

        Raises:
            ValueError: If the name is already registered as a constant.
        """
        if name in self.constants:
            raise ValueError(
                f"Cannot set default for read-only config option: {name!r}"
            )
        self.defaults[name] = value

    def set_constant(self, name: str, value: Any) -> None:
        """Register a read-only config option.

        Constants have the highest priority and cannot be overridden by
        args, conf, or defaults.  Attempting to register a constant
        that already exists with a different value raises ``ValueError``.

        Raises:
            ValueError: If the name is already registered with a different
                        value, or if it conflicts with an existing default.
        """
        if name in self.constants:
            if self.constants[name] != value:
                raise ValueError(
                    f"Cannot redefine read-only config option {name!r}: "
                    f"{self.constants[name]!r} -> {value!r}"
                )
            return
        if name in self.defaults:
            raise ValueError(
                f"Cannot register constant {name!r}: already exists as a default"
            )
        self.constants[name] = value

    def __getattr__(self, name: str) -> Any:
        """Fall back to constants -> args -> conf -> defaults for unknown attributes.

        This lets ``IshConfig`` act as a drop-in for an argparse namespace::

            cfg = IshConfig.from_args(parsed_args)
            cfg.dry_run      # dataclass field  (direct)
            cfg.custom_opt   # from parsed_args (via __getattr__)
        """
        # Avoid infinite recursion: these are dataclass fields resolved via
        # __dict__ directly.  If we get here for them they truly don't exist
        # yet (e.g. during __init__), so bail out.
        if name in ("args", "conf", "repo_conf", "defaults", "constants", "context"):
            raise AttributeError(name)
        constants = self.__dict__.get("constants") or {}
        if name in constants:
            return constants[name]
        args = self.__dict__.get("args")
        conf = self.__dict__.get("conf")
        repo_conf = self.__dict__.get("repo_conf")
        defaults = self.__dict__.get("defaults") or {}
        if args is not None and hasattr(args, name):
            return getattr(args, name)
        if conf is not None and hasattr(conf, name):
            return getattr(conf, name)
        if repo_conf is not None and hasattr(repo_conf, name):
            return getattr(repo_conf, name)
        if name in defaults:
            return defaults[name]
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def is_explicit(self, name: str) -> bool:
        """Return True iff *name* was set on the command line by the user.

        Backed by the ``_ish_explicit`` set populated by the wrapped argparse
        actions in :func:`pyishlib.cli_base._explicit_action`.  Values that
        come from TOML config, :meth:`set_constant`, or :meth:`set_default`
        are NOT explicit by this definition — "explicit" means argv-sourced.

        Duck-typed on ``self.args``: works for any object with an
        ``_ish_explicit`` attribute (e.g. a plain :class:`argparse.Namespace`
        populated by a tool that has not adopted :class:`IshConfig`).
        """
        if self.args is None:
            return False
        return name in getattr(self.args, "_ish_explicit", ())

    def get_opt(self, name: str, default: Any = _MISSING) -> Any:
        """Look up *name* with constants -> args -> conf -> defaults -> *default* priority.

        Constants always win.  Unlike attribute access, this returns
        *default* instead of raising ``AttributeError`` when the name is
        not found.  When no explicit *default* is given and the name is
        not found, returns ``None``.
        """
        if name in self.constants:
            return self.constants[name]
        if self.args is not None and hasattr(self.args, name):
            return getattr(self.args, name)
        if self.conf is not None and hasattr(self.conf, name):
            return getattr(self.conf, name)
        if self.repo_conf is not None and hasattr(self.repo_conf, name):
            return getattr(self.repo_conf, name)
        if name in self.defaults:
            return self.defaults[name]
        return None if default is _MISSING else default

    def get_origin(self, name: str) -> Tuple[str, Optional[str]]:
        """Return the layer that supplies *name* under :meth:`get_opt`.

        Walks the same chain as :meth:`get_opt` so the two never
        disagree.  Returns a ``(layer, source)`` tuple where *layer* is
        one of ``"constant"``, ``"cli"``, ``"user-config"``,
        ``"repo-config"``, ``"default"``, or ``"unset"``, and *source*
        is the originating file path (as a string) when applicable
        (``user-config`` / ``repo-config``) or ``None`` otherwise.
        """
        if name in self.constants:
            return ("constant", None)
        if self.args is not None and hasattr(self.args, name):
            return ("cli", None)
        if self.conf is not None and hasattr(self.conf, name):
            cfg_file = self.get_opt("config_file")
            return ("user-config", str(cfg_file) if cfg_file is not None else None)
        if self.repo_conf is not None and hasattr(self.repo_conf, name):
            source = self.get_opt("source")
            if source is not None:
                repo_path: Optional[str] = str(
                    Path(source)
                    / self.get_opt("config_dir")
                    / self.get_opt("repo_config_file")
                )
            else:
                repo_path = None
            return ("repo-config", repo_path)
        if name in self.defaults:
            return ("default", None)
        return ("unset", None)

    # -- user-config persistence ----------------------------------------------

    def persist_user_value(
        self,
        section: str,
        leaf: str,
        value: str,
    ) -> Path:
        """Write ``[<section>] <leaf> = "<value>"`` to the user-config TOML.

        Targets the path stored under ``self.constants["config_file"]``,
        i.e. whatever was resolved at startup (default
        ``~/.config/ishfiles/config.toml`` for ishfiles, etc.).  The
        edit is line-targeted via
        :func:`pyishlib._toml_edit.set_kv_in_text` so siblings of any
        TOML value type and any comments / blank lines survive.

        The write is atomic
        (:func:`pyishlib._compat.atomic_write_text`); parent directories
        are created on demand.

        Args:
            section: Top-level table name (e.g. ``"ishfiles"``,
                     ``"data"``).
            leaf:    Bare-key name within the section.
            value:   Scalar string value; escaped internally.

        Returns:
            The path written.

        Raises:
            RuntimeError: If no ``config_file`` is registered.
        """
        cfg_file = self.get_opt("config_file")
        if cfg_file is None:
            raise RuntimeError(
                "IshConfig.persist_user_value: no 'config_file' constant registered"
            )
        path = Path(cfg_file)
        path.parent.mkdir(parents=True, exist_ok=True)

        from ._compat import atomic_write_text
        from ._toml_edit import set_kv_in_text

        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        atomic_write_text(path, set_kv_in_text(existing, section, leaf, value))
        return path

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
