# -*- coding: utf-8 -*-

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from . import *


def test_run_prove(project_root):
    os.chdir(project_root)
    run_check_call("prove")
