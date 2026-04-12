#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Executable script with ``@ish`` directive preprocessing.

Provides :class:`DotfileScript` which represents a script file that
lives in a dotfile-managed location (e.g. the ``ishinstallers/`` folder),
gets preprocessed through the same ``@ish`` directive pipeline used for
dotfiles, and can then be executed.

The preprocessing applies the same variable substitution and conditional
logic as dotfile installation, allowing user-provided scripts to adapt
to the current environment via ``${__ish_<name>}`` references and
``#@ish if`` conditionals.
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

from .command_runner import CommandRunner
from .file_preprocessor import FilePreprocessor

if TYPE_CHECKING:
    from .ishfiles.script_logger import ScriptLogger

log = logging.getLogger(__name__)


class DotfileScript:
    """A script file that is preprocessed and executed.

    The script goes through the standard ``@ish`` preprocessing pipeline
    (metadata extraction, directive handling, variable substitution) before
    being written to a temporary file and executed.

    The script type (shell or Python) is auto-detected from the shebang
    line or file extension.

    Args:
        path: Path to the source script file.
        preprocessor: A :class:`FilePreprocessor` instance for directive
                       processing.  If *None*, a new one is created.
        runner: A :class:`CommandRunner` for execution.  If *None*, a
                new one is created.
    """

    def __init__(
        self,
        path: Path,
        preprocessor: Optional[FilePreprocessor] = None,
        runner: Optional[CommandRunner] = None,
    ) -> None:
        self._path = Path(path)
        self._preprocessor = preprocessor or FilePreprocessor()
        self._runner = runner or CommandRunner()
        self._metadata: Optional[dict] = None
        self._preprocessed_text: Optional[str] = None

    @property
    def path(self) -> Path:
        """The source script path."""
        return self._path

    @property
    def metadata(self) -> Optional[dict]:
        """Metadata extracted during preprocessing, if any."""
        return self._metadata

    def preprocess(self) -> str:
        """Preprocess the script and return the processed text.

        Results are cached so that a subsequent :meth:`execute` call
        reuses the same text and metadata without re-running directives.

        Raises:
            UnicodeDecodeError: If the file cannot be read as UTF-8.
            FileNotFoundError: If the script file does not exist.
        """
        if self._preprocessed_text is not None:
            return self._preprocessed_text

        if not self._path.is_file():
            raise FileNotFoundError(f"Script not found: {self._path}")

        text, meta = self._preprocessor.preprocess_file(self._path)
        self._metadata = meta
        self._preprocessed_text = text
        return text

    def execute(
        self,
        env: Optional[Dict[str, str]] = None,
        script_logger: Optional["ScriptLogger"] = None,
    ) -> bool:
        """Preprocess and execute the script.

        The preprocessed script is written to a temporary file which is
        then executed.  The interpreter is chosen based on the shebang
        line or file extension.

        When *script_logger* is provided, the bash helper prelude
        (``ish_info``, ``ish_warn``, ``ish_error``, ``ish_fatal``) is
        injected after the shebang line of shell scripts, and all
        stdout/stderr from the script is captured and written to the run
        log.

        Args:
            env:           Optional extra environment variables to set for
                           the script process (merged with the current
                           environment).
            script_logger: Optional :class:`~pyishlib.ishfiles.script_logger.ScriptLogger`
                           for structured logging and output capture.

        Returns:
            True if the script exited successfully (returncode 0).
        """
        text = self.preprocess()

        # Inject the log-helper prelude for shell and PowerShell scripts.
        ext = self._path.suffix
        if script_logger is not None and (self._is_shell_script(text) or ext == ".ps1"):
            from .ishfiles.script_logger import inject_prelude

            text = inject_prelude(text, ext)

        interpreter = self._detect_interpreter(text)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=self._path.suffix or ".sh",
            prefix="ish_script_",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)

        try:
            # Make executable
            tmp_path.chmod(tmp_path.stat().st_mode | stat.S_IEXEC)

            cmd = interpreter + [str(tmp_path)]
            script_env = dict(os.environ)
            if env:
                script_env.update(env)
            if script_logger is not None:
                script_env.update(script_logger.env())

            log.info("Executing script: %s", self._path.name)

            if script_logger is not None and not self._runner.dry_run:
                # Capture stdout+stderr for the log file.
                result = subprocess.run(
                    cmd,
                    env=script_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                output = result.stdout.decode("utf-8", errors="replace")
                script_logger.log_script_output(self._path.name, output)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(
                        result.returncode, cmd, output=result.stdout
                    )
            else:
                self._runner.run(
                    cmd,
                    check=True,
                    env=script_env,
                )
            return True
        except subprocess.CalledProcessError as e:
            log.error(
                "Script %s failed with exit code %d",
                self._path.name,
                e.returncode,
            )
            raise
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _is_shell_script(text: str) -> bool:
        """True if the script appears to be a shell script.

        Checks the shebang line for ``sh``, ``bash``, ``zsh``, or ``dash``.
        Scripts with no shebang also default to shell execution.
        """
        first_line = text.split("\n", 1)[0].strip()
        if not first_line.startswith("#!"):
            return True  # No shebang: default /bin/sh execution
        shebang = first_line[2:].strip()
        return any(shell in shebang for shell in ("sh", "bash", "zsh", "dash"))

    @staticmethod
    def _detect_interpreter(text: str) -> list:
        """Detect the interpreter from the shebang or return a default.

        Returns a command list suitable for prepending to the script path.
        If the shebang specifies an interpreter, it is used.  Otherwise
        the script is run with ``/bin/sh``.
        """
        first_line = text.split("\n", 1)[0].strip()
        if first_line.startswith("#!"):
            shebang = first_line[2:].strip()
            if "python" in shebang:
                return shebang.split()
            # For shell shebangs, use the script directly (via chmod +x)
            return []
        # Default to sh
        return ["/bin/sh"]
