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
zsh, etc.).  ``TMPDIR``/``TMP``/``TEMP`` are kept for portable temp-file
creation.  ``HOME`` is **not** copied; a fresh temporary directory is
created and assigned to ``HOME`` (and ``XDG_*_HOME``) instead, so
production code that calls ``Path.home()`` or consults ``HOME`` /
``XDG_*_HOME`` at runtime after session setup reads from an empty sandbox
rather than the developer's real dotfiles or
``~/.config/ishlib/ishproject.toml``.  This makes runtime home-directory
lookups during tests deterministic regardless of what is in the developer's
home directory.

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
# HOME and USERPROFILE are intentionally absent: the fixture creates a fresh
# temp directory and assigns it instead so no real user config leaks in.
# SYSTEMROOT is essential on Windows (system DLLs); absent on Linux/macOS.
_PASSTHROUGH = frozenset({"PATH", "TMPDIR", "TMP", "TEMP", "SYSTEMROOT"})

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
def _clean_env(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Replace os.environ with a minimal hermetic environment.

    ``HOME`` is redirected to a fresh per-worker temporary directory so
    that any production code path relying on ``Path.home()`` (config
    loaders, XDG cache resolution, …) operates in an empty sandbox rather
    than the developer's real home directory.
    """
    fake_home = tmp_path_factory.mktemp("hermetic_home")
    # Pre-seed config files so bootstrap() finds them and never prompts,
    # even when stdin is a TTY (e.g. during local development).
    ishproject_cfg = fake_home / ".config" / "ishlib" / "ishproject.toml"
    ishproject_cfg.parent.mkdir(parents=True, exist_ok=True)
    ishproject_cfg.write_text(
        '[ishproject]\nprefix = "ishlib"\npostfix = "ishproject"\n',
        encoding="utf-8",
    )
    clean = {k: os.environ[k] for k in _PASSTHROUGH if k in os.environ}
    clean["HOME"] = str(fake_home)
    clean["USERPROFILE"] = str(fake_home)
    clean["XDG_CONFIG_HOME"] = str(fake_home / ".config")
    clean["XDG_CACHE_HOME"] = str(fake_home / ".cache")
    clean["XDG_DATA_HOME"] = str(fake_home / ".local" / "share")
    clean.update(_SYNTHETIC)
    os.environ.clear()
    os.environ.update(clean)
