#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Common utilities for pyishlib: logging setup and process helpers.

Interactive prompting has moved to :mod:`pyishlib.userio`.  ``Choice`` and
``prompt_yes_no_always`` are re-exported here for backward compatibility.
"""

import logging
import sys
from typing import NoReturn


class IshLogFormatter(logging.Formatter):
    """Custom formatter to prefix log levels"""

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno == logging.DEBUG:
            record.msg = f"[DD] {record.msg}"
        elif record.levelno == logging.INFO:
            record.msg = f"[--] {record.msg}"
        elif record.levelno == logging.WARNING:
            record.msg = f"[WW] {record.msg} - "
        elif record.levelno == logging.ERROR:
            record.msg = f"[EE] {record.msg}"
        elif record.levelno == logging.CRITICAL:
            record.msg = f"[!!] {record.msg}"
        return super().format(record)


def setup_logging(log_level: int = logging.WARNING) -> None:
    """Configure the ``pyishlib`` package logger once.

    Call this at the application entry point (CLI ``main``, script top-level,
    etc.).  Individual modules obtain their own loggers with
    ``logging.getLogger(__name__)`` and inherit this configuration.
    """
    pkg_logger = logging.getLogger("pyishlib")
    pkg_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(IshLogFormatter())
    pkg_logger.addHandler(handler)
    pkg_logger.setLevel(log_level)


def die(msg: str, exit_code: int = 1) -> NoReturn:
    """Log a critical message and exit."""
    logging.getLogger("pyishlib").critical(msg)
    sys.exit(exit_code)
