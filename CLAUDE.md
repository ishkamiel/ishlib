# CLAUDE.md

## Project Overview

**ishlib** is a modular shell scripting library providing utility functions for sysadmin and development tasks. It has three components:

- **Shell library** (`ishlib.sh`): A compiled, self-documenting POSIX/Bash function library built from modular sources in `src/`
- **Python library** (`src/pyishlib/`): Installer framework with backends for apt, brew, cargo, dnf, pip, winget, and custom scripts; plus the `ishfiles` CLI for dotfile/package/script management
- **isholate** (`src/pyishlib/isholate/`): Incus-based isolation containers with host user mirroring for testing `ishfiles` setups without touching the real home directory. Linux-only.

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
    schema/       # Config schemas (JSON), shipped with the package
  docs/           # Documentation *sources* (intro templates etc.)
pytest/
  shell/          # Shell function tests (parametrized across bash, dash, sh, zsh)
  python/         # Python unit tests
t/                # Legacy Perl/TAP tests, run via `prove` by pytest/shell/test_legacy_prove.py
scripts/          # Build scripts (build_ishlib.py, build_pydocs.py)
bin/              # Bootstrap entry point (ishlib-install)
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

## Python Environment

This project uses a `.venv` managed by direnv (`.envrc` + `layout pyenv`). Always invoke Python and Python-based tools (`pytest`, `ruff`, `mypy`, `mkdocs`, …) via the `.venv`:

```bash
.venv/bin/python   # Python interpreter
.venv/bin/pytest   # test runner
.venv/bin/ruff     # linter/formatter
.venv/bin/mypy     # type checker
```

If `.venv` is missing or a tool is not found inside it, ask the user to set it up or update it before proceeding:

```bash
# From the ishlib directory:
direnv allow    # activates the layout and creates/updates .venv
# or manually:
python -m venv .venv && .venv/bin/pip install -U 'pip>=25.1' && .venv/bin/pip install --group dev
```

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

### System dependencies for tests

Beyond the Python deps installed via `pip install --group test --group extras`,
the test suite also relies on a handful of system binaries:

| Binary | Lane | Notes |
|---|---|---|
| `bash`, `dash`, `sh`, `zsh` | `pytest/shell/` | Cross-shell parametrization; missing shells skip individually. |
| `shellcheck` | `pytest/shell/` | Linting; missing skips the shellcheck tests only. |
| `bwrap` (bubblewrap) | `pytest/integration/` | Per-scenario mount namespace. Without it the integration lane skips with an install hint; never falls back to unisolated execution. |
| `git`, `prove` | misc | Already standard on Linux dev/CI. |

Install on Debian/Ubuntu:

```bash
sudo apt-get install -y shellcheck dash zsh bubblewrap
```

CI (`.github/workflows/pytest.yml`) installs the same set. `pytest/integration/`
is Linux-only by design (the macOS and Windows jobs already restrict to
`pytest/python/`); on other platforms the integration lane is reported as
skipped rather than failed.

#### Ubuntu 24.04 caveat: unprivileged user namespaces

Ubuntu 24.04 (noble) ships an AppArmor profile that blocks unprivileged user
namespaces by default, which makes `bwrap` fail with `setting up uid map:
Permission denied` even when invoked with `--unshare-user`.  CI works around
this with one extra step before pytest.  For local dev on 24.04, run the
same tweak once per boot:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
```

The sysctl does not exist on older kernels and is irrelevant on 22.04 or
on container hosts that already opt out of the restriction.

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
- Output goes to stderr via `ish_warning`, `ish_error`, `ish_critical`
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
    ish_info "hello"
    """))
    assert "hello" in out
```

### Python Tests (`pytest/python/`)

Python tests use `unittest.TestCase` classes with `@patch` for mocking. No shared conftest -- each file imports directly from `pyishlib`.

#### Hermetic subprocess environment — `pytest/conftest.py`

Pre-commit sets `GIT_DIR` and other variables before invoking pytest. Any test
that spawns a subprocess without an explicit `env=` argument would inherit the
host's full environment and might corrupt the real repository index, use the
host's signing keys, or behave differently across machines.

