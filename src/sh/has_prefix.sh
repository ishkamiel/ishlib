#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_has_prefix_sh:-}" ] && return 0
ish_SOURCED_has_prefix_sh=1 # source guard

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"

: <<'DOCSTRING'
`has_prefix str prefx`

Source:

Arguments:
  str - string to look into
  prefix - the prefix to check for

Returns:
  0 - if prefix is found
  1 - if prefix isn't found

DOCSTRING
has_prefix() {
  case "$1" in "$2"*) return 0 ;; esac
  return 1
}
