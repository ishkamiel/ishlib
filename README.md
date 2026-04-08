# ishlib

> [!WARNING]
> This repository is intended for personal use and contains lots of broken,
> nonsensical and overly complex solutions for simple problems...

A modular shell scripting library providing utility functions for sysadmin and
development tasks.

## Components

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash
  function library built from modular sources in `src/sh/` and `src/bash/`.
  See the [shell library documentation](../../wiki/ishlib_shell) for the full
  function reference.

- **Python library** (`src/pyishlib/`): Installer framework with backends for
  apt, brew, cargo, pip, and winget.
  See the [Python library documentation](../../wiki/pyishlib) for details.

- **ishfiles**: CLI tool built on `pyishlib` for managing dotfiles and
  package installations.
  See the [ishfiles documentation](../../wiki/ishfiles) for usage details.

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

# Build wiki pages locally
make wiki
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
```
