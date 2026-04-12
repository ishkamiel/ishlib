#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Shared tag-filter logic for packages and scripts.

Both :class:`~pyishlib.installer_config.InstallerConfig` (package tags)
and :func:`~pyishlib.ishfiles.script_runner.scan_scripts` (script tags)
use the same tag semantics.  This module centralises that logic so that
the two callers stay in sync.

Tag semantics (derived from ``cfg.data_template``)
--------------------------------------------------
- ``<var>`` — where ``var`` is a ``bool`` key in the data template:
  include when the context value is truthy.
- ``!<var>`` — negation of the above.
- ``<val>`` — where ``val`` appears in a ``tags`` variable's ``values``
  list: include when the variable equals ``val``.
- ``<val>`` — where ``val`` appears in an ``ordered_tags`` variable's
  ``values`` list: include when the variable's current index ≥ ``val``'s
  index (higher index implies lower — e.g., ``personal`` satisfies
  ``min`` and ``def`` for ``values = ["min", "def", "personal"]``).

Items without tags are always included.  Unknown tags produce a warning
and evaluate to ``False``.

Public API
----------
- :func:`passes_tags` -- evaluate a list of tags against the current config.
- :func:`tag_matches` -- evaluate a single (non-negated) tag name.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .userio import normalise_bool, normalise_str

log = logging.getLogger(__name__)


def passes_tags(tags: List[str], cfg: Any, *, label: str = "") -> bool:
    """Return True if every tag in *tags* is satisfied by the current context.

    Args:
        tags:  List of tag strings (may include leading ``!`` for negation).
        cfg:   :class:`~pyishlib.ish_config.IshConfig` providing
               ``data_template`` and ``context``.
        label: Human-readable label used in warning messages (e.g. a
               package or script name).

    Returns:
        True when all tags pass, False if any tag fails.
    """
    if not tags:
        return True

    template: Dict[str, Any] = {}
    if cfg is not None:
        template = getattr(cfg, "data_template", None) or {}

    for tag in tags:
        negated = tag.startswith("!")
        name = tag[1:] if negated else tag
        matched = tag_matches(name, template, cfg=cfg, label=label)
        if negated:
            matched = not matched
        if not matched:
            return False
    return True


def tag_matches(
    tag: str,
    template: Dict[str, Any],
    *,
    cfg: Any = None,
    label: str = "",
) -> bool:
    """Return True if the single (non-negated) tag name *tag* is satisfied.

    Args:
        tag:      Tag name without leading ``!``.
        template: The ``data_template`` dict (from ``cfg.data_template``).
        cfg:      :class:`~pyishlib.ish_config.IshConfig` for context lookups.
        label:    Human-readable label for warning messages.

    Returns:
        True if the tag matches, False otherwise (including for unknown tags).
    """
    ntag = normalise_str(tag)

    # 1. tag name == a bool variable
    for var, vspec in template.items():
        if normalise_str(var) == ntag and vspec.get("type") == "bool":
            return normalise_bool(_ctx_get(cfg, var)) == "true"

    # 2. tag value appears in a tags / ordered_tags variable
    for var, vspec in template.items():
        t = vspec.get("type")
        if t not in ("tags", "ordered_tags"):
            continue
        nvalues = [normalise_str(v) for v in vspec.get("values", [])]
        if ntag not in nvalues:
            continue
        ncurrent = normalise_str(_ctx_get(cfg, var))
        if t == "tags":
            return ncurrent == ntag
        # ordered_tags: current index >= tag index (higher index implies lower)
        if ncurrent not in nvalues:
            return False
        return nvalues.index(ncurrent) >= nvalues.index(ntag)

    target = label or tag
    log.warning("Unknown tag %r (on %s)", tag, target)
    return False


def _ctx_get(cfg: Optional[Any], key: str, default: str = "") -> str:
    """Look up *key* in ``cfg.context``, returning *default* if absent."""
    if cfg is not None and hasattr(cfg, "context"):
        return cfg.context.get(key, default)
    return default
