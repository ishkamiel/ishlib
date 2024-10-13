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
    metafunc.parametrize("shell", shellcheck_shells)
    metafunc.parametrize("src_file", get_src_files())


def test_shellcheck(src_folder, shell, all_src_files, src_file, sh_only):
    if src_file.suffix != ".sh" and shell in sh_only:
        pytest.skip(f"Skipping non-sh script file: {src_file}")

    src_file = Path(src_file)

    old_dir = os.getcwd()
    os.chdir(Path(src_file).parent)

    run_check_call("shellcheck", "-s", shell, "-x", str(src_file.name))
