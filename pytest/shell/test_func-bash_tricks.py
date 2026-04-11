#!/usr/bin/env python3
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import inspect
from . import *


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash"])


def test_copy_function(shell, tmp_path, ishlib):
    """copy_function should create a working copy of a function."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    my_func() {{ echo "hello from my_func"; }}
    copy_function my_func my_copy
    my_copy
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "hello from my_func"


def test_copy_function_preserves_original(shell, tmp_path, ishlib):
    """copy_function should preserve the original function."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    my_func() {{ echo "original"; }}
    copy_function my_func my_copy
    my_func
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "original"


def test_rename_function(shell, tmp_path, ishlib):
    """rename_function should move a function to a new name."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    my_func() {{ echo "renamed"; }}
    rename_function my_func new_name
    new_name
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "renamed"


def test_rename_function_removes_original(shell, tmp_path, ishlib):
    """rename_function should remove the original function."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    my_func() {{ echo "gone"; }}
    rename_function my_func new_name
    if declare -f my_func >/dev/null 2>&1; then
        echo "still exists"
    else
        echo "removed"
    fi
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "removed"
