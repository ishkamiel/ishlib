# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Top-level pytest configuration shared by all test workers.

## Hermetic subprocess environment

Pre-commit sets GIT_DIR (and related variables) before invoking pytest.
Any test that spawns a subprocess without an explicit ``env=`` argument
would therefore inherit the host's full environment and might corrupt the
real repository index, use the host's git signing keys, or behave
differently depending on which machine runs the tests.

Rather than maintaining per-call blacklists, this conftest replaces
``os.environ`` wholesale at session start with a minimal, deterministic
environment:

``_PASSTHROUGH`` — a small whitelist of variables copied verbatim from the
host.  ``PATH`` is the only strictly required entry (to locate git, bash,
zsh, etc.).  ``HOME`` is kept so shells and git do not warn about a missing
home directory; ``TMPDIR``/``TMP``/``TEMP`` are kept for portable temp-file
creation.  Nothing else is copied.

``_SYNTHETIC`` — variables injected unconditionally regardless of the host.
These point git at ``/dev/null`` configs (so the host ``~/.gitconfig`` and
signing setup are invisible) and supply a fixed committer identity so every
``git commit`` in tests succeeds without reading any per-user configuration.

Each xdist worker process gets its own copy of the environment, so the
session fixture runs independently and safely in every worker.

Tests that need additional variables (e.g. a custom ``GIT_AUTHOR_NAME`` for
a specific scenario) set them explicitly via ``monkeypatch.setenv`` or by
building an ``env`` dict from ``os.environ.copy()`` inside the test.
"""

from __future__ import annotations

import os

import pytest

# Variables copied verbatim from the host.
_PASSTHROUGH = frozenset({"PATH", "HOME", "TMPDIR", "TMP", "TEMP"})

# Variables synthesised unconditionally; these shadow any host value.
_SYNTHETIC: dict[str, str] = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


@pytest.fixture(autouse=True, scope="session")
def _clean_env() -> None:
    """Replace os.environ with a minimal hermetic environment."""
    clean = {k: os.environ[k] for k in _PASSTHROUGH if k in os.environ}
    clean.update(_SYNTHETIC)
    os.environ.clear()
    os.environ.update(clean)
