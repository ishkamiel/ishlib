# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Version parsing and probing helpers used by the installer pipeline.

These helpers let a package config declare a ``min_version`` requirement
and an optional ``command_version`` line; the installer then runs the
probe, parses the first dotted-int run from the combined stdout/stderr,
and compares it to the minimum.  Failures (probe errors, unparsable
output) deliberately return ``None``/``False`` so the caller treats the
package as not installed and proceeds to install a working version.
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from subprocess import CalledProcessError
from typing import Optional, Tuple

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


def parse_version(text: Optional[str]) -> Optional[Tuple[int, ...]]:
    """Return the first dotted-int version found in *text* as an int tuple.

    Handles ``v``-prefixed versions, trailing suffixes like ``-beta``, and
    multi-line input (search is unanchored).  Returns ``None`` if *text*
    is empty/None or no version-like substring is present.
    """
    if not text:
        return None
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def meets_min_version(actual_text: str, minimum: str) -> bool:
    """True iff the version parsed from *actual_text* is >= *minimum*.

    Returns False if either side fails to parse.  The shorter tuple is
    zero-padded to the longer one's length before comparison, so
    ``"1.2"`` and ``"1.2.0"`` compare equal.
    """
    actual = parse_version(actual_text)
    if actual is None:
        return False
    wanted = parse_version(minimum)
    if wanted is None:
        log.warning("Unparsable min_version %r", minimum)
        return False
    width = max(len(actual), len(wanted))
    actual_padded = actual + (0,) * (width - len(actual))
    wanted_padded = wanted + (0,) * (width - len(wanted))
    return actual_padded >= wanted_padded


def probe_version(runner, cmd_str: str) -> Optional[str]:
    """Run *cmd_str* through *runner* and return combined stdout+stderr.

    *cmd_str* is split with :func:`shlex.split` so it accepts a quoted
    argument list (e.g. ``"java -version"``).  Returns ``None`` on any
    failure to launch or run the probe.  Both streams are captured and
    concatenated because tools like ``git`` print to stdout while
    ``java -version`` prints to stderr.
    """
    if not isinstance(cmd_str, str):
        log.debug("Invalid command_version type %r; expected str", type(cmd_str))
        return None
    try:
        argv = shlex.split(cmd_str)
    except ValueError as e:
        log.debug("Could not parse command_version %r: %s", cmd_str, e)
        return None
    if not argv:
        return None
    try:
        result = runner.run(
            argv,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (CalledProcessError, FileNotFoundError, OSError) as e:
        log.debug("Version probe %r failed: %s", cmd_str, e)
        return None

    def _decode(stream) -> str:
        if stream is None:
            return ""
        if isinstance(stream, bytes):
            return stream.decode("utf-8", errors="replace")
        return stream

    stdout = _decode(result.stdout)
    stderr = _decode(result.stderr)
    if result.returncode != 0 and not stdout and not stderr:
        return None
    return f"{stdout}\n{stderr}"
