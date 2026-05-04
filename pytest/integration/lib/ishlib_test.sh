#!/usr/bin/env sh
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Helper library for ishlib integration scenarios.  Sourced by every
# scenario script via:
#
#     . "$ISHLIB_LIB"
#
# The collector exports these variables before invoking a scenario:
#
#   ISHLIB_REPO     absolute path to the repo root
#   ISHLIB_SRC      $ISHLIB_REPO/src (also on PYTHONPATH)
#   ISHLIB_LIB      absolute path to this file
#   ISHLIB_SH       absolute path to ishlib.sh
#   ISHLIB_SANDBOX  per-scenario sandbox directory (cwd of the script)
#   ISHFILES        invocation prefix for the ishfiles CLI
#                   (currently: "python3 -m pyishlib.ishfiles")
#   ISHPROJECT      invocation prefix for the ishproject CLI
#                   (currently: "python3 -m pyishlib.ishproject")
#   PYTHONPATH      includes $ISHLIB_SRC
#
# The library exposes assertion helpers (it_assert_*) and sandbox
# builders (it_make_*).  All output goes to stderr so scenarios that
# legitimately produce stdout do not interleave with diagnostics.

set -eu

it_log() {
    printf '[scenario] %s\n' "$*" >&2
}

it_die() {
    printf '[scenario] FAIL: %s\n' "$*" >&2
    exit 1
}

# -- sandbox layout ---------------------------------------------------------

# Standard sandbox subdirs:
#   $ISHLIB_SANDBOX/source   ishfiles source folder
#   $ISHLIB_SANDBOX/target   target/home directory for installed dotfiles
#   $ISHLIB_SANDBOX/config   directory for the ishfiles config file
#
# Scenarios call `it_sandbox_dirs` once at the top to create these.

it_sandbox_dirs() {
    : "${ISHLIB_SANDBOX:?ISHLIB_SANDBOX must be set by the collector}"
    mkdir -p \
        "$ISHLIB_SANDBOX/source" \
        "$ISHLIB_SANDBOX/target" \
        "$ISHLIB_SANDBOX/config"
}

it_source_path() {
    printf '%s' "$ISHLIB_SANDBOX/source"
}

it_target_path() {
    printf '%s' "$ISHLIB_SANDBOX/target"
}

it_config_path() {
    printf '%s' "$ISHLIB_SANDBOX/config/ishfiles.toml"
}

# Write a file under the source tree at relative path $1 with contents $2.
# Parent directories are created automatically.
it_make_fake_source() {
    [ "$#" -eq 2 ] || it_die "it_make_fake_source needs <relpath> <content>"
    _it_dest="$ISHLIB_SANDBOX/source/$1"
    mkdir -p "$(dirname "$_it_dest")"
    printf '%s' "$2" > "$_it_dest"
}

# Write a file under the target tree at relative path $1 with contents $2.
it_make_fake_target() {
    [ "$#" -eq 2 ] || it_die "it_make_fake_target needs <relpath> <content>"
    _it_dest="$ISHLIB_SANDBOX/target/$1"
    mkdir -p "$(dirname "$_it_dest")"
    printf '%s' "$2" > "$_it_dest"
}

# -- ishfiles invocation ----------------------------------------------------

# Run the ishfiles CLI with sandbox flags pre-applied.  Any extra
# arguments are forwarded after `apply` / `diff` / etc.
it_run_ishfiles() {
    # shellcheck disable=SC2086
    $ISHFILES \
        -s "$(it_source_path)" \
        -t "$(it_target_path)" \
        -c "$(it_config_path)" \
        "$@"
}

# Like it_run_ishfiles but captures stdout to $ISHLIB_SANDBOX/last.out and
# stderr to $ISHLIB_SANDBOX/last.err.  Returns the CLI exit code.
it_run_ishfiles_capture() {
    set +e
    it_run_ishfiles "$@" \
        > "$ISHLIB_SANDBOX/last.out" \
        2> "$ISHLIB_SANDBOX/last.err"
    _it_rc=$?
    set -e
    return $_it_rc
}

# -- ishproject invocation --------------------------------------------------

# Run the ishproject CLI.  ishproject resolves source/target itself from
# cwd (it expects to be invoked inside a project git-repo root), so no
# -s/-t/-c flags are injected.  Scenarios should `cd` into the project
# root before calling this helper.
it_run_ishproject() {
    # shellcheck disable=SC2086
    $ISHPROJECT "$@"
}

# Like it_run_ishproject but captures stdout/stderr like it_run_ishfiles_capture.
it_run_ishproject_capture() {
    set +e
    it_run_ishproject "$@" \
        > "$ISHLIB_SANDBOX/last.out" \
        2> "$ISHLIB_SANDBOX/last.err"
    _it_rc=$?
    set -e
    return $_it_rc
}

# -- assertions -------------------------------------------------------------

it_assert_file_exists() {
    [ -f "$1" ] || it_die "expected file to exist: $1"
}

it_assert_file_missing() {
    [ ! -e "$1" ] || it_die "expected path to be missing: $1"
}

it_assert_dir_exists() {
    [ -d "$1" ] || it_die "expected directory to exist: $1"
}

it_assert_file_contains() {
    [ "$#" -eq 2 ] || it_die "it_assert_file_contains needs <path> <needle>"
    it_assert_file_exists "$1"
    if ! grep -F -- "$2" "$1" > /dev/null; then
        it_die "expected $1 to contain: $2 (got: $(cat -- "$1"))"
    fi
}

it_assert_file_equals() {
    [ "$#" -eq 2 ] || it_die "it_assert_file_equals needs <path> <expected>"
    it_assert_file_exists "$1"
    _it_actual=$(cat -- "$1")
    if [ "$_it_actual" != "$2" ]; then
        it_die "expected $1 to equal $2 (got: $_it_actual)"
    fi
}

it_assert_exit_zero() {
    [ "$#" -ge 1 ] || it_die "it_assert_exit_zero needs <cmd>"
    set +e
    "$@"
    _it_rc=$?
    set -e
    [ $_it_rc -eq 0 ] || it_die "expected exit 0, got $_it_rc from: $*"
}

it_assert_exit_nonzero() {
    [ "$#" -ge 1 ] || it_die "it_assert_exit_nonzero needs <cmd>"
    set +e
    "$@"
    _it_rc=$?
    set -e
    [ $_it_rc -ne 0 ] || it_die "expected non-zero exit, got 0 from: $*"
}

# Source the compiled ishlib.sh for scenarios that exercise the shell
# library directly.  Returns void; on failure the scenario aborts via
# the inherited `set -e`.
it_source_ishlib() {
    : "${ISHLIB_SH:?ISHLIB_SH must be set by the collector}"
    [ -f "$ISHLIB_SH" ] || it_die "ishlib.sh missing at $ISHLIB_SH"
    # shellcheck disable=SC1090
    . "$ISHLIB_SH"
}
