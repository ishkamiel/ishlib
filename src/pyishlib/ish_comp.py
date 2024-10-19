# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Some common functionality for internal ishpy use"""

import sys
from enum import Enum
from typing import Optional, Any, NoReturn


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


class IshComp:
    """Base class for all ishlib classes"""

    def __init__(
        self,
        args: Optional[Any] = None,
        conf: Optional[Any] = None,
        dry_run: Optional[bool] = None,
        quiet: Optional[bool] = None,
    ) -> None:
        self._args: Optional[Any] = args
        self._conf: Optional[Any] = conf
        self._quiet: Optional[bool] = quiet
        self._dry_run: Optional[bool] = dry_run

    @property
    def verbose(self) -> bool:
        """Is verbose mode enabled, either by args, config, or explicitly"""
        return self._get_opt("verbose", False)

    @property
    def quiet(self) -> bool:
        """Is quiet mode enabled, either by args, config, or explicitly"""
        return self._get_opt("quiet", False)

    @verbose.setter
    def verbose(self, verbose: bool) -> None:
        self._verbose = verbose

    @quiet.setter
    def quiet(self, quiet: bool) -> None:
        self._quiet = quiet

    def set_args(self, args: Any) -> None:
        """Set optional the arguments object, assuming argparse behavior"""
        self._args = args

    def set_conf(self, conf: Any) -> None:
        """Set the configuration object, e.g., a json or tomlib file"""
        self._conf = conf

    def log_debug(self, msg: str) -> None:
        """Log a debug message"""
        if self.verbose:
            print(f"[DD]: {msg}")

    def log_info(self, msg: str) -> None:
        """Log an info message"""
        if self.verbose:
            print(f"[--]: {msg}")

    def log_warn(self, msg: str) -> None:
        """Log a warning"""
        if not self.quiet:
            print(f"[WW]: {msg}")

    def log_error(self, msg: str) -> None:
        """Log an error"""
        print(f"[EE]: {msg}", file=sys.stderr)

    def log_fatal(self, msg: str, exit_code: int = 1) -> NoReturn:
        """Log a fatal error and exit"""
        print(f"[!!]: {msg}", file=sys.stderr)
        sys.exit(exit_code)

    def print(self, msg: str) -> None:
        """Print message without any decoration or prefix"""
        if not self.quiet:
            print(msg)

    def prompt_yes_no_always(self, msg: str) -> Choice:
        """Prompt for a yes/no/always choice"""
        while True:
            choice = input(f"{msg} [y/n/A] (Ctr-C to abort): ").strip().lower()
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
