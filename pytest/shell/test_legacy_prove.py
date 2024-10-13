#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

from . import *


def test_run_prove(project_root):
    os.chdir(project_root)
    run_check_call("prove")
