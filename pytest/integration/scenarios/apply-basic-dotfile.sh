#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: a single dot_-prefixed source file is applied to the target
# directory and the result is idempotent on re-run.

set -eu
. "$ISHLIB_LIB"

it_sandbox_dirs
it_make_fake_source "dot_bashrc" "# managed by ishfiles
export FOO=bar
"

# First apply: should create $TARGET/.bashrc.
it_run_ishfiles apply --skip-launchers --dotfiles-only --yes
it_assert_file_exists  "$(it_target_path)/.bashrc"
it_assert_file_contains "$(it_target_path)/.bashrc" "FOO=bar"

# Re-apply: idempotent, no error.
it_run_ishfiles apply --skip-launchers --dotfiles-only --yes
it_assert_file_contains "$(it_target_path)/.bashrc" "FOO=bar"

it_log "ok"
