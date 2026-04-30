# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Daemon-level container backend abstraction.

:class:`ContainerBackend` is the daemon-level counterpart to the
per-container :class:`pyishlib.container.Container` ABC.  It owns
operations that are not bound to a single container instance: probing
daemon health, listing all containers visible to the user, creating
managed networks, and applying network-isolation policies that span
multiple host-side primitives (firewalls, bridges, …).

Per-container handles are produced via :meth:`ContainerBackend.container`
which returns a :class:`Container` of the appropriate concrete type.
The factory call is pure (no I/O) — callers are free to invoke it for
names that do not yet exist.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .container import Container


class ContainerBackend(ABC):
    """Abstract base for container-engine backends.

    Concrete backends (e.g. :class:`pyishlib.container.IncusBackend`)
    implement the daemon-level primitives below.  Tool layers
    (``pyishlib.isholate``, future ishfiles backends) must build on top
    of this ABC and :class:`Container` rather than shelling out to the
    backend's CLI directly.
    """

    #: Short backend identifier ("incus", "docker", …).
    name: str = ""

    @abstractmethod
    def check_available(self) -> Optional[str]:
        """Probe the backend daemon.

        Returns ``None`` when the backend is installed and reachable for
        the current user.  Otherwise returns a multi-line, user-facing
        message describing what to do next.
        """

    @abstractmethod
    def container(self, name: str) -> Container:
        """Return a :class:`Container` handle for *name*.

        Pure factory — no I/O.  The handle may refer to a container that
        does not yet exist; call :meth:`Container.exists` to probe.
        """

    @abstractmethod
    def list_containers(self) -> List[dict]:
        """Return all containers visible to the current user.

        Each entry is a backend-native dictionary; the only key callers
        rely on is ``name``.
        """

    @property
    def supports_managed_networks(self) -> bool:
        """Whether this backend can host managed networks.

        Default ``False``; backends that implement
        :meth:`ensure_managed_network` override to ``True``.
        """
        return False

    def ensure_managed_network(
        self,
        name: str,
        *,
        create_config: List[str],
        set_config: Dict[str, str],
    ) -> None:
        """Ensure a backend-managed network exists with the given config.

        Default implementation raises :class:`NotImplementedError`.
        """
        raise NotImplementedError(
            f"{self.name or type(self).__name__}: backend does not support "
            "managed networks"
        )
