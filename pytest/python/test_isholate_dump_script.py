# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

#
# Tests for ``isholate dump-script``

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="isholate is Linux-only",
)

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.isholate.cli import build_parser, main as cli_main  # noqa: E402
from pyishlib.isholate.commands.dump_script import (  # noqa: E402
    DEFAULT_DUMP_SHELL,
    dump_script,
)
from pyishlib.isholate.commands.run import DEFAULT_IMAGE  # noqa: E402
from pyishlib.isholate.container import _SANDBOX_RUNTIME_VERSION  # noqa: E402
from pyishlib.isholate.dump_script_template import render_dump_script  # noqa: E402

_USER = "testuser"


def _parse(*argv):
    return build_parser().parse_args(["dump-script", *argv])


def _render(**overrides):
    kwargs = dict(
        image=DEFAULT_IMAGE,
        shell=DEFAULT_DUMP_SHELL,
        username=_USER,
        default_name="isholate-testuser-dump",
        sandbox_runtime_version="1.2.3",
    )
    kwargs.update(overrides)
    return render_dump_script(**kwargs)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_defaults():
    args = _parse()
    assert args.subcommand == "dump-script"
    assert args.image == DEFAULT_IMAGE
    assert args.shell == DEFAULT_DUMP_SHELL
    assert args.container_name is None
    assert args.project_root is None
    assert args.output is None
    assert args.force is False


def test_parser_overrides():
    args = _parse(
        "--image",
        "images:debian/12",
        "--shell",
        "/bin/bash",
        "--container-name",
        "box",
        "-o",
        "out.sh",
        "--force",
    )
    assert args.image == "images:debian/12"
    assert args.shell == "/bin/bash"
    assert args.container_name == "box"
    assert args.output == "out.sh"
    assert args.force is True


def test_parser_accepts_common_flags():
    assert _parse("-v").verbose


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def test_render_bakes_values():
    script = _render(image="images:debian/12")
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "IMAGE=images:debian/12\n" in script
    assert "SHELL_PATH=/usr/bin/zsh\n" in script
    assert f"USERNAME={_USER}\n" in script
    assert "DEFAULT_NAME=isholate-testuser-dump\n" in script
    assert "SANDBOX_RUNTIME=@anthropic-ai/sandbox-runtime@1.2.3\n" in script
    assert 'NAME="${1:-$DEFAULT_NAME}"' in script
    assert "zsh" in script.split("PACKAGES=", 1)[1].splitlines()[0]


def test_render_has_no_ishlib_dependency():
    script = _render()
    for needle in ("ishlib", "ishfiles", "pyishlib", "/run/isholate"):
        assert needle not in script


def test_render_quotes_unsafe_values():
    evil = "a b'; rm -rf / #"
    script = _render(username=evil)
    assert f"USERNAME={shlex.quote(evil)}\n" in script


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_render_is_valid_bash(tmp_path):
    path = tmp_path / "s.sh"
    path.write_text(_render(username="o'brien"))
    subprocess.run(["bash", "-n", str(path)], check=True)


@pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck not available"
)
def test_render_passes_shellcheck(tmp_path):
    path = tmp_path / "s.sh"
    path.write_text(_render())
    subprocess.run(["shellcheck", str(path)], check=True)


# ---------------------------------------------------------------------------
# Rendered script behaviour against a fake incus
# ---------------------------------------------------------------------------

_FAKE_INCUS = """#!/usr/bin/env bash
echo "incus $*" >> "$LOG"
case "$1" in
  info) [ -n "${EXISTS:-}" ] && exit 0 || exit 1;;
  list) echo "${STATE:-STOPPED}";;
  exec)
    if [[ "$*" == *"id -u"* ]]; then echo 1000; exit 0; fi
    if [[ -n "${FAIL_NPM:-}" && "$*" == *"npm install"* ]]; then exit 7; fi;;
esac
exit 0
"""


