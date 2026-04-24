# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Base class for argparse subcommands shared by all ishlib CLI tools.

Also owns the passthrough machinery (``CliCommand.passthrough`` and
``CliCommand.compose_passthrough_argv``) used by wrapper tools such as
``ishproject`` whose subcommands delegate to ``ishfiles``.  The argv
composition helpers (:func:`_compose_argv` and :func:`_split_for_target`)
are module-level so they are unit-testable without instantiating a
subclass.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable, List, Optional, Tuple


class CliCommand(ABC):
    """A single argparse subcommand.

    Subclasses set :attr:`NAME`, :attr:`HELP`, and optionally
    :attr:`DESCRIPTION`; override :meth:`add_arguments` to declare
    subcommand-specific flags; and implement :meth:`run`.

    The resolved context object (whatever :meth:`BaseCLI.resolve_config`
    returned — an :class:`IshConfig` for ishfiles, an
    :class:`argparse.Namespace` for isholate/ishproject) is stashed on
    ``self.cfg`` by :meth:`_entry` before :meth:`run` is called.

    To forward to another ishlib CLI, set :attr:`TARGET_MAIN` and
    :attr:`TARGET_BUILD_PARSER` on the subclass and call
    :meth:`passthrough` from ``run``.
    """

    NAME: str = ""
    HELP: str = ""
    DESCRIPTION: Optional[str] = None
    ADD_COMMON_FLAGS: bool = True

    # Passthrough targets — ``None`` means this command does not passthrough.
    # When set, :meth:`passthrough` and :meth:`compose_passthrough_argv`
    # become callable.
    TARGET_MAIN: Optional[Callable[[List[str]], int]] = None
    TARGET_BUILD_PARSER: Optional[Callable[[], argparse.ArgumentParser]] = None

    def __init__(self) -> None:
        self.cfg: Any = None

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
        inst = cls()
        inst.cfg = ctx
        return inst.run()

    @abstractmethod
    def run(self) -> int:
        """Execute the subcommand; return the process exit code.

        ``self.cfg`` has been populated by :meth:`_entry` before this is
        called.
        """

    # ------------------------------------------------------------------
    # Passthrough
    # ------------------------------------------------------------------
    def forward_explicit_globals(self) -> List[str]:
        """Reconstruct argv tokens for explicitly-set common flags.

        Decides whether each flag was typed on argv (versus defaulted
        or sourced from config) by checking:

        1. ``self.cfg.is_explicit(name)`` when ``self.cfg`` exposes it
           (the :class:`IshConfig` shape — ishfiles).
        2. ``name in self.cfg._ish_explicit`` otherwise (the raw
           :class:`argparse.Namespace` shape — ishproject / isholate).

        Only explicit flags are returned so a passthrough does not
        forge ``--dry-run`` when the user did not ask for it.
        """
        cfg = self.cfg
        if cfg is None:
            return []
        explicit = _explicit_test(cfg)
        out: List[str] = []
        if explicit("dry_run"):
            out.append("--dry-run")
        if explicit("debug"):
            out.append("--debug")
        if explicit("quiet"):
            out.append("--quiet")
        if explicit("verbose"):
            out.append("--verbose")
        if explicit("log_file"):
            log_file = _read_cfg_value(cfg, "log_file")
            if log_file is not None:
                out.extend(["--log-file", str(log_file)])
        return out

    def _require_target(self) -> None:
        if self.TARGET_MAIN is None or self.TARGET_BUILD_PARSER is None:
            raise TypeError(
                f"{type(self).__name__}.passthrough() requires "
                "TARGET_MAIN and TARGET_BUILD_PARSER to be set on the class."
            )

    def compose_passthrough_argv(
        self,
        subcommand: str,
        remainder: Iterable[str],
        *,
        global_args: Iterable[str] = (),
    ) -> List[str]:
        """Build the argv the target CLI would be invoked with.

        Returns the list instead of running anything — useful for
        pre-scans that need to honour the same flags the real
        passthrough will.

        ``global_args`` is inserted verbatim before the subcommand —
        use it only for flags that the target parser declares at the
        *top level* (e.g. ``--source``/``--target`` on ``ishfiles``).
        Explicit common flags from :meth:`forward_explicit_globals`
        join *remainder* so ``_split_for_target`` routes them to the
        correct side of the subcommand based on where the target
        declares them (ishfiles has ``-v``/``--dry-run``/etc. on its
        subparsers, so they must land after the subcommand).
        """
        self._require_target()
        assert self.TARGET_BUILD_PARSER is not None  # for type-checkers
        merged_remainder = [
            *self.forward_explicit_globals(),
            *list(remainder),
        ]
        return _compose_argv(
            subcommand,
            merged_remainder,
            global_args=global_args,
            target_parser=self.TARGET_BUILD_PARSER(),
        )

    def passthrough(
        self,
        subcommand: str,
        remainder: Iterable[str],
        *,
        global_args: Iterable[str] = (),
    ) -> int:
        """Invoke the target CLI with a composed argv; return its exit code."""
        argv = self.compose_passthrough_argv(
            subcommand, remainder, global_args=global_args
        )
        assert self.TARGET_MAIN is not None  # for type-checkers
        return self.TARGET_MAIN(argv)


