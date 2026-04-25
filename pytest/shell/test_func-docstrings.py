#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

import inspect

from . import gen_script_and_check_output


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])


def test_print_docstrings_does_not_leak_IFS(shell, tmp_path, ishlib):
    """print_docstrings should not leave _old_IFS in the environment."""
    # Create a small file with a docstring for print_docstrings to parse
    test_file = tmp_path / "doctest.sh"
    test_file.write_text(": <<'DOCSTRING'\ntest doc\nDOCSTRING\n")

    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    print_docstrings --text-only "{test_file}"
    if [ -n "${{_old_IFS+x}}" ]; then
        echo "LEAKED"
    else
        echo "CLEAN"
    fi
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    lines = [line.strip() for line in out.strip().splitlines()]
    assert lines[-1] == "CLEAN"
