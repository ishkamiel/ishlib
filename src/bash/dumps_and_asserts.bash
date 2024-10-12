#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_dumps_and_asserts_bash:-}" ] && return 0
ish_SOURCED_dumps_and_asserts_bash=1 # source guard

# shellcheck source=common.bash
. "$ISHLIB/src/bash/common.bash"

: <<'DOCSTRING'
`dump $var1 [var2 var3 ...]`
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
      ish_say "$var=${!var}"
    else
      ish_say "$var is unbound"
      unbound=$((unbound + 1))
    fi
  done
  return $unbound
}

assert_dir() {
  local vars=("$@")
  local bad=0

  for d in "${vars[@]}"; do
    if ! [[ -e "$d" ]]; then
      ish_warn "does not exist: $d"
      bad=$((bad + 1))
    elif ! [[ -d "$d" ]]; then
      ish_warn "not a directory: $d"
      bad=$((bad + 1))
    fi
  done

  return $bad
}

assert_exists() {
  local vars=("$@")
  local bad=0

  for d in "${vars[@]}"; do
    if ! [[ -e "$d" ]]; then
      ish_warn "does not exist: $d"
      bad=$((bad + 1))
    fi
  done

  return $bad
}

dump_and_assert_dir() {
  local vars=("$@")
  local bad=0

  for var in "${vars[@]}"; do
    if [[ -n "${var+x}" ]]; then
      ish_debug "${var}=${!var}"
      assert_dir "${!var}"
    else
      ish_debug "$var is unbound"
      unbound=$((bad + 1))
    fi
  done

  return $bad
}
