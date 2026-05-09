# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``python -m pyishlib.launchers`` — install ishlib tool launchers.

One-shot installer that writes launcher shims for every registered tool
into ``~/.local/bin``.  ``--full`` additionally pip-installs the optional
extras (``shtab``, ``cerberus``, ``jsonschema``, ``PyYAML``, ``tomli_w``)
into the interpreter the launchers will actually pick at runtime, so the
in-tree install path matches ``pipx install '.[full]'`` semantically.
The destination (``~/.local/bin``) and baked-in source path (the ``src/``
dir containing this package) are auto-detected.  Programmatic callers
should call :func:`pyishlib.launchers.install_all` directly.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from . import install_all
from ..ish_logging import log_level_from_args, setup_logging

log = logging.getLogger(__name__)

# Mirrors the `full` extra in pyproject.toml.  Kept in sync manually so the
# in-tree install path agrees with `pipx install '.[full]'`.
_FULL_EXTRAS: List[str] = [
    "shtab>=1.8.0",
    "cerberus",
    "jsonschema",
    "PyYAML",
    "tomli_w",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pyishlib.launchers",
        description=(
            "Install launcher shims for all registered ishlib tools into "
            "~/.local/bin.  Source dir and destination are auto-detected."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Log the path of each installed launcher.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Log auto-detected paths and every up-to-date skip.",
    )
    extras = parser.add_mutually_exclusive_group()
    extras.add_argument(
        "--full",
        dest="full",
        action="store_true",
        default=False,
        help=(
            "Also pip install --user the optional extras (shtab, cerberus, "
            "jsonschema, PyYAML, tomli_w) into the interpreter the "
            "launchers will use."
        ),
    )
    extras.add_argument(
        "--minimal",
        dest="full",
        action="store_false",
        help="Only write launchers; do not install optional extras (default).",
    )
    return parser


def _pick_python() -> Optional[Path]:
    """Pick the interpreter the launchers will use at runtime.

    Mirrors the ``_pick_python`` helper baked into the bash launcher
    template (``_template.py``) so ``--full`` installs extras into the
    same interpreter that ``ishfiles``/``isholate`` will eventually run
    under.
    """
    env = os.environ.get("ISHLIB_PYTHON")
    if env and os.access(env, os.X_OK):
        return Path(env)

    pyenv = shutil.which("pyenv")
    if pyenv:
        try:
            res = subprocess.run(
                [pyenv, "global"],
                check=False,
                capture_output=True,
                text=True,
            )
            version = (res.stdout.splitlines() or [""])[0].strip()
            if version and version != "system":
                root = subprocess.run(
                    [pyenv, "root"],
                    check=False,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if root:
                    candidate = Path(root) / "versions" / version / "bin" / "python3"
                    if os.access(candidate, os.X_OK):
                        return candidate
        except OSError:
            pass

    if os.access("/usr/bin/python3", os.X_OK):
        return Path("/usr/bin/python3")

    fallback = shutil.which("python3")
    return Path(fallback) if fallback else None


def _install_extras(python: Path) -> int:
    """Pip-install the ``full`` extras into *python* (user site)."""
    cmd = [
        str(python),
        "-m",
        "pip",
        "install",
        "--user",
        "--upgrade",
        *_FULL_EXTRAS,
    ]
    log.info("Installing optional extras into %s", python)
    log.debug("running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        log.error(
            "Failed to install extras into %s (exit %d). Launchers were "
            "still written; rerun with --full or `pip install --user "
            "%s` to retry.",
            python,
            proc.returncode,
            " ".join(_FULL_EXTRAS),
        )
    return proc.returncode


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    setup_logging(log_level_from_args(args))

    dest_dir = (Path.home() / ".local" / "bin").resolve()
    # Default: src/ two levels above this package's directory.
    source_dir = Path(__file__).resolve().parent.parent.parent

    if not source_dir.is_dir():
        log.error("ishlib source directory not found: %s", source_dir)
        return 1

    log.debug("installing launchers: source=%s dest=%s", source_dir, dest_dir)
    rc = install_all(dest_dir=dest_dir, source_dir=source_dir)
    if rc != 0:
        return rc

    if args.full:
        python = _pick_python()
        if python is None:
            log.error(
                "--full: no python3 interpreter found; install extras "
                "manually with `pip install --user %s`.",
                " ".join(_FULL_EXTRAS),
            )
            return 1
        extras_rc = _install_extras(python)
        if extras_rc != 0:
            return extras_rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
