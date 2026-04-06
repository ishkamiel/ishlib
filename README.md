# ishlib

> [!WARNING]
> This repository is intended for personal use and contains lots of broken,
> nonsensical and overly complex solutions for simple problems...

A modular shell scripting library providing utility functions for sysadmin and
development tasks.

## Components

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash
  function library built from modular sources in `src/sh/` and `src/bash/`.
  See the [shell library documentation](docs/ishlib_shell.md) for the full
  function reference.

- **Python library** (`src/pyishlib/`): Installer framework with backends for
  apt, brew, cargo, pip, and winget.
  See the [Python library documentation](docs/pyishlib/index.md) for details.

- **ishfiles** (planned): CLI tool built on `pyishlib` for managing system
  configuration and dotfiles.
  <!-- TODO: Add ishfiles quick start and usage documentation here once the
       CLI tool is implemented. -->

## Quick start

Source `ishlib.sh` in your script:

```sh
. /path/to/ishlib.sh
```

Or run it directly for the built-in help:

```sh
./ishlib.sh -h
```

## Building

```bash
# Build everything and run tests
make all

# Build just ishlib.sh from sources
make ishlib.sh

# Regenerate shell docs
make docs/ishlib_shell.md

# Serve documentation locally (MkDocs)
mkdocs serve
```

## Repository structure

```text
src/
  sh/         # POSIX-compliant shell functions (sourced into ishlib.sh)
  bash/       # Bash-only extensions (sourced into ishlib.sh)
  pyishlib/   # Python installer framework
  schema/     # Config schemas
  docs/       # Documentation sources
pytest/       # Test suite (shell + python)
t/            # Legacy Perl/TAP tests
docs/         # Generated/served documentation (MkDocs site source)
```
