#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

from . import *
from pathlib import Path


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", all_shells)


def test_check_shell_n(shell, ishlib, tmp_path, sh_only):
    if not shell in sh_only:
        run_check_call(shell, "-n", ishlib)
    else:
        script_content = ""
        with open(ishlib, "r") as src:
            for line in src:
                if ishlib_bash_variant in line:
                    break
                script_content += line
        run_script_content(shell, tmp_path, script_content)
