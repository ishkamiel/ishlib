#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import os
import subprocess
import time
import argparse
import re

ISHLIB_NAME = "ishlib"

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_FN = os.path.join(ROOT_DIR, "ishlib.sh")
BASE_FN = os.path.join(ROOT_DIR, "src/sh/base.sh")
README_FN = os.path.join(ROOT_DIR, "src/readme_src.md")

header_end = (
    "###############################################################################"
)

readme_documentation_start = "## Documentation"

# src_dir = os.path.dirname(base_fn)

debug_mode = False


def main():
    global debug_mode

    parser = argparse.ArgumentParser(description="Build the ishlib project.")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    debug_mode = args.debug

    Parser(ROOT_DIR, BASE_FN, OUT_FN).build_ishlib()


def log_debug(message):
    global debug_mode
    if debug_mode:
        print(f"DEBUG: {message}")


def get_ishlib_version():
    git_revision = (
        subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
        .strip()
        .decode("utf-8")
    )
    return time.strftime("%Y-%m-%d.%H%M.") + git_revision


class Parser:
    def __init__(self, root, base, output):
        # self.cwd = root
        self.base = base
        self.output = output
        self.ishlib_version = get_ishlib_version()
        # self.src_dir = os.path.dirname(base)
        self.empty_lines = 0

    def build_ishlib(self):
        # self.current_fn = ROOT_DIR

        log_debug(f"Starting from base {self.base}")
        # os.chdir(os.path.dirname(self.base))
        with open(self.base, "r") as base_fh, open(self.output, "w") as self.out_fh:
            for line in base_fh:
                self.process_oneline(line, True)
        print("Generated ishlib.sh (version %s)" % self.ishlib_version)

    def process_oneline(self, line, do_includes=False):
        # Handle __ISHLIB_README__
        if line.strip() == "__ISHLIB_README__":
            self.source_readme(line)
            return

        # Handle includes
        if line.strip().startswith("."):
            if do_includes:
                log_debug(f"Found include line {line.strip()}")
                self.source_file(line.strip().split()[1])
            return

        # Handle empty lines
        if line.strip() == "":
            if self.empty_lines == 0:
                self.out_fh.write("\n")
            self.empty_lines += 1
            return

        # Ignore shellcheck source lines
        if re.match(r"^\s*#\s*shellcheck\s*source.*", line):
            return

        # Just process sline
        self.empty_lines = 0
        line = line.replace("__ISHLIB_VERSION__", self.ishlib_version)
        line = line.replace("__ISHLIB_NAME__", ISHLIB_NAME)
        self.out_fh.write(line)

    def source_readme(self, fn):
        log_debug(f"source_readme from {README_FN}")
        with open(README_FN, "r") as fh:
            for line in fh:
                self.process_oneline(line)
                if line.strip() == readme_documentation_start:
                    return
        raise Exception("Unexpected EOF file")

    def is_ignored_header_line(self, line, do_includes=False):
        # Ignore leading comments
        if line.startswith("#"):
            return True

        # Ignore include guard

        if line.startswith('[ -n "${ish_SOURCED'):
            return True
        if line.startswith("ish_SOURCED"):
            return True

        # Ignore empty lines
        if line.strip() == "":
            return True

        # Ignore includes, unless do_includes = True
        if not do_includes and line.strip().startswith("."):
            return False

        log_debug(f"Not a header line: {line}")
        return False

    def source_file(self, path, do_includes=False):
        log_debug(f"source_file {path}")
        start_reading = False

        fn = path.replace("$ISHLIB", ROOT_DIR)

        # remove surrounding quotes, if present
        if fn.startswith('"') and fn.endswith('"'):
            fn = fn[1:-1]

        log_debug(f"Sourcing {fn}")
        with open(fn, "r") as fh:
            for line in fh:
                if not start_reading and self.is_ignored_header_line(line, do_includes):
                    log_debug(f"Ignoring: {line.strip()}")
                    pass
                # elif not do_includes and line.strip().startswith('.'):
                #     self.source_file(line.strip().split()[1])
                else:
                    start_reading = True
                    self.process_oneline(line, do_includes)


if __name__ == "__main__":
    main()
