#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: when the target already matches the source, `ishfiles diff`
# reports no changes and exits 0.

set -eu
. "$ISHLIB_LIB"

it_sandbox_dirs
it_make_fake_source "dot_bashrc" "same
"
it_make_fake_target ".bashrc" "same
"

it_run_ishfiles_capture diff
# A no-op diff must not contain any diff hunk markers (lines beginning
# with '+', '-', or '@@').  ishfiles emits a friendly "up to date"
# message, which we tolerate.
if grep -E '^[-+@]' "$ISHLIB_SANDBOX/last.out" > /dev/null; then
    it_die "expected no diff hunks, got: $(cat "$ISHLIB_SANDBOX/last.out")"
fi

it_log "ok"
