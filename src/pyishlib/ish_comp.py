# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import sys
from enum import Enum
from typing import Optional, Any, NoReturn


class IshComp:
    class Choice(Enum):
        YES = "y"
        NO = "n"
        ALWAYS = "a"

        @property
        def yes(self) -> bool:
            return self == self.YES or self == self.ALWAYS

        @property
        def no(self) -> bool:
            return self == self.NO

        @property
        def always(self) -> bool:
            return self == self.ALWAYS

    def __init__(
        self,
        args: Optional[Any] = None,
        conf: Optional[Any] = None,
        dry_run: Optional[bool] = None,
        quiet: Optional[bool] = None,
    ) -> NoReturn:
        self._args = args
        self._conf = conf
        self._quiet = quiet
        self._dry_run = dry_run

    @property
    def verbose(self) -> bool:
        return self._get_opt("verbose", False)

    @property
    def quiet(self) -> bool:
        return self._get_opt("quiet", False)

    @verbose.setter
    def verbose(self, verbose: bool) -> NoReturn:
        self._verbose = verbose

    @quiet.setter
    def quiet(self, quiet: bool) -> NoReturn:
        self._quiet = quiet

    def set_args(self, args: Any) -> NoReturn:
        self._args = args

    def set_conf(self, conf: Any) -> NoReturn:
        self._conf = conf

    def log_info(self, msg: str) -> NoReturn:
        if self.verbose:
            print(f"[--]: {msg}")

    def log_warn(self, msg: str) -> NoReturn:
        if not self.quiet:
            print(f"[WW]: {msg}")

    def log_error(self, msg: str) -> NoReturn:
        print(f"[EE]: {msg}", file=sys.stderr)

    def log_fatal(self, msg: str, exit_code: int = 1) -> NoReturn:
        print(f"[!!]: {msg}", file=sys.stderr)
        sys.exit(exit_code)

    def print(self, msg: str) -> NoReturn:
        if not self.quiet:
            print(msg)

    def prompt_yes_no_always(self, msg: str, always: bool = True) -> "IshComp.Choice":
        while True:
            choice = input(f"{msg} [y/n/A] (Ctr-C to abort): ").strip().lower()
            if choice in ["y", "n", "a"]:
                return self.Choice(choice)

    def _get_opt(self, opt: str, default: Optional[Any] = None) -> Any:
        if self._args is not None and hasattr(self._args, opt):
            return getattr(self._args, opt)
        if self._conf is not None and hasattr(self._conf, opt):
            return getattr(self._conf, opt)
        if hasattr(self, f"_opt"):
            return getattr(self, f"_opt")
        return default
