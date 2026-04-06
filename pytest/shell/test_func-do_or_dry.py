#!/usr/bin/env python3
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import inspect
from . import *
import pytest


def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash"])


def test_is_dry_when_set(shell, tmp_path, ishlib):
    """is_dry should return 0 when DRY_RUN=1."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    DRY_RUN=1
    is_dry && echo "dry" || echo "wet"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "dry"


def test_is_dry_when_disabled(shell, tmp_path, ishlib):
    """is_dry should return 1 when DRY_RUN is 0."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    DRY_RUN=0
    is_dry && echo "dry" || echo "wet"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "wet"


def test_do_or_dry_executes(shell, tmp_path, ishlib):
    """do_or_dry should execute the command when not in dry run."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    set -euo pipefail
    . "{ishlib}"
    DRY_RUN=0
    do_or_dry echo "hello world"
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert "hello world" in out


def test_do_or_dry_skips_in_dry_mode(shell, tmp_path, ishlib):
    """do_or_dry should not execute the command when DRY_RUN=1."""
    outfile = tmp_path / "marker"
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    DRY_RUN=1
    do_or_dry touch "{outfile}" 2>/dev/null
    """)
    gen_script_and_check_output(shell, tmp_path, script_content)
    assert not outfile.exists()


def test_do_or_dry_returns_failure(shell, tmp_path, ishlib):
    """do_or_dry should return 1 when the command fails."""
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    DRY_RUN=0
    do_or_dry false 2>/dev/null
    echo $?
    """)
    out = gen_script_and_check_output(shell, tmp_path, script_content)
    assert out.strip() == "1"
