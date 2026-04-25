#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

import inspect

from . import gen_script_and_check_output


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


def test_has_command_finds_existing(shell, tmp_path, ishlib):
    """has_command should return 0 for a command that exists."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    has_command echo && echo "found" || echo "not found"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "found"


def test_has_command_rejects_missing(shell, tmp_path, ishlib):
    """has_command should return 1 for a command that doesn't exist."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    has_command no_such_command_xyz && echo "found" || echo "not found"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "not found"


def test_has_command_empty_arg(shell, tmp_path, ishlib):
    """has_command should return 2 for an empty argument."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    has_command "" 2>/dev/null
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "2"


def test_has_command_finds_shell_function(shell, tmp_path, ishlib):
    """has_command should find shell functions."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    my_test_func() {{ echo "hi"; }}
    has_command my_test_func && echo "found" || echo "not found"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "found"