# ----------------------------------------------------------------------
# Passthrough argv composition (module-level helpers)
# ----------------------------------------------------------------------
def _explicit_test(cfg: Any) -> Callable[[str], bool]:
    """Return ``lambda name: True`` iff *name* was explicitly set on *cfg*.

    Accepts either an :class:`IshConfig` (uses ``cfg.is_explicit``) or
    any object with an ``_ish_explicit`` attribute (the shape produced
    by the wrapped argparse actions in :mod:`pyishlib.cli_base`).
    """
    is_explicit = getattr(cfg, "is_explicit", None)
    if callable(is_explicit):
        return is_explicit
    explicit_set = getattr(cfg, "_ish_explicit", None) or ()
    return lambda name: name in explicit_set


def _read_cfg_value(cfg: Any, name: str) -> Any:
    """Read *name* from *cfg* via attribute, then ``cfg.args`` fallback."""
    value = getattr(cfg, name, None)
    if value is None:
        args = getattr(cfg, "args", None)
        if args is not None:
            value = getattr(args, name, None)
    return value


def _compose_argv(
    subcommand: str,
    remainder: Iterable[str],
    *,
    global_args: Iterable[str] = (),
    target_parser: Optional[argparse.ArgumentParser] = None,
) -> List[str]:
    """Compose the argv for forwarding to another ishlib CLI's ``main()``.

    When *target_parser* is provided, the remainder is first split into
    flags the target's *top-level* parser recognises and flags it does
    not.  Top-level flags are inserted before the subcommand; the rest
    follow it.  Without *target_parser*, every remainder argument lands
    after the subcommand (legacy behaviour).

    Args:
        subcommand:    The subcommand name to invoke on the target CLI.
        remainder:     Arguments forwarded by the wrapping CLI.
        global_args:   Arguments to insert before the subcommand
                       (e.g. ``["--source", "<dir>"]``).
        target_parser: Optional ``ArgumentParser`` for the target CLI.
                       Used only to split *remainder* into top-level vs
                       subcommand flags so that ``--dry-run`` etc. land
                       in front of the subcommand where the target's
                       top-level parser expects them.

    Returns:
        The composed argv list.
    """
    rest = list(remainder)
    pre_sub: List[str] = []
    if target_parser is not None and rest:
        pre_sub, rest = _split_for_target(target_parser, rest)
    return [*global_args, *pre_sub, subcommand, *rest]


def _split_for_target(
    parser: argparse.ArgumentParser, args: List[str]
) -> Tuple[List[str], List[str]]:
    """Split *args* into (top-level, leftover) for the target parser.

    Builds a copy of *parser* with no subparsers and runs
    ``parse_known_args`` to find which arguments the top-level
    recognises.  Anything it consumes is placed before the subcommand;
    everything else (subcommand-specific flags, positionals) follows.
    """
    # Match the target parser's abbreviation behaviour. Argparse
    # defaults to allow_abbrev=True; if the target explicitly disables
    # it, mirror that so `--ver` (for example) classifies the same way
    # on both parsers.
    probe = argparse.ArgumentParser(
        add_help=False,
        allow_abbrev=getattr(parser, "allow_abbrev", True),
    )
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        if not action.option_strings:
            # Skip top-level positionals (e.g. nothing in ishfiles).
            continue
        if action.option_strings == ["-h", "--help"]:
            continue
        kwargs: dict = {
            "dest": action.dest,
            "default": action.default,
            "required": False,
            "help": argparse.SUPPRESS,
        }
        if isinstance(action, argparse._StoreTrueAction):
            kwargs["action"] = "store_true"
        elif isinstance(action, argparse._StoreFalseAction):
            kwargs["action"] = "store_false"
        elif isinstance(action, argparse._CountAction):
            kwargs["action"] = "count"
        elif isinstance(action, argparse._StoreAction):
            kwargs["action"] = "store"
            kwargs["nargs"] = action.nargs
            if action.choices is not None:
                kwargs["choices"] = action.choices
        else:
            # Unknown action class — be conservative and skip.
            continue
        probe.add_argument(*action.option_strings, **kwargs)

    _, leftover = probe.parse_known_args(args)
    # Preserve order and handle duplicates by treating leftover as a
    # FIFO queue: walk *args*; if it matches the head of *leftover*,
    # pop and route to the leftover bucket; otherwise it was consumed
    # by the probe.
    leftover_queue = list(leftover)
    consumed: List[str] = []
    not_consumed: List[str] = []
    for token in args:
        if leftover_queue and token == leftover_queue[0]:
            not_consumed.append(leftover_queue.pop(0))
        else:
            consumed.append(token)
    return consumed, not_consumed
