#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: source ishlib.sh from a real shell and exercise a few
# canonical helpers.  This is a pure-shell smoke test independent of
# ishfiles -- if the compiled ishlib.sh is unparsable or its log helpers
# regress, this scenario catches it.

set -eu
. "$ISHLIB_LIB"

it_source_ishlib

# `has_command` should return 0 for a ubiquitous binary.
it_assert_exit_zero has_command sh
it_assert_exit_nonzero has_command this-binary-definitely-does-not-exist-xyz

# Log helpers must write to stderr (captured by us into files) and exit 0.
ish_info "info-from-scenario"     2> "$ISHLIB_SANDBOX/ish.info"
ish_warning "warning-from-scenario" 2> "$ISHLIB_SANDBOX/ish.warn"

it_assert_file_contains "$ISHLIB_SANDBOX/ish.info" "info-from-scenario"
it_assert_file_contains "$ISHLIB_SANDBOX/ish.warn" "warning-from-scenario"

# Library identity sanity check: ish_VERSION_NAME / _NUMBER must be set.
[ -n "${ish_VERSION_NAME:-}" ]   || it_die "ish_VERSION_NAME not set after sourcing ishlib.sh"
[ -n "${ish_VERSION_NUMBER:-}" ] || it_die "ish_VERSION_NUMBER not set after sourcing ishlib.sh"

it_log "ok (${ish_VERSION_NAME} ${ish_VERSION_NUMBER})"
