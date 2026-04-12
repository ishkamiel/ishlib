#!/usr/bin/env python3
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

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
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    DEBUG=1
    ISHLIB="{Path(ishlib).parent}"
    cd "{Path(src_file).parent}"
    . "{str(src_file)}"
    ish_warn "test_warning_goes_here"
    """)
    print(f"script_content:\n{script_content}")
    res = gen_script_and_check_output(shell, tmp_path, script_content)

    assert "test_warning_goes_here" in res


def test_ishlib_warn_debug(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    DEBUG=1
    . "{str(ishlib)}"
    ish_warn "test_warning_goes_here"
    """)
    print(f"script_content:\n{script_content}")
    res = gen_script_and_check_output(shell, tmp_path, script_content)

    assert "test_warning_goes_here" in res


def test_ish_info_stderr(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{str(ishlib)}"
    ish_info "info_message_here"
    """)
    res = gen_script_and_check_output(shell, tmp_path, script_content)
    assert "info_message_here" in res


def test_ish_error_stderr(shell, tmp_path, ishlib):
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{str(ishlib)}"
    ish_error "error_message_here"
    """)
    res = gen_script_and_check_output(shell, tmp_path, script_content)
    assert "error_message_here" in res


def test_ish_fatal_exits(shell, tmp_path, ishlib):
    import subprocess
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{str(ishlib)}"
    ish_fatal "fatal_message_here"
    echo "SHOULD_NOT_REACH"
    """)
    tmp_file = tmp_path / "test.sh"
    tmp_file.write_text(script_content)
    result = subprocess.run(
        [shell, str(tmp_file)],
        capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "SHOULD_NOT_REACH" not in result.stdout + result.stderr
    assert "fatal_message_here" in result.stdout + result.stderr


def test_warn_routes_to_ishlib_log_out(shell, tmp_path, ishlib):
    log_file = tmp_path / "out.log"
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    ISHLIB_LOG_OUT="{log_file}"
    . "{str(ishlib)}"
    ish_warn "warn_via_env"
    """)
    gen_script_and_check_output(shell, tmp_path, script_content)
    assert log_file.exists()
    content = log_file.read_text()
    assert "warn\twarn_via_env" in content


def test_info_routes_to_ishlib_log_out(shell, tmp_path, ishlib):
    log_file = tmp_path / "out.log"
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    ISHLIB_LOG_OUT="{log_file}"
    . "{str(ishlib)}"
    ish_info "info_via_env"
    """)
    gen_script_and_check_output(shell, tmp_path, script_content)
    assert log_file.exists()
    content = log_file.read_text()
    assert "info\tinfo_via_env" in content


def test_error_routes_to_ishlib_log_out(shell, tmp_path, ishlib):
    log_file = tmp_path / "out.log"
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    ISHLIB_LOG_OUT="{log_file}"
    . "{str(ishlib)}"
    ish_error "error_via_env"
    """)
    gen_script_and_check_output(shell, tmp_path, script_content)
    assert log_file.exists()
    content = log_file.read_text()
    assert "error\terror_via_env" in content


def test_fatal_routes_to_ishlib_log_out(shell, tmp_path, ishlib):
    import subprocess
    log_file = tmp_path / "out.log"
    script_content = inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    ISHLIB_LOG_OUT="{log_file}"
    . "{str(ishlib)}"
    ish_fatal "fatal_via_env"
    echo "SHOULD_NOT_REACH"
    """)
    tmp_file = tmp_path / "test.sh"
    tmp_file.write_text(script_content)
    result = subprocess.run([shell, str(tmp_file)], capture_output=True, text=True)
    assert result.returncode != 0
    assert log_file.exists()
    content = log_file.read_text()
    assert "fatal\tfatal_via_env" in content
