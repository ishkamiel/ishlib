# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper for forwarding to another pyishlib CLI's ``main()``.

Used by tools such as ``ishproject`` whose subcommands delegate the
heavy lifting to ``ishfiles``. The single seam keeps tests hermetic and
keeps argv composition consistent.
"""

from __future__ import annotations

import argparse
from typing import Callable, Iterable, List, Optional, Tuple


def passthrough_to_cli(
    main_fn: Callable[[List[str]], int],
    subcommand: str,
    remainder: Iterable[str],
    *,
    global_args: Iterable[str] = (),
    target_parser: Optional[argparse.ArgumentParser] = None,
) -> int:
    """Invoke another pyishlib CLI by composing its argv and calling ``main_fn``.

    When *target_parser* is provided, the remainder is first split into
    flags the target's *top-level* parser recognises and flags it does
    not. Top-level flags are inserted before the subcommand; the rest
    follow it. Without *target_parser*, every remainder argument lands
    after the subcommand (legacy behaviour).

    Args:
        main_fn: The other CLI's ``main`` function (takes a single
            ``argv`` list, returns an exit code).
        subcommand: The subcommand name to invoke on the target CLI.
        remainder: Arguments forwarded by the wrapping CLI.
        global_args: Arguments to insert before the subcommand
            (e.g. ``["--source", "<dir>"]``).
        target_parser: Optional ``ArgumentParser`` for the target CLI.
            Used only to split *remainder* into top-level vs
            subcommand flags so that ``--dry-run`` etc. land in front
            of the subcommand where the target's top-level parser
            expects them.

    Returns:
        The exit code returned by ``main_fn``.
    """
    rest = list(remainder)
    pre_sub: List[str] = []
    if target_parser is not None and rest:
        pre_sub, rest = _split_for_target(target_parser, rest)
    argv: List[str] = [*global_args, *pre_sub, subcommand, *rest]
    return main_fn(argv)


def _split_for_target(
    parser: argparse.ArgumentParser, args: List[str]
) -> Tuple[List[str], List[str]]:
    """Split *args* into (top-level, leftover) for the target parser.

    Builds a copy of *parser* with no subparsers and runs
    ``parse_known_args`` to find which arguments the top-level
    recognises. Anything it consumes is placed before the subcommand;
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
        kwargs = {
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
