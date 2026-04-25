#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

import inspect

from . import gen_script_and_check_output


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash"])


def test_assert_dir_existing(shell, tmp_path, ishlib):
    """assert_dir should return 0 for an existing directory."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    assert_dir "{tmp_path}"
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "0"


def test_assert_dir_missing(shell, tmp_path, ishlib):
    """assert_dir should return non-zero for a missing directory."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    assert_dir "/no/such/dir/here" 2>/dev/null
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "1"


def test_assert_dir_file_not_dir(shell, tmp_path, ishlib):
    """assert_dir should return non-zero when given a file, not a directory."""
    test_file = tmp_path / "afile.txt"
    test_file.write_text("content")
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    assert_dir "{test_file}" 2>/dev/null
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "1"


def test_assert_exists_existing(shell, tmp_path, ishlib):
    """assert_exists should return 0 for an existing file."""
    test_file = tmp_path / "exists.txt"
    test_file.write_text("content")
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    assert_exists "{test_file}"
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "0"


def test_assert_exists_missing(shell, tmp_path, ishlib):
    """assert_exists should return non-zero for a missing file."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    assert_exists "/no/such/file" 2>/dev/null
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "1"


def test_assert_dir_multiple(shell, tmp_path, ishlib):
    """assert_dir should count all bad directories."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    assert_dir "/no/a" "/no/b" "/no/c" 2>/dev/null
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "3"
