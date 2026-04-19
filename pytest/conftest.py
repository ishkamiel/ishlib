# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Top-level pytest configuration shared by all test workers.

## GIT_* environment isolation

Pre-commit sets GIT_DIR (and related variables) to point at the project's
own git index before invoking pytest. Any test that spawns a git subprocess
without an explicit clean env would therefore operate on the real repository
instead of its own temp directory, potentially corrupting the staged index.

Rather than requiring every call site to blacklist specific variable names,
this conftest strips all GIT_* variables from os.environ at session start.
Each xdist worker process gets its own copy of the environment, so the
fixture runs independently and safely in every worker.

Tests that genuinely need specific git env vars (e.g. GIT_AUTHOR_NAME) should
set them explicitly via monkeypatch.setenv or by building an env dict in the
test itself.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _strip_git_env():
    """Remove all GIT_* env vars for the duration of the test session."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        del os.environ[key]
