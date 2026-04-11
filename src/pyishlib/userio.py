#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""User I/O utilities: prompting, boolean parsing, and interactive choices.

All interactive prompting — string input, yes/no questions, and multi-choice
selections — goes through this module so there is a single place to adapt for
non-interactive environments, testing, and cross-platform differences.

Public API
----------
- :func:`normalise_bool`       -- parse boolean synonyms to ``"true"``/``"false"``
- :func:`getch`                -- read one keypress without requiring Enter
- :func:`prompt_string`        -- prompt for an arbitrary string value
- :func:`prompt_bool`          -- prompt for yes/no (single keypress)
- :class:`Choice`              -- enum for y/n/always selections
- :func:`prompt_yes_no_always` -- prompt for y/n/always (single keypress)
"""

from __future__ import annotations

import logging
import sys
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Boolean normalisation
# ---------------------------------------------------------------------------

_BOOL_TRUE = {"true", "yes", "y", "1", "on"}
_BOOL_FALSE = {"false", "no", "n", "0", "off"}


def normalise_bool(value: str) -> Optional[str]:
    """Normalise a boolean-like string to the canonical ``"true"`` or ``"false"``.

    Accepts ``true``/``false``, ``yes``/``no``, ``y``/``n``, ``1``/``0``,
    ``on``/``off`` (all case-insensitive).  Returns *None* for unrecognised
    input so callers can distinguish "invalid" from "false".

    >>> normalise_bool("Yes")
    'true'
    >>> normalise_bool("0")
    'false'
    >>> normalise_bool("maybe")  # returns None
    """
    v = value.strip().lower()
    if v in _BOOL_TRUE:
        return "true"
    if v in _BOOL_FALSE:
        return "false"
    return None


# ---------------------------------------------------------------------------
# Single-keypress input
# ---------------------------------------------------------------------------


def getch() -> str:
    """Read exactly one character from stdin without requiring Enter.

    On POSIX systems the terminal is put into raw/cbreak mode for the
    duration of the read.  On Windows ``msvcrt.getwch()`` is used.

    Raises :exc:`EOFError` if stdin is closed.
    """
    if sys.platform == "win32":
        import msvcrt  # type: ignore[import]

        ch = msvcrt.getwch()
        return ch
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if not ch:
            raise EOFError
        return ch


# ---------------------------------------------------------------------------
# String prompt
# ---------------------------------------------------------------------------


def prompt_string(
    message: str,
    default: str = "",
    *,
    name: str = "",
) -> str:
    """Prompt the user for an arbitrary string value.

    In non-interactive environments (stdin is not a tty) the *default* is
    returned immediately with a warning.

    Args:
        message: The question to display.
        default: Value returned when the user presses Enter without typing.
        name:    Optional variable name used in the non-interactive warning
                 so the log message is informative.
    """
    if not sys.stdin.isatty():
        label = f"'{name}'" if name else "prompt"
        log.warning("Non-interactive session, using default for %s: %s", label, default)
        return default
    suffix = f" [{default}]" if default else ""
    return input(f"{message}{suffix}: ").strip() or default


# ---------------------------------------------------------------------------
# Boolean prompt (single keypress)
# ---------------------------------------------------------------------------


def prompt_bool(
    message: str,
    default: bool = False,
    *,
    name: str = "",
) -> bool:
    """Prompt the user for a yes/no answer using a single keypress.

    Displays ``[Y/n]`` when *default* is ``True``, or ``[y/N]`` when
    *default* is ``False``.  Accepts ``y``/``Y`` (→ True), ``n``/``N``
    (→ False), or Enter (→ *default*).  Any other key is ignored and the
    prompt is reprinted.

    In non-interactive environments *default* is returned with a warning.

    Args:
        message: The question to display.
        default: Value used when the user presses Enter without typing.
        name:    Optional variable name used in the non-interactive warning.
    """
    if not sys.stdin.isatty():
        label = f"'{name}'" if name else "prompt"
        log.warning(
            "Non-interactive session, using default for %s: %s",
            label,
            "true" if default else "false",
        )
        return default

    hint = "[Y/n]" if default else "[y/N]"
    while True:
        sys.stdout.write(f"{message} {hint}: ")
        sys.stdout.flush()
        ch = getch()
        if ch in ("y", "Y"):
            sys.stdout.write("y\n")
            sys.stdout.flush()
            return True
        if ch in ("n", "N"):
            sys.stdout.write("n\n")
            sys.stdout.flush()
            return False
        if ch in ("\r", "\n"):
            sys.stdout.write(("y" if default else "n") + "\n")
            sys.stdout.flush()
            return default
        # Any other key: reprint the prompt
        sys.stdout.write("\n")


# ---------------------------------------------------------------------------
# y / n / always choice
# ---------------------------------------------------------------------------


class Choice(Enum):
    """Result of a yes / no / always prompt."""

    YES = "y"
    NO = "n"
    ALWAYS = "a"

    @property
    def yes(self) -> bool:
        """True for YES and ALWAYS."""
        return self in (self.YES, self.ALWAYS)

    @property
    def no(self) -> bool:
        """True for NO."""
        return self == self.NO

    @property
    def always(self) -> bool:
        """True for ALWAYS."""
        return self == self.ALWAYS


def prompt_yes_no_always(
    msg: str,
    *,
    name: str = "",
    default: Optional[str] = None,
) -> Choice:
    """Prompt for a yes / no / always choice using a single keypress.

    Displays ``[y/n/A]`` (A = always).  Accepts ``y``/``Y``, ``n``/``N``,
    ``a``/``A``, or Enter (→ *default* when provided).  Any other key is
    ignored and the prompt is reprinted.

    In non-interactive environments *default* is returned if set; otherwise
    ``Choice.NO`` is used as a safe fallback.

    Args:
        msg:     The question to display.
        name:    Optional variable name for non-interactive warnings.
        default: One of ``"y"``, ``"n"``, or ``"a"`` to accept on Enter.
                 If *None*, Enter is ignored and the user must press a key.
    """
    if not sys.stdin.isatty():
        label = f"'{name}'" if name else "prompt"
        fallback = Choice(default) if default in ("y", "n", "a") else Choice.NO
        log.warning(
            "Non-interactive session, using default for %s: %s", label, fallback.value
        )
        return fallback

    _default_choice = Choice(default) if default in ("y", "n", "a") else None
    _hint_map = {None: "[y/n/A]", "y": "[Y/n/a]", "n": "[y/N/a]", "a": "[y/n/A]"}
    hint = _hint_map.get(default, "[y/n/A]")

    while True:
        sys.stdout.write(f"{msg} {hint} (Ctrl-C to abort): ")
        sys.stdout.flush()
        ch = getch()
        if ch in ("y", "Y"):
            sys.stdout.write("y\n")
            sys.stdout.flush()
            return Choice.YES
        if ch in ("n", "N"):
            sys.stdout.write("n\n")
            sys.stdout.flush()
            return Choice.NO
        if ch in ("a", "A"):
            sys.stdout.write("a\n")
            sys.stdout.flush()
            return Choice.ALWAYS
        if ch in ("\r", "\n") and _default_choice is not None:
            sys.stdout.write(_default_choice.value + "\n")
            sys.stdout.flush()
            return _default_choice
        sys.stdout.write("\n")
