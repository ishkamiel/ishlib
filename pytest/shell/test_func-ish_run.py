#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys
import inspect
from pathlib import Path
from . import *
import pytest


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "zsh"])


def run_cmd(shell, tmp_path, ishlib, cmd, env=""):
    script_content = inspect.cleandoc(
        f"""
    #!/usr/bin/env {shell}

    {env}

    set -euo pipefail
    . "{ishlib}"
    {cmd}
    """
    )
    res = gen_script_and_check_output(shell, tmp_path, script_content)
    res = res.splitlines()
    res = [line.strip() for line in res]
    if len(res) < 1:
        res.append("")
    if len(res) < 2:
        res.append("")
    return res


def test_dry_run(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run echo hello")
    assert res[0] == "echo hello"
    assert res[1] == "hello"


def test_dry_run_q(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -q echo hello")
    assert res[0] == "hello"
    assert res[1] == ""


def test_dry_run_qn(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -q -n echo hello")
    assert res[0] == ""
    assert res[1] == ""


def test_dry_run_n(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -n echo hello")
    assert res[0] == "echo hello"
    assert res[1] == ""


def test_dry_run_dry_n(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -n echo hello", "DRY_RUN=1")
    assert res[0] == "echo hello"
    assert res[1] == ""


def test_dry_run_dry_f(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -f echo hello", "DRY_RUN=1")
    assert res[0] == "echo hello"
    assert res[1] == "hello"


def test_dry_run_dry_fq(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -f -q echo hello", "DRY_RUN=1")
    assert res[0] == "hello"
    assert res[1] == ""


def test_dry_run_dry_q(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -q echo hello", "DRY_RUN=1")
    assert res[0] == ""
    assert res[1] == ""


def test_dash_dash(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -- echo -hello --hello")
    assert res[0] == "echo -hello --hello"
    assert res[1] == "-hello --hello"


def test_dash_dash_q(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -q -- echo -hello --hello")
    assert res[0] == "-hello --hello"
    assert res[1] == ""


def test_dash_dash_q(shell, tmp_path, ishlib):
    res = run_cmd(shell, tmp_path, ishlib, "ish_run -q -- echo -- -n -hello --hello")
    assert res[0] == "-- -n -hello --hello"
    assert res[1] == ""
