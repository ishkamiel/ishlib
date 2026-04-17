#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""File-locks that serialize concurrent isholate base-container builds.

Parallel ``isholate`` invocations that target the same persistent base
container (host base or project base) would otherwise race ``incus init`` /
``incus copy`` / ``incus delete --force`` against each other.  This module
provides a single :func:`base_build_lock` context manager backed by
``fcntl.flock`` on a per-base file under ``~/.local/state/isholate/locks/``.

Locks are held only across the base build/rebuild critical section in
:func:`pyishlib.isholate.container.ensure_host_base` and
:func:`pyishlib.isholate.container.ensure_project_base`.  They are released
before any ephemeral clone or interactive ``incus exec``, so N concurrent
ephemeral launches from the same stopped base never serialize on each other.

The lock scheme uses ``fcntl.flock`` (per-open-file-description semantics)
on a file opened with ``O_CLOEXEC`` so the lock fd cannot leak into child
processes such as ``incus exec``.  ``flock`` is released automatically when
the holding process dies, so there is no stale-lock cleanup to worry about.

isholate is Linux-only (see :func:`pyishlib.isholate.cli.main`), so the
dependency on ``fcntl`` is safe.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .config import LOCKS_STATE_DIR

log = logging.getLogger(__name__)

# How long to wait before announcing at INFO that we are blocked on a peer.
# Tests patch this to a smaller value to keep runtimes snappy.
_WAIT_LOG_AFTER_SECONDS: float = 1.0

# Polling interval while waiting for the lock.  Uses a short sleep so that
# SIGINT interrupts cleanly (unlike a blocking ``flock(LOCK_EX)`` call).
_POLL_INTERVAL_SECONDS: float = 0.1


def _lock_path(name: str) -> Path:
    """Return the lock-file path for a given base container *name*.

    Creates the parent directory on first use.
    """
    root = Path.home() / LOCKS_STATE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{name}.lock"


@contextmanager
def base_build_lock(name: str) -> Iterator[None]:
    """Serialize base-container build/rebuild work keyed on *name*.

    Acquires an exclusive ``fcntl.flock`` on ``LOCKS_STATE_DIR/<name>.lock``.
    If the lock is not immediately available, polls until it is — logging an
    INFO-level "waiting..." note once the wait exceeds
    :data:`_WAIT_LOG_AFTER_SECONDS` so users understand why a run paused.

    Callers MUST perform a "does the base already exist and is its
    fingerprint current?" re-check *inside* the ``with`` block so that a
    waiter observing a peer's just-finished build can skip its own rebuild
    (double-checked locking idiom).

    Args:
        name: The container name to key the lock on — typically the output
            of :func:`pyishlib.isholate.container._host_base_name` or
            :func:`pyishlib.isholate.container._project_base_name`.

    Yields:
        Nothing.  The lock is released when the ``with`` block exits.
    """
    # Imported here, not at module top-level, so the surrounding module can
    # still be imported on non-POSIX platforms (e.g. Windows CI collectors).
    # isholate.cli bails on non-Linux, so this path is never reached there.
    import fcntl  # noqa: PLC0415

    path = _lock_path(name)
    # O_CLOEXEC so the lock fd cannot leak into ``incus exec`` children.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        # Fast path: try non-blocking first so the common uncontended case
        # never touches the poll/log machinery.
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.debug("waiting for isholate base-build lock on '%s'...", name)
            start = time.monotonic()
            noted = False
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if (
                        not noted
                        and time.monotonic() - start >= _WAIT_LOG_AFTER_SECONDS
                    ):
                        log.info(
                            "another isholate is building base '%s'; waiting...",
                            name,
                        )
                        noted = True
                    time.sleep(_POLL_INTERVAL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
