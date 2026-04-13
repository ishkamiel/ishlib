# CLAUDE.md

## Project Overview

**ishlib** is a modular shell scripting library providing utility functions for sysadmin and development tasks. It has three components:

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash function library built from modular sources in `src/`
- **Python library** (`src/pyishlib/`): Installer framework with backends for apt, brew, cargo, dnf, pip, winget, and custom scripts; plus the `ishfiles` CLI for dotfile/package/script management
- **isholate** (`src/pyishlib/isholate/`, entry point `bin/isholate`): Incus-based isolation containers with host user mirroring for testing `ishfiles` setups without touching the real home directory. Linux-only.

## Repository Structure

```text
src/
  sh/             # POSIX-compliant shell functions (sourced into ishlib.sh)
  bash/           # Bash-only extensions (sourced into ishlib.sh)
  pyishlib/       # Python installer framework (shared primitives)
    ishfiles/     # ishfiles CLI subcommand modules (dotfiles/packages/scripts/externals)
      commands/   # One module per subcommand: add, apply, cd, diff,
                  #   external, git, init, install, log, pd, runscripts
    isholate/     # isholate CLI (Incus container launcher): cli, config, container
  schema/         # Config schemas (JSON)
  docs/           # Documentation *sources* (intro templates etc.)
pytest/
  shell/          # Shell function tests (parametrized across bash, dash, sh, zsh)
  python/         # Python unit tests
t/                # Legacy Perl/TAP tests, run via `prove` by pytest/shell/test_legacy_prove.py
scripts/          # Build scripts (build_ishlib.py, build_pydocs.py)
bin/              # Executable entry points (ishfiles, isholate)
docs/             # Generated MkDocs site pages (do not edit by hand)
  ishlib_shell.md     # Generated shell function reference
  pyishlib/           # Generated Python library reference (per-module pages)
  ishfiles.md         # CLI tool docs (placeholder)
.github/workflows/   # CI workflows (pre-commit, pylint, pytest, docs)
```

`src/docs/` holds hand-written documentation **sources**; `docs/` is the
published MkDocs site (mostly generated). Don't confuse the two.

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

To run a single test file or test function:

```bash
pytest pytest/shell/test_func-path.py            # one test file
pytest pytest/shell/test_func-path.py::test_name  # one test function
pytest -k "test_pattern"                          # by name pattern
```

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

- Formatted with **ruff-format**
- Linted with **ruff** (pytest/ directory is excluded)
- 4-space indentation
- Files must include the MIT license header (auto-inserted by pre-commit)

### General

- Indentation: 2 spaces for shell/YAML/JSON, 4 spaces for Python, tabs for Makefile
- LF line endings, final newline required
- No trailing whitespace

## Testing Patterns

### Shell Tests (`pytest/shell/`)

Shell tests execute scripts in subprocesses across multiple shells. Shared helpers live in `pytest/shell/__init__.py`:

- `gen_script_and_check_output(shell, tmp_path, script_content)` -- write and run a script, return stdout
- `gen_file(tmp_path, content)` -- write a temp `test.sh` file

Each test file defines `pytest_generate_tests` to set which shells to parametrize:

```python
import inspect
from . import gen_script_and_check_output

def pytest_generate_tests(metafunc):
    metafunc.parametrize("shell", ["bash", "dash", "sh", "zsh"])  # or ["bash"] for bash-only

def test_example(shell, tmp_path, ishlib):
    out = gen_script_and_check_output(shell, tmp_path, inspect.cleandoc(f"""
    #!/usr/bin/env {shell}
    . "{ishlib}"
    ish_say "hello"
    """))
    assert "hello" in out
```

### Python Tests (`pytest/python/`)

Python tests use `unittest.TestCase` classes with `@patch` for mocking. No shared conftest -- each file imports directly from `pyishlib`.

## Pre-commit Hooks

The repo uses pre-commit with: ruff (lint + format), mypy, markdownlint, typos, license header insertion, and pytest. Shellcheck is exercised via the pytest shell tests rather than a dedicated pre-commit hook.

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

## Build Pipeline Details

`scripts/build_ishlib.py` compiles `ishlib.sh` from `src/sh/base.sh` as the entry point:

- Include directives (`. "$ISHLIB/path/to/file"`) are recursively expanded inline
- `__ISHLIB_VERSION__` and `__ISHLIB_NAME__` are replaced with build-time values
- Shellcheck directives and source guards are stripped
- POSIX functions are included first, then a shell gate (`[ -z "${BASH_VERSION:-}" ]`) causes early return for non-bash shells, followed by bash-only extensions

