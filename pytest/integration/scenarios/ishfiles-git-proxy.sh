#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: `ishfiles git ...` proxies arbitrary git commands against
# the source repository.  We initialise a git repo in the sandbox source,
# add a tracked file, and verify that the proxy reports it.

set -eu
. "$ISHLIB_LIB"

it_sandbox_dirs

src=$(it_source_path)
git -C "$src" init -q
git -C "$src" -c commit.gpgsign=false commit --no-gpg-sign --allow-empty -q -m "init"

it_make_fake_source "dot_bashrc" "tracked
"
git -C "$src" add dot_bashrc
git -C "$src" -c commit.gpgsign=false commit --no-gpg-sign -q -m "add dot_bashrc"

# Add an unstaged change so `ishfiles git status --porcelain` produces output.
it_make_fake_source "dot_bashrc" "modified
"

it_run_ishfiles_capture git status --porcelain

# Porcelain status for a modified tracked file starts with " M".
grep -F " M dot_bashrc" "$ISHLIB_SANDBOX/last.out" > /dev/null \
    || it_die "expected 'M dot_bashrc' in proxy git status, got: $(cat "$ISHLIB_SANDBOX/last.out")"

it_log "ok"
