#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper commands for running commands and common shell tasks."""

import logging
import os
import subprocess
from pathlib import Path
import shutil
from typing import Optional, Iterable

from .ish_config import IshConfig
from .ish_comp import die
from .userio import prompt_yes_no_always
from .environment import is_windows

log = logging.getLogger(__name__)


class CommandRunner:
    """Helper class for running commands and common shell tasks"""

    def __init__(
        self,
        cfg: Optional[IshConfig] = None,
        always_sudo: bool = False,
    ) -> None:
        self.cfg: IshConfig = cfg if cfg is not None else IshConfig()
        self._always_sudo: bool = always_sudo

    @property
    def on_windows(self) -> bool:
        """True if running on Windows"""
        return is_windows()

    @property
    def dry_run(self) -> bool:
        """Is dry-run mode enabled"""
        return self.cfg.dry_run

    @dry_run.setter
    def dry_run(self, dry_run: bool) -> None:
        self.cfg.dry_run = dry_run

    @property
    def verbose(self) -> bool:
        """Is verbose mode enabled"""
        return self.cfg.verbose

    @property
    def quiet(self) -> bool:
        """Is quiet mode enabled"""
        return self.cfg.quiet

    @property
    def always_sudo(self) -> bool:
        """Is always-sudo mode enabled, i.e., sudo without asking"""
        return self._always_sudo

    @always_sudo.setter
    def always_sudo(self, always_sudo: bool) -> None:
        self._always_sudo = always_sudo

    def run_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False, **kwargs
    ) -> subprocess.CompletedProcess:
        """Thin wrapper for :meth:`run` with ``sudo=True``.

        Prefer ``runner.run(cmd, sudo=True)`` in new code.
        """
        return self.run(command, sudo=True, force_sudo=force_sudo, **kwargs)

    def run(
        self,
        command: Iterable[str],
        work_dir: Optional[Path] = None,
        quiet: bool = False,
        sudo: bool = False,
        force_sudo: Optional[bool] = False,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run command.

        When *sudo* is True the command is prefixed with ``sudo`` and
        runs through :meth:`_check_sudo` for user confirmation (unless
        *force_sudo* is True or ``always_sudo`` is set).  Raises
        ``OSError`` on Windows when *sudo* is True.
        """

        command = [str(c) for c in command]

        if sudo:
            if self.on_windows:
                raise OSError("sudo is not available on Windows")
            command = ["sudo"] + command
            if not self._check_sudo(command, force_sudo):
                raise KeyboardInterrupt("User aborted sudo command")

        if "check" not in kwargs:
            kwargs["check"] = True

        self._print_cmd(command)

        if quiet:
            if "stdout" not in kwargs:
                kwargs["stdout"] = subprocess.DEVNULL
            if "stderr" not in kwargs:
                kwargs["stderr"] = subprocess.DEVNULL

        if self.dry_run:
            return subprocess.CompletedProcess(
                args=command, returncode=0, stdout=b"", stderr=b""
            )

        if work_dir is not None:
            old_path: Path = Path(os.getcwd())
            os.chdir(work_dir)

        try:
            result = subprocess.run(command, **kwargs)
        finally:
            if work_dir is not None:
                os.chdir(old_path)
        return result

    def git(
        self, command: Iterable[str], work_dir: Optional[Path] = None, **kwargs
    ) -> subprocess.CompletedProcess:
        """Run git command using Commandrunner.run"""
        command_list = list(command)
        if work_dir is not None and "-C" not in command_list:
            command_list = ["-C", str(work_dir)] + command_list
        return self.run(["git"] + command_list, work_dir=work_dir, **kwargs)

    def chdir(
        self,
        path: Path,
        mkdir: Optional[bool] = False,
        may_fail: Optional[bool] = False,
    ) -> bool:
        """Change directory to path, optionally creating it if it does not exist"""
        if os.getcwd() == str(path):
            log.debug("Already in directory %s, skipping chdir", path)
            return True

        if not path.exists():
            if mkdir:
                self.mkdir(path)
            else:
                log.error("Path %s does not exist, cannot chdir", path)
                if not may_fail:
                    die(f"Path {path} does not exist, stopping")
                return False

        self._print_cmd([f"cd {path}"])
        if self.dry_run:
            return True

        os.chdir(path)
        return True

    def rm(self, path: Path, recursive: Optional[bool] = False) -> bool:
        """Remove path, optionally recursively"""
        if not path.exists():
            log.debug("Path %s does not exist, skipping delete", path)
            return True

        self._print_rm(path, recursive)
        if self.dry_run:
            return True

        if recursive:
            shutil.rmtree(path)
        else:
            path.unlink()
        return True

    def mkdir(self, path: Path, parents: bool = False) -> bool:
        """Create path, optionally creating parent directories"""
        if path.exists():
            log.debug("Path %s already exists, skipping mkdir", path)
            return True

        self._print_mkdir(path, parents)
        if self.dry_run:
            return True

        path.mkdir(parents=parents)
        return True

    def copy(self, src: Path, dst: Path) -> bool:
        """Copy a file from src to dst, creating parent directories as needed"""
        self._print_cmd([f"cp {src} {dst}"])
        if self.dry_run:
            return True

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True

    def which(self, command: str) -> Optional[str]:
        """Find the path to a command"""
        return shutil.which(command)

    def _print_cmd(self, command: Iterable[str]) -> None:
        cmd_str: str = " ".join([str(c) for c in command])
        log.debug("_print_cmd: %s", cmd_str)
        if self.verbose or self.dry_run:
            print(cmd_str)

    def _print_rm(self, path: Path, recursive: Optional[bool] = False) -> None:
        if self.quiet:
            return

        if recursive:
            self._print_cmd([f"rm -rf {path}"])
        else:
            self._print_cmd([f"rm -f {path}"])

    def _print_mkdir(self, path: Path, parents: bool = False) -> None:
        if self.quiet:
            return

        if parents:
            self._print_cmd([f"mkdir -p {path}"])
        else:
            self._print_cmd([f"mkdir {path}"])

    def _error_or_die(
        self, msg: str, is_fatal: bool = False, exit_code: int = 1
    ) -> None:
        if is_fatal:
            die(msg, exit_code)
        else:
            log.error(msg)

    def _check_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False
    ) -> bool:
        if self._always_sudo or force_sudo:
            return True

        if self.dry_run:
            log.info("Dry run, skipping sudo check")
            return True

        choice = prompt_yes_no_always(f"Going to run {' '.join(command)}")
        if choice.always:
            self._always_sudo = True
        return choice.yes
