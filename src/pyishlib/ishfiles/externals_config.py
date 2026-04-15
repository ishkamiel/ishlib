#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Configuration loader for externals (git-repo dotfiles).

Reads ``<source>/ishconfig/externals.toml`` and returns a list of
:class:`ExternalSpec` objects.  Each TOML table key is the relative target
path under ``$HOME`` (e.g. ``".fzf"``).

Example ``externals.toml``::

    [".fzf"]
    url = "https://github.com/junegunn/fzf.git"
    revision = "v0.62.0"
    refresh_period = "168h"

    [".oh-my-zsh"]
    url = "https://github.com/ohmyzsh/ohmyzsh.git"
    revision = "master"

Supported fields
----------------
- ``url`` (required) -- git clone URL.
- ``revision`` (required) -- tag name or 40-hex SHA.
- ``type`` (optional, default ``"git-repo"``) -- reserved for future
  ``"archive"`` support.
- ``refresh_period`` (optional) -- duration string like ``"168h"`` or
  ``"7d"`` specifying the minimum gap between remote re-fetches.  If
  absent, the remote is always fetched on every run.
- ``strip_prefix`` (optional) -- subdirectory inside the clone to treat as
  the root for copying (contents of that dir are copied, not the dir itself).
- ``include`` (optional) -- list of glob patterns; only matching paths are
  copied.
- ``exclude`` (optional) -- list of glob patterns to exclude in addition to
  the built-in defaults (``.git``, ``.github``, ``*.pyc``,
  ``__pycache__``).

``refreshPeriod`` (camelCase) is accepted as an alias for
``refresh_period`` to ease migration from chezmoi externals.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .._compat import load_toml_file

log = logging.getLogger(__name__)

_KNOWN_TYPES = {"git-repo"}

# Duration multipliers for parse_refresh_period
_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
}


@dataclass
class ExternalSpec:
    """Parsed representation of one entry in ``externals.toml``.

    Args:
        path:           Relative target path under ``$HOME`` (TOML table key).
        url:            Git clone URL.
        revision:       Tag or 40-hex SHA to check out.
        type:           External type — currently only ``"git-repo"``.
        refresh_period: Minimum seconds between remote re-fetches.
                        ``None`` means always refresh.
        strip_prefix:   Leading subdirectory to strip from the clone before
                        copying into the target.
        include:        Inclusion glob patterns (empty = include everything).
        exclude:        Additional exclusion glob patterns.
    """

    path: str
    url: str
    revision: str
    type: str = "git-repo"
    refresh_period: Optional[int] = None
    strip_prefix: str = ""
    include: List[str] = field(default_factory=list)
    exclude: List[str] = field(default_factory=list)


def parse_refresh_period(s: str) -> Optional[int]:
    """Convert a duration string to seconds.

    Accepts values like ``"7d"``, ``"168h"``, ``"30m"``, ``"3600s"``.
    Returns ``None`` for ``None`` or empty input.

    Args:
        s: Duration string.

    Returns:
        Number of seconds, or ``None`` if *s* is ``None`` or empty.

    Raises:
        ValueError: If the format is unrecognised.
    """
    if not s:
        return None
    m = re.fullmatch(r"(\d+)\s*([smhdw]?)", s.strip().lower())
    if not m:
        raise ValueError(f"Unrecognised refresh_period format: {s!r}")
    amount, unit = int(m.group(1)), m.group(2) or "s"
    return amount * _DURATION_UNITS[unit]


def load_externals(cfg) -> List[ExternalSpec]:
    """Load and validate the externals config for *cfg*.

    Reads ``<source>/ishconfig/<externals_config_file>`` using the
    constants registered on *cfg* by :func:`~.config.load_config`.

    Returns an empty list (non-fatal) when the file is absent, TOML is
    unavailable, or the file is empty.  Invalid entries are logged and
    skipped rather than raising.

    Args:
        cfg: :class:`~pyishlib.ish_config.IshConfig` instance.

    Returns:
        List of :class:`ExternalSpec` objects in TOML order.
    """
    source = Path(cfg.get_opt("source") or "").expanduser().resolve()
    config_dir = cfg.get_opt("config_dir")
    config_file = cfg.get_opt("externals_config_file")
    config_path = source / config_dir / config_file

    if not config_path.is_file():
        return []

    raw = load_toml_file(config_path, default=None, warn_missing_toml=True)
    if not raw:
        return []

    specs: List[ExternalSpec] = []
    for path, entry in raw.items():
        if not isinstance(entry, dict):
            log.warning("externals.toml: entry %r is not a table — skipping", path)
            continue

        url = entry.get("url")
        revision = entry.get("revision")

        if not url:
            log.warning("externals.toml: entry %r missing 'url' — skipping", path)
            continue
        if not revision:
            log.warning("externals.toml: entry %r missing 'revision' — skipping", path)
            continue

        ext_type = entry.get("type", "git-repo")
        if ext_type not in _KNOWN_TYPES:
            log.warning(
                "externals.toml: entry %r has unknown type %r — skipping",
                path,
                ext_type,
            )
            continue

        # Accept both snake_case and camelCase for migration from chezmoi.
        rp_raw = entry.get("refresh_period") or entry.get("refreshPeriod")
        try:
            refresh_period = parse_refresh_period(rp_raw) if rp_raw else None
        except ValueError as exc:
            log.warning(
                "externals.toml: entry %r invalid refresh_period %r: %s — skipping",
                path,
                rp_raw,
                exc,
            )
            continue

        include = entry.get("include", [])
        exclude = entry.get("exclude", [])
        if not isinstance(include, list):
            log.warning(
                "externals.toml: entry %r 'include' is not a list — skipping", path
            )
            continue
        if not isinstance(exclude, list):
            log.warning(
                "externals.toml: entry %r 'exclude' is not a list — skipping", path
            )
            continue

        specs.append(
            ExternalSpec(
                path=path,
                url=str(url),
                revision=str(revision),
                type=ext_type,
                refresh_period=refresh_period,
                strip_prefix=entry.get("strip_prefix", ""),
                include=include,
                exclude=exclude,
            )
        )

    return specs
