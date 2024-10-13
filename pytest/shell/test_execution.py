#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import subprocess
import os
import sys
import inspect
from pathlib import Path
from . import *
import pytest


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


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
    run_script_content(shell, tmp_path, script_content)


def test_include_run_debug(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(
        f"""
	#!/usr/bin/env {shell}
	DEBUG=1
	. "{ishlib}"
	"""
    )
    run_script_content(shell, tmp_path, script_content)
