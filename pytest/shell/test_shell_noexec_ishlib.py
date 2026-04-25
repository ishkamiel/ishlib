#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

from . import all_shells, ishlib_bash_variant, run_check_call, run_script_content


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", all_shells)


def test_check_shell_n(shell, ishlib, tmp_path, sh_only):
    if shell not in sh_only:
        run_check_call(shell, "-n", ishlib)
    else:
        script_content = ""
        with open(ishlib, "r") as src:
            for line in src:
                if ishlib_bash_variant in line:
                    break
                script_content += line
        run_script_content(shell, tmp_path, script_content)
