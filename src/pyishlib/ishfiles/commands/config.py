# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``config`` subcommand -- view or modify the resolved ishfiles config.

The resolved config is the layered chain
``constants > CLI args > user TOML > repo TOML > defaults``.  This
subcommand exposes that chain for inspection (default view and
``--show-origins``) and provides a one-shot writer (``--set``) that
persists a value to whichever user TOML was resolved at startup.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..._compat import is_toml_bare_key
from ...cli_command import CliCommand
from ..config import _load_data_section

log = logging.getLogger(__name__)

# Keys printable in the default view, in display order.  Each entry is
# (dotted-key, attribute-name-on-cfg).  ``data.<*>`` is enumerated
# dynamically from the user TOML's ``[data]`` section.
_USER_FACING_KEYS: Tuple[Tuple[str, str], ...] = (
    ("ishfiles.source", "source"),
    ("ishfiles.target", "target"),
    ("ishfiles.default_shell", "default_shell"),
    ("ignore.patterns", "patterns"),
)

# Leaves accepted by ``--set ishfiles.<leaf>``.  Mirrors the user schema.
_ISHFILES_LEAVES = frozenset({"source", "target", "default_shell"})

# Sections accepted by ``--set <section>.<leaf>``.
_WRITABLE_SECTIONS = frozenset({"ishfiles", "ignore", "data"})


class ConfigCommand(CliCommand):
    """View or modify ishfiles configuration."""

    NAME = "config"
    HELP = "View or modify the resolved ishfiles configuration"
    DESCRIPTION = (
        "View the resolved ishfiles configuration.  Use --show-origins to "
        "see which layer (constant/cli/user-config/repo-config/default) "
        "supplied each value, or --set <section.key> <value> to persist a "
        "value to the user config TOML resolved at startup."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--show-origins",
            action="store_true",
            help=(
                "Annotate each value with the layer that supplied it "
                "(constant/cli/user-config/repo-config/default)."
            ),
        )
        group.add_argument(
            "--set",
            dest="set_kv",
            nargs=2,
            metavar=("KEY", "VALUE"),
            help=(
                "Persist KEY=VALUE to the user config (KEY is dotted, "
                "e.g. ishfiles.source)."
            ),
        )

    def run(self) -> int:
        set_kv = self.cfg.get_opt("set_kv", None)
        if set_kv is not None:
            return self._do_set(set_kv[0], set_kv[1])
        show_origins = bool(self.cfg.get_opt("show_origins", False))
        return self._do_view(show_origins)

    # -- view ---------------------------------------------------------------

    def _do_view(self, show_origins: bool) -> int:
        rows = self._collect_rows()
        if not rows:
            return 0

        prev_section: Optional[str] = None
        for key, value, origin in rows:
            section = key.split(".", 1)[0]
            if prev_section is not None and section != prev_section:
                print()
            prev_section = section
            line = f"{key} = {_format_value(value)}"
            if show_origins:
                line = f"{line}  # {origin}"
            print(line)
        return 0

    def _collect_rows(self) -> List[Tuple[str, Any, str]]:
        """Return ``(dotted-key, value, origin-tag)`` triples to display.

        Skips keys whose origin is ``"unset"`` so the default view stays
        copy-paste compatible with ``--set`` and the show-origins view
        doesn't list noise.
        """
        rows: List[Tuple[str, Any, str]] = []
        for dotted, attr in _USER_FACING_KEYS:
            origin_tag = self._origin_tag(attr)
            if origin_tag == "unset":
                continue
            value = self.cfg.get_opt(attr)
            rows.append((dotted, value, origin_tag))

        # data.* — enumerate from the user TOML's [data] section directly.
        cfg_file = self.cfg.get_opt("config_file")
        data_origin: str
        if cfg_file is not None:
            data_origin = f"user-config: {cfg_file}"
            data_items = _load_data_section(Path(cfg_file))
        else:
            data_origin = "user-config"
            data_items = {}
        for key in sorted(data_items):
            rows.append((f"data.{key}", data_items[key], data_origin))
        return rows

    def _origin_tag(self, attr: str) -> str:
        """Format ``cfg.get_origin(attr)`` as a single short tag."""
        layer, source = self.cfg.get_origin(attr)
        if source is None:
            return layer
        return f"{layer}: {source}"

    # -- set ----------------------------------------------------------------

    def _do_set(self, key: str, value: str) -> int:
        if "." not in key:
            log.error(
                "Invalid key %r: expected dotted form '<section>.<leaf>' "
                "(e.g. ishfiles.source).",
                key,
            )
            return 2
        section, leaf = key.split(".", 1)

        if section not in _WRITABLE_SECTIONS:
            log.error(
                "Unknown config section %r.  Writable sections: %s.",
                section,
                ", ".join(sorted(_WRITABLE_SECTIONS)),
            )
            return 2

        if leaf in self.cfg.constants:
            log.error("Cannot set %r: it is a read-only constant.", key)
            return 2

        if section == "ishfiles":
            if leaf not in _ISHFILES_LEAVES:
                log.error(
                    "Unknown key %r in [ishfiles].  Allowed: %s.",
                    leaf,
                    ", ".join(sorted(_ISHFILES_LEAVES)),
                )
                return 2
        elif section == "ignore":
            if leaf == "patterns":
                log.error(
                    "Setting list-valued keys (ignore.patterns) is not "
                    "supported via --set in this release; edit the config "
                    "file directly."
                )
                return 2
            log.error(
                "Unknown key %r in [ignore].  Allowed: patterns "
                "(via direct file edit).",
                leaf,
            )
            return 2
        # section == "data": any leaf is allowed (free-form schema).

        if not is_toml_bare_key(leaf):
            log.error(
                "Invalid key name %r: must be a TOML bare key ([A-Za-z0-9_-]+).",
                leaf,
            )
            return 2

        cfg_file = self.cfg.get_opt("config_file")
        if cfg_file is None:
            log.error("No config file resolved; cannot --set.")
            return 2

        if self.cfg.dry_run:
            log.info("[dry-run] Would write %s = %r to %s", key, value, cfg_file)
            return 0

        path = self.cfg.persist_user_value(section, leaf, value)
        log.info("Wrote %s = %r to %s", key, value, path)
        return 0


# ---------------------------------------------------------------------------
# View helpers (display formatting -- not generic enough to share)
# ---------------------------------------------------------------------------


def _format_value(value: Any) -> str:
    """Format *value* for the default view.

    - strings render bare (no quoting); copy-pasting the line into
      ``ishfiles config --set <key> <value>`` works for plain values,
      but values that contain shell metacharacters (spaces, ``#``,
      newlines, quotes, ``$``, ...) need the user's own shell quoting
      around the value argument.
    - lists render as a JSON-ish array (display only — list values are
      not currently accepted by ``--set``).
    - other scalars are ``str()``'d.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [f'"{v}"' if isinstance(v, str) else str(v) for v in value]
        return "[" + ", ".join(parts) + "]"
    if value is None:
        return ""
    return str(value)
