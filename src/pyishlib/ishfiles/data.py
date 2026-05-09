# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Data template processing for ishfiles.

Loads ``ishconfig/config-local.toml`` from the source repository, prompts the
user for any values not already present in the config, and offers to persist
new values back to ``~/.config/ishfiles/config.toml``.

The data template format is a TOML file where each top-level table is a
variable definition::

    [machineType]
    prompt = "Machine type (min/def/personal)"
    default = "def"
    isholate = "min"    # optional: used when --isholate is passed

    [email]
    prompt = "Email address"
    default = "hans@liljestrand.dev"

When ``ishfiles apply --isholate`` is in effect (e.g. inside an isholate
container), any entry carrying an ``isholate`` key uses that hardcoded value
instead of the user's saved or prompted value.  The override is never written
back to the config file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from .._compat import load_toml_file
from ..ish_config import IshConfig
from ..userio import normalise_bool, normalise_str, prompt_yes_no_always

log = logging.getLogger(__name__)


def process_data_template(cfg: IshConfig, isholate: bool = False) -> None:
    """Check source repo for a data template and prompt for missing values.

    Reads ``<source>/<config_dir>/<data_file>`` (typically
    ``ishconfig/config-local.toml``).  For each declared variable, if a value is
    already present on ``cfg.context`` (loaded from the ``[data]`` section of
    the config file), it is validated against the declared type.  Invalid
    values (e.g. an unrecognised string for a ``type = "bool"`` field) are
    cleared and the user is re-prompted.  Missing values are collected via
    ``cfg.context.prompt()``.

    If any new values were collected and the session is interactive,
    the user is asked whether to save them to the config file.

    When *isholate* is ``True``, entries that carry an ``isholate`` key in
    their spec use that hardcoded value instead of the saved/prompted value.
    The override is never written to the config file.
    """
    source = Path(cfg.get_opt("source"))
    template_path = source / cfg.get_opt("config_dir") / cfg.get_opt("data_file")

    if not template_path.is_file():
        log.debug("No data template found at %s", template_path)
        return

    template = _load_template(template_path)
    if not template:
        return

    # Publish the template so InstallerConfig can derive tag-type info.
    cfg.data_template = template

    new_values: Dict[str, str] = {}
    for key, spec in template.items():
        # --isholate mode: use the hardcoded override when present.
        if isholate and "isholate" in spec:
            raw = spec["isholate"]
            if isinstance(raw, bool):
                coerced = "true" if raw else "false"
            else:
                nb = normalise_bool(str(raw))
                coerced = nb if nb is not None else str(raw)
            if _validate_value(key, coerced, spec):
                log.debug("isholate override for %r: %r", key, coerced)
                cfg.context.set(key, coerced)
                continue
            log.warning(
                "isholate override for %r is invalid (%r); falling back to normal resolution",
                key,
                coerced,
            )

        existing = cfg.context.get(key)
        if existing:
            if not _validate_value(key, existing, spec):
                cfg.context.set(key, "")  # invalid — clear and re-prompt
            else:
                # Normalise in-place for bool synonyms (e.g. "yes" → "true")
                if spec.get("type") == "bool":
                    normalised = normalise_bool(existing)
                    if normalised:
                        cfg.context.set(key, normalised)
                continue  # valid, done
        msg = _default_prompt(key, spec)
        t = spec.get("type")
        if t == "bool":
            raw_default = spec.get("default", False)
            if isinstance(raw_default, str):
                bool_default = normalise_bool(raw_default) == "true"
            else:
                bool_default = bool(raw_default)
            value = cfg.context.prompt_bool(key, msg, bool_default)
        elif t in ("tags", "ordered_tags"):
            values = spec.get("values", [])
            raw_default = spec.get("default")
            str_default = str(raw_default) if raw_default is not None else None
            value = cfg.context.prompt_choice(key, msg, values, str_default)
        else:
            value = cfg.context.prompt(key, msg, str(spec.get("default", "")))
        new_values[key] = value

    if not new_values:
        return

    if cfg.dry_run or not sys.stdin.isatty():
        return

    print(f"\n{len(new_values)} new config value(s) collected.")
    choice = prompt_yes_no_always("Save to config file?")
    if choice.yes:
        config_path = Path(cfg.get_opt("config_file"))
        _save_data_section(config_path, new_values)
        if not cfg.quiet:
            print(f"Saved to {config_path}")


