# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
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
        self._always_sudo: bool | None = always_sudo
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

    def run(
        self,
        command: Iterable[str],
        sudo: Optional[bool] = None,
        force_sudo: Optional[bool] = False,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run command, optionally with sudo"""
        command = [str(c) for c in command]
        if sudo:
            command = ["sudo"] + command
            if not self._check_sudo(command, force_sudo):
                raise KeyboardInterrupt("User aborted sudo command")

        self._print_cmd(command)
        if not self.dry_run:
            # pylint: disable=W1510
            return subprocess.run(command, **kwargs)
        return subprocess.CompletedProcess(args=command, returncode=0)

    def chdir(
        self,
        path: Path,
        mkdir: Optional[bool] = False,
        may_fail: Optional[bool] = False,
    ) -> bool:
        """Change directory to path, optionally creating it if it does not exist"""
        if os.getcwd() == str(path):
            self.log_debug(f"Already in directory {path}, skipping chdir")
            return True

        if not path.exists():
            if mkdir:
                self.mkdir(path)
            else:
                self._error_or_die(
                    f"Path {path} does not exist, cannot change directory", may_fail
                )
                return False

        self._print_cmd([f"cd {path}"])
        if self.dry_run:
            return True

        os.chdir(path)
        return True

    def rm(self, path: Path, recursive: Optional[bool] = False) -> bool:
        """Remove path, optionally recursively"""
        if not path.exists():
            self.log_debug(f"Path {path} does not exist, skipping delete")
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
            self.log_debug(f"Path {path} already exists, skipping mkdir")
            return True

        self._print_mkdir(path, parents)
        if self.dry_run:
            return True

        path.mkdir(parents=parents)
        return True

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
            self.log_fatal(msg, exit_code)
        self.log_error(msg)

    def _check_sudo(
        self, command: Iterable[str], force_sudo: Optional[bool] = False
    ) -> bool:
        if self._always_sudo or force_sudo:
            return True

        if self.dry_run:
            self.log_info("Dry run, skipping sudo check")
            return True

        choice = self.prompt_yes_no_always(f"Going to run{' '.join(command)}")
        if choice.always:
            self._always_sudo = True
        return choice.yes
