# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Base class for argparse-based CLI tools shared by ishfiles/isholate/ishproject."""

from __future__ import annotations

import argparse
import sys
from abc import ABC
from typing import Any, List, Optional, Sequence, Type

from .ish_logging import log_level_from_args, setup_logging

from .cli_command import CliCommand


class BaseCLI(ABC):
    """Template-method base for ishlib CLI tools.

    Subclasses set class attributes to declare their shape and override
    a small set of hooks.  :meth:`main` is the shared template that
    parses argv, configures logging, resolves a context object, and
    dispatches to the subcommand's ``run``.

    Class attributes:
        PROG: Program name shown in ``--help`` (e.g. ``"ishfiles"``).
        DESCRIPTION: Top-level description text.
        COMMANDS: Ordered list of :class:`CliCommand` subclasses to
            register as subparsers.
        SUBPARSER_DEST: ``dest`` for ``add_subparsers`` (default
            ``"command"``).  Must match the attribute name used by
            :meth:`main` to detect a missing subcommand.
        SUBPARSER_METAVAR: Optional ``metavar`` for the subparsers group.
        SUBPARSER_REQUIRED: If True, a missing subcommand is an argparse
            error.  If False, :meth:`main` prints help and returns 2.
        COLLECT_UNKNOWN: If True, uses ``parse_known_args`` and stashes
            unknown tokens into ``args.rest`` (ishproject passthrough).
    """

    PROG: str = ""
    DESCRIPTION: str = ""
    COMMANDS: Sequence[Type[CliCommand]] = ()
    SUBPARSER_DEST: str = "command"
    SUBPARSER_METAVAR: Optional[str] = None
    SUBPARSER_REQUIRED: bool = False
    COLLECT_UNKNOWN: bool = False

    # ------------------------------------------------------------------
    # Template
    # ------------------------------------------------------------------
    def main(self, argv: Optional[List[str]] = None) -> int:
        """Parse argv, configure logging, resolve config, dispatch."""
        if argv is None:
            argv = sys.argv[1:]
        argv = self.default_argv(list(argv))

        parser = self.build_parser()

        if self.COLLECT_UNKNOWN:
            args, unknown = parser.parse_known_args(argv)
        else:
            args = parser.parse_args(argv)
            unknown = []

        subcommand = getattr(args, self.SUBPARSER_DEST, None)
        if subcommand is None:
            parser.print_help()
            return 2

        if self.COLLECT_UNKNOWN:
            if hasattr(args, "rest"):
                args.rest = list(args.rest) + unknown
            elif unknown:
                parser.error(f"unrecognized arguments: {' '.join(unknown)}")

        log_file = getattr(args, "log_file", None)
        quiet = getattr(args, "quiet", False)
        setup_logging(self.log_level_from_args(args), log_file=log_file, quiet=quiet)

        rc = self.preflight(args)
        if rc is not None:
            return rc

        ctx = self.resolve_config(args)

        ctx_level = getattr(ctx, "log_level", None)
        if ctx_level is not None:
            setup_logging(ctx_level, log_file=log_file, quiet=quiet)

        return args.func(ctx)

    def build_parser(self) -> argparse.ArgumentParser:
        """Build the top-level argparse parser with all subcommands."""
        parser = argparse.ArgumentParser(
            prog=self.PROG,
            description=self.DESCRIPTION,
        )
        self.add_global_args(parser)
        subparsers_kwargs: dict = {
            "dest": self.SUBPARSER_DEST,
            "required": self.SUBPARSER_REQUIRED,
        }
        if self.SUBPARSER_METAVAR is not None:
            subparsers_kwargs["metavar"] = self.SUBPARSER_METAVAR
        subparsers = parser.add_subparsers(**subparsers_kwargs)
        for cmd_cls in self.COMMANDS:
            cmd_cls.register(subparsers, self.add_common_flags)
        return parser

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------
    def add_global_args(self, parser: argparse.ArgumentParser) -> None:
        """Attach tool-specific globals (NOT -v/-q/--debug/-n/--log-file).

        Common flags live on the subparsers; see
        :meth:`add_common_flags` and the CLAUDE.md argparse rule.
        """

    def add_common_flags(self, parser: argparse.ArgumentParser) -> None:
        """Attach ``-v/--debug/-q/-n/--log-file`` to a subparser.

        This writes the unified ishlib flag shape.  Subclasses should
        not override this method — override :meth:`log_level_from_args`
        instead if flag semantics differ.
        """
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=False,
            help="Enable verbose output",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            default=False,
            help="Enable debug output",
        )
        parser.add_argument(
            "-q",
            "--quiet",
            action="store_true",
            default=False,
            help="Suppress non-essential output",
        )
        parser.add_argument(
            "-n",
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--log-file",
            metavar="FILE",
            default=None,
            help=(
                "Append all log output (DEBUG and above) to this file, "
                "regardless of terminal verbosity."
            ),
        )

    def preflight(self, args: argparse.Namespace) -> Optional[int]:
        """Short-circuit hook.  Return an exit code to abort, or None to continue."""
        return None

    def resolve_config(self, args: argparse.Namespace) -> Any:
        """Turn parsed args into the context passed to ``run``.  Default: args itself."""
        return args

    def log_level_from_args(self, args: argparse.Namespace) -> int:
        """Map parsed CLI flags to a logging level.

        Delegates to :func:`pyishlib.ish_logging.log_level_from_args` so the
        booleans-to-level mapping has a single source of truth across all
        ishlib CLIs.  Subclasses may override for tools with non-standard flag
        semantics.
        """
        return log_level_from_args(args)

    def default_argv(self, argv: List[str]) -> List[str]:
        """Transform argv before parsing (e.g. ``[]`` → ``["run"]`` for isholate)."""
        return argv
