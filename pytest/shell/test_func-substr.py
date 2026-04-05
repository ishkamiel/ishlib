#!/usr/bin/env python3
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import inspect
from . import *
import pytest


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


def test_substr_basic(shell, tmp_path, ishlib):
    """substr should extract a substring by start and end position."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    result=$(substr "hello world" 7)
    echo "$result"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "world"


def test_substr_with_end(shell, tmp_path, ishlib):
    """substr with start and end should extract a bounded range."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    result=$(substr "hello world" 1 5)
    echo "$result"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "hello"


def test_substr_var(shell, tmp_path, ishlib):
    """substr --var should store the result in the given variable."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    myvar=""
    substr "abcdef" 2 4 --var myvar
    echo "$myvar"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "bcd"


def test_strlen_returns_length(shell, tmp_path, ishlib):
    """strlen should return the length of the input string."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    result=$(strlen "hello" 2>/dev/null)
    echo "$result"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "5"


def test_strlen_empty_string(shell, tmp_path, ishlib):
    """strlen of empty string should be 0."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    result=$(strlen "" 2>/dev/null)
    echo "$result"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "0"


def test_strlen_var(shell, tmp_path, ishlib):
    """strlen --var should store the result in the given variable."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    mylen=""
    strlen "abcdef" --var mylen 2>/dev/null
    echo "$mylen"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "6"
