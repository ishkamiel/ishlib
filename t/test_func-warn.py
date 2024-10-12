#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys
import inspect
from pathlib import Path
from . import *
import pytest


@pytest.fixture
def src_file(src_folder):
    return src_folder / "sh" / "prints_and_prompts.sh"


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


def test_include_warn_debug(shell, tmp_path, src_file, ishlib):
    script_content = inspect.cleandoc(
        f"""
    #!/usr/bin/env {shell}
    DEBUG=1
    ISHLIB="{Path(ishlib).parent}"
    cd "{Path(src_file).parent}"
    . "{str(src_file)}"
    warn "test_warning_goes_here"
    """
    )
    print(f"script_content:\n{script_content}")
    res = gen_script_and_check_output(shell, tmp_path, script_content)

    assert "test_warning_goes_here" in res


def test_ishlib_warn_debug(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(
        f"""
    #!/usr/bin/env {shell}
    DEBUG=1
    . "{str(ishlib)}"
    warn "test_warning_goes_here"
    """
    )
    print(f"script_content:\n{script_content}")
    res = gen_script_and_check_output(shell, tmp_path, script_content)

    assert "test_warning_goes_here" in res
