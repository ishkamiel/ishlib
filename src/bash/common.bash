#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021-2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_common_bash:-}" ] && return 0
ish_SOURCED_common_bash=1 # source guard

export ish_VERSION_VARIANT="POSIX+bash"

# shellcheck source=../sh/common.sh
. "$ISHLIB/src/sh/common.sh"
