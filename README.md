# ishlib

> [!WARNING]
> This repository is intended for personal use and contains lots of broken,
> nonsensical and overly complex solutions for simple problems...

A modular shell scripting library providing utility functions for sysadmin and
development tasks.

## Components

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash
  function library built from modular sources in `src/sh/` and `src/bash/`.
  See the [shell library documentation](docs/ishlib.md) for the full function
  reference.

- **Python library** (`src/pyishlib/`): Installer framework with backends for
  apt, brew, cargo, and pip.

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
make docs/ishlib.md
```

## Repository structure

```text
src/
  sh/         # POSIX-compliant shell functions (sourced into ishlib.sh)
  bash/       # Bash-only extensions (sourced into ishlib.sh)
  pyishlib/   # Python installer framework
  schema/     # Config schemas
pytest/       # Test suite (shell + python)
t/            # Legacy Perl/TAP tests
docs/         # Generated documentation
```

## Known bugs and issues

- Documentation for `dry_run` is wrong.
