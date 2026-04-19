# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Shell-completion generators for all registered ishlib tools.

Completions are produced by the optional `shtab`_ package from each
tool's live :mod:`argparse` parser, so they stay in sync with the CLI
automatically.  When ``shtab`` is not installed the helpers in this
module still import cleanly and :data:`HAS_SHTAB` is ``False``; callers
should check that flag and degrade gracefully (for instance, the
``ishfiles init`` subcommand emits only the POSIX ``cd`` wrapper and
logs a hint to install ``shtab``).

.. _shtab: https://pypi.org/project/shtab/
"""

from __future__ import annotations

from importlib import import_module
from typing import Tuple

from .. import tools as _tools

try:
    import shtab

    HAS_SHTAB = True
except ImportError:
    HAS_SHTAB = False

#: Shells that :func:`generate` can emit for.  Matches what ``shtab``
#: itself supports at the time of writing.
SUPPORTED_SHELLS: Tuple[str, ...] = ("bash", "zsh", "tcsh")


def generate(tool: str, shell: str) -> str:
    """Generate a completion script for *tool* in *shell*.

    Args:
        tool:  Name of any registered ishlib tool (see
               :mod:`pyishlib.tools`).
        shell: One of :data:`SUPPORTED_SHELLS` (``"bash"``, ``"zsh"``,
               ``"tcsh"``).

    Returns:
        The completion script as a single string.

    Raises:
        RuntimeError: If ``shtab`` is not installed.
        ValueError:   If *tool* or *shell* is unknown.
    """
    if not HAS_SHTAB:
        raise RuntimeError(
            "shtab is required for completion generation; install with `pip install shtab`"
        )
    if shell not in SUPPORTED_SHELLS:
        raise ValueError(
            f"unsupported shell {shell!r}; expected one of {SUPPORTED_SHELLS}"
        )

    spec = _tools.get(tool)  # raises ValueError for unknown tool
    mod = import_module(f"{spec.module}.cli")
    return shtab.complete(mod.build_parser(), shell=shell)
