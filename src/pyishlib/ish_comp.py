# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Some common functionality for internal ishpy use"""

import sys
from enum import Enum
from typing import Optional, Any, NoReturn
import logging


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


class IshComp:
    """Base class for all ishlib classes"""

    def __init__(
        self,
        args: Optional[Any] = None,
        conf: Optional[Any] = None,
        dry_run: Optional[bool] = None,
        log_level: Optional[int] = None,
    ) -> None:
        self._args: Optional[Any] = args
        self._conf: Optional[Any] = conf
        self._dry_run: Optional[bool] = dry_run

        # Start logging facilities
        self.log: logging.Logger = logging.getLogger(__name__)
        handler = logging.StreamHandler()
        handler.setFormatter(IshLogFormatter())
        self.log.handlers.clear()  # Remove any existing handlers
        self.log.addHandler(handler)
        if log_level is None:
            if self._get_opt("debug", False):
                log_level = logging.DEBUG
            elif self._get_opt("verbose", False):
                log_level = logging.INFO
            elif self._get_opt("quiet", False):
                log_level = logging.ERROR
            else:
                log_level = logging.WARNING
        self.log.setLevel(log_level)
        self.log.debug(
            "Log level set to %s (%d)", logging.getLevelName(log_level), log_level
        )

    @property
    def debug(self) -> bool:
        """Is debug mode enabled, either by args, config, or explicitly"""
        return self.log.level <= logging.DEBUG

    @property
    def verbose(self) -> bool:
        """Is verbose mode enabled, either by args, config, or explicitly"""
        return self.log.level <= logging.INFO

    @property
    def quiet(self) -> bool:
        """Is quiet mode enabled, either by args, config, or explicitly"""
        return self.log.level >= logging.ERROR

    @property
    def dry_run(self) -> bool:
        """Is dry-run mode enabled, either by args, config, or explicitly"""
        return self._get_opt("dry_run", False)

    def set_dry_run(self, quiet: bool) -> None:
        """Set dry-run mode"""
        self._dry_run = quiet

    def set_args(self, args: Any) -> None:
        """Set optional the arguments object, assuming argparse behavior"""
        self._args = args

    def set_conf(self, conf: Any) -> None:
        """Set the configuration object, e.g., a json or tomlib file"""
        self._conf = conf

    def set_log_level(self, log_level: int) -> None:
        """Set the log level"""
        self.log.setLevel(log_level)
        self.log.debug("Log level set to %s", logging.getLevelName(log_level))

    def die(self, msg: str, exit_code: int = 1) -> NoReturn:
        """Log a critical message and exit"""
        self.log.critical(msg)
        sys.exit(exit_code)

    def print(self, msg: str) -> None:
        """Print message without any decoration or prefix"""
        self.log.log(logging.NOTSET, msg)

    def prompt_yes_no_always(self, msg: str) -> Choice:
        """Prompt for a yes/no/always choice"""
        while True:
            choice: str = input(f"{msg} [y/n/A] (Ctr-C to abort): ").strip().lower()
            if choice in ["y", "n", "a"]:
                return Choice(choice)

    def _get_opt(self, opt: str, default: Optional[Any] = None) -> Any:
        if self._args is not None and hasattr(self._args, opt):
            return getattr(self._args, opt)
        if self._conf is not None and hasattr(self._conf, opt):
            return getattr(self._conf, opt)
        if hasattr(self, f"_{opt}"):
            return getattr(self, f"_{opt}")
        return default
