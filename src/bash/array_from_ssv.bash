#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021-2025 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_array_from_ssv_bash:-}" ] && return 0
ish_SOURCED_array_from_ssv_bash=1 # source guard

# shellcheck source=common.bash
. "$ISHLIB/src/bash/common.bash"

: <<'DOCSTRING'
`array_from_ssv var str`

Read space-separated values into an array variable.

Arguments:
  var - the name of an array variable to populate
  str - the string to split

Returns:
  0 - on success
  1 - on failure

DOCSTRING
array_from_ssv() {
  # Create a local reference
  declare -n _ish_tmp="${1}"
  # Then allows us to populate local variables...

  #shellcheck disable=SC2048
  for e in ${*:2}; do
    _ish_tmp+=("$e")
  done
  return 0
}
