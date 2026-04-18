# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>

"""Backend-agnostic container abstraction.

:class:`Container` is an abstract base class that wraps a single named
container.  Subclasses implement the low-level primitives
(create/start/stop/delete/exec/add_device/...) by talking to a particular
backend; the base class provides concrete composed helpers (``add_mount``,
``add_folder``) built on top of those primitives.

This module must stay tool-agnostic — no isholate-specific, no ishfiles-
specific, no Claude-specific code belongs here.
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


class Container(ABC):
    """Abstract base for container backends.

    Wraps a single named container.  Subclasses implement the abstract
    primitives; the base class composes them into higher-level helpers
    that callers can use without knowing which backend is in play.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    # ------------------------------------------------------------------
    # Lifecycle primitives
    # ------------------------------------------------------------------

    @abstractmethod
    def exists(self) -> bool:
        """Return True when a container with this name exists (any state)."""

    @abstractmethod
    def is_running(self) -> bool:
        """Return True when the container is in the running state."""

    @abstractmethod
    def create(self, image: str, **config: str) -> None:
        """Create (but do not start) a container from *image*.

        Additional ``key=value`` configuration entries are passed through
        as backend-specific container configuration.
        """

    @abstractmethod
    def start(self) -> None:
        """Start the container."""

    @abstractmethod
    def stop(self, *, force: bool = True) -> None:
        """Stop the container."""

    @abstractmethod
    def delete(self, *, force: bool = True) -> None:
        """Delete the container."""

    @abstractmethod
    def copy_to(self, dest_name: str) -> "Container":
        """Clone this container to *dest_name* and return the new handle."""

    # ------------------------------------------------------------------
    # Exec / file I/O
    # ------------------------------------------------------------------

    @abstractmethod
    def exec(
        self,
        cmd: Sequence[str],
        *,
        env: Optional[Mapping[str, str]] = None,
        cwd: Optional[str] = None,
        user: Optional[int] = None,
        check: bool = False,
        capture_output: bool = False,
        text: bool = False,
        stdin: Any = None,
    ) -> subprocess.CompletedProcess:
        """Execute *cmd* inside the container and return the completed process.

        Optional keyword arguments map onto backend-specific exec flags.
        ``check``/``capture_output``/``text`` follow the same semantics as
        :func:`subprocess.run`.
        """

    @abstractmethod
    def pull_file(
        self,
        container_path: str,
        host_dest: Path,
        *,
        recursive: bool = False,
    ) -> bool:
        """Copy *container_path* out of the container to *host_dest*.

        Returns True on success, False on failure.  Implementations must
        not raise on transport-level errors; callers may retry or log.
        """

    @abstractmethod
    def push_file(
        self,
        host_src: Path,
        container_path: str,
        *,
        uid: Optional[int] = None,
        gid: Optional[int] = None,
        mode: Optional[int] = None,
    ) -> bool:
        """Copy *host_src* into the container at *container_path*.

        Optional ``uid``/``gid``/``mode`` set the in-container ownership
        and permissions (backends map these onto their native flags).
        Returns True on success, False on failure.  Implementations must
        not raise on transport-level errors.
        """

    # ------------------------------------------------------------------
    # Device primitives
    # ------------------------------------------------------------------

    @abstractmethod
    def add_device(self, device_name: str, device_type: str, **options: str) -> None:
        """Attach a backend-level device to the container.

        ``device_type`` and ``options`` are backend-specific (e.g. ``"disk"``
        with ``source=...``/``path=...`` for Incus bind-mounts).
        """

    @abstractmethod
    def remove_device(self, device_name: str) -> None:
        """Detach a previously-added device; should be best-effort."""

    @abstractmethod
    def list_devices(self) -> List[str]:
        """Return all device names configured on this container."""

    # ------------------------------------------------------------------
    # Arbitrary key/value metadata on the container
    # ------------------------------------------------------------------

    @abstractmethod
    def get_metadata(self, key: str) -> Optional[str]:
        """Return the stored value for *key*, or None when absent."""

    @abstractmethod
    def set_metadata(self, key: str, value: str) -> None:
        """Store *value* under *key* on the container's metadata."""

    # ------------------------------------------------------------------
    # Concrete helpers (composed from the primitives above)
    # ------------------------------------------------------------------

    def add_mount(
        self,
        device_name: str,
        src: Path,
        dst: str,
        *,
        readonly: bool = False,
        shift: bool = False,
    ) -> None:
        """Attach a bind-mount: host *src* -> in-container *dst*."""
        options: Dict[str, str] = {"source": str(src), "path": dst}
        if readonly:
            options["readonly"] = "true"
        if shift:
            options["shift"] = "true"
        self.add_device(device_name, "disk", **options)

    def add_folder(
        self,
        device_name: str,
        host_dir: Path,
        container_dir: str,
        *,
        readonly: bool = False,
        shift: bool = False,
    ) -> bool:
        """Bind-mount a host folder or file into the container if it exists.

        Returns True when the source exists and the mount was attached,
        False when the source is missing (the mount is skipped silently).
        """
        if not host_dir.is_dir() and not host_dir.is_file():
            return False
        self.add_mount(
            device_name, host_dir, container_dir, readonly=readonly, shift=shift
        )
        return True
