# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""The ``doctor`` subcommand -- report optional-dependency availability.

Prints a table of optional Python packages that enhance ishlib's
functionality (shell-completion generation, strict schema validation,
TOML writing, ...) and indicates which ones are installed.  Nothing in
this list is required for base functionality; packages marked as
missing simply mean the associated feature falls back to a simpler
behaviour or is unavailable.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from typing import List, NamedTuple

from ...cli_command import CliCommand
from ...ish_config import IshConfig


class _OptionalDep(NamedTuple):
    module: str
    distribution: str  # PyPI name used in the `pip install ...` hint
    feature: str


class _ProbeResult(NamedTuple):
    status: str  # one of: "ok", "missing", "error"
    detail: str  # version string, install hint, or error description


OPTIONAL_DEPS: List[_OptionalDep] = [
    _OptionalDep(
        module="shtab",
        distribution="shtab",
        feature="Shell tab-completion via `ishfiles init --bash/--zsh`",
    ),
    _OptionalDep(
        module="cerberus",
        distribution="cerberus",
        feature="Schema validation for packages.toml and __ISH__ metadata",
    ),
    _OptionalDep(
        module="jsonschema",
        distribution="jsonschema",
        feature="Installer config schema validation",
    ),
    _OptionalDep(
        module="yaml",
        distribution="PyYAML",
        feature="Tolerant schema file parsing (comments, trailing commas)",
    ),
    _OptionalDep(
        module="tomli_w",
        distribution="tomli_w",
        feature="Writing TOML metadata files",
    ),
]


def _probe(dep: _OptionalDep) -> _ProbeResult:
    try:
        spec = importlib.util.find_spec(dep.module)
    except Exception as exc:  # noqa: BLE001
        return _ProbeResult("error", f"import check failed: {exc!s}")
    if spec is None:
        return _ProbeResult("missing", f"install with: pip install {dep.distribution}")
    try:
        version = importlib.metadata.version(dep.distribution)
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    except Exception as exc:  # noqa: BLE001
        return _ProbeResult("error", f"version lookup failed: {exc!s}")
    return _ProbeResult("ok", f"version {version}")


_STATUS_TAG = {
    "ok": "[ ok    ]",
    "missing": "[missing]",
    "error": "[ error ]",
}


class DoctorCommand(CliCommand):
    """Report availability of optional Python packages."""

    NAME = "doctor"
    HELP = "Report availability of optional Python packages"
    DESCRIPTION = (
        "Report which optional Python packages are installed.  None "
        "of the packages listed here are required for ishlib's base "
        "functionality -- each one simply enables an enhancement "
        "(for example, `shtab` is needed to generate shell "
        "tab-completion scripts from `ishfiles init --bash/--zsh`)."
    )

    def run(self, cfg: IshConfig) -> int:  # noqa: ARG002
        problems = 0
        name_w = max(len(d.distribution) for d in OPTIONAL_DEPS)

        print("Optional Python packages for enhanced ishlib functionality:")
        print()
        for dep in OPTIONAL_DEPS:
            result = _probe(dep)
            if result.status != "ok":
                problems += 1
            status = _STATUS_TAG.get(result.status, f"[{result.status}]")
            print(f"  {status} {dep.distribution:<{name_w}}  {dep.feature}")
            print(f"  {'':<9} {'':<{name_w}}  {result.detail}")
        print()
        if problems:
            print(
                f"{problems} optional package(s) missing or broken; "
                "base functionality is unaffected."
            )
        else:
            print("All optional packages installed.")

        return 0 if problems == 0 else 1