def _run_with_fake_incus(tmp_path, env_extra, *script_args):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "incus"
    fake.write_text(_FAKE_INCUS)
    fake.chmod(0o755)
    script = tmp_path / "s.sh"
    script.write_text(_render())
    log = tmp_path / "incus.log"
    env = os.environ.copy()
    env.update(PATH=f"{bindir}:{env['PATH']}", LOG=str(log), **env_extra)
    proc = subprocess.run(
        ["bash", str(script), *script_args], env=env, capture_output=True, text=True
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_creates_missing_container_then_enters(tmp_path):
    proc, calls = _run_with_fake_incus(tmp_path, {}, "mybox")
    assert proc.returncode == 0, proc.stderr
    assert calls[0] == "incus info mybox"
    assert (
        "incus init images:ubuntu/24.04 mybox --config security.nesting=true" in calls
    )
    assert "incus exec mybox -- useradd -m -s /usr/bin/zsh testuser" in calls
    assert any("npm install -g" in c for c in calls)
    assert calls[-1].startswith("incus exec mybox --user 1000 --cwd /home/testuser")
    assert calls[-1].endswith("-- /usr/bin/zsh -l")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_uses_default_name_without_arg(tmp_path):
    _proc, calls = _run_with_fake_incus(tmp_path, {"EXISTS": "1", "STATE": "RUNNING"})
    assert calls[0] == "incus info isholate-testuser-dump"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_reuses_existing_container(tmp_path):
    proc, calls = _run_with_fake_incus(tmp_path, {"EXISTS": "1"}, "mybox")
    assert proc.returncode == 0, proc.stderr
    assert not any(c.startswith("incus init") for c in calls)
    assert "incus start mybox" in calls
    assert calls[-1].endswith("-- /usr/bin/zsh -l")


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_does_not_restart_running_container(tmp_path):
    _proc, calls = _run_with_fake_incus(
        tmp_path, {"EXISTS": "1", "STATE": "RUNNING"}, "mybox"
    )
    assert "incus start mybox" not in calls


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_deletes_container_on_provision_failure(tmp_path):
    proc, calls = _run_with_fake_incus(tmp_path, {"FAIL_NPM": "1"}, "mybox")
    assert proc.returncode != 0
    assert calls[-1] == "incus delete --force mybox"
    assert not any(c.endswith("-l") for c in calls)


# ---------------------------------------------------------------------------
# Command implementation / dispatch
# ---------------------------------------------------------------------------


def test_dump_script_stdout_uses_project_image(tmp_path, capsys):
    cfg_dir = tmp_path / ".ishlib" / "isholate"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text('image = "images:fedora/40"\n')
    rc = dump_script(_parse(), _USER, tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "IMAGE=images:fedora/40\n" in out
    assert "DEFAULT_NAME=isholate-testuser-dump\n" in out
    assert f"sandbox-runtime@{_SANDBOX_RUNTIME_VERSION}" in out


def test_dump_script_cli_image_beats_project_config(tmp_path, capsys):
    cfg_dir = tmp_path / ".ishlib" / "isholate"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text('image = "images:fedora/40"\n')
    dump_script(_parse("--image", "images:debian/12"), _USER, tmp_path)
    assert "IMAGE=images:debian/12\n" in capsys.readouterr().out


def test_dump_script_container_name_flag(tmp_path, capsys):
    dump_script(_parse("--container-name", "box"), _USER, tmp_path)
    assert "DEFAULT_NAME=box\n" in capsys.readouterr().out


def test_dump_script_bad_project_root(tmp_path):
    rc = dump_script(_parse("--project-root", str(tmp_path / "nope")), _USER, tmp_path)
    assert rc == 2


def test_dump_script_writes_executable_file(tmp_path):
    out = tmp_path / "setup.sh"
    rc = dump_script(_parse("-o", str(out)), _USER, tmp_path)
    assert rc == 0
    assert out.read_text().startswith("#!/usr/bin/env bash\n")
    assert os.access(out, os.X_OK)
    assert "# Usage: setup.sh [CONTAINER_NAME]" in out.read_text()


def test_dump_script_refuses_overwrite_without_force(tmp_path):
    out = tmp_path / "setup.sh"
    out.write_text("keep")
    assert dump_script(_parse("-o", str(out)), _USER, tmp_path) == 1
    assert out.read_text() == "keep"
    assert dump_script(_parse("-o", str(out), "--force"), _USER, tmp_path) == 0
    assert out.read_text().startswith("#!/usr/bin/env bash\n")


def test_cli_dispatch_skips_incus_preflight(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with patch("pyishlib.isholate.cli.get_backend") as backend:
        with patch("pyishlib.isholate.commands.dump_script.dump_script") as impl:
            impl.return_value = 0
            rc = cli_main(["dump-script", "--container-name", "box"])
    assert rc == 0
    backend.assert_not_called()
    impl.assert_called_once()
    args, username, cwd = impl.call_args.args
    assert args.container_name == "box"
    assert cwd == Path(tmp_path)
