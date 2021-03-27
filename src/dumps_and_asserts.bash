#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_dumps_and_asserts_bash:-}" ] && return 0
ish_SOURCED_dumps_and_asserts_bash=1 # source guard
./common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
dump var1 [var2 var3 ...]
-----------------

Will call dumpVariable for each member of vars.

Globals:
Arguments:
  varN - name of a variable to dump
Returns:
  0 - if all varN were bound
  n - number of unbound varN encountered
DOCSTRING
dump() {
  local vars=("$@")
  local unbound=0
  for var in "${vars[@]}"; do
    if [[ -n "${var+x}" ]]; then
      debug "$var=${!var}"
    else
      debug "$var is unbound"
      unbound=$((unbound + 1))
    fi
  done
  return $unbound
}
