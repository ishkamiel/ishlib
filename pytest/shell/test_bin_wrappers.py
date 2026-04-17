#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

import os
import stat
import subprocess
from pathlib import Path

from . import rel_path, run_check_call

_BIN_FILES = [
    rel_path("bin/ishfiles"),
    rel_path("bin/isholate"),
    rel_path("bin/_ishlib_launch.sh"),
]


def pytest_generate_tests(metafunc):
    if "bin_file" in metafunc.fixturenames:
        metafunc.parametrize("bin_file", _BIN_FILES, ids=[f.name for f in _BIN_FILES])


def test_shellcheck(bin_file):
    # Run from the file's parent so that shellcheck resolves relative source= paths.
    original_cwd = os.getcwd()
    try:
        os.chdir(bin_file.parent)
        run_check_call("shellcheck", "-s", "bash", "-x", bin_file.name)
    finally:
        os.chdir(original_cwd)


def test_bash_syntax(bin_file):
    run_check_call("bash", "-n", str(bin_file))


def _make_fake_python(tmp_path: Path) -> Path:
    """Return an executable stub that prints its own path to stdout and exits 0."""
    fake = tmp_path / "fake_python"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$0"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def test_ishlib_python_override_ishfiles(tmp_path):
    fake_py = _make_fake_python(tmp_path)
    env = {**os.environ, "ISHLIB_PYTHON": str(fake_py)}
    result = subprocess.run(
        [str(rel_path("bin/ishfiles"))], env=env, capture_output=True, text=True
    )
    assert str(fake_py) in result.stdout


def test_ishlib_python_override_isholate(tmp_path):
    fake_py = _make_fake_python(tmp_path)
    env = {**os.environ, "ISHLIB_PYTHON": str(fake_py)}
    result = subprocess.run(
        [str(rel_path("bin/isholate"))], env=env, capture_output=True, text=True
    )
    assert str(fake_py) in result.stdout