## Markdown Linting

Markdownlint (mdl) excludes rules: MD013 (line length), MD024 (duplicate headers), MD026 (trailing punctuation in headers). Generated docs (`docs/ishlib_shell.md`, `docs/pyishlib/`) are excluded from linting.

## ishfiles CLI Architecture

The `ishfiles` CLI tool (`src/pyishlib/ishfiles/`) manages dotfiles, packages, and scripts. Key design rules:

### IshConfig as the Single Source of Truth

All configuration — directory names, file names, defaults, and constants — flows through the `IshConfig` object built by `ishfiles/config.py:load_config()`. Components must **never** import path constants directly from other modules; instead, read them from the `cfg` (`IshConfig`) instance via `cfg.get_opt("name")`.

- **Constants** (read-only): Reserved directory and file names (`config_dir`, `scripts_dir`, `installers_dir`, `ignore_file`, `package_files`, `data_file`, `externals_config_file`, `externals_cache_dirname`, `externals_state_filename`) plus the resolved `config_file` path for the current invocation are registered via `cfg.set_constant()` in `load_config()`. They cannot be overridden by CLI args, TOML config, or defaults. Attempting to shadow a constant via `set_default()` raises `ValueError`.
- **Defaults** (overridable): Values like `source`, `target`, `patterns` that users can override via CLI args or TOML config.
- **Lookup priority**: constants > args > conf > defaults.

New ishfiles-specific directory or file name constants should be defined in `ishfiles/config.py` and registered as constants on `IshConfig`.

### DotfileContext and Preprocessing Variables

Preprocessing variables (used in `${__ish_<name>}` substitution and `@ish if` conditionals) are stored on `cfg.context`, a `DotfileContext` instance that is a field of `IshConfig`. `DotfileContext` lives in `src/pyishlib/dotfile_context.py` (not in `environment.py`). Components that need preprocessing variables should read them from `cfg.context.as_dict()` — never accept a separate `variables` parameter.

- `DotfileContext` is auto-populated on construction with platform detection defaults. Additional variables can be set via `cfg.context.set(name, value)`.
- Components access it via `cfg.context.as_dict()` when constructing a `FilePreprocessor` or `DotFilePreprocessor`.
- In `@ish if` expressions, the context is exposed as the `ish` namespace (e.g., `ish.platform == 'linux'`). An `EnvironmentNamespace` is attached as `ish.env`, providing live checks such as `ish.env.is_linux()` and `ish.env.is_macos()`.
- The dotfiles source directory is read from `cfg.get_opt("source")`, not passed as a separate `dotfiles_dir` parameter.

### Subcommand Pattern

Subcommands live in `ishfiles/commands/<name>.py` with `register(subparsers)` and `run(cfg)` functions. Register new commands in `ishfiles/cli.py`. Current subcommands:

- `add` — add a file to the dotfiles source
- `apply` — the main pipeline (see below)
- `cd` — spawn a subshell in the dotfiles source directory (fallback; see `init` for a real cd)
- `diff` — show pending dotfile changes without applying
- `external` — manage external git-repo dotfiles (`apply`/`update`/`list`)
- `init [--bash|--zsh|--sh]` — print shell integration; eval in your rc so `ishfiles cd` does a real cwd change
- `pd` — print the dotfiles source directory path (used by the `init` shell wrapper)
- `git` — proxy `git` commands against the dotfiles source
- `install` — run the installer pipeline (packages only)
- `log` — inspect script-run logs
- `runscripts` — execute user scripts only (bypasses the rest of apply)

### The `apply` Pipeline

`apply` runs in six phases (see `ishfiles/commands/apply.py:run`):

- **Phase 0 — Self-links**: create `~/.local/bin` symlinks to `ishfiles` and `isholate` so the tools are on the user's PATH. Best-effort; failures log a warning.
- **Phase 1 — Scan**: discover dotfiles and scripts, read `__ISH__` metadata, apply OS/tag filtering, and collect embedded package declarations.
- **Phase 2 — Merge**: combine metadata-declared packages with the main package list.
- **Phase 3 — Install**: run the installer pipeline for all packages (main + metadata).
- **Phase 4 — Apply dotfiles**: preprocess and install changed dotfiles.
- **Phase 4b — Externals**: fetch and install external git-repo dotfiles (see the Externals section below).
- **Phase 5 — Scripts**: execute user scripts with logging and `run_when` state gating.

Flags:

