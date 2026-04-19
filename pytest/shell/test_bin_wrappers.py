#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for generated launcher scripts and bin/ishlib-install."""

import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from pyishlib.launchers import install_all  # noqa: E402
from pyishlib.tools import TOOLS, get as get_tool  # noqa: E402

from . import rel_path, run_check_call  # noqa: E402

_TOOL_NAMES = [t.name for t in TOOLS]


def pytest_generate_tests(metafunc):
    if "tool_name" in metafunc.fixturenames:
        metafunc.parametrize("tool_name", _TOOL_NAMES)


def test_bash_syntax(tool_name, tmp_path):
    """Generated launcher must pass ``bash -n`` syntax check."""
    dest = tmp_path / "bin"
    install_all(dest_dir=dest, source_dir=rel_path("src"))
    run_check_call("bash", "-n", str(dest / tool_name))


def test_shellcheck(tool_name, tmp_path):
    """Generated launcher must pass shellcheck."""
    dest = tmp_path / "bin"
    install_all(dest_dir=dest, source_dir=rel_path("src"))
    run_check_call("shellcheck", "-s", "bash", str(dest / tool_name))


def test_launcher_is_executable(tool_name, tmp_path):
    """Generated launcher must have executable bits set."""
    dest = tmp_path / "bin"
    install_all(dest_dir=dest, source_dir=rel_path("src"))
    launcher = dest / tool_name
    assert launcher.exists(), f"{tool_name} launcher not created"
    mode = launcher.stat().st_mode
    assert mode & stat.S_IXUSR, f"{tool_name} launcher is not user-executable"


def test_launcher_contains_module(tool_name, tmp_path):
    """Generated launcher must reference the correct Python module."""
    dest = tmp_path / "bin"
    install_all(dest_dir=dest, source_dir=rel_path("src"))
    content = (dest / tool_name).read_text()
    tool = get_tool(tool_name)
    assert tool.module in content


def test_launcher_shebang(tool_name, tmp_path):
    """Generated launcher must start with #!/usr/bin/env bash."""
    dest = tmp_path / "bin"
    install_all(dest_dir=dest, source_dir=rel_path("src"))
    first_line = (dest / tool_name).read_text().splitlines()[0]
    assert first_line == "#!/usr/bin/env bash"


def _make_fake_python(tmp_path: Path) -> Path:
    """Return an executable stub that prints its own path to stdout and exits 0."""
    fake = tmp_path / "fake_python"
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$0"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def test_ishlib_python_override(tool_name, tmp_path):
    """ISHLIB_PYTHON env var must be used as the interpreter."""
    dest = tmp_path / "bin"
    install_all(dest_dir=dest, source_dir=rel_path("src"))
    fake_py = _make_fake_python(tmp_path)
    env = {**os.environ, "ISHLIB_PYTHON": str(fake_py)}
    result = subprocess.run(
        [str(dest / tool_name)], env=env, capture_output=True, text=True
    )
    assert str(fake_py) in result.stdout


def test_ishlib_install_bash_syntax():
    """bin/ishlib-install must pass ``bash -n`` syntax check."""
    run_check_call("bash", "-n", str(rel_path("bin/ishlib-install")))


def test_ishlib_install_shellcheck():
    """bin/ishlib-install must pass shellcheck."""
    run_check_call("shellcheck", "-s", "bash", str(rel_path("bin/ishlib-install")))
