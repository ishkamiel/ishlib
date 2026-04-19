---
name: add-python-command
description: Add or update a subcommand on one of ishlib's Python CLI tools (ishfiles, isholate, or any future tool). Use when the user asks to "add a new command", "add a subcommand", "wire up ishfiles/isholate with a new command", or "update the subcommand". Covers both new subcommands and edits to existing ones. Enforces the project's argparse/subparser rule from CLAUDE.md.
argument-hint: "TOOL COMMAND-NAME   # e.g. isholate restart"
---

# Add or update a Python CLI subcommand

Every CLI in `src/pyishlib/` uses argparse subcommands — never flag-based
dispatch. This skill walks through the four-way update every new or changed
subcommand needs.

**Before you start:** read the relevant CLI's current `cli.py` and one
nearby subcommand implementation so the new one matches style. Also
skim the "Python CLI Tools" section of `CLAUDE.md`.

## Where each tool lives

| Tool       | Parser            | Subcommand implementations                               |
|------------|-------------------|-----------------------------------------------------------|
| `ishfiles` | `ishfiles/cli.py` | One module per command in `ishfiles/commands/<name>.py`. |
| `isholate` | `isholate/cli.py` | Functions in `isholate/container.py` (or a sibling).     |

Other (future) Python CLIs follow the same split.

## The four-way update

A subcommand is always four things kept in sync. Land them in the same
commit.

### 1. Implementation

- **ishfiles**: create `src/pyishlib/ishfiles/commands/<name>.py` with
  `register(subparsers)` and `run(cfg)` functions. `register` attaches
  the subparser; `run` takes the `IshConfig` object and returns `int`.
  Read paths/constants from `cfg`, never from module-level imports.
- **isholate**: add a named function in `container.py` (or a sibling
  module if it's large). It takes explicit kwargs — not `argparse.Namespace` —
  so it's easy to unit-test.
- Output goes through `log = logging.getLogger(__name__)`. Only a
  command's *product output* (a diff, a table, a path) may use `print()`.
  See the Logging section in `CLAUDE.md`.

### 2. Parser wiring in `cli.py`

- In `build_parser()`, add a subparser via
  `sub.add_parser("<name>", help="...", description="...")`.
- Attach the common `-v/-q` flags via the shared helper (e.g.
  `_add_common_args(p)`). Do **not** attach them to the top-level parser
  — argparse subparser defaults would clobber top-level values. The
  `parents=[common]` pattern has the same bug and must not be used for
  `-v/-q`.
- Add subcommand-specific flags with full `help=...` text.
- Use `parser.add_mutually_exclusive_group()` for mutex flag sets.
- For passthrough command args, use `nargs=argparse.REMAINDER` as the
  last positional on the subparser (not the top-level parser).

### 3. Dispatch in `main()`

Match `args.subcommand` and call the implementation with explicit kwargs:

```python
if args.subcommand == "<name>":
    return <implementation>(
        username,
        option=args.option,
        ...
    )
```

Don't pass the whole `args` namespace unless the implementation genuinely
needs most of it (the `run` subcommand in isholate is the one exception —
it forwards a lot of state to `launch_and_exec`).

### 4. Tests in `pytest/python/test_<tool>.py`

> **Hermetic environment.** `pytest/conftest.py` replaces `os.environ`
> wholesale at session start, keeping only `PATH`/`HOME`/`TMPDIR` from the
> host and injecting fixed git identity and `/dev/null` git config vars.
> Subprocesses spawned without `env=` automatically inherit this clean
> environment — no per-test env setup needed. To override a var for a specific
> test, build `env = os.environ.copy()` and extend it. See
> `CLAUDE.md §Hermetic subprocess environment`.

At minimum:

- **Parser defaults** — a test that `parse_args(["<name>"])` sets the
  expected defaults.
- **Each flag** — one test per non-trivial flag confirming it parses.
- **Mutex groups** — a test that conflicting flags raise `SystemExit`.
- **Dispatch** — a test that `cli_main(["<name>", ...])` calls the
  implementation with the right kwargs (use `unittest.mock.patch` on the
  `cli.py`-level name, e.g. `pyishlib.isholate.cli.<impl>`).
- **Doesn't dispatch other things** — when useful, assert that unrelated
  implementations (`launch_and_exec`, etc.) are NOT called.

Run just the affected test module while iterating:

```bash
pytest pytest/python/test_<tool>.py -q
```

## Updating an existing subcommand

Same four-way update. Treat flag renames, removed flags, changed defaults,
and changed dispatch kwargs as CLI-breaking: migrate the tests in the same
commit. Don't leave dead `--old-name` aliases as compat shims unless the
user asks for them explicitly.

## Breaking CLI changes

Call out the break in the commit message so users who pull the change can
update their invocations.

## Quick checklist

- [ ] Implementation module/function with docstring
- [ ] Subparser in `build_parser()` with `help=` and `description=`
- [ ] Common args via shared helper (NOT on top-level parser)
- [ ] Dispatch branch in `main()`
- [ ] Parser-shape tests (defaults + each flag)
- [ ] Mutex-group tests (if any mutex flags)
- [ ] Dispatch test with mocked implementation
- [ ] README / docs swept for old invocation shapes (if renaming)
- [ ] `pytest pytest/python/test_<tool>.py` passes
- [ ] `ruff check src/` and `ruff format --check src/` clean