**`pytest/conftest.py` handles this globally.** A session-scoped `autouse`
fixture replaces `os.environ` wholesale at session start with a minimal,
deterministic environment:

- **Passed through from host**: `PATH`, `HOME`, `TMPDIR`/`TMP`/`TEMP` only.
- **Synthesised unconditionally**: `GIT_CONFIG_GLOBAL=/dev/null`,
  `GIT_CONFIG_SYSTEM=/dev/null`, and fixed git identity vars
  (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`,
  `GIT_COMMITTER_EMAIL`) so commits work without reading any per-user config.
- **Everything else is stripped** — no `GIT_DIR`, no `PYTHONPATH`, no signing
  keys, no credential helpers, nothing else from the host.

Each xdist worker gets its own `os.environ` copy, so the fixture runs
independently in every worker. Subprocesses spawned without an explicit `env=`
automatically inherit this clean environment.

Tests that need to override a specific variable for a scenario do so explicitly:

```python
env = os.environ.copy()   # already minimal; safe to copy and extend
env["MY_VAR"] = "value"
subprocess.run(["some-tool", ...], env=env, check=True)
```

Do **not** add per-test `_scrub_git_env()` helpers or inline `GIT_*` env setup —
the conftest covers all of it globally.

`CommandRunner.git()` and `GitRepo` methods additionally clear the four
dir-override vars (`GIT_DIR`, `GIT_INDEX_FILE`, `GIT_WORK_TREE`,
`GIT_OBJECT_DIRECTORY`) in production code paths so they are safe to call from
outside pytest as well (e.g. from `ishfiles apply` running under a git hook).

## Pre-commit Hooks

The repo uses pre-commit with: ruff (lint + format), mypy, markdownlint, typos, license header insertion, and pytest. Shellcheck is exercised via the pytest shell tests rather than a dedicated pre-commit hook.

## CI

GitHub Actions runs four workflows:

- **Pre-commit** (`.github/workflows/pre-commit.yml`): Runs all pre-commit hooks with Python 3.13 (on push and pull request)
- **Pylint** (`.github/workflows/pylint.yml`): Runs pylint with Python 3.12 (on push only, not pull request)
- **Pytest** (`.github/workflows/pytest.yml`): Runs the full test suite across Python 3.9-3.13 with shellcheck/dash/zsh for cross-shell testing (on push and pull request)
- **Docs** (`.github/workflows/docs.yml`): Verifies generated docs (`docs/ishlib_shell.md`, `docs/pyishlib/`) are up to date (on push and pull request)

### Accessing CI logs

The `gh` CLI is available and authenticated in this environment. Use it to access run logs, job output, and other GitHub Actions details that the MCP tools cannot provide:

```bash
# List recent runs for the PR branch
gh run list --repo ishkamiel/ishlib --branch <branch>

# View run summary (all jobs + annotations)
gh run view <run-id> --repo ishkamiel/ishlib

# Stream full step-level logs for a specific job
gh run view --job=<job-id> --repo ishkamiel/ishlib --log

# Show only failed step logs (empty output means all jobs passed)
gh run view <run-id> --repo ishkamiel/ishlib --log-failed
```

When investigating a CI failure on a PR, prefer `gh run view --log-failed` first, then drill into a specific job with `--job=<job-id> --log` if needed.

## Config File Support

The `pyishlib` installer framework supports loading package configuration from **JSON** (`InstallerConfigJSON`) and **TOML** (`InstallerConfigTOML`) files. Both formats use the same Cerberus schema validation. TOML support uses `tomllib` (Python 3.11+ stdlib) with automatic fallback to the `tomli` package for older Python versions.

## Python Version Support

- Development environment uses Python 3.13.2 (`.python-version`)
- CI tests against Python 3.9, 3.10, 3.11, 3.12, 3.13
- TOML support uses `tomllib` (Python 3.11+ stdlib) with `tomli` fallback for older versions (declared in `pyproject.toml`'s `runtime` dependency group)

## Build Pipeline Details

`scripts/build_ishlib.py` compiles `ishlib.sh` from `src/sh/base.sh` as the entry point:

- Include directives (`. "$ISHLIB/path/to/file"`) are recursively expanded inline
- `__ISHLIB_VERSION__` and `__ISHLIB_NAME__` are replaced with build-time values
- Shellcheck directives and source guards are stripped
- POSIX functions are included first, then a shell gate (`[ -z "${BASH_VERSION:-}" ]`) causes early return for non-bash shells, followed by bash-only extensions

## Markdown Linting

Markdownlint (mdl) excludes rules: MD013 (line length), MD024 (duplicate headers), MD026 (trailing punctuation in headers). Generated docs (`docs/ishlib_shell.md`, `docs/pyishlib/`) are excluded from linting.

## Python CLI Tools

Every Python CLI in ishlib (`ishfiles`, `isholate`, and any future tool) uses
**argparse subcommands** — never a flag-based dispatch layer (e.g. `--purge`,
`--run`). The subcommand shape is the public contract of the tool.

### Required structure

- Build the parser in a `build_parser()` function that returns the
  `argparse.ArgumentParser`. Keep argparse wiring out of `main()` so tests can
  call `build_parser()` directly.
- Use `parser.add_subparsers(dest="subcommand", required=True, metavar="COMMAND")`.
  A missing subcommand must be an argparse error, not a silent default.
- Put each subcommand in its own module and register it via a common pattern.
  **ishfiles**: `ishfiles/commands/<name>.py` with `register(subparsers)`
  and `run(cfg)` functions; register the module in `ishfiles/cli.py`.
  **isholate**: subcommand definitions live in `isholate/cli.py`'s
  `build_parser()`, and each subcommand dispatches to a named function
  (e.g. `_run_subcommand`, `purge_containers`, `list_containers`,
  `stop_containers`) in `isholate/container.py`.
- Always add a short, one-sentence `help=...` and a multi-sentence
  `description=...` on every subparser — both show up in `--help`.

### Common flags live on subparsers, NOT the top-level parser

`-v/-q` (and any other flag that should apply to every subcommand) **MUST**
be attached to each subparser individually. Do not attach them to the
top-level parser, because argparse's subparser namespace defaults will
silently overwrite values set by the top-level parse. Example of the bug
this rule prevents:

```python
# WRONG — args.verbose is 0, not 1
parser.add_argument("-v", action="count", default=0)
sub = parser.add_subparsers(dest="cmd", required=True)
p_run = sub.add_parser("run")
p_run.add_argument("-v", action="count", default=0)
parser.parse_args(["-v", "run"])  # subparser default=0 clobbers top-level -v
```

The accepted workaround is to attach the flags only to the subparsers (so
every subcommand accepts `-v`/`-q` after its own name) and to leave the
top-level parser empty apart from its subparsers. Factor the flag
definitions into a helper (e.g. `_add_common_args(parser)`) so every
subparser gets them consistently. The `parents=[common]` pattern suffers
from the same overwrite bug and must not be used for these flags.

### Adding or updating a subcommand

A new subcommand is always four things — don't skip any:

1. **Module** under the tool's `commands/` dir (or a clearly named function
   for isholate-style CLIs) that knows how to do the work. Input comes from
   `cfg` / `args`; output follows the logging convention (product output
   via `print()`, everything else via `log.*`).
2. **Parser wiring** in the tool's `cli.py`: add a subparser, attach common
   flags via the shared helper, declare subcommand-specific flags.
3. **Dispatch** in `cli.py`'s `main()`: match `args.subcommand` and call
   the implementation with the right kwargs. Don't reach for globals; pass
   what the implementation needs explicitly.
4. **Tests** in `pytest/python/`: parser defaults, flag parsing, mutually
   exclusive combinations (if any), and a dispatch test that asserts the
   implementation is called with the right kwargs.

A change to an existing subcommand follows the same four-way update; keep
them in sync so the CLI never drifts from its tests or docstrings.

### Breaking CLI changes

No silent compat shims. When a subcommand's shape changes, migrate the
tests in the same commit and update README / `src/docs/` references if
they exist. Document the breaking change in the commit message.

## ishfiles CLI Architecture

The `ishfiles` CLI tool (`src/pyishlib/ishfiles/`) manages dotfiles, packages, and scripts. Key design rules:

### IshConfig as the Single Source of Truth

All configuration — directory names, file names, defaults, and constants — flows through the `IshConfig` object built by `ishfiles/config.py:load_config()`. Components must **never** import path constants directly from other modules; instead, read them from the `cfg` (`IshConfig`) instance via `cfg.get_opt("name")`.

- **Constants** (read-only): Reserved directory and file names (`config_dir`, `scripts_dir`, `installers_dir`, `ignore_file`, `package_files`, `data_file`, `externals_config_file`, `externals_state_filename`) plus the resolved `config_file` path and the XDG-compliant externals cache path (`externals_cache_dir`) are registered via `cfg.set_constant()` in `load_config()`. They cannot be overridden by CLI args, TOML config, or defaults. Attempting to shadow a constant via `set_default()` raises `ValueError`.
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

- **Phase 0 — Launchers**: generate tool launcher scripts into `~/.local/bin` for all registered ishlib tools. Best-effort; failures log a warning.
- **Phase 1 — Scan**: discover dotfiles and scripts, read `__ISH__` metadata, apply OS/tag filtering, and collect embedded package declarations.
- **Phase 2 — Merge**: combine metadata-declared packages with the main package list.
- **Phase 3 — Install**: run the installer pipeline for all packages (main + metadata).
- **Phase 4 — Apply dotfiles**: preprocess and install changed dotfiles.
- **Phase 4b — Externals**: fetch and install external git-repo dotfiles (see the Externals section below).
- **Phase 5 — Scripts**: execute user scripts with logging and `run_when` state gating.

Flags:

- `--dotfiles-only` skips phases 3, 4b, and 5 (package install, externals, scripts).
- `--force-scripts [NAMES...]` re-runs named scripts (or all, with no names) ignoring `run_when` state.
- `--isholate` (internal, used by `isholate` when provisioning containers): for each `config-local.toml` entry that carries an `isholate = <value>` key, uses that hardcoded value instead of the user's saved/prompted value. Overrides are never written back to the config file.

### Filename Prefixes for Dotfiles

Files in the dotfiles source can carry these prefixes (chezmoi-compatible):

- `dot_<name>` — target name becomes `.<name>` (e.g. `dot_bashrc` → `.bashrc`).
- `executable_<name>` — after the file is applied, the target is `chmod +x`'d (Windows is a no-op). The prefix is stripped from the target name and can combine with `dot_` (`dot_executable_foo` → `.foo`, executable).
- `mergejson_<name>` — the file is treated as an RFC 7396 JSON Merge Patch. When the target already exists, it is parsed as JSON and deep-merged with the source (objects merge recursively, arrays and scalars are replaced wholesale, `null` in the source removes the corresponding target key). When the target is missing, behaves like a plain copy. Change detection and diff output are key-order-insensitive: reordering keys inside a JSON object is not treated as a change. Composes with `dot_` (`mergejson_dot_settings.json` → `.settings.json`).

### Externals

External git-repo dotfiles are declared in `<source>/ishconfig/externals.toml`. Support is implemented by the triplet in `src/pyishlib/ishfiles/`:

- `externals_config.py` — load/validate `ExternalSpec` entries from TOML.
- `externals.py` — `ExternalsEngine` fetches, caches, applies, and checks for updates.
- `externals_state.py` — persists resolved revisions to `<target>/.config/ishfiles/externals-state.json`.

The `external` subcommand exposes `apply`, `update`, and `list`. `apply_externals_stage()` is the entry point called as Phase 4b of `apply`. The cache lives in `${XDG_CACHE_HOME:-~/.cache}/ishfiles/external` (outside the source tree; resolved via `externals_cache_dir` constant).

### Reserved Directories in Dotfile Source

The ishfiles source folder reserves these directories (ignored during dotfile application):

- `ishconfig/` — repo-level config (`config.toml`), per-machine data templates (`config-local.toml`), package configuration (`packages.toml` / `packages.json`), and externals config (`externals.toml`)
- `ishscripts/` — user scripts executed on `apply` and `runscripts`
- `ishinstallers/` — custom per-package install scripts

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

See **§Logging** below for the definitive rules. Quick summary of the three channels:

- **`logging`** (via `log = logging.getLogger(__name__)`) — all diagnostic messages, status info, warnings, and errors.  Honours the CLI `--verbose` / `--quiet` / `--debug` flags automatically.
- **`pyishlib.userio`** — every interactive prompt (yes/no/always, string, choice) goes through this module so non-interactive environments and tests have a single seam to patch.
- **`print()`** — only for deliberate, structured CLI output that is the command's product (`diff`, `log`, metadata dumps). Do not use `print` for status chatter.

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

`isholate` (`src/pyishlib/isholate/`) launches ephemeral Incus containers that mirror the host user so `ishfiles` setups can be tested without touching the real `$HOME`. Linux-only — `cli.main` bails out on non-Linux hosts via `environment.is_linux()`.

Key modules:

- `cli.py` — argparse front-end. Subcommands: `run` (launch + exec),
  `purge` (delete user's containers), `list` (table of containers), `stop`
  (stop running containers). The `run` subcommand discovers project-local
  config under an `.ishlib/` umbrella in cwd (no parent search) so
  image/shell overrides take effect. The umbrella has two independent
  paths: `.ishlib/isholate/ishfiles/` is the project-local ishfiles source
  tree (mounted in pass 2), and `.ishlib/isholate/config.toml` holds
  isholate's own project config (`image`, `shell`). Either may exist
  without the other.
- `config.py` — TOML config loading, host-ishfiles-source discovery, and project overlay resolution.
- `container.py` — container lifecycle: create/launch/exec, host user/group mirroring, bind-mount handling, and the lifecycle helpers shared by the subcommands: `_find_isholate_containers` (the single `incus list` code path), `purge_containers`, `list_containers`, `stop_containers`.

When editing isholate, keep the boundary with `pyishlib` clean: reuse `environment.py` for platform checks and `command_runner.py` for subprocess execution rather than re-implementing them.

`_provision` runs a **network pre-flight probe** (`_network_preflight`) before apt. It tests raw IPv4 egress to 1.1.1.1 and then to archive.ubuntu.com. On failure it prints a focused diagnostic (firewall hints, sysctl, incus restart) and raises `RuntimeError`, which is caught in `launch_and_exec` so the container is still stopped cleanly.

Network isolation (`--no-network`) is enforced entirely on the host — nothing is configured inside the container, so a malicious in-container process cannot tamper with the rules.

Without `--claude`, `_apply_network_restrictions` detaches `eth0` via an Incus device override.

With `--claude`, isolation combines three layers, all on the host:

1. **Dedicated Incus bridge** (`isholate-claude`). Created by `_ensure_claude_network` with `ipv4.nat=true`, `ipv6.address=none`, and `ipv4.firewall=false` so Incus does not auto-generate FORWARD rules for it — isholate owns the FORWARD policy for this bridge entirely.
2. **DNS allowlist via `raw.dnsmasq`**. The bridge's dnsmasq gets `local=/#/` (catch-all NXDOMAIN) plus a `server=/<domain>/<upstream>` line per entry in `_CLAUDE_ALLOW_DOMAINS`, so only Claude API domains (anthropic.com, claude.ai, statsig.com, statsigapi.net, sentry.io, and their subdomains) resolve. An `ipset=/…/<setname>` directive makes dnsmasq add each resolved IP to a host ipset on every successful lookup.
3. **Host iptables + ipset enforcement**. `_install_claude_firewall` installs a host ipset `isholate-claude-allowed` and a FORWARD chain `ISHOLATE-CLAUDE` that allows ESTABLISHED/RELATED, DNS to the bridge gateway, and TCP/443 only to IPs currently in the ipset; everything else is dropped. A systemd unit (`isholate-claude-firewall.service`) and an apply script at `/usr/local/libexec/isholate-claude-firewall` are installed so the rules come back on boot.

First use prompts once for sudo (to install the ipset, iptables chain, and the systemd unit). Subsequent runs pass `_claude_firewall_rules_in_place` and skip sudo entirely; reboots are handled by the systemd unit. The "rules in place" check is deliberately file-based — on-disk content match plus `systemctl is-enabled` — since `ipset list` and `iptables -S` require root on every modern distro and would force a sudo prompt on every run. A manual `iptables -F` after install is re-repaired by the systemd unit on next boot; to recover immediately, re-run the apply script under sudo.

## Tool registry

All ishlib CLI tools are registered in a single source of truth:
`src/pyishlib/tools.py`. Completions, launcher generation, `ishfiles init`,
and `IshlibFolder` all read from this registry, so a new tool only needs one
entry there.

To register a new tool, add one entry to `TOOLS` in `src/pyishlib/tools.py`:

```python
Tool(
    name="ishnew",
    module="pyishlib.ishnew",
    description="One-line description.",
    subdir="ishnew",
),
```

No other file needs to change. See the `add-ishlib-tool` skill for the full
scaffolding checklist.

## Entry scripts

`bin/ishlib-install` is a thin bash bootstrap (~15 lines) that resolves
the repo root, sets `PYTHONPATH`, and delegates to
`python3 -m pyishlib.launchers install`. It is the **only** file in `bin/`;
per-tool launcher scripts (`ishfiles`, `isholate`, `ishproject`, …) are
generated by `pyishlib.launchers` into `~/.local/bin/` and never stored in
`bin/` directly.

### Interpreter precedence (first match wins)

1. `$ISHLIB_PYTHON` if set and executable — escape hatch that applies to every
   ishlib Python CLI. Set once in your shell rc and all tools agree.
2. `$(pyenv root)/versions/$(pyenv global)/bin/python3` if pyenv is on PATH,
   the global version is not `system`, and the resolved path is executable.
3. `/usr/bin/python3` if executable.
4. `command -v python3` (last resort).

### Optional deps

`shtab`, `cerberus`, `PyYAML`, `tomli_w`, and `jsonschema` (see the `extras`
dependency group in `pyproject.toml`) must be installed into whichever interpreter wins
precedence — typically the pyenv-global interpreter for deployed use. Run
`ishfiles doctor` to see what is available against the active interpreter.

### Container invocations

`isholate`'s `incus exec` commands inject `ISHLIB_PYTHON=/usr/bin/python3`
via `--env`, so rule 1 fires first and the system python inside the container
is used rather than anything from the host.

### Adding a future ishlib Python CLI

Add one entry to `src/pyishlib/tools.py` (see §Tool registry above).
The launcher generator, shell completions, `ishfiles init`, and
`IshlibFolder` all pick it up automatically — no other file needs changing.
Use the `add-ishlib-tool` Claude skill for the full scaffolding checklist.

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

## Logging

All diagnostic output — Python and shell — **MUST** flow through the unified
logging pipeline in `src/pyishlib/ish_logging.py`. Do not introduce new code
paths that bypass it.

### Python rules

- Every module obtains a logger with `log = logging.getLogger(__name__)`.
  Never configure handlers inside modules other than `ish_logging.py`.
- Status chatter (what is happening, why, dry-run previews, skip notices,
  summaries) goes through `log.debug` / `log.info` / `log.warning` /
  `log.error` / `log.critical`. **NOT** `print()`, **NOT** `sys.stderr.write`.
- Do **not** gate log calls behind `if cfg.verbose:` or `if not cfg.quiet:` —
  let the handler's level filter decide. The handler is configured once in
  `setup_logging()` based on CLI flags.
- Reserve `print()` strictly for a command's *product output* — the thing the
  user asked the tool to produce. Examples: `ishfiles diff` (the diff text),
  `ishfiles log` (the log table), `ishfiles pd` (the path), `ishfiles init`
  (the shell snippet), `ishfiles cd` (the `cd <path>` sentinel), `ishfiles git`
  (passthrough), `ishfiles external list` (the table). Everything else is
  logging.
- Interactive prompts go through `pyishlib.userio`, not `print()`.

### Shell rules (ishscripts and ishlib.sh)

Use the canonical function names that mirror Python's `logging` vocabulary:

| Function | Wire level | Meaning |
|---|---|---|
| `ish_debug` | `debug` | Internal trace; shown only at `--debug` |
| `ish_info` | `info` | Normal progress; shown with `-v` |
| `ish_warning` | `warning` | Recoverable issue; shown by default |
| `ish_error` | `error` | Failure of a unit of work; shown by default |
| `ish_critical` | `critical` | Fatal abort; stops subsequent scripts |

Do not `echo` or `printf` directly to stderr for diagnostics; the helpers
honour `ISHLIB_LOG_OUT` and get captured into the run log. Raw stdout/stderr
from a script is still captured (tagged as `1>` / `2>`) but loses level
information — prefer `ish_*` for anything that needs a log level.

### Log levels — shared vocabulary

| Level | Python constant | Meaning |
|---|---|---|
| `debug` | `logging.DEBUG` | Internal trace; noisy; off by default |
| `info` | `logging.INFO` | Normal progress; shown with `-v` |
| `warning` | `logging.WARNING` | Recoverable issue; shown by default |
| `error` | `logging.ERROR` | Failure of a unit of work; shown by default |
| `critical` | `logging.CRITICAL` | Fatal; script-side also aborts remaining scripts |

### The FIFO wire format (shell → Python)

Shell helpers write `level<TAB>message\n` to `$ISHLIB_LOG_OUT`. Valid levels:
`debug`, `info`, `warning`, `error`, `critical`. Anything else is silently
dropped by the Python reader.

### Central entry point: `src/pyishlib/ish_logging.py`

```python
from pyishlib.ish_logging import setup_logging
setup_logging(logging.INFO, log_file=path, quiet=False)
```

- Call once at the CLI entry point (`ishfiles/cli.py`, `isholate/cli.py`).
- `--log-file <path>` attaches a `FileHandler` at `DEBUG` unconditionally;
  all messages land in the file regardless of terminal verbosity.

### Isholate

Isholate calls `setup_logging` from `ish_logging` (not `ish_comp`). When
launching ishfiles inside a container it passes `--log-file` and pulls the
file back to the host after exec so container diagnostics are never lost.

## Commit Discipline

Keep commits small, self-contained, and squash-friendly so the history is clean before merge.

- **One logical change per commit.** A fix for a CI failure, a response to a single review comment, and a new feature are three separate commits — not one.
- **Each Copilot/review suggestion gets its own commit** unless two suggestions touch the exact same lines for the same reason. Grouping unrelated suggestions makes squashing painful.
- **CI/test fixes are separate from review-comment fixes.** A commit that both adds `from __future__ import annotations` (CI fix) and removes an unused import (review suggestion) should be two commits.
- **Name fix commits after what they fix**, not after the process that found the issue. Prefer `"test_launchers: skip exec-bits check on Windows"` over `"address Copilot comment"`.

This discipline lets the author squash each fix into its parent feature commit with a single `fixup` line before merge, without manual conflict resolution.

## Important Warnings

- **Never edit `ishlib.sh`, `docs/ishlib_shell.md`, or `docs/pyishlib/` directly** - they are generated. Edit sources in `src/` and run `make`.
- Documentation sources live in `src/docs/`; the `docs/` directory contains MkDocs site pages (some hand-written, some generated). Python docs are generated by `scripts/build_pydocs.py` from `src/pyishlib/` docstrings.
- Shell tests are parametrized across multiple shells (bash, dash, sh, zsh). Ensure POSIX functions work in all of them.
- The `t/` directory contains legacy Perl/TAP tests run via `prove` (invoked by `pytest/shell/test_legacy_prove.py`). Do not add new tests there; use `pytest/` instead.
