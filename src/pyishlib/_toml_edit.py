# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Surgical TOML editing helpers.

These functions edit TOML *text* without depending on a TOML
serializer.  They aim to preserve byte-for-byte everything outside the
line(s) being changed -- comments, blank lines, sibling keys with any
TOML value type (numbers, bools, arrays, multi-line strings, ...).

Use the regular ``tomllib`` parser for *reading* values; these helpers
are for the narrow case of "set one scalar key in a known section
while preserving the rest of the file".

Limitations:

- :func:`set_kv_in_text` only writes scalar (basic-string) values.  If
  the *target* key's existing assignment spans multiple physical lines
  (multi-line strings, multi-line arrays), the call replaces only the
  first line and leaves stale continuation lines behind.  Callers that
  need to overwrite multi-line values must do a full TOML round-trip
  via ``tomli_w`` instead.
- Section detection treats any ``[`` at the start of a line as a new
  table header (matches both ``[name]`` and ``[name.subtable]``).
"""

from __future__ import annotations

import re
from typing import Optional

from ._compat import toml_escape_basic_string


def set_kv_in_text(text: str, section: str, leaf: str, value: str) -> str:
    """Return *text* with ``[section] leaf = "value"`` set in place.

    - If the section exists and contains an assignment for *leaf*,
      that one line is rewritten.
    - If the section exists but the key is absent, a new line is
      inserted at the end of the section (before any trailing blank
      lines).
    - If the section is absent, a fresh ``[section]`` block is
      appended after a blank-line separator.

    Comments, blank lines, and sibling assignments of any TOML value
    type are left untouched.  *value* is escaped via
    :func:`pyishlib._compat.toml_escape_basic_string`; the caller does
    not pre-quote it.
    """
    new_line = f'{leaf} = "{toml_escape_basic_string(value)}"\n'
    return _replace_or_insert_kv_line(text, section, leaf, new_line)


def replace_or_append_section(text: str, section: str, block: str) -> str:
    """Replace an existing ``[section]`` block in *text*, or append one.

    The section's body runs from its header line up to (but not
    including) the next ``[`` table header at the start of a line, or
    end of file.  ``[`` characters inside values (e.g. inline arrays
    like ``patterns = ["*.bak"]``) are preserved.  *block* must
    already include the ``[section]\\n`` header.  When the section is
    absent, *block* is appended after a blank line.
    """
    pattern = re.compile(
        r"^\[" + re.escape(section) + r"\][^\n]*\n(?:(?!^\[)[^\n]*\n?)*",
        re.MULTILINE,
    )
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text, count=1)
    return text.rstrip("\n") + ("\n\n" if text.strip() else "") + block


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_or_insert_kv_line(
    text: str, section: str, leaf: str, new_line: str
) -> str:
    """Body of :func:`set_kv_in_text` -- pre-formatted *new_line*."""
    lines = text.splitlines(keepends=True)
    section_re = re.compile(r"^\[" + re.escape(section) + r"\]\s*$")
    table_header_re = re.compile(r"^\[")
    key_re = re.compile(r"^\s*" + re.escape(leaf) + r"\s*=")

    section_start: Optional[int] = None
    for i, line in enumerate(lines):
        if section_re.match(line):
            section_start = i
            break

    if section_start is None:
        prefix = text.rstrip("\n") + ("\n\n" if text.strip() else "")
        return prefix + f"[{section}]\n{new_line}"

    section_end = len(lines)
    for j in range(section_start + 1, len(lines)):
        if table_header_re.match(lines[j]):
            section_end = j
            break

    for k in range(section_start + 1, section_end):
        if key_re.match(lines[k]):
            lines[k] = new_line
            return "".join(lines)

    insert_at = section_end
    while insert_at > section_start + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1
    lines.insert(insert_at, new_line)
    return "".join(lines)
