# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper commands for running commands and common shell tasks"""

import subprocess
import os
from pathlib import Path
import shutil
from typing import Optional, Iterable
from .ish_comp import IshComp


class CommandRunner(IshComp):
    """Helper class for running commands and common shell tasks"""

    def __init__(self, always_sudo: Optional[bool] = False, **kwargs) -> None:
        self._always_sudo: Optional[bool] = always_sudo
        super().__init__(**kwargs)

    @property
    def dry_run(self) -> bool:
        """Is dry-run mode enabled"""
        return self._get_opt("dry_run", False)

    @property
    def always_sudo(self) -> bool:
        """Is always-sudo mode enabled, i.e., sudo without asking"""
        return self._get_opt("dry_run", False)

    @always_sudo.setter
    def always_sudo(self, always_sudo: bool) -> None:
        self._always_sudo = always_sudo

    @dry_run.setter
    def dry_run(self, dry_run: bool) -> None:
        self._dry_run = dry_run

    def run_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False, **kwargs
    ) -> subprocess.CompletedProcess:
        """Run command with sudo"""
        command = ["sudo"] + command
        if not self._check_sudo(command, force_sudo):
            raise KeyboardInterrupt("User aborted sudo command")
        self.run(command, **kwargs)

    def run(
        self,
        command: Iterable[str],
        work_dir: Optional[Path] = None,
        quiet: Optional[bool] = False,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run command"""

        command = [str(c) for c in command]

        if "check" not in kwargs:
            kwargs["check"] = True

        self._print_cmd(command)

        if quiet:
            if "stdout" not in kwargs:
                kwargs["stdout"] = subprocess.DEVNULL
            if "stderr" not in kwargs:
                kwargs["stderr"] = subprocess.DEVNULL

        if self.dry_run:
            # pylint: disable=W1510
            return subprocess.CompletedProcess(
                args=command, returncode=0, stdout=b"", stderr=b""
            )

        if work_dir is not None:
            old_path: Path = Path(os.getcwd())
            os.chdir(work_dir)

        # pylint: disable=W1510
        result = subprocess.run(command, **kwargs)
        if work_dir is not None:
            os.chdir(old_path)
        return result

    def chdir(
        self,
        path: Path,
        mkdir: Optional[bool] = False,
        may_fail: Optional[bool] = False,
    ) -> bool:
        """Change directory to path, optionally creating it if it does not exist"""
        if os.getcwd() == str(path):
            self.log.debug("Already in directory %s, skipping chdir", path)
            return True

        if not path.exists():
            if mkdir:
                self.mkdir(path)
            else:
                self.log.error("Path %s does not exist, cannot chdir", path)
                if not may_fail:
                    self.die("Path %s does not exist, stopping")
                return False

        self._print_cmd([f"cd {path}"])
        if self.dry_run:
            return True

        os.chdir(path)
        return True

    def rm(self, path: Path, recursive: Optional[bool] = False) -> bool:
        """Remove path, optionally recursively"""
        if not path.exists():
            self.log.debug("Path %s does not exist, skipping delete", path)
            return True

        self._print_rm(path, recursive)
        if self.dry_run:
            return True

        if recursive:
            shutil.rmtree(path)
        else:
            path.unlink()
        return True

    def mkdir(self, path: Path, parents: Optional[bool] = False) -> bool:
        """Create path, optionally creating parent directories"""
        if path.exists():
            self.log.debug("Path %s already exists, skipping mkdir", path)
            return True

        self._print_mkdir(path, parents)
        if self.dry_run:
            return True

        path.mkdir(parents=parents)
        return True

    def which(self, command: str) -> Optional[str]:
        """Find the path to a command"""
        return shutil.which(command)

    def _print_cmd(self, command: Iterable[str]) -> None:
        if not self.quiet:
            self.print(" ".join([str(c) for c in command]))

    def _print_rm(self, path: Path, recursive: Optional[bool] = False) -> None:
        if self.quiet:
            return

        if recursive:
            self._print_cmd([f"rm -rf {path}"])
        else:
            self._print_cmd([f"rm -f {path}"])

    def _print_mkdir(self, path: Path, parents: Optional[bool] = False) -> None:
        if self.quiet:
            return

        if parents:
            self._print_cmd([f"mkdir -p {path}"])
        else:
            self._print_cmd([f"mkdir {path}"])

    def _error_or_die(
        self, msg: str, is_fatal: Optional[bool] = False, exit_code: Optional[int] = 1
    ) -> None:
        if is_fatal:
            self.die(msg, exit_code)
        self.log.error(msg)

    def _check_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False
    ) -> bool:
        if self._always_sudo or force_sudo:
            return True

        if self.dry_run:
            self.log.info("Dry run, skipping sudo check")
            return True

        choice = self.prompt_yes_no_always(f"Going to run{' '.join(command)}")
        if choice.always:
            self._always_sudo = True
        return choice.yes
