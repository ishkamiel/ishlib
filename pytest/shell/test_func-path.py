#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

import inspect

from . import gen_script_and_check_output


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


def test_prepend_to_path_adds_new(shell, tmp_path, ishlib):
    """ish_prepend_to_path should prepend a new directory to PATH."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    PATH="/usr/bin:/bin"
    ish_prepend_to_path /my/new/path
    echo "$PATH"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "/my/new/path:/usr/bin:/bin"


def test_prepend_to_path_no_duplicate(shell, tmp_path, ishlib):
    """ish_prepend_to_path should not add a path that already exists."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    PATH="/usr/bin:/bin"
    ish_prepend_to_path /usr/bin
    echo "$PATH"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "/usr/bin:/bin"
