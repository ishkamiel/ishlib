#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import inspect
from . import *
import pytest


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


def test_strlen_returns_length(shell, tmp_path, ishlib):
    """strlen should return the length of the input string."""
    script_content = inspect.cleandoc(
        f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    result=$(strlen "hello" 2>/dev/null)
    echo "$result"
    """
    )
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "5"


def test_strlen_empty_string(shell, tmp_path, ishlib):
    """strlen of empty string should be 0."""
    script_content = inspect.cleandoc(
        f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    result=$(strlen "" 2>/dev/null)
    echo "$result"
    """
    )
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "0"


def test_strlen_var(shell, tmp_path, ishlib):
    """strlen --var should store the result in the given variable."""
    script_content = inspect.cleandoc(
        f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    mylen=""
    strlen "abcdef" --var mylen 2>/dev/null
    echo "$mylen"
    """
    )
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "6"
