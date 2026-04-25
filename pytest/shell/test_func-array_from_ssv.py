#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

import inspect

from . import gen_script_and_check_output


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash"])


def test_array_from_ssv_basic(shell, tmp_path, ishlib):
    """array_from_ssv should split space-separated values into an array."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    my_arr=()
    array_from_ssv my_arr "alpha beta gamma"
    echo "${{#my_arr[@]}}"
    echo "${{my_arr[0]}}"
    echo "${{my_arr[1]}}"
    echo "${{my_arr[2]}}"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    lines = out.strip().splitlines()
    assert lines[0] == "3"
    assert lines[1] == "alpha"
    assert lines[2] == "beta"
    assert lines[3] == "gamma"


def test_array_from_ssv_single(shell, tmp_path, ishlib):
    """array_from_ssv with a single value should produce a one-element array."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    my_arr=()
    array_from_ssv my_arr "only"
    echo "${{#my_arr[@]}}"
    echo "${{my_arr[0]}}"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    lines = out.strip().splitlines()
    assert lines[0] == "1"
    assert lines[1] == "only"


def test_array_from_ssv_empty(shell, tmp_path, ishlib):
    """array_from_ssv with empty string should produce an empty array."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    my_arr=()
    array_from_ssv my_arr ""
    echo "${{#my_arr[@]}}"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "0"
