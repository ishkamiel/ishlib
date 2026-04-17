# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""RFC 7396 JSON Merge Patch helpers.

Used by the ``mergejson_`` dotfile prefix to combine an existing target
JSON file with a source patch without clobbering unrelated keys.

Semantics (:rfc:`7396`):

- If both *base* and *patch* are JSON objects, merge recursively.
- If a key maps to ``None`` (JSON ``null``) in *patch*, the key is removed
  from the merged result.
- Otherwise, the value in *patch* replaces the value in *base*. Arrays
  are replaced wholesale (no element-wise merging).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def deep_merge_json(base: Any, patch: Any) -> Any:
    """Merge *patch* into *base* using RFC 7396 semantics.

    Args:
        base: The existing JSON value (usually what the target already
              contains).  May be any JSON-serialisable value.
        patch: The incoming JSON value (the ``mergejson_`` source).

    Returns:
        A new JSON value.  When both inputs are objects the result is a
        deep merge; otherwise *patch* replaces *base* entirely.  Keys
        whose patch value is ``None`` are removed from the result.

    The original inputs are never mutated.
    """
    if not isinstance(patch, dict) or not isinstance(base, dict):
        return patch

    result = dict(base)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_json(result[key], value)
        else:
            result[key] = value
    return result


def canonical_json(data: Any) -> str:
    """Render *data* as a canonical JSON string.

    Keys are sorted, indentation is two spaces, and non-ASCII characters
    are preserved.  A trailing newline is appended so the output is a
    well-formed text file.
    """
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def semantic_equal(path_a: Path, path_b: Path) -> bool:
    """Return *True* if both files parse to equal JSON values.

    Equality ignores key ordering inside objects but preserves list
    order.  Returns *False* if either file cannot be read or parsed as
    JSON.
    """
    try:
        data_a = json.loads(Path(path_a).read_text(encoding="utf-8"))
        data_b = json.loads(Path(path_b).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return data_a == data_b
