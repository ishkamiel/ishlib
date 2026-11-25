# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

"""Helper library for common sysadmin and developments tasks

The public names below are resolved lazily (PEP 562) so that importing
any ``pyishlib`` submodule -- which always runs this ``__init__`` first --
does not drag in the installer/dotfile stack.  ``from pyishlib import
CommandRunner`` keeps working unchanged.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from .command_runner import CommandRunner as CommandRunner
    from .dotfile import DotFile as DotFile
    from .dotfile_applier import DotfileApplier as DotfileApplier
    from .ish_config import IshConfig as IshConfig

_LAZY = {
    "CommandRunner": ".command_runner",
    "DotFile": ".dotfile",
    "DotfileApplier": ".dotfile_applier",
    "IshConfig": ".ish_config",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> List[str]:
    return sorted([*globals(), *_LAZY])
