#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021-2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_strstr_bash:-}" ] && return 0
ish_SOURCED_strstr_bash=1 # source guard

# shellcheck source=common.bash
. "$ISHLIB/src/bash/common.bash"

: <<'DOCSTRING'
strstr haystack needle [pos_var]
--------------------------------

Finds needle in given haystack, if pos_var is given, then also stores the
position of the found variable into ${!pos_var}.

Arguments:
    haystack - the string to look in
    needle - the string to search for
    pos_var - name of a variable for positionli
Side-effects:
    ${!pos_var} - set to -1 on ish_fail, otherwise to the position of needle
Returns:
    0 - if needle was found
    1 - otherwise

DOCSTRING
strstr() {
  local x=${1%%"$2"*}
  if [[ "$x" = "$1" ]]; then
    [[ -n "${3+x}" ]] && printf -v "$3" "%s" "-1"
    return 1
  fi
  [[ -n "${3+x}" ]] && printf -v "$3" "%s" "${#x}"
  return 0
}
