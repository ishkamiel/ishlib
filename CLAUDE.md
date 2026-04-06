# CLAUDE.md

## Project Overview

**ishlib** is a modular shell scripting library providing utility functions for sysadmin and development tasks. It has two components:

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash function library built from modular sources in `src/`
- **Python library** (`src/pyishlib/`): Installer framework with backends for apt, brew, cargo, pip, and winget

## Repository Structure

```text
src/
  sh/             # POSIX-compliant shell functions (sourced into ishlib.sh)
  bash/           # Bash-only extensions (sourced into ishlib.sh)
  pyishlib/       # Python installer framework
    ishfiles/     # CLI tool subcommand modules
  schema/         # Config schemas (JSON)
  docs/           # Documentation sources (e.g., shell library intro template)
pytest/
  shell/          # Shell function tests (parametrized across bash, dash, sh, zsh)
  python/         # Python unit tests
t/                # Legacy Perl/TAP tests, run via `prove` by pytest/shell/test_legacy_prove.py
scripts/          # Build scripts (build_ishlib.py, build_pydocs.py)
bin/              # Executable scripts
docs/             # MkDocs site source and generated docs
  ishlib_shell.md     # Generated shell function reference
  pyishlib/           # Generated Python library reference (per-module pages)
  ishfiles.md         # CLI tool docs (placeholder)
.github/workflows/   # CI workflows (pre-commit, pylint, pytest, docs)
```

Key root files:

- `ishlib.sh` - **Generated file**. Do NOT edit directly; modify sources in `src/sh/` and `src/bash/` then rebuild.
- `scripts/build_ishlib.py` - Build script that compiles modular sources into `ishlib.sh`
- `scripts/build_pydocs.py` - Build script that generates Python API docs from docstrings
- `mkdocs.yml` - MkDocs configuration for documentation site
- `README.md` - Project overview (hand-written)
- `docs/ishlib_shell.md` - **Generated file**. Auto-generated from docstrings via `./ishlib.sh -h --markdown`
- `docs/pyishlib/` - **Generated files**. Auto-generated from docstrings via `scripts/build_pydocs.py`
- `Makefile` - Build orchestration

## Build and Test Commands

```bash
# Build everything and run tests
make all

# Build just ishlib.sh from sources
make ishlib.sh

# Regenerate shell library docs from docstrings
make docs/ishlib_shell.md

# Regenerate Python library docs from docstrings
make docs/pyishlib/index.md

# Serve documentation site locally
mkdocs serve

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

### General

- Indentation: 2 spaces for shell/YAML/JSON, 4 spaces for Python, tabs for Makefile
- LF line endings, final newline required
- No trailing whitespace

## Pre-commit Hooks

The repo uses pre-commit with: pylint, black, markdownlint, typos, license header insertion, and pytest. Shellcheck is exercised via the pytest shell tests rather than a dedicated pre-commit hook.

## CI

GitHub Actions runs four workflows:

- **Pre-commit** (`.github/workflows/pre-commit.yml`): Runs all pre-commit hooks with Python 3.13 (on push and pull request)
- **Pylint** (`.github/workflows/pylint.yml`): Runs pylint with Python 3.12 (on push only, not pull request)
- **Pytest** (`.github/workflows/pytest.yml`): Runs the full test suite across Python 3.8-3.12 with shellcheck/dash/zsh for cross-shell testing (on push and pull request)
- **Docs** (`.github/workflows/docs.yml`): Verifies generated docs (`docs/ishlib_shell.md`, `docs/pyishlib/`) are up to date (on push and pull request)

## Config File Support

The `pyishlib` installer framework supports loading package configuration from **JSON** (`InstallerConfigJSON`) and **TOML** (`InstallerConfigTOML`) files. Both formats use the same Cerberus schema validation. TOML support uses `tomllib` (Python 3.11+ stdlib) with automatic fallback to the `tomli` package for older Python versions.

## Python Version Support

- Development environment uses Python 3.13.2 (`.python-version`)
- CI tests against Python 3.8, 3.9, 3.10, 3.11, 3.12
- TOML support uses `tomllib` (Python 3.11+ stdlib) with `tomli` fallback for older versions (declared in `requirements.txt`)

## Important Warnings

- **Never edit `ishlib.sh`, `docs/ishlib_shell.md`, or `docs/pyishlib/` directly** - they are generated. Edit sources in `src/` and run `make`.
- Documentation sources live in `src/docs/`; the `docs/` directory contains MkDocs site pages (some hand-written, some generated). Python docs are generated by `scripts/build_pydocs.py` from `src/pyishlib/` docstrings.
- Shell tests are parametrized across multiple shells (bash, dash, sh, zsh). Ensure POSIX functions work in all of them.
- The `t/` directory contains legacy Perl/TAP tests run via `prove` (invoked by `pytest/shell/test_legacy_prove.py`). Do not add new tests there; use `pytest/` instead.
