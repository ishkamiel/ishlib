#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
"""Unified logging setup for pyishlib.

This is the **single** place where logging handlers are configured.
No other module should add or configure handlers.

Usage (at the CLI entry point)::

    from pyishlib.ish_logging import setup_logging
    setup_logging(logging.INFO, log_file=args.log_file, quiet=args.quiet)

All modules obtain their own logger with::

    import logging
    log = logging.getLogger(__name__)

The ``pyishlib.script.*`` sub-loggers carry an optional ``script`` extra
that identifies the running ishscript by filename.  The formatter renders
it as ``[<script>]`` after the level tag.

Log level tags
--------------
==========  =====
Level       Tag
==========  =====
DEBUG       [DD]
INFO        [--]
WARNING     [WW]
ERROR       [EE]
CRITICAL    [!!]
==========  =====
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class IshLogFormatter(logging.Formatter):
    """Format log records with short level tags and optional script label.

    When a record carries a ``script`` attribute (set via
    ``extra={"script": name}``), the formatted line is::

        [WW] [my_script.sh] Something went wrong

    Otherwise::

        [WW] Something went wrong
    """

    _TAGS = {
        logging.DEBUG: "[DD]",
        logging.INFO: "[--]",
        logging.WARNING: "[WW]",
        logging.ERROR: "[EE]",
        logging.CRITICAL: "[!!]",
    }

    def format(self, record: logging.LogRecord) -> str:
        tag = self._TAGS.get(record.levelno, "[??]")
        script = getattr(record, "script", None)
        script_label = f" [{script}]" if script else ""
        # Temporarily mutate msg so the parent formatter sees the full line.
        original_msg = record.msg
        original_args = record.args
        record.msg = f"{tag}{script_label} {record.getMessage()}"
        record.args = None
        result = super().format(record)
        record.msg = original_msg
        record.args = original_args
        return result


# ---------------------------------------------------------------------------
# Filter: suppress script stdout lines on the terminal when quiet
# ---------------------------------------------------------------------------


class _ScriptStdoutFilter(logging.Filter):
    """Drop ``pyishlib.script.stdout`` records (used by -q terminal handler).

    Script stderr lines (``pyishlib.script.stderr``) are never dropped so
    that diagnostics printed to stderr by a script remain visible even when
    the user passes ``--quiet``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("pyishlib.script.stdout")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logging(
    level: int = logging.WARNING,
    *,
    log_file: Optional[Path] = None,
    quiet: bool = False,
) -> None:
    """Configure the ``pyishlib`` package logger.

    Call once at the CLI entry point.  Subsequent calls reconfigure the
    existing handler (safe for the two-phase setup in ``ishfiles/cli.py``
    where logging is set up once before config load and again after).

    Args:
        level:    Terminal log level (e.g. ``logging.INFO`` for ``-v``).
        log_file: When set, attach an additional :class:`~logging.FileHandler`
                  at ``DEBUG`` level so every message lands in the file
                  regardless of terminal verbosity.  Used by ``--log-file``
                  and by isholate to retrieve in-container diagnostics.
        quiet:    When ``True``, suppress ``pyishlib.script.stdout`` records
                  on the terminal (script stdout captured as ``1>`` lines).
                  Script stderr (``2>`` lines) remains visible.
    """
    pkg_logger = logging.getLogger("pyishlib")
    pkg_logger.setLevel(logging.DEBUG)  # let handlers decide what to show
    # Do NOT set propagate=False: pytest's caplog fixture attaches a handler
    # to the root logger and relies on propagation to capture records.
    # Without propagation, caplog misses all pyishlib log records in tests.

    # -- terminal handler (stderr) --------------------------------------------
    # Always create a fresh StreamHandler so the stream reference picks up the
    # current sys.stderr.  This is important for pytest's capsys fixture, which
    # replaces sys.stderr per test — a reused handler would point to the wrong
    # stream and capsys would miss the output.
    file_handler_paths: list[str] = []

    for h in list(pkg_logger.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ):
            # Remove old terminal handlers so we can create a fresh one.
            pkg_logger.removeHandler(h)
        elif isinstance(h, logging.FileHandler):
            file_handler_paths.append(h.baseFilename)

    terminal_handler = logging.StreamHandler(sys.stderr)
    terminal_handler.setFormatter(IshLogFormatter())
    terminal_handler.setLevel(level)
    if quiet:
        terminal_handler.addFilter(_ScriptStdoutFilter())
    pkg_logger.addHandler(terminal_handler)

    # -- optional extra file handler ------------------------------------------
    if log_file is not None:
        log_file = Path(log_file)
        log_file_str = str(log_file.resolve())
        if log_file_str not in file_handler_paths:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(IshLogFormatter())
            pkg_logger.addHandler(fh)
