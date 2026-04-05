# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Shared configuration for pyishlib components."""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IshConfig:
    """Shared configuration for all pyishlib components.

    Instead of threading ``args``, ``conf``, and ``dry_run`` through every
    constructor, create a single ``IshConfig`` and pass it around.  All
    components that share a config instance will see the same state.

    Attributes:
        dry_run:   When *True*, commands are printed but not executed.
        log_level: The logging level (e.g. ``logging.DEBUG``).
    """

    dry_run: bool = False
    log_level: int = field(default=logging.WARNING)

    @classmethod
    def from_args(cls, args: Any, conf: Any = None) -> "IshConfig":
        """Build an ``IshConfig`` from argparse / conf objects.

        The priority order mirrors the old ``IshComp._get_opt`` behaviour:
        *args* wins over *conf* which wins over the default.
        """
        dry_run = _resolve_opt("dry_run", args, conf, False)
        if _resolve_opt("debug", args, conf, False):
            log_level = logging.DEBUG
        elif _resolve_opt("verbose", args, conf, False):
            log_level = logging.INFO
        elif _resolve_opt("quiet", args, conf, False):
            log_level = logging.ERROR
        else:
            log_level = logging.WARNING
        return cls(dry_run=dry_run, log_level=log_level)

    # -- convenience properties ------------------------------------------------

    @property
    def debug(self) -> bool:
        """True when the log level is DEBUG or lower."""
        return self.log_level <= logging.DEBUG

    @property
    def verbose(self) -> bool:
        """True when the log level is INFO or lower."""
        return self.log_level <= logging.INFO

    @property
    def quiet(self) -> bool:
        """True when the log level is ERROR or higher."""
        return self.log_level >= logging.ERROR


def _resolve_opt(name: str, args: Any, conf: Any, default: Optional[Any] = None) -> Any:
    """Look up *name* in *args* then *conf*, falling back to *default*."""
    if args is not None and hasattr(args, name):
        return getattr(args, name)
    if conf is not None and hasattr(conf, name):
        return getattr(conf, name)
    return default
