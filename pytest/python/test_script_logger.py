#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for ishfiles.script_logger."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.script_logger import (
    ScriptLogger,
    _prune_logs,
    inject_prelude,
    BASH_PRELUDE,
)


def _make_cfg(tmp_dir, quiet=False, verbose=False):
    """Build a minimal config-like namespace pointing at *tmp_dir*."""
    return SimpleNamespace(
        dry_run=False,
        quiet=quiet,
        verbose=verbose,
        get_opt=lambda name, default=None: str(tmp_dir) if name == "target" else default,
    )


class TestInjectPrelude(unittest.TestCase):
    """inject_prelude() inserts BASH_PRELUDE in the right place."""

    def test_with_shebang(self):
        text = "#!/bin/bash\necho hello\n"
        result = inject_prelude(text)
        assert result.startswith("#!/bin/bash\n")
        assert BASH_PRELUDE in result
        assert "echo hello" in result
        # Prelude comes before the script body
        idx_prelude = result.index(BASH_PRELUDE)
        idx_body = result.index("echo hello")
        assert idx_prelude < idx_body

    def test_without_shebang(self):
        text = "echo hello\n"
        result = inject_prelude(text)
        assert result.startswith(BASH_PRELUDE)
        assert "echo hello" in result

    def test_shebang_preserved(self):
        text = "#!/usr/bin/env zsh\necho hi\n"
        result = inject_prelude(text)
        assert result.startswith("#!/usr/bin/env zsh\n")