- `--dotfiles-only` skips phases 3, 4b, and 5 (package install, externals, scripts).
- `--force-scripts [NAMES...]` re-runs named scripts (or all, with no names) ignoring `run_when` state.
- `--isholate` (internal, used by `isholate` when provisioning containers): for each `data.toml` entry that carries an `isholate = <value>` key, uses that hardcoded value instead of the user's saved/prompted value. Overrides are never written back to the config file.

### Filename Prefixes for Dotfiles

Files in the dotfiles source can carry these prefixes (chezmoi-compatible):

- `dot_<name>` — target name becomes `.<name>` (e.g. `dot_bashrc` → `.bashrc`).
- `executable_<name>` — after the file is applied, the target is `chmod +x`'d (Windows is a no-op). The prefix is stripped from the target name and can combine with `dot_` (`dot_executable_foo` → `.foo`, executable).

### Externals

External git-repo dotfiles are declared in `<source>/ishconfig/externals.toml`. Support is implemented by the triplet in `src/pyishlib/ishfiles/`:

- `externals_config.py` — load/validate `ExternalSpec` entries from TOML.
- `externals.py` — `ExternalsEngine` fetches, caches, applies, and checks for updates.
- `externals_state.py` — persists resolved revisions to `<target>/.config/ishfiles/externals-state.json`.

The `external` subcommand exposes `apply`, `update`, and `list`. `apply_externals_stage()` is the entry point called as Phase 4b of `apply`. The cache lives in `<source>/.cache/` (reserved, ignored for dotfile application).

### Reserved Directories in Dotfile Source

The ishfiles source folder reserves these directories (ignored during dotfile application):

- `ishconfig/` — package configuration (`packages.toml` / `packages.json`), data templates (`data.toml`), and externals config (`externals.toml`)
- `ishscripts/` — user scripts executed on `apply` and `runscripts`
- `ishinstallers/` — custom per-package install scripts
- `.cache/` — externals fetch cache (managed by `ExternalsEngine`)

### Installer Backends

Package installer backends live at `src/pyishlib/installer_*.py` and all subclass `InstallerBase` (`installer_base.py`):

- `installer_apt.py` — Debian/Ubuntu (`apt`)
- `installer_brew.py` — Homebrew (`brew`)
- `installer_cargo.py` — Rust toolchain (`cargo` + `rustup`)
- `installer_dnf.py` — Fedora/RHEL (`dnf`)
- `installer_pip.py` — Python packages (`pip` / `pip3` / `python -m pip`)
- `installer_winget.py` — Windows Package Manager
- `installer_custom.py` — arbitrary per-package install scripts

Backends implement the abstract methods (`is_pkg_installed`, `install_pkgs`, `update_pkgs`, `update_and_install_all`). Two `InstallerBase` helpers exist to reduce boilerplate and should be preferred over open-coding:

- `self._run_cmd(cmd, *, sudo=False, action="running")` — run a subprocess via `self.runner`, log a critical message and re-raise on `CalledProcessError`. Use this everywhere an install/update command is invoked.
- `self._require_available()` — raises `RuntimeError` if the backend's tool is missing. Use this instead of `assert self.can_install()` for public-entry preconditions (asserts can be stripped by `python -O`).

### Output & Logging Convention

Three distinct channels, picked by purpose:

- **`logging`** (via `log = logging.getLogger(__name__)`) — all diagnostic messages, status info (`log.info`), recoverable errors (`log.warning`), and terminal failures (`log.critical`). Honours the CLI `--verbose` / `--quiet` flags.
- **`pyishlib.userio`** — every interactive prompt (yes/no/always, string, choice) goes through this module so non-interactive environments and tests have a single seam to patch.
- **`print()`** — only for deliberate, structured CLI output that is the command's product (`diff`, `log`, metadata dumps, run summaries). Do not use `print` for status chatter that should respect verbosity — use logging instead.

### Environment Detection (`environment.py`)

`src/pyishlib/environment.py` is the single home for **all OS/distro detection, platform-conditional logic, and environment checks**. Key functions:

- `detect_os()` — returns `"linux"`, `"macos"`, or `"windows"`
- `detect_distro()` — returns distro family (`"debian"`, `"fedora"`) on Linux, or `None`
- `detect_os_tags()` — returns all applicable tags (e.g. `["linux", "debian"]`)
- `normalise_os(name)` — canonicalises OS/distro aliases (e.g. `"ubuntu"` → `"debian"`, `"darwin"` → `"macos"`)
- `should_skip_for_os(only_on, ignore_on, current_os)` — evaluates OS-conditional rules
- `should_skip_for_os_from_metadata(metadata, current_os)` — checks `only_on`/`ignore_on` keys in `__ISH__` metadata
- `is_linux()`, `is_macos()`, `is_windows()`, `is_ubuntu()`, `is_gnome()`, `is_linux_desktop()` — simple boolean environment checks

