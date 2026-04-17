#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>

from . import *


def test_run_prove(project_root):
    os.chdir(project_root)
    run_check_call("prove")