def _default_prompt(key: str, spec: Dict[str, Any]) -> str:
    """Build a default prompt string when the spec omits ``prompt``."""
    if "prompt" in spec:
        return spec["prompt"]
    t = spec.get("type")
    if t in ("tags", "ordered_tags"):
        values = spec.get("values", [])
        return f"{key} [{'/'.join(values)}]"
    if t == "bool":
        return f"{key}?"
    return key


def _validate_value(key: str, value: str, spec: Dict[str, Any]) -> bool:
    """Return True if *value* is acceptable for the template *spec*.

    - ``bool``: must be recognised by :func:`~pyishlib.userio.normalise_bool`.
    - ``tags`` / ``ordered_tags``: normalised value must be in ``spec["values"]``.
    - string (default): any non-empty value is accepted.

    Logs a warning and returns False when invalid.
    """
    t = spec.get("type")
    if t == "bool":
        if normalise_bool(value) is None:
            print(
                f"Unrecognized value for '{key}': {value!r} — prompting for a new value."
            )
            log.warning(
                "Unrecognized value for '%s': %r — prompting for a new value",
                key,
                value,
            )
            return False
    elif t in ("tags", "ordered_tags"):
        values = spec.get("values", [])
        nvalues = [normalise_str(v) for v in values]
        if normalise_str(value) not in nvalues:
            print(
                f"Unrecognized value for '{key}': {value!r} — expected one of {values}."
            )
            log.warning(
                "Unrecognized value for '%s': %r — not in %s, prompting for a new value",
                key,
                value,
                values,
            )
            return False
    return True


def _load_template(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load and return a data template from *path*.

    Returns a dict mapping variable names to their spec dicts
    (with ``prompt`` and ``default`` keys).  Returns empty dict on error.
    """
    raw = load_toml_file(path, default=None, warn_missing_toml=True)
    if raw is None:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            result[key] = value
        else:
            log.warning("Skipping non-table entry in data template: %s", key)
    return result


def _save_data_section(config_path: Path, new_values: Dict[str, str]) -> None:
    """Write or update the ``[data]`` section in *config_path*.

    Merges *new_values* into the existing ``[data]`` section if present,
    or appends a new section.  Existing non-data content is preserved.
    Creates parent directories if needed.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing_text = (
        config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    )

    # Build new [data] section lines from existing + new values.
    # First read existing [data] entries so we don't lose them.
    existing_data = _parse_data_section(existing_text)
    merged = {**existing_data, **new_values}

    data_block = "[data]\n" + "".join(
        f'{k} = "{v}"\n' for k, v in sorted(merged.items())
    )

    new_text = _replace_or_append_data_section(existing_text, data_block)
    config_path.write_text(new_text, encoding="utf-8")


def _parse_data_section(text: str) -> Dict[str, str]:
    """Extract key=value pairs from the ``[data]`` section of TOML text."""
    import re

    result: Dict[str, str] = {}
    in_data = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[data]":
            in_data = True
            continue
        if in_data:
            if stripped.startswith("["):
                break  # next section
            m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*"([^"]*)"', stripped)
            if m:
                result[m.group(1)] = m.group(2)
    return result


def _replace_or_append_data_section(text: str, data_block: str) -> str:
    """Replace an existing ``[data]`` section in *text*, or append one."""
    from .._toml_edit import replace_or_append_section

    return replace_or_append_section(text, "data", data_block)
