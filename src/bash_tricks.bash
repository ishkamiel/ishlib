#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_bash_tricks_bash:-}" ] && return 0
ish_SOURCED_bash_tricks_bash=1 # source guard
. common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
copy_function src dst
----------------------

Copies the src function to a new function named dst.

Source: https://stackoverflow.com/a/18839557

Arguments:
  src - the name to rename from
  dst - the name to rename to
Returns:
  0 - on success
  1 - on failure

DOCSTRING
copy_function() {
  test -n "$(declare -f "$1")" || return 1
  eval "${_/$1/$2}" || return 1
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
rename_function src dst
-----------------------

Renames the src function to dst.

Source: https://stackoverflow.com/a/18839557

Arguments:
  src - the name to rename from
  dst - the name to rename to
Returns:
  0 - on success
  1 - on failure

DOCSTRING
rename_function() {
  copy_function "$@" || return 1
  unset -f "$1"
  return 0
}
