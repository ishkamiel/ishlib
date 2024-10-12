# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import subprocess

import os
from pathlib import Path
import shutil
from .ish_comp import IshComp


class CommandRunner(IshComp):
    def __init__(self):
        super().__init__()

    def run(self, command, **kwargs):
        command = [str(c) for c in command]
        print(f"DRY-RUN: {' '.join(command)}")
        if not self.dry_run:
            return subprocess.run(command, **kwargs)
        else:
            return subprocess.CompletedProcess(args=command, returncode=0)

    def _print_cmd(self, command):
        if not self.quiet:
            print(" ".join([str(c) for c in command]))

    def _print_rm(self, path, recursive=False):
        if self.quiet:
            return

        if recursive:
            self._print_cmd(f"rm -rf {path}")
        else:
            self._print_cmd(f"rm -f {path}")

    def _print_mkdir(self, path, parents=False):
        if self.quiet:
            return

        if parents:
            self._print_cmd(f"mkdir -p {path}")
        else:
            self._print_cmd(f"mkdir {path}")

    def _error_or_die(self, msg, is_fatal: bool = False, exit_code: int = 1):
        if is_fatal:
            self.log_fatal(msg, exit_code)
        self.log_error(msg)

    def chdir(self, path: Path, mkdir: bool = False, may_fail: bool = False) -> bool:
        if os.getcwd() == path:
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

        self._print_cmd(f"cd {path}")
        if self.dry_run:
            return True

        os.chdir(path)
        return True

    def rm(self, path: Path, recursive: bool = False) -> bool:
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

    def mkdir(self, path: Path, parents: bool = False) -> bool:
        if path.exists():
            self.log_debug(f"Path {path} already exists, skipping mkdir")
            return True

        self._print_mkdir(path, parents)
        if self.dry_run:
            return True

        path.mkdir(parents=parents)
        return True
