# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import sys


class IshComp:
    def __init__(self, args=None, conf=None, dry_run=None, quiet=None):
        self._args = args
        self._conf = conf
        self_quiet = quiet
        self._dry_run = dry_run

    @property
    def dry_run(self):
        return self._get_opt("dry_run", False)

    @property
    def verbose(self):
        return self._get_opt("verbose", False)

    @property
    def quiet(self):
        return self._get_opt("quiet", False)

    def set_args(self, args):
        self._args = args

    def set_conf(self, conf):
        self._conf = conf

    def set_dry_run(self, dry_run):
        self._dry_run = dry_run

    def set_verbose(self, dry_run):
        self._dry_run = dry_run

    def set_quiet(self, quiet):
        self._quiet = quiet

    def _get_opt(self, opt, default=None):
        if self._args is not None and hasattr(self._args, opt):
            return getattr(self._args, opt)
        if self._conf is not None and hasattr(self._conf, opt):
            return getattr(self._conf, opt)
        if hasattr(self, f"_opt"):
            return getattr(self, f"_opt")
        return default

    def log_info(self, msg):
        if self.verbose:
            print(f"[--]: {msg}")

    def log_warn(self, msg):
        if not self.quiet:
            print(f"[WW]: {msg}")

    def log_error(self, msg):
        print(f"[EE]: {msg}", file=sys.stderr)

    def log_fatal(self, msg, exit_code=1):
        print(f"[!!]: {msg}", file=sys.stderr)
        sys.exit(exit_code)
