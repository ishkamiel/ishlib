#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Per-run structured logging for ishfiles script execution.

Every ishscript automatically receives the full ``ishlib.sh`` shell library
(sourced via ``ISHLIB_SH``) which provides ``ish_info``, ``ish_warning``,
``ish_error``, and ``ish_critical``.  When ``ISHLIB_LOG_OUT`` is set in the
environment those functions write structured ``level<TAB>message`` lines to
that path (a named FIFO owned by :class:`ScriptLogger`) instead of stderr.

A background thread reads those lines and writes them to a timestamped log
file under ``<target>/.local/state/ishfiles/logs/``.  All script
stdout/stderr is also captured and appended to the same log file.
``ish_critical`` sets an abort flag that prevents subsequent scripts from
running.

Public API
----------
- :class:`ScriptLogger` -- context manager owning one run log.
- :func:`inject_prelude`  -- add the bash helper snippet after the shebang.

Prelude injected into every shell script
-----------------------------------------

.. code-block:: bash

    # Source ishlib.sh for ish_info/warning/error/critical (which honour ISHLIB_LOG_OUT).
    if [ -n "${ISHLIB_SH:-}" ] && [ -f "${ISHLIB_SH}" ]; then
      . "${ISHLIB_SH}"
    else
      # Minimal fallback when ishlib.sh is unavailable.
      ish_debug()    { printf 'debug\\t%s\\n'    "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_info()     { printf 'info\\t%s\\n'     "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_warning()  { printf 'warning\\t%s\\n'  "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_error()    { printf 'error\\t%s\\n'    "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; }
      ish_critical() { printf 'critical\\t%s\\n' "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}"; exit 1; }
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

# Sub-loggers for script-originated messages.
# pyishlib.script.ish  — structured ish_info/warning/error/critical messages
# pyishlib.script.stdout — captured stdout lines (1> prefix)
# pyishlib.script.stderr — captured stderr lines (2> prefix)
_log_ish = logging.getLogger("pyishlib.script.ish")
_log_stdout = logging.getLogger("pyishlib.script.stdout")
_log_stderr = logging.getLogger("pyishlib.script.stderr")

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
# Sources ishlib.sh (which honours ISHLIB_LOG_OUT for ish_info/warning/error/critical).
# Falls back to minimal inline definitions when ishlib.sh is unavailable.
BASH_PRELUDE: str = """\
# -- ishfiles (auto-injected) --
if [ -n "${ISHLIB_SH:-}" ] && [ -f "${ISHLIB_SH}" ]; then
  . "${ISHLIB_SH}"
else
  ish_debug()    { printf 'debug\\t%s\\n'    "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_info()     { printf 'info\\t%s\\n'     "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_warning()  { printf 'warning\\t%s\\n'  "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_error()    { printf 'error\\t%s\\n'    "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; }
  ish_critical() { printf 'critical\\t%s\\n' "$*" >> "${ISHLIB_LOG_OUT:-/dev/stderr}" 2>/dev/null || true; exit 1; }
fi
# -- end ishfiles --
"""

_LEVELS = ("debug", "info", "warning", "error", "critical")

# PowerShell equivalent of BASH_PRELUDE.  Appends structured ``level<TAB>msg``
# lines to ``$env:ISHLIB_LOG_OUT`` using ``Add-Content`` (thread-safe append).
PS_PRELUDE: str = """\
# -- ishfiles (auto-injected) --
function ish_debug    { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "debug`t$m" } }
function ish_info     { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "info`t$m" } }
function ish_warning  { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "warning`t$m" } }
function ish_error    { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "error`t$m" } }
function ish_critical { param([string]$m) if ($env:ISHLIB_LOG_OUT) { Add-Content -Path $env:ISHLIB_LOG_OUT -Value "critical`t$m" }; exit 1 }
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
          file on Windows) that ``ish_info``/``ish_warning``/``ish_error``/
          ``ish_critical`` write structured messages to.
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
        """Return the bash snippet that defines ish_info/warning/error/critical."""
        return BASH_PRELUDE

    @staticmethod
    def powershell_prelude() -> str:
        """Return the PowerShell snippet that defines ish_info/warning/error/critical."""
        return PS_PRELUDE

    @property
    def aborted(self) -> bool:
        """True after ``ish_critical`` was called by any script in this run."""
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

        Call this just before executing each script so that ``ish_warning`` /
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
        where at least one ``warning``, ``error``, or ``critical`` message was
        logged, in execution order.
        """
        with self._lock:
            return [
                (name, dict(counts))
                for name, counts in self._script_counts.items()
                if any(
                    counts.get(lvl, 0) > 0 for lvl in ("warning", "error", "critical")
                )
            ]

    def summary_line(self) -> str:
        """One-line summary: ``"2 warn, 1 error"`` (omits zero counts)."""
        with self._lock:
            parts = [f"{self._counts[k]} {k}" for k in _LEVELS if self._counts[k]]
        return ", ".join(parts) if parts else "no messages"

    def log_stream(self, stream: str, script_name: str, line: str) -> None:
        """Route one captured stdout/stderr line through the logging system.

        Called by :mod:`~pyishlib.dotfile_script` for each line read from
        the script's stdout (``stream="stdout"``) or stderr
        (``stream="stderr"``).

        - stdout lines are emitted at DEBUG via ``pyishlib.script.stdout``.
        - stderr lines are emitted at WARNING via ``pyishlib.script.stderr``.

        Both carry ``extra={"script": script_name}`` so
        :class:`~pyishlib.ish_logging.IshLogFormatter` renders the script
        label.  They are also written to the run-log file directly so the
        file always contains the full stream regardless of the terminal
        handler's level filter.

        Args:
            stream:      ``"stdout"`` or ``"stderr"``.
            script_name: Filename of the script being run.
            line:        One decoded text line (without trailing newline).
        """
        prefix = "1>" if stream == "stdout" else "2>"
        logger = _log_stdout if stream == "stdout" else _log_stderr
        level_int = logging.DEBUG if stream == "stdout" else logging.WARNING
        logger.log(
            level_int,
            "%s %s",
            prefix,
            line,
            extra={"script": script_name},
        )
        # Always write to the run-log file (bypasses handler level filters).
        ts = datetime.now().strftime(_LOG_TIMESTAMP_FMT)
        tag = "[DD]" if stream == "stdout" else "[WW]"
        with self._lock:
            if self._log_fh is not None:
                self._log_fh.write(f"[{ts}] {tag} [{script_name}] {prefix} {line}\n")
                self._log_fh.flush()

    def log_message(self, level: str, message: str) -> None:
        """Write a structured message directly (bypassing the FIFO).

        Useful for the Python side to log events in the same log file.

        Args:
            level:   One of ``"debug"``, ``"info"``, ``"warning"``,
                     ``"error"``, ``"critical"``.
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

        Used on Windows where POSIX FIFOs are not available.  The sink file is
        re-read from scratch on every poll cycle (``Path.read_bytes()``) so the
        reader always sees the latest data written by any process.  A running
        byte offset avoids reprocessing data that has already been dispatched.

        After the stop event fires a final read captures any bytes written just
        before the signal, so no messages are lost in the race between the
        writer and the stop event.
        """
        sink_path = self._sink_path
        if sink_path is None:
            return
        buf = b""
        offset = 0
        while not self._stop_event.is_set():
            try:
                data = sink_path.read_bytes()
            except OSError:
                time.sleep(0.05)
                continue
            if len(data) > offset:
                buf += data[offset:]
                offset = len(data)
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._dispatch(line.decode("utf-8", errors="replace"))
            else:
                time.sleep(0.05)
        # Final drain: capture any bytes written just before stop was signalled.
        try:
            data = sink_path.read_bytes()
        except OSError:
            data = b""
        if len(data) > offset:
            buf += data[offset:]
        # Dispatch any remaining complete lines.
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            self._dispatch(line.decode("utf-8", errors="replace"))
        # Handle an unterminated final line (no trailing newline).
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
            script_name = self._current_script
            if script_name:
                self._script_counts[script_name][level] = (
                    self._script_counts[script_name].get(level, 0) + 1
                )
            if level == "critical":
                self._aborted = True
            script_label = f" [{script_name}]" if script_name else ""
            formatted = f"[{ts}] [{level.upper():8s}]{script_label} {message}\n"
            if self._log_fh is not None:
                self._log_fh.write(formatted)
                self._log_fh.flush()

        # Mirror to terminal via the pyishlib.script.ish logger so that
        # IshLogFormatter and handler level filters apply uniformly.
        _level_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        _log_ish.log(
            _level_map[level],
            "%s",
            message,
            extra={"script": script_name},
        )


def _prune_logs(log_dir: Path) -> None:
    """Delete all but the :data:`_MAX_LOGS` most recent log files."""
    logs = sorted(log_dir.glob("run-*.log"), key=lambda p: p.stat().st_mtime)
    for old in logs[:-_MAX_LOGS]:
        try:
            old.unlink()
        except OSError:
            pass
