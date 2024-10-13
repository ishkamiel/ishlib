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
    metafunc.parametrize("src_file", get_src_files())


def test_check_shell_n(shell, src_file, sh_only):
    if src_file.suffix != ".sh" and shell in sh_only:
        pytest.skip(f"Skipping {src_file} file for {shell}")
    run_check_call(shell, "-n", src_file)
