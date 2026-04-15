# TODO

Code-quality items surfaced by a sweep of `src/pyishlib/` and
`.github/workflows/`. Items below are deferred to follow-up branches — check
them off or delete them as they land.

## Python DRY

- **Installer base helpers.** `is_pkg_installed()` starts with an identical
  `if not self.can_install() or not self.can_install(pkg): …` guard in six
  backends; move into `InstallerBase._skip_if_unavailable(pkg)`. Also add
  `InstallerBase._decode(data)` to collapse the repeated
  `result.stdout.decode("utf-8", errors="replace")` copies in
  `installer_apt.py`, `installer_brew.py`, `installer_cargo.py`,
  `installer_pip.py`.

- **`_tool_cmd()` / `_pkg_key()` boilerplate.** Most backends override both
  methods to return a hardcoded string. Replace with class-level
  `TOOL_CMD` / `PKG_KEY` constants (or infer from `INSTALLER_NAME`).

- **`InstallerCustom` inheritance.** `installer_custom.py` does not inherit
  from `InstallerBase` and re-implements the `namespace` pattern. Unify
  so new backend features reach the custom backend automatically.

- **Dead alias.** `installer_pip.py::has_pip` is an unused backward-compat
  alias for `available`; remove after confirming no external callers.

- **Command registration boilerplate.** Every `ishfiles/commands/*.py`
  repeats `register(subparsers)` / `set_defaults(func=run)`. A small
  `@register_command(name, help=…)` decorator could collapse ~15 lines per
  command across 12 files. Purely stylistic — only worth it if we touch
  that area for another reason.

## Logging rule compliance (CLAUDE.md §Logging)

- `src/pyishlib/dotfile_applier.py` (~lines 313-372): status `print()`
  calls gated by `if self.cfg.verbose:` — replace with `log.debug/info`
  and drop the gate.
- `src/pyishlib/ishfiles/commands/diff.py` (~lines 57-66): `if not
  cfg.quiet:` gating around status `print(...)` — use `log.info`.
- `src/pyishlib/ishfiles/data.py` (~lines 131-178): `print(...)` chatter
  about collected config values — move to `log.info`.
- Keep legitimate *product* `print()` (diff text, log table, `pd`, `init`,
  `cd`, `git` passthrough, `external list` table).

## CI / testing

- **Concurrency groups.** Add
  `concurrency: { group: '${{ github.workflow }}-${{ github.ref }}',
  cancel-in-progress: true }` to all four workflows to auto-cancel
  superseded PR runs.
- **`pre-commit.yml` cleanup.** The workflow sets `SKIP: pytest` but the
  pre-commit config does not list a `pytest` hook — dead config. Remove.
- **`docs.yml` drift check.** The job regenerates `docs/ishlib_shell.md`
  and `docs/pyishlib/` but never compares them to the committed files.
  Add `git diff --exit-code -- docs/` after the regen so stale docs break
  CI (the CLAUDE.md contract already says generated docs must be
  committed).
- **Coverage.** Add `pytest-cov` to `requirements-dev.txt`, a
  `[tool.coverage.run]` block to `pyproject.toml`, and a `--cov=pyishlib`
  run in CI (non-blocking at first).
- **Python conftest.** `pytest/python/` has ~750 mock/patch call sites
  across 31 files with no shared `conftest.py`. Introduce one for the
  most-repeated fixtures (temp home, mock `CommandRunner`, captured
  logger).
- **Dependency pinning / dependabot.** `requirements*.txt` are unpinned;
  add minimum version ranges and a `.github/dependabot.yml` for weekly
  pip + github-actions updates.
- **macOS runner.** Currently only Ubuntu + Windows (Python-only). Add a
  macOS job restricted to `pytest/shell/` under bash/zsh to catch
  BSD-vs-GNU regressions.
- **Legacy `t/` TAP tests.** Four `.t` files still run via
  `pytest/shell/test_legacy_prove.py`. Decide whether to port or retire.
