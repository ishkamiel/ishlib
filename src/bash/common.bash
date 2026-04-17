#! /usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2021-2026 Hans Liljestrand <hans@liljestrand.dev>
#
[ -n "${ish_SOURCED_common_bash:-}" ] && return 0
ish_SOURCED_common_bash=1 # source guard

export ish_VERSION_VARIANT="POSIX+bash"

# shellcheck source=../sh/common.sh
. "$ISHLIB/src/sh/common.sh"
