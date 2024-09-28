#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys
import inspect
from pathlib import Path
import pytest

script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
project_root = script_dir.parent


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


@pytest.fixture
def ishlib():
    return str(project_root / "ishlib.sh")


def run_script_content(shell, tmp_path, ishlib, script_content):
    tmp_file = Path(tmp_path) / f"test_{shell}.sh"
    tmp_file.write_text(script_content)
    run_check_call(shell, tmp_file)


def run_check_call(*args):
    subprocess.check_call([str(i) for i in args])


def test_standalone_run(shell, ishlib):
    run_check_call(shell, ishlib)


def test_standalone_run_help(shell, ishlib):
    run_check_call(shell, ishlib, "--help")


def test_include_run(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(
        f"""
	#!/usr/bin/env {shell}
	. "{ishlib}"
	"""
    )
    run_script_content(shell, tmp_path, ishlib, script_content)


def test_include_run_debug(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(
        f"""
	#!/usr/bin/env {shell}
	DEBUG=1
	. "{ishlib}"
	"""
    )
    run_script_content(shell, tmp_path, ishlib, script_content)
