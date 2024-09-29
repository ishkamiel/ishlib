#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from . import *
from pathlib import Path


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", shellcheck_shells)
    metafunc.parametrize("src_file", get_src_files())


def test_shellcheck(src_folder, shell, src_file, all_src_files, sh_only):
    if src_file.suffix != ".sh" and shell in sh_only:
        pytest.skip(f"Skipping non-sh script file: {src_file}")

    include_args = []
    for file in all_src_files:
        if not shell in sh_only or file.suffix == ".sh":
            include_args.extend(["-x", file])
    os.chdir(src_folder)

    run_check_call("shellcheck", "-s", shell, *include_args, src_file)
