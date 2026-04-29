# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Generic container backend abstractions for pyishlib.

Provides:

- :class:`Container` — per-container handle ABC.
- :class:`ContainerBackend` — daemon-level backend ABC.
- :class:`IncusContainer` / :class:`IncusBackend` — Incus implementations.
- :func:`get_backend` — single seam for selecting a backend.

This package owns every backend-specific code path (today: Incus only).
Tool-specific layers (such as ``pyishlib.isholate``) must build on top
of these classes rather than reach for a backend's CLI directly.
"""

from typing import Optional

from .backend import ContainerBackend
from .container import Container
from .incus import (
    IncusBackend,
    IncusContainer,
    check_incus_available,
    ensure_managed_network,
    list_incus_containers,
)

__all__ = [
    "Container",
    "ContainerBackend",
    "IncusBackend",
    "IncusContainer",
    "check_incus_available",
    "ensure_managed_network",
    "get_backend",
    "list_incus_containers",
]


_BACKENDS = {
    "incus": IncusBackend,
}


def get_backend(name: Optional[str] = None) -> ContainerBackend:
    """Return the requested :class:`ContainerBackend`.

    With ``name=None`` (the default) returns an :class:`IncusBackend`.
    Future backends register themselves in the lookup table above.

    Raises:
        ValueError: when *name* is not a known backend.
    """
    key = (name or "incus").lower()
    try:
        cls = _BACKENDS[key]
    except KeyError as exc:
        known = ", ".join(sorted(_BACKENDS))
        raise ValueError(
            f"unknown container backend: {name!r} (known: {known})"
        ) from exc
    return cls()
