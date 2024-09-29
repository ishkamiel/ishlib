#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from . import *


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", shellcheck_shells)
    metafunc.parametrize("sh_only", poisix_only_shells)


def test_shellcheck_ishlib(shell, sh_only, ishlib, tmp_path):
    if not shell in sh_only:
        run_check_call("shellcheck", "-s", shell, ishlib)
    else:
        script_content = ""
        with open(ishlib, "r") as src:
            for line in src:
                if ishlib_bash_variant in line:
                    break
                script_content += line
        tmp_file = gen_file(tmp_path, script_content)
        run_check_call("shellcheck", "-s", shell, tmp_file)
