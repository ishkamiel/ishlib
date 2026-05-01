#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: a `mergejson_dot_settings.json` source file is deep-merged
# into a pre-existing target `.settings.json` (RFC 7396 merge patch).

set -eu
. "$ISHLIB_LIB"

it_sandbox_dirs

# Existing target file: object with one key.
it_make_fake_target ".settings.json" '{"existing": "stays"}
'

# Source patch: adds a new top-level key.
it_make_fake_source "mergejson_dot_settings.json" '{"new_key": "new_value"}
'

it_run_ishfiles apply --skip-launchers --dotfiles-only --yes

# Both keys must be present after apply.
it_assert_file_contains "$(it_target_path)/.settings.json" '"existing"'
it_assert_file_contains "$(it_target_path)/.settings.json" '"stays"'
it_assert_file_contains "$(it_target_path)/.settings.json" '"new_key"'
it_assert_file_contains "$(it_target_path)/.settings.json" '"new_value"'

it_log "ok"
