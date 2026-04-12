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
from datetime import datetime
from pathlib import Path
from typing import Dict, IO, Optional

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


def inject_prelude(text: str) -> str:
    """Insert :data:`BASH_PRELUDE` after the shebang line (if any).

    If the first line is a shebang (``#!``), the prelude is inserted after
    it.  Otherwise it is prepended to the text.

    Args:
        text: The preprocessed script text.

    Returns:
        Script text with the prelude injected.
    """
    lines = text.split("\n", 1)
    if lines and lines[0].startswith("#!"):
        return lines[0] + "\n" + BASH_PRELUDE + (lines[1] if len(lines) > 1 else "")
    return BASH_PRELUDE + text


class ScriptLogger:
    """Context manager that owns a per-run log file and structured FIFO.

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
        self._fifo_path: Optional[Path] = None
        self._fifo_fd: Optional[int] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event: threading.Event = threading.Event()
        self._counts: Dict[str, int] = {k: 0 for k in _LEVELS}
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

        # Create FIFO in a temporary directory.
        self._tmp_dir = tempfile.TemporaryDirectory(prefix="ishfiles_log_")
        self._fifo_path = Path(self._tmp_dir.name) / "log.fifo"
        os.mkfifo(self._fifo_path)

        # Open with O_RDWR | O_NONBLOCK so:
        # - No blocking on open (no need for a writer to be present first).
        # - Python acts as both reader and writer, preventing premature EOF.
        # - Reads return EAGAIN when no data is available.
        self._fifo_fd = os.open(str(self._fifo_path), os.O_RDWR | os.O_NONBLOCK)

        # Start background reader thread.
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="ish-log-reader"
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

        # Close the FIFO FD.
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

        # Clean up the temp dir (removes the FIFO).
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

    # -- public interface ------------------------------------------------------

    def env(self) -> Dict[str, str]:
        """Environment variables to set in script subprocesses.

        Returns a dict containing:

        - ``ISHLIB_LOG_OUT``: path to the FIFO that ``ish_info``/``ish_warn``/
          ``ish_error``/``ish_fatal`` write structured messages to.
        - ``ISHLIB_SH``: path to the compiled ``ishlib.sh`` shell library, so
          the :data:`BASH_PRELUDE` can source it.  Omitted when the file does
          not exist (e.g. in a clean checkout before ``make ishlib.sh``).
        """
        result: Dict[str, str] = {"ISHLIB_LOG_OUT": str(self._fifo_path)}
        if _ISHLIB_SH.is_file():
            result["ISHLIB_SH"] = str(_ISHLIB_SH)
        return result

    @staticmethod
    def bash_prelude() -> str:
        """Return the bash snippet that defines ish_info/warn/error/fatal."""
        return BASH_PRELUDE

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

    def _dispatch(self, line: str) -> None:
        """Parse and handle one structured log line (``"level\\tmessage"``)."""
        if "\t" not in line:
            return
        level, _, message = line.partition("\t")
        level = level.strip().lower()
        if level not in _LEVELS:
            return

        ts = datetime.now().strftime(_LOG_TIMESTAMP_FMT)
        formatted = f"[{ts}] [{level.upper():5s}] {message}\n"

        with self._lock:
            self._counts[level] = self._counts.get(level, 0) + 1
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
