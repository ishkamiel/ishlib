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
from typing import Dict, Optional

from .command_runner import CommandRunner
from .file_preprocessor import FilePreprocessor

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

        Raises:
            UnicodeDecodeError: If the file cannot be read as UTF-8.
            FileNotFoundError: If the script file does not exist.
        """
        if not self._path.is_file():
            raise FileNotFoundError(f"Script not found: {self._path}")

        text, meta = self._preprocessor.preprocess_file(self._path)
        self._metadata = meta
        return text

    def execute(self, env: Optional[Dict[str, str]] = None) -> bool:
        """Preprocess and execute the script.

        The preprocessed script is written to a temporary file which is
        then executed.  The interpreter is chosen based on the shebang
        line or file extension.

        Args:
            env: Optional extra environment variables to set for the
                 script process (merged with the current environment).

        Returns:
            True if the script exited successfully (returncode 0).
        """
        text = self.preprocess()
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
            script_env = None
            if env:
                script_env = dict(os.environ)
                script_env.update(env)

            log.info("Executing custom script: %s", self._path.name)
            result = self._runner.run(
                cmd,
                check=False,
                env=script_env,
            )
            if result.returncode != 0:
                log.error(
                    "Script %s failed with exit code %d",
                    self._path.name,
                    result.returncode,
                )
                return False
            return True
        except subprocess.CalledProcessError as e:
            log.error("Script %s failed: %s", self._path.name, e)
            return False
        finally:
            tmp_path.unlink(missing_ok=True)

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
