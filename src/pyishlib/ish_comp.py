#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Common utilities for pyishlib: logging setup, prompts, and enums."""

import sys
import logging
from enum import Enum
from typing import NoReturn


class Choice(Enum):
    """Enum for choices"""

    YES = "y"
    NO = "n"
    ALWAYS = "a"

    @property
    def yes(self) -> bool:
        """Return True if the choice is 'yes' or 'always'"""
        return self in (self.YES, self.ALWAYS)

    @property
    def no(self) -> bool:
        """Return True if the choice is 'no'"""
        return self == self.NO

    @property
    def always(self) -> bool:
        """Return True if the choice is 'always'"""
        return self == self.ALWAYS


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


def prompt_yes_no_always(msg: str) -> Choice:
    """Prompt for a yes/no/always choice on *stdin*."""
    while True:
        choice: str = input(f"{msg} [y/n/A] (Ctr-C to abort): ").strip().lower()
        if choice in ["y", "n", "a"]:
            return Choice(choice)


def die(msg: str, exit_code: int = 1) -> NoReturn:
    """Log a critical message and exit."""
    logging.getLogger("pyishlib").critical(msg)
    sys.exit(exit_code)
