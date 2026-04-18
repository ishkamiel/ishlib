# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Base class for argparse subcommands shared by all ishlib CLI tools."""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional


class CliCommand(ABC):
    """A single argparse subcommand.

    Subclasses set :attr:`NAME`, :attr:`HELP`, and optionally
    :attr:`DESCRIPTION`; override :meth:`add_arguments` to declare
    subcommand-specific flags; and implement :meth:`run`.

    The context object passed to :meth:`run` is whatever
    :meth:`BaseCLI.resolve_config` returned — an ``IshConfig`` for
    ishfiles, the parsed ``argparse.Namespace`` for isholate, etc.
    """

    NAME: str = ""
    HELP: str = ""
    DESCRIPTION: Optional[str] = None
    ADD_COMMON_FLAGS: bool = True

    @classmethod
    def register(
        cls,
        subparsers: argparse._SubParsersAction,
        add_common_flags: Callable[[argparse.ArgumentParser], None],
    ) -> argparse.ArgumentParser:
        """Create the subparser, attach common + subcommand flags, wire dispatch."""
        parser = subparsers.add_parser(
            cls.NAME,
            help=cls.HELP,
            description=cls.DESCRIPTION or cls.HELP,
        )
        if cls.ADD_COMMON_FLAGS:
            add_common_flags(parser)
        cls.add_arguments(parser)
        parser.set_defaults(func=cls._entry)
        return parser

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Declare subcommand-specific flags. Default: no extra arguments."""

    @classmethod
    def _entry(cls, ctx: Any) -> int:
        """argparse dispatch target — instantiates the command and runs it."""
        return cls().run(ctx)

    @abstractmethod
    def run(self, ctx: Any) -> int:
        """Execute the subcommand; return the process exit code."""
