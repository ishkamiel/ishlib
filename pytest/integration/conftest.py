# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Pytest collector for shell-script-driven integration scenarios.

Each ``scenarios/*.sh`` file is collected as a single pytest test item.
The collector spawns the script under ``bash`` inside a ``bubblewrap``
mount namespace where the host filesystem is read-only and only the
per-scenario sandbox directory is writable.  This means a stray
hardcoded path inside a scenario (e.g. ``$HOME/.bashrc``) hits ``EROFS``
rather than corrupting the developer's real home directory.

When ``bwrap`` is not on ``$PATH`` (e.g. on macOS or a stripped-down
container), each scenario is reported as ``skipped`` with a clear
message; we deliberately refuse to fall back to a non-isolated mode.

Scripts source ``lib/ishlib_test.sh`` (path exposed via ``$ISHLIB_LIB``)
for assertions and sandbox helpers.  See that file for the helper API.

The collector also exposes ``--keep-sandbox-on-failure``.  When set, the
sandbox of any failing scenario is copied to
``./_failed_scenarios/<name>-<timestamp>/`` and the destination path is
included in the failure report for post-mortem inspection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Iterator

import pytest


_INTEGRATION_DIR = Path(__file__).parent
_REPO_ROOT = _INTEGRATION_DIR.parent.parent
_SCENARIOS_DIR = _INTEGRATION_DIR / "scenarios"
_LIB_SCRIPT = _INTEGRATION_DIR / "lib" / "ishlib_test.sh"
_FAILED_DIR = _REPO_ROOT / "_failed_scenarios"
_TIMEOUT_SECONDS = 120

# Resolved at import time so xdist workers don't repeat the lookup per item.
_BWRAP = shutil.which("bwrap")

# Hermetic git identity for scenarios that run `git commit`.  The session
# autouse fixture in pytest/conftest.py sets these on os.environ, but
# under xdist a worker that only receives custom pytest.Item subclasses
# (no Function items) never triggers the fixture, so we pin the same
# values here explicitly.
_GIT_HERMETIC_ENV: dict[str, str] = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}

# Git dir-override variables set by pre-commit (and git hooks in general)
# that must be stripped before spawning scenarios.  If left in the
# environment, `git init` inside the sandbox tries to re-init the
# *parent* repo's git dir (which is read-only inside bwrap), producing
# "could not lock config file … Read-only file system" failures.
# This mirrors what CommandRunner.git() does in production code paths.
_GIT_DIR_VARS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--keep-sandbox-on-failure",
        action="store_true",
        default=False,
        help=(
            "Copy a failing scenario's sandbox to ./_failed_scenarios/ for "
            "post-mortem inspection."
        ),
    )


def pytest_collect_file(parent: pytest.Collector, file_path: Path):
    if file_path.suffix == ".sh" and file_path.parent == _SCENARIOS_DIR:
        return ScenarioFile.from_parent(parent, path=file_path)
    return None


class ScenarioFile(pytest.File):
    def collect(self) -> Iterator["ScenarioItem"]:
        yield ScenarioItem.from_parent(self, name=self.path.name)


class ScenarioFailed(Exception):
    """Raised by ScenarioItem.runtest when the scenario exits non-zero or times out."""

    def __init__(
        self,
        *,
        scenario: Path,
        sandbox: Path,
        returncode: int | None,
        stdout: str,
        stderr: str,
        elapsed: float,
        kept_sandbox: Path | None,
        timed_out: bool,
    ) -> None:
        self.scenario = scenario
        self.sandbox = sandbox
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.elapsed = elapsed
        self.kept_sandbox = kept_sandbox
        self.timed_out = timed_out
        super().__init__(scenario.name)


class ScenarioItem(pytest.Item):
    def runtest(self) -> None:
        if _BWRAP is None:
            pytest.skip(
                "bubblewrap (bwrap) not found on PATH; install it to run "
                "integration scenarios (e.g. `apt-get install bubblewrap`)."
            )

        scenario = self.path
        sandbox = Path(tempfile.mkdtemp(prefix=f"scenario-{scenario.stem}-"))
        # Pre-create the directories that the namespace's HOME and TMPDIR
        # will point at; bwrap binds the sandbox writable but the inner
        # process expects these to already exist.
        (sandbox / "home").mkdir(parents=True, exist_ok=True)
        (sandbox / "tmp").mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(_GIT_HERMETIC_ENV)
        for _var in _GIT_DIR_VARS:
            env.pop(_var, None)
        env["ISHLIB_REPO"] = str(_REPO_ROOT)
        env["ISHLIB_SRC"] = str(_REPO_ROOT / "src")
        env["ISHLIB_LIB"] = str(_LIB_SCRIPT)
        env["ISHLIB_SANDBOX"] = str(sandbox)
        env["ISHFILES"] = "python3 -m pyishlib.ishfiles"
        env["ISHPROJECT"] = "python3 -m pyishlib.ishproject"
        env["ISHLIB_SH"] = str(_REPO_ROOT / "ishlib.sh")
        # HOME and TMPDIR redirect well-behaved code that consults them
        # (Python tempfile, mktemp, etc.) into the writable sandbox; the
        # rest of the host filesystem is read-only inside the namespace
        # so accidental writes elsewhere fail with EROFS.
        env["HOME"] = str(sandbox / "home")
        env["TMPDIR"] = str(sandbox / "tmp")
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{_REPO_ROOT / 'src'}{os.pathsep}{existing_pp}"
            if existing_pp
            else str(_REPO_ROOT / "src")
        )

        bwrap_argv = [
            _BWRAP,
            "--die-with-parent",
            # --unshare-user is required on Ubuntu 24.04 / GitHub runners
            # where AppArmor's unprivileged_userns profile blocks bwrap
            # from setting up a uid map without first opting into a user
            # namespace.  Without this flag, every scenario fails with
            # "bwrap: setting up uid map: Permission denied".
            "--unshare-user",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            # ro-bind the entire host fs first, then override the
            # sandbox path (and a couple of pseudofs mounts) so they
            # are writable.
            "--ro-bind",
            "/",
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--bind",
            str(sandbox),
            str(sandbox),
            "--chdir",
            str(sandbox),
        ]

        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                bwrap_argv + ["bash", str(scenario)],
                env=env,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            returncode: int | None = proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = (
                exc.stdout.decode()
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            stderr = (
                exc.stderr.decode()
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )
            returncode = None
            timed_out = True
        elapsed = time.monotonic() - start

        if returncode == 0 and not timed_out:
            shutil.rmtree(sandbox, ignore_errors=True)
            return

        kept = None
        if self.config.getoption("--keep-sandbox-on-failure"):
            kept = self._preserve_sandbox(sandbox)
        # Always remove the original tmpdir so failing scenarios do not
        # accumulate under TMPDIR over time.  The preserved copy (if any)
        # is reported in repr_failure for post-mortem inspection.
        shutil.rmtree(sandbox, ignore_errors=True)

        raise ScenarioFailed(
            scenario=scenario,
            sandbox=sandbox,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            elapsed=elapsed,
            kept_sandbox=kept,
            timed_out=timed_out,
        )

    def repr_failure(self, excinfo, style=None):  # type: ignore[override]
        if isinstance(excinfo.value, ScenarioFailed):
            f = excinfo.value
            head = (
                f"SCENARIO FAILED: {f.scenario.name} "
                f"({'TIMEOUT' if f.timed_out else f'exit {f.returncode}'}, "
                f"{f.elapsed:.2f}s)"
            )
            lines = [
                head,
                f"scenario: {f.scenario}",
            ]
            if f.kept_sandbox is not None:
                lines.append(f"preserved: {f.kept_sandbox}")
            else:
                lines.append(
                    "sandbox:  removed (re-run with --keep-sandbox-on-failure to preserve)"
                )
            lines.append("--- stdout ---")
            lines.append(f.stdout.rstrip() or "(empty)")
            lines.append("--- stderr ---")
            lines.append(f.stderr.rstrip() or "(empty)")
            return "\n".join(lines)
        return super().repr_failure(excinfo, style)

    def reportinfo(self):  # type: ignore[override]
        return self.path, 0, f"scenario: {self.path.name}"

    @staticmethod
    def _preserve_sandbox(sandbox: Path) -> Path | None:
        if not sandbox.exists():
            return None
        _FAILED_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = _FAILED_DIR / f"{sandbox.name}-{stamp}"
        try:
            shutil.copytree(sandbox, dest, symlinks=True)
        except OSError:
            return None
        return dest