New OS detection, platform-conditional logic, or environment helpers should be added to this module. `CommandRunner` (`src/pyishlib/command_runner.py`) handles command execution, file operations, and sudo — it delegates to `environment.py` for platform checks.

Call these helpers from everywhere else — do not reach for `sys.platform` directly outside `environment.py`. The one intentional exception is `userio.getch`, which keeps `if sys.platform == "win32":` so mypy can narrow the branch for the Windows-only `msvcrt` import.

### OS-conditional Ignore Rules

Ignore files (`.ishignore`, `.dotfileignore`) support OS-conditional sections:

- `[only_on.<os>]` — patterns listed here apply *only* on `<os>`; they are ignored on all other platforms.
- `[ignore_on.<os>]` — patterns listed here are ignored *on* `<os>`; they have no effect on other platforms.

Recognised OS/distro names: `linux`, `macos`, `windows`, `unixlike` (Linux or macOS), `debian` (includes Ubuntu, Mint, Pop!_OS, etc.), `fedora` (includes RHEL, CentOS, Asahi Remix, etc.). Common aliases (`mac`, `darwin`, `win`, `ubuntu`) are accepted and normalised.

Matching is hierarchical: a system running Ubuntu matches both `debian` and `linux` rules.

`only_on` uses **AND** semantics — all listed tags must match the current system. Listing multiple tags narrows the target further (e.g. `["linux", "debian"]` means Debian-family Linux only). Use `unixlike` as a shorthand for "Linux or macOS":

Files and scripts can also use `only_on` and `ignore_on` keys in their `__ISH__` metadata (TOML) to control per-file OS filtering:

```toml
only_on = ["unixlike"]
ignore_on = ["fedora"]
```

## isholate Architecture

`isholate` (`src/pyishlib/isholate/`, entry point `bin/isholate`) launches ephemeral Incus containers that mirror the host user so `ishfiles` setups can be tested without touching the real `$HOME`. Linux-only — `cli.main` bails out on non-Linux hosts via `environment.is_linux()`.

Key modules:

- `cli.py` — argparse front-end, subcommands (`run`, `purge`, …). Discovers a project-local overlay at `.isholate/ishconfig/isholate.toml` before parsing args so image/shell overrides take effect.
- `config.py` — TOML config loading, host-ishfiles-source discovery, and project overlay resolution.
- `container.py` — container lifecycle: create/launch/exec, host user/group mirroring, bind-mount handling, purge.

When editing isholate, keep the boundary with `pyishlib` clean: reuse `environment.py` for platform checks and `command_runner.py` for subprocess execution rather than re-implementing them.

## ishfiles Manual Testing Safety

**Never run `ishfiles apply`, `install`, or `runscripts` against the real home directory.** These commands modify files and install packages. Only use `ishfiles diff` for manual testing, and always point to safe temporary directories:

```bash
TEST_HOME=$(mktemp -d)
TEST_CONFIG="$TEST_HOME/.config/ishfiles/config.toml"
mkdir -p "$(dirname "$TEST_CONFIG")"

# Safe: diff only, temp home, temp config
./bin/ishfiles --home "$TEST_HOME" -s /path/to/dotfiles -c "$TEST_CONFIG" diff

# Inspect results
cat "$TEST_CONFIG"

# Clean up
rm -rf "$TEST_HOME"
```

The `--home`, `-s` (source), and `-c` (config) flags redirect all file operations away from `$HOME`. Unit tests in `pytest/` use temp directories and are always safe to run.

## Important Warnings

- **Never edit `ishlib.sh`, `docs/ishlib_shell.md`, or `docs/pyishlib/` directly** - they are generated. Edit sources in `src/` and run `make`.
- Documentation sources live in `src/docs/`; the `docs/` directory contains MkDocs site pages (some hand-written, some generated). Python docs are generated by `scripts/build_pydocs.py` from `src/pyishlib/` docstrings.
- Shell tests are parametrized across multiple shells (bash, dash, sh, zsh). Ensure POSIX functions work in all of them.
- The `t/` directory contains legacy Perl/TAP tests run via `prove` (invoked by `pytest/shell/test_legacy_prove.py`). Do not add new tests there; use `pytest/` instead.
