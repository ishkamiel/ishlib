---
name: add-ishlib-tool
description: >
  Add a new top-level CLI tool to ishlib alongside ishfiles/isholate/ishproject.
  Use this skill whenever the user asks to create a new utility, add a new ishlib
  tool, scaffold a new CLI under pyishlib, or register a new tool in the ishlib
  plugin registry. Also trigger when the user mentions wanting a new `ish<name>`
  command that should live in `src/pyishlib/`.
---

# Adding a new top-level ishlib CLI tool

## Overview

All ishlib CLI tools are registered in `src/pyishlib/tools.py`. Adding a
tool is five steps:

1. Register in `tools.py`
2. Scaffold the Python package
3. Write tests
4. Verify
5. (Optional) update `CLAUDE.md`

Steps 1 and 2 are the core work. Launchers, completions, `ishfiles init`,
and `IshlibFolder` pick up the new tool automatically — **no other file needs
to change**.

---

## Step 1 — Register in `src/pyishlib/tools.py`

Add one entry to `TOOLS`:

```python
Tool(
    name="ishnew",                      # the CLI binary name
    module="pyishlib.ishnew",           # python -m target
    description="One-line description.",
    subdir="ishnew",                    # .ishlib/<subdir> accessor key
),
```

That is the complete registration. Everything else is automatic.

---

## Step 2 — Scaffold `src/pyishlib/<name>/`

### `__init__.py`

```python
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""<One-line description of the tool>."""
```

### `__main__.py`

```python
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Entry point for ``python -m pyishlib.<name>``."""

from .cli import main

raise SystemExit(main())
```

### `cli.py`

```python
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Argument parser and entry point for the ``<name>`` CLI."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from ..ish_config import IshConfig
from ..ish_logging import setup_logging
from .commands import subcmd  # one import per subcommand module


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Attach -v/-q to a subparser."""
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Increase log verbosity (-v=info, -vv=debug).",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", default=False,
        help="Suppress non-essential output.",
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", default=False,
        help="Show actions without executing them.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="<name>",
        description="<Full description of the tool.>",
    )
    subs = parser.add_subparsers(dest="subcommand", required=True, metavar="COMMAND")

    # Register each subcommand module here:
    subcmd.register(subs)

    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    level = (
        logging.DEBUG if args.verbose >= 2
        else logging.INFO if args.verbose
        else logging.WARNING
    )
    setup_logging(level, log_file=None, quiet=args.quiet)

    cfg = IshConfig(dry_run=args.dry_run, verbose=args.verbose > 0, quiet=args.quiet)
    return args.func(cfg)
```

**Key rules (from `CLAUDE.md §Python CLI Tools`):**

- `-v/-q/-n` attach to **each subparser** via `_add_common_args()`, not the
  top-level parser. The `parents=` pattern has the same bug — don't use it.
- `build_parser()` must be a standalone function (tests call it directly).
- Missing subcommand must be an argparse error (`required=True`).

### `commands/<subcmd>.py`

```python
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``<name> <subcmd>`` — <one-line description>."""

from __future__ import annotations

import argparse
import logging

from ...ish_config import IshConfig

log = logging.getLogger(__name__)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "<subcmd>",
        help="<Short help shown in `<name> --help`>",
        description="<Longer description shown in `<name> <subcmd> --help`>.",
    )
    _add_common_args(parser)
    # Add subcommand-specific flags here.
    parser.set_defaults(func=run)


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("-q", "--quiet", action="store_true", default=False)
    parser.add_argument("-n", "--dry-run", action="store_true", default=False)


def run(cfg: IshConfig) -> int:
    log.info("Running <name> <subcmd>")
    # Implementation here.
    return 0
```

---

## Step 3 — Write tests in `pytest/python/test_<name>.py`

```python
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for the <name> CLI."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

from pyishlib.<name>.cli import build_parser, main  # noqa: E402


class TestParser(unittest.TestCase):
    def test_missing_subcommand_errors(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_subcmd_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["<subcmd>"])
        self.assertEqual(args.verbose, 0)
        self.assertFalse(args.quiet)
        self.assertFalse(args.dry_run)

    def test_subcmd_verbose(self):
        parser = build_parser()
        args = parser.parse_args(["-v", "<subcmd>"])
        # NOTE: -v is on the subparser, not the top-level parser.
        # To pass it, it must come AFTER the subcommand name:
        args = parser.parse_args(["<subcmd>", "-v"])
        self.assertEqual(args.verbose, 1)


class TestDispatch(unittest.TestCase):
    def test_subcmd_calls_run(self):
        from unittest.mock import patch
        with patch("pyishlib.<name>.commands.<subcmd>.run") as mock_run:
            mock_run.return_value = 0
            ret = main(["<subcmd>"])
        mock_run.assert_called_once()
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
```

---

## Step 4 — Verify

```bash
cd ishlib

# Run the new tool's tests
.venv/bin/pytest pytest/python/test_<name>.py -v

# Confirm launcher generation picks up the new tool
python3 -c "
from src.pyishlib.launchers import render_launcher
from src.pyishlib.tools import get
import sys
content = render_launcher(get('<name>'), sys.path[0])
assert '<name>' in content
assert 'pyishlib.<name>' in content
print('OK')
"

# Full suite
make verify
```

---

## Step 5 — Update docs (optional)

If the tool is prominent, add a one-line row to `CLAUDE.md §Project Overview`.
The registry entry's `description` field is enough for less prominent tools.

**Do NOT create a `bin/<name>` stub.** Launchers are generated by
`pyishlib.launchers` on next `ishfiles apply` or `./bin/ishlib-install`.
