# ishlib

> [!WARNING]
> This repository is intended for personal use and contains lots of broken,
> nonsensical and overly complex solutions for simple problems...

A modular shell scripting library and Python toolkit for sysadmin and
development tasks.

## Components

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash
  function library built from modular sources in `src/sh/` and `src/bash/`.
  See the [shell library documentation](https://github.com/ishkamiel/ishlib/wiki/ishlib_shell) for the full
  function reference.

- **Python library** (`src/pyishlib/`): Shared Python framework providing
  package installation backends (apt, dnf, brew, cargo, pip, winget, custom
  scripts), dotfile preprocessing, OS/distro detection, and a command runner
  with dry-run and sudo support.
  See the [Python library documentation](https://github.com/ishkamiel/ishlib/wiki/pyishlib) for details.

- **ishfiles**: CLI tool for managing dotfiles, packages, and post-install
  scripts. Subcommands: `apply`, `diff`, `add`, `install`, `runscripts`,
  `external`, `git`, `log`.
  See the [ishfiles documentation](https://github.com/ishkamiel/ishlib/wiki/ishfiles) for usage details.

- **isholate**: CLI tool for launching ephemeral [Incus](https://linuxcontainers.org/incus/)
  containers with the host user mirrored and optional bind mounts.

## Stable alternatives to ishfiles

> [!CAUTION]
> **ishfiles is not stable.** It is a personal project under active
> development, with breaking changes made without notice. Do not use it for
> anything you care about.

If you are looking for a dotfile manager that actually works, use one of these
instead:

- **[chezmoi](https://www.chezmoi.io/)** — feature-rich, well-documented, and
  widely used. Handles templating, secrets, and cross-platform setups.
- **[dotbot](https://github.com/anishathalye/dotbot)** — minimal and
  configuration-driven. Easy to understand and extend.

## Quick start

Source `ishlib.sh` in your script:

```sh
. /path/to/ishlib.sh
```

Or run it directly for the built-in help:

```sh
./ishlib.sh -h
```

## Installing the Python tools (`ishfiles`, `isholate`, `ishproject`)

Pick whichever fits your environment.  Options 1 and 2 install ishlib
as a real Python package and put launchers on `$PATH` that are
independent of the repo's location — moving or deleting the source
tree leaves them working.  Option 3 keeps a hard link back to this
checkout: it is the developer/live-edit path and breaks if you move
the repo.

1. **pipx (recommended).** Creates a dedicated virtualenv under
   `~/.local/pipx/venvs/ishlib/` and shims on `$PATH`.  Independent of
   any active venv, pyenv shell, or current working directory.

   ```sh
   pipx install '/path/to/ishlib[full]'   # all extras
   pipx install /path/to/ishlib            # minimal
   pipx install --editable '/path/to/ishlib[full]'   # live edits
   ```

2. **`pip install --user`.** Same shape, lives in `--user` site instead
   of a private venv.  Use this when pipx is unavailable.

   ```sh
   pip install --user '.[full]'
   ```

3. **In-tree launchers (developer fallback).** Generates wrappers in
   `~/.local/bin/` that bake in this repo's `src/` path.  Works without
   pipx/pip-install permissions but breaks if you move the repo.

   ```sh
   bin/ishlib-install --full     # also pip-installs the optional extras
   bin/ishlib-install            # launchers only
   ```

After installing, run `ishfiles doctor` to verify the optional
packages (`shtab`, `cerberus`, `jsonschema`, `PyYAML`, `tomli_w`)
resolved against the active interpreter.

## Building

```bash
# Build everything and run tests
make all

# Build just ishlib.sh from sources
make ishlib.sh

# Build wiki pages locally
make wiki
```
