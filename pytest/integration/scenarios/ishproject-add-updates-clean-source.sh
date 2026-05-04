#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: `ishproject add <file>` must succeed when the in-repo copy
# of the file is committed cleanly and the user has fresh edits in the
# working tree.  The bug was that the dirty check fired on any source≠
# target diff, blocking the every-day update workflow.

set -eu
. "$ISHLIB_LIB"

it_sandbox_dirs

target=$(it_target_path)
source="$target/.ishlib/ishproject"

# Project repo (target side).  ishproject add requires this to be a
# git working tree -- it discovers the repo via GitRepo.discover(target)
# to write the .ishlib/ exclude entry.
git -C "$target" init -q -b main
git -C "$target" -c commit.gpgsign=false commit --no-gpg-sign --allow-empty -q -m "init"

# In-project dotfiles repo (source side).  In a real workflow this is
# created by `ishproject init` as a worktree; for this scenario any
# clean git repo is sufficient.
mkdir -p "$source"
git -C "$source" init -q -b main
echo "old content" > "$source/dot_bashrc"
git -C "$source" add dot_bashrc
git -C "$source" -c commit.gpgsign=false commit --no-gpg-sign -q -m "track dot_bashrc"

# Fresh edits in the user's working tree -- this is what the next
# `ishproject add` is supposed to copy across.
echo "new content" > "$target/.bashrc"

# The fix: this must succeed without -f because the source file is
# tracked and clean (no uncommitted edits to lose).
cd "$target"
it_run_ishproject_capture add ./.bashrc \
    || it_die "ishproject add failed (expected exit 0); stderr was: $(cat "$ISHLIB_SANDBOX/last.err")"

# Source file is now updated to the target's content.
it_assert_file_equals "$source/dot_bashrc" "new content"

# And the just-copied path is staged in the source repo (the optional
# `_stage_in_git` step at the end of `ishfiles add`).
git -C "$source" diff --cached --name-only > "$ISHLIB_SANDBOX/staged.out"
grep -F -x "dot_bashrc" "$ISHLIB_SANDBOX/staged.out" > /dev/null \
    || it_die "expected dot_bashrc to be staged; got: $(cat "$ISHLIB_SANDBOX/staged.out")"

it_log "ok"
