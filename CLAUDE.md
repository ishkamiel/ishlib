# CLAUDE.md

## Project Overview

**ishlib** is a modular shell scripting library providing utility functions for sysadmin and development tasks. It has two components:

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash function library built from modular sources in `src/`
- **Python library** (`src/pyishlib/`): Installer framework with backends for apt, brew, cargo, and pip

## Repository Structure

```
src/
  sh/         # POSIX-compliant shell functions (sourced into ishlib.sh)
  bash/       # Bash-only extensions (sourced into ishlib.sh)
  pyishlib/   # Python installer framework
  schema/     # Config schemas
pytest/
  shell/      # Shell function tests (parametrized across bash, dash, sh, zsh)
  python/     # Python unit tests
t/            # Legacy Perl/TAP tests, run via `prove` by pytest/shell/test_legacy_prove.py
```

Key root files:

- `ishlib.sh` - **Generated file**. Do NOT edit directly; modify sources in `src/sh/` and `src/bash/` then rebuild.
- `build_ishlib.py` - Build script that compiles modular sources into `ishlib.sh`
- `README.md` - **Generated file**. Auto-generated from docstrings via `./ishlib.sh -h --markdown`
- `Makefile` - Build orchestration

## Build and Test Commands

```bash
# Build everything and run tests
make all

# Build just ishlib.sh from sources
make ishlib.sh

# Regenerate README.md from docstrings
make README.md

# Run tests only
make verify
# or directly:
pytest
```

Pytest runs in parallel by default (`--numprocesses=auto` in `pytest.ini`).

## Key Conventions

### Shell Code

- **POSIX functions** go in `src/sh/*.sh`; **Bash-only functions** go in `src/bash/*.bash`
- Every source file must have a **source guard**:
  ```sh
  [ -n "${ish_SOURCED_module:-}" ] && return 0
  ish_SOURCED_module=1
  ```
- Document functions with **DOCSTRING heredocs**:
  ```sh
  : <<'DOCSTRING'
  `function_name args...`

  Description.

  ##### Arguments:
  arg1 - description

  ##### Returns:
  0 - on success
  DOCSTRING
  ```
- Variable naming: globals use `ish_` prefix (e.g., `ish_VERSION`), locals use `_` prefix (e.g., `_target`), constants are UPPERCASE
- Output goes to stderr via `ish_say`, `ish_warn`, `ish_fail`
- Many functions respect the `DRY_RUN` flag
- Shebangs: `#!/usr/bin/env sh` for POSIX files, `#!/usr/bin/env bash` for Bash files

### Python Code

- Formatted with **Black**
- Linted with **Pylint** (pytest/ directory is excluded from pylint)
- 4-space indentation
- Files must include the MIT license header (auto-inserted by pre-commit)
- `# -*- coding: utf-8 -*-` at top of files

### General

- Indentation: 2 spaces for shell/YAML/JSON, 4 spaces for Python, tabs for Makefile
- LF line endings, final newline required
- No trailing whitespace

## Pre-commit Hooks

The repo uses pre-commit with: pylint, black, markdownlint, typos, license header insertion, and pytest. Shellcheck is exercised via the pytest shell tests rather than a dedicated pre-commit hook.

## CI

GitHub Actions runs two workflows on push and pull request:

- **Pylint** (`.github/workflows/pylint.yml`): Runs pylint across Python 3.8-3.12 (on push)
- **Pytest** (`.github/workflows/pytest.yml`): Runs the full test suite across Python 3.8-3.12 with shellcheck/dash/zsh for cross-shell testing (on push and pull request)

## Important Warnings

- **Never edit `ishlib.sh` or `README.md` directly** - they are generated. Edit sources in `src/` and run `make`.
- Shell tests are parametrized across multiple shells (bash, dash, sh, zsh). Ensure POSIX functions work in all of them.
- The `t/` directory contains legacy Perl/TAP tests run via `prove` (invoked by `pytest/shell/test_legacy_prove.py`). Do not add new tests there; use `pytest/` instead.
