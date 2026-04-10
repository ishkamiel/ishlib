#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Compatibility shims for optional dependencies."""

import sys

if sys.version_info >= (3, 11):
    import tomllib  # pylint: disable=unused-import

    HAS_TOML = True
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]  # pylint: disable=unused-import

        HAS_TOML = True
    except ImportError:
        tomllib = None  # type: ignore[assignment]
        HAS_TOML = False
