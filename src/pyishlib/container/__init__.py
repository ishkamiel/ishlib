# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Generic container backend abstractions for pyishlib.

Provides a backend-agnostic :class:`Container` ABC and the
:class:`IncusContainer` implementation.  This package owns every
``incus``-specific code path — tool-specific layers (such as
``pyishlib.isholate``) must build on top of these classes rather than
reach for the ``incus`` CLI directly.
"""

from .container import Container
from .incus import (
    IncusContainer,
    check_incus_available,
    ensure_managed_network,
    list_incus_containers,
)

__all__ = [
    "Container",
    "IncusContainer",
    "check_incus_available",
    "ensure_managed_network",
    "list_incus_containers",
]
