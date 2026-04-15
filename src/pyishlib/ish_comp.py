#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Common utilities for pyishlib: process helpers.

Logging setup lives in :mod:`pyishlib.ish_logging`.
Interactive prompting lives in :mod:`pyishlib.userio`.
"""

import logging
import sys
from typing import NoReturn


def die(msg: str, exit_code: int = 1) -> NoReturn:
    """Log a critical message and exit."""
    logging.getLogger("pyishlib").critical(msg)
    sys.exit(exit_code)
