# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Shared ``PRE_COMMIT_ALLOW_NO_CONFIG`` guard for ishproject commits.

The ishproject branch is intentionally created without a
``.pre-commit-config.yaml``.  Any git commit we make on it (orphan
bootstrap, per-branch bootstrap, phase-2 sync, user-visible ``commit``)
would therefore abort if the user has ``pre-commit`` installed as a
git template hook.  Wrap each such commit in this context manager to
neutralise the template hook for the duration of the call.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def allow_missing_precommit_config() -> Iterator[None]:
    """Set ``PRE_COMMIT_ALLOW_NO_CONFIG=1`` for the duration of the block.

    Restores the previous value (or unsets it) on exit, even on exception.
    """
    prev = os.environ.get("PRE_COMMIT_ALLOW_NO_CONFIG")
    os.environ["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("PRE_COMMIT_ALLOW_NO_CONFIG", None)
        else:
            os.environ["PRE_COMMIT_ALLOW_NO_CONFIG"] = prev