class TestScriptLoggerLifecycle(unittest.TestCase):
    """ScriptLogger can be used as a context manager."""

    def test_context_manager_creates_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                assert slog.log_path is not None
                assert slog.log_path.is_file()

    def test_log_path_timestamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                assert slog.log_path.name.startswith("run-")
                assert slog.log_path.suffix == ".log"

    def test_env_contains_fifo(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                env = slog.env()
                assert "ISHLIB_LOG_OUT" in env
                fifo_path = Path(env["ISHLIB_LOG_OUT"])
                assert fifo_path.exists()

    def test_bash_prelude_static(self):
        assert ScriptLogger.bash_prelude() is BASH_PRELUDE

    def test_initial_counts_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                counts = slog.counts
                assert all(v == 0 for v in counts.values())

    def test_not_aborted_initially(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                assert not slog.aborted

    def test_override_log_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "custom_logs"
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg, log_dir=log_dir) as slog:
                assert slog.log_path is not None
                assert slog.log_path.parent == log_dir

    def test_summary_line_no_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                assert slog.summary_line() == "no messages"


class TestScriptLoggerMessages(unittest.TestCase):
    """Messages dispatched via log_message() update counts."""

    def _counts_after_messages(self, messages):
        """Helper: send *messages* via log_message, return counts."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                for level, msg in messages:
                    slog.log_message(level, msg)
                # Give the reader thread a moment to process.
                # (log_message dispatches directly, but counts update under lock)
                return dict(slog.counts)

    def test_info_increments_count(self):
        counts = self._counts_after_messages([("info", "hello")])
        assert counts["info"] == 1

    def test_warn_increments_count(self):
        counts = self._counts_after_messages([("warn", "watch out")])
        assert counts["warn"] == 1

    def test_error_increments_count(self):
        counts = self._counts_after_messages([("error", "something broke")])
        assert counts["error"] == 1

    def test_fatal_sets_aborted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_message("fatal", "boom")
                assert slog.aborted

    def test_summary_line_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_message("warn", "a")
                slog.log_message("error", "b")
                summary = slog.summary_line()
                assert "warn" in summary
                assert "error" in summary

    def test_invalid_level_ignored(self):
        counts = self._counts_after_messages([("bogus", "ignored")])
        assert all(v == 0 for v in counts.values())

    def test_log_file_contains_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_message("info", "hello world")
                log_path = slog.log_path
            content = log_path.read_text(encoding="utf-8")
            assert "hello world" in content

    def test_log_file_contains_level_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_message("error", "oh no")
                log_path = slog.log_path
            content = log_path.read_text(encoding="utf-8")
            assert "[ERROR]" in content


@unittest.skipIf(sys.platform == "win32", "bash not available on Windows")
class TestScriptLoggerFifo(unittest.TestCase):
    """The FIFO-based message path works with a real bash subprocess."""

    def _run_bash_with_logger(self, cfg, script_body):
        """Run a small bash snippet that writes to ISHLIB_LOG_OUT."""
        import subprocess

        with ScriptLogger(cfg) as slog:
            env = {**os.environ, **slog.env()}
            subprocess.run(
                ["bash", "-c", script_body],
                env=env,
                check=False,
            )
            # Give reader thread time to process before exit
            time.sleep(0.15)
            return slog

    def test_fifo_info_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            slog = self._run_bash_with_logger(
                cfg,
                'printf "info\\thello from bash\\n" >> "$ISHLIB_LOG_OUT"',
            )
            assert slog.counts["info"] == 1

    def test_fifo_warn_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            slog = self._run_bash_with_logger(
                cfg,
                'printf "warn\\twatch out\\n" >> "$ISHLIB_LOG_OUT"',
            )
            assert slog.counts["warn"] == 1

    def test_fifo_fatal_sets_aborted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            slog = self._run_bash_with_logger(
                cfg,
                'printf "fatal\\tdead\\n" >> "$ISHLIB_LOG_OUT"',
            )
            assert slog.aborted

    def test_fifo_message_appears_in_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                import subprocess

                env = {**os.environ, **slog.env()}
                subprocess.run(
                    [
                        "bash",
                        "-c",
                        'printf "error\\ttest error\\n" >> "$ISHLIB_LOG_OUT"',
                    ],
                    env=env,
                    check=False,
                )
                time.sleep(0.15)
                log_path = slog.log_path
            content = log_path.read_text(encoding="utf-8")
            assert "test error" in content


@unittest.skipIf(sys.platform != "win32", "PowerShell sink tests are Windows-only")
class TestScriptLoggerWindowsSink(unittest.TestCase):
    """The polled-file sink works with a real PowerShell subprocess."""

    def _run_ps_with_logger(self, cfg, ps_body):
        import subprocess

        with ScriptLogger(cfg) as slog:
            env = {**os.environ, **slog.env()}
            subprocess.run(
                ["pwsh", "-NoProfile", "-Command", ps_body],
                env=env,
                check=False,
            )
            time.sleep(0.2)
            return slog

    def test_sink_info_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            slog = self._run_ps_with_logger(
                cfg,
                'Add-Content -Path $env:ISHLIB_LOG_OUT -Value "info`thello from pwsh"',
            )
            assert slog.counts["info"] == 1

    def test_sink_warn_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            slog = self._run_ps_with_logger(
                cfg,
                'Add-Content -Path $env:ISHLIB_LOG_OUT -Value "warn`twatch out"',
            )
            assert slog.counts["warn"] == 1

    def test_sink_fatal_sets_aborted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            slog = self._run_ps_with_logger(
                cfg,
                'Add-Content -Path $env:ISHLIB_LOG_OUT -Value "fatal`tdead"',
            )
            assert slog.aborted

    def test_sink_message_appears_in_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                import subprocess

                env = {**os.environ, **slog.env()}
                subprocess.run(
                    ["pwsh", "-NoProfile", "-Command",
                     'Add-Content -Path $env:ISHLIB_LOG_OUT -Value ("error`t" + "test error")'],
                    env=env,
                    check=False,
                )
                time.sleep(0.2)
                log_path = slog.log_path
            content = log_path.read_text(encoding="utf-8")
            assert "test error" in content


class TestScriptLoggerOutput(unittest.TestCase):
    """log_script_output() writes captured output to the log file."""

    def test_output_appears_in_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_script_output("test.sh", "line one\nline two\n")
                log_path = slog.log_path
            content = log_path.read_text(encoding="utf-8")
            assert "line one" in content
            assert "line two" in content

    def test_output_label_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_script_output("myscript.sh", "something")
                log_path = slog.log_path
            content = log_path.read_text(encoding="utf-8")
            assert "myscript.sh" in content

    def test_empty_output_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            with ScriptLogger(cfg) as slog:
                slog.log_script_output("test.sh", "")
                log_path = slog.log_path
            # File exists but has no OUTPUT section
            content = log_path.read_text(encoding="utf-8")
            assert "OUTPUT" not in content


class TestPruneLogs(unittest.TestCase):
    """_prune_logs() keeps only the newest _MAX_LOGS files."""

    def test_prune_keeps_ten(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            for i in range(15):
                lf = log_dir / f"run-2026010{i:02d}-120000-{i}.log"
                lf.write_text("x", encoding="utf-8")
                # Stagger mtimes so sort is deterministic
                os.utime(lf, (i, i))
            _prune_logs(log_dir)
            remaining = list(log_dir.glob("run-*.log"))
            assert len(remaining) == 10

    def test_prune_deletes_oldest(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            for i in range(12):
                lf = log_dir / f"run-2026010{i:02d}-120000-{i}.log"
                lf.write_text(f"content {i}", encoding="utf-8")
                os.utime(lf, (i, i))
            _prune_logs(log_dir)
            remaining = sorted(
                log_dir.glob("run-*.log"), key=lambda p: p.stat().st_mtime
            )
            # The two oldest (mtime 0, 1) should be gone
            contents = [p.read_text() for p in remaining]
            assert "content 0" not in contents
            assert "content 1" not in contents

    def test_prune_noop_under_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            for i in range(5):
                lf = log_dir / f"run-{i}.log"
                lf.write_text("x", encoding="utf-8")
            _prune_logs(log_dir)
            assert len(list(log_dir.glob("run-*.log"))) == 5


if __name__ == "__main__":
    unittest.main()
