---
name: run-tests
description: Run the test suite for the ishlib repository. Use this whenever the user asks to run tests, verify changes, check that things pass, or validate code. Also use it when the user says "/test", "test this", "does this work", or "make sure nothing broke". Triggers on any request to validate, test, or verify code correctness in this repo.
argument-hint: "[pytest-args]  # e.g. -k test_shellcheck, pytest/shell/test_func-path.py, -x"
---

# Run Tests

The ishlib test suite lives in `pytest/`. All commands must be run from the `ishlib/` directory (`/home/ishkamiel/.local/share/ishfiles/ishlib`).

## Quick reference

| Goal | Command |
|------|---------|
| Build + full test suite | `make verify` |
| Tests only (no rebuild) | `pytest` |
| Specific file | `pytest pytest/shell/test_func-path.py` |
| By name pattern | `pytest -k "test_pattern"` |
| Stop on first failure | `pytest -x` |
| Verbose | `pytest -v` |
| Pre-commit hooks | `pre-commit run --all-files` |

Tests run in parallel by default (`--numprocesses=auto`). Shell tests are parametrized across bash, dash, sh, and zsh.

## Steps

1. If no arguments are given, run `make verify` (builds `ishlib.sh` first, then runs the full test suite).
2. If the user supplies pytest args (file path, `-k pattern`, `-x`, etc.), run `pytest $ARGUMENTS` directly — no need to rebuild.
3. If tests fail:
   - Show the relevant failure output.
   - Diagnose the root cause before suggesting a fix.
   - Do not re-run the same failing command — fix the issue first.
4. If all tests pass and the user hasn't already run pre-commit, mention: "You can also run `pre-commit run --all-files` to check formatting and linting."
