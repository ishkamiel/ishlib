#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Per-run structured logging for ishfiles script execution.

Every ishscript automatically receives the full ``ishlib.sh`` shell library
(sourced via ``ISHLIB_SH``) which provides ``ish_info``, ``ish_warn``,
``ish_error``, and ``ish_fatal``.  When ``ISHLIB_LOG_OUT`` is set in the
environment those functions write structured ``level<TAB>message`` lines to
that path (a named FIFO owned by :class:`ScriptLogger`) instead of stderr.

A background thread reads those lines and writes them to a timestamped log
file under ``<target>/.local/state/ishfiles/logs/``.  All script
stdout/stderr is also captured and appended to the same log file.
``ish_fatal`` sets an abort flag that prevents subsequent scripts from
running.

Public API
----------
- :class:`ScriptLogger` -- context manager owning one run log.
- :func:`inject_prelude`  -- add the bash helper snippet after the shebang.

Prelude injected into every shell script
-----------------------------------------

.. code-block:: bash

    # Source ishlib.sh for ish_info/warn/error/fatal (which honour ISHLIB_LOG_OUT).
    if [ -n "${ISHLIB_SH:-}" ] && [ -f "${ISHLIB_SH}" ]; then
      . "${ISHLIB_SH}"
    else
      # Minimal fallback when ishlib.sh is unavailable.
      ish_info()  { printf 'info\\t%s\\n'  "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_warn()  { printf 'warn\\t%s\\n'  "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_error() { printf 'error\\t%s\\n' "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_fatal() { printf 'fatal\\t%s\\n' "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; exit 1; }
    fi

``ISHLIB_LOG_OUT`` points to the FIFO.  Append-mode writes do not block
because the Python side keeps the FIFO open with ``O_RDWR`` for the entire
run.
"""

from __future__ import annotations

import errno
import logging
import os
import select
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, IO, List, Optional, Tuple

# FIFOs are a POSIX-only feature.  On Windows we fall back to a plain file
# that scripts append to and the reader thread polls.
_USE_FIFO: bool = hasattr(os, "mkfifo")

log = logging.getLogger(__name__)

# Number of log files to keep per log directory.
_MAX_LOGS: int = 10

# Relative path (from target home) for the log directory.
_LOG_DIR_SUFFIX: str = ".local/state/ishfiles/logs"

# Format written to the log file for structured messages.
_LOG_TIMESTAMP_FMT: str = "%H:%M:%S"

# Path to the compiled ishlib.sh shell library, resolved relative to this file.
# Layout: script_logger.py → ishfiles/ → pyishlib/ → src/ → ishlib root
_ISHLIB_SH: Path = Path(__file__).resolve().parent.parent.parent.parent / "ishlib.sh"

# Bash snippet injected after the shebang of every shell script.
# Sources ishlib.sh (which honours ISHLIB_LOG_OUT for ish_info/warn/error/fatal).
# Falls back to minimal inline definitions when ishlib.sh is unavailable.
BASH_PRELUDE: str = """\
# -- ishfiles (auto-injected) --
if [ -n "${ISHLIB_SH:-}" ] && [ -f "${ISHLIB_SH}" ]; then
  . "${ISHLIB_SH}"
else
  ish_info()  { printf 'info\\t%s\\n'  "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_warn()  { printf 'warn\\t%s\\n'  "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_error() { printf 'error\\t%s\\n' "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_fatal() { printf 'fatal\\t%s\\n' "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; exit 1; }
fi
# -- end ishfiles --
"""

_LEVELS = ("info", "warn", "error", "fatal")

# PowerShell equivalent of BASH_PRELUDE.  Appends structured ``level<TAB>msg``
# lines to ``$env:ISHLIB_LOG_OUT`` using ``Add-Content`` (thread-safe append).
PS_PRELUDE: str = """\
# -- ishfiles (auto-injected) --
function ish_info  { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "info`t$m" } }
function ish_warn  { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "warn`t$m" } }
function ish_error { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "error`t$m" } }
function ish_fatal { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "fatal`t$m" }; exit 1 }
# -- end ishfiles --
"""


def inject_prelude(text: str, ext: str = "") -> str:
    """Insert the appropriate log-helper prelude into a script.

    For PowerShell scripts (``ext=".ps1"``) :data:`PS_PRELUDE` is prepended.
    For all other scripts :data:`BASH_PRELUDE` is inserted after the shebang
    line (if any), or prepended when there is no shebang.

    Args:
        text: The preprocessed script text.
        ext:  File extension of the original script (e.g. ``".ps1"``).

    Returns:
        Script text with the prelude injected.
    """
    if ext == ".ps1":
        return PS_PRELUDE + text
    lines = text.split("\n", 1)
    if lines and lines[0].startswith("#!"):
        return lines[0] + "\n" + BASH_PRELUDE + (lines[1] if len(lines) > 1 else "")
    return BASH_PRELUDE + text


class ScriptLogger:
    """Context manager that owns a per-run log file and structured log sink.

    On POSIX systems the sink is a named FIFO; on Windows a plain file that
    the reader thread polls.  Both appear to scripts as ``ISHLIB_LOG_OUT``.

    Usage::

        with ScriptLogger(cfg) as slog:
            env = slog.env()               # dict of env vars for subprocesses
            prelude = slog.bash_prelude()  # bash snippet to inject

    Args:
        cfg: :class:`~pyishlib.ish_config.IshConfig` providing ``target``
             (and ``quiet`` / ``verbose`` for mirror-to-terminal control).
        log_dir: Override log directory (for testing).
    """

    def __init__(self, cfg, *, log_dir: Optional[Path] = None) -> None:
        self._cfg = cfg
        self._log_dir_override = log_dir

        self._log_path: Optional[Path] = None
        self._sink_path: Optional[Path] = None  # FIFO on POSIX, plain file on Windows
        self._fifo_fd: Optional[int] = None  # only used on POSIX
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self._counts: Dict[str, int] = {k: 0 for k in _LEVELS}
        self._current_script: Optional[str] = None
        self._script_counts: Dict[str, Dict[str, int]] = {}
        self._aborted: bool = False
        self._tmp_dir: Optional[tempfile.TemporaryDirectory] = None
        self._log_fh: Optional[IO[str]] = None
        self._lock: threading.Lock = threading.Lock()

    # -- context manager -------------------------------------------------------

    def __enter__(self) -> "ScriptLogger":
        log_dir = self._log_dir_override or self._default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        # Open timestamped log file.
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._log_path = log_dir / f"run-{ts}-{os.getpid()}.log"
        self._log_fh = open(  # noqa: WPS515
            self._log_path, "w", encoding="utf-8"
        )

        # Create the log sink (FIFO on POSIX, plain file on Windows) in a
        # temporary directory so it is cleaned up by __exit__.
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="ishfiles_log_")

        if _USE_FIFO:
            self._sink_path = Path(self._tmp_dir.name) / "log.fifo"
            os.mkfifo(self._sink_path)
            # Open with O_RDWR | O_NONBLOCK so:
            # - No blocking on open (no need for a writer to be present first).
            # - Python acts as both reader and writer, preventing premature EOF.
            # - Reads return EAGAIN when no data is available.
            self._fifo_fd = os.open(str(self._sink_path), os.O_RDWR | os.O_NONBLOCK)
        else:
            # Windows: plain append-mode file.  Scripts write with Add-Content;
            # the reader thread polls for new bytes.
            self._sink_path = Path(self._tmp_dir.name) / "log.sink"
            self._sink_path.write_bytes(b"")

        # Start background reader thread.
        self._stop_event.clear()
        reader_target = self._reader_loop if _USE_FIFO else self._reader_loop_polled
        self._reader_thread = threading.Thread(
            target=reader_target, daemon=True, name="ish-log-reader"
        )
        self._reader_thread.start()

        # Prune old logs (keep the newest _MAX_LOGS files).
        _prune_logs(log_dir)

        return self

    def __exit__(self, *_) -> None:
        # Signal reader thread to stop and wait for it.
        self._stop_event.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)

        # Close the FIFO FD (POSIX only).
        if self._fifo_fd is not None:
            try:
                os.close(self._fifo_fd)
            except OSError:
                pass
            self._fifo_fd = None

        # Close the log file.
        if self._log_fh is not None:
            self._log_fh.close()
            self._log_fh = None

        # Clean up the temp dir (removes the sink file/FIFO).
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

    # -- public interface ------------------------------------------------------

    def env(self) -> Dict[str, str]:
        """Environment variables to set in script subprocesses.

        Returns a dict containing:

        - ``ISHLIB_LOG_OUT``: path to the log sink (a FIFO on POSIX, a plain
          file on Windows) that ``ish_info``/``ish_warn``/``ish_error``/
          ``ish_fatal`` write structured messages to.
        - ``ISHLIB_SH``: path to the compiled ``ishlib.sh`` shell library, so
          the :data:`BASH_PRELUDE` can source it.  Omitted when the file does
          not exist (e.g. in a clean checkout before ``make ishlib.sh``).
        """
        result: Dict[str, str] = {"ISHLIB_LOG_OUT": str(self._sink_path)}
        if _ISHLIB_SH.is_file():
            result["ISHLIB_SH"] = str(_ISHLIB_SH)
        return result

    @staticmethod
    def bash_prelude() -> str:
        """Return the bash snippet that defines ish_info/warn/error/fatal."""
        return BASH_PRELUDE

    @staticmethod
    def powershell_prelude() -> str:
        """Return the PowerShell snippet that defines ish_info/warn/error/fatal."""
        return PS_PRELUDE

    @property
    def aborted(self) -> bool:
        """True after ``ish_fatal`` was called by any script in this run."""
        return self._aborted

    @property
    def log_path(self) -> Optional[Path]:
        """Path to the current run log file (available after ``__enter__``)."""
        return self._log_path

    @property
    def counts(self) -> Dict[str, int]:
        """Snapshot of message counts per level."""
        with self._lock:
            return dict(self._counts)

    def set_current_script(self, name: str) -> None:
        """Set the currently-running script for per-script message attribution.

        Call this just before executing each script so that ``ish_warn`` /
        ``ish_error`` messages are associated with the right script name.

        Args:
            name: Script filename (e.g. ``"50_setup_fzf.sh"``).
        """
        with self._lock:
            self._current_script = name
            if name not in self._script_counts:
                self._script_counts[name] = {k: 0 for k in _LEVELS}

    def script_issues(self) -> List[Tuple[str, Dict[str, int]]]:
        """Return per-script issue counts for scripts that had warnings or errors.

        Returns a list of ``(script_name, counts_dict)`` for every script
        where at least one ``warn``, ``error``, or ``fatal`` message was
        logged, in execution order.
        """
        with self._lock:
            return [
                (name, dict(counts))
                for name, counts in self._script_counts.items()
                if any(counts.get(lvl, 0) > 0 for lvl in ("warn", "error", "fatal"))
            ]

    def summary_line(self) -> str:
        """One-line summary: ``"2 warn, 1 error"`` (omits zero counts)."""
        with self._lock:
            parts = [f"{self._counts[k]} {k}" for k in _LEVELS if self._counts[k]]
        return ", ".join(parts) if parts else "no messages"

    def log_script_output(self, script_name: str, output: str) -> None:
        """Write captured stdout/stderr of a script to the log file.

        Args:
            script_name: Human-readable label (e.g. the script filename).
            output:      Combined stdout+stderr text from the script.
        """
        if not output:
            return
        with self._lock:
            if self._log_fh is None:
                return
            ts = datetime.now().strftime(_LOG_TIMESTAMP_FMT)
            self._log_fh.write(f"[{ts}] [OUTPUT] {script_name}:\n")
            for line in output.rstrip("\n").splitlines():
                self._log_fh.write(f"  {line}\n")
            self._log_fh.flush()

    def log_message(self, level: str, message: str) -> None:
        """Write a structured message directly (bypassing the FIFO).

        Useful for the Python side to log events in the same log file.

        Args:
            level:   One of ``"info"``, ``"warn"``, ``"error"``, ``"fatal"``.
            message: The message text.
        """
        self._dispatch(f"{level}\t{message}")

    # -- internal helpers ------------------------------------------------------

    def _default_log_dir(self) -> Path:
        target = Path(self._cfg.get_opt("target") or Path.home()).expanduser().resolve()
        return target / _LOG_DIR_SUFFIX

    def _reader_loop(self) -> None:
        """Background thread: read from FIFO and dispatch structured lines."""
        buf = b""
        while not self._stop_event.is_set():
            fd = self._fifo_fd
            if fd is None:
                break
            try:
                r, _, _ = select.select([fd], [], [], 0.05)
            except (ValueError, OSError):
                break
            if not r:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._dispatch(line.decode("utf-8", errors="replace"))

    def _reader_loop_polled(self) -> None:
        """Background thread: poll a plain file and dispatch structured lines.

        Used on Windows where POSIX FIFOs are not available.  The sink file
        is opened once; the thread reads new bytes as they arrive and feeds
        them through the same dispatch path as the FIFO reader.
        """
        buf = b""
        offset = 0
        with open(self._sink_path, "rb") as fh:  # type: ignore[arg-type]
            while not self._stop_event.is_set():
                chunk = fh.read(4096)
                if not chunk:
                    time.sleep(0.05)
                    continue
                offset += len(chunk)
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._dispatch(line.decode("utf-8", errors="replace"))
        # Drain any remaining data after stop is signalled.
        if buf.strip():
            self._dispatch(buf.decode("utf-8", errors="replace"))

    def _dispatch(self, line: str) -> None:
        """Parse and handle one structured log line (``"level\\tmessage"``)."""
        if "\t" not in line:
            return
        level, _, message = line.partition("\t")
        level = level.strip().lower()
        if level not in _LEVELS:
            return

        ts = datetime.now().strftime(_LOG_TIMESTAMP_FMT)

        with self._lock:
            self._counts[level] = self._counts.get(level, 0) + 1
            if self._current_script:
                self._script_counts[self._current_script][level] = (
                    self._script_counts[self._current_script].get(level, 0) + 1
                )
                script_label = f" [{self._current_script}]"
            else:
                script_label = ""
            formatted = f"[{ts}] [{level.upper():5s}]{script_label} {message}\n"
            if self._log_fh is not None:
                self._log_fh.write(formatted)
                self._log_fh.flush()

        # Mirror to stderr based on configured verbosity.
        quiet = getattr(self._cfg, "quiet", False)
        verbose = getattr(self._cfg, "verbose", False)
        if level == "fatal":
            self._aborted = True
            sys.stderr.write(f"FATAL: {message}\n")
        elif level == "error" and not quiet:
            sys.stderr.write(f"ERROR: {message}\n")
        elif level == "warn" and not quiet:
            sys.stderr.write(f"WARNING: {message}\n")
        elif level == "info" and verbose:
            sys.stderr.write(f"INFO: {message}\n")


def _prune_logs(log_dir: Path) -> None:
    """Delete all but the :data:`_MAX_LOGS` most recent log files."""
    logs = sorted(log_dir.glob("run-*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-_MAX_LOGS]:
        try:
            old.unlink()
        except OSError:
            pass
