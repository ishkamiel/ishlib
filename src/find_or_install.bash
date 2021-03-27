#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_find_or_install_bash:-}" ] && return 0
ish_SOURCED_find_or_install_bash=1 # source guard
./common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
find_or_install var [installer [installer args]]
-----------------------------

Tries to find and set path for command defined by the variable named var,
i.e., ${!var}. Will also update the var variable with a full path if
applicable.

Arguments:
  var - name of variable holding command
  installer - optional installer function
  install_path - where the installer will install the binary
Side effects:
  ${!var} - the variable named by var is set to the found or installed cmd
Returns:
  0 - if cmd found or installed
  1 - if cmd not found, nor successfully installed

DOCSTRING
find_or_install() {
  [[ -n "$1" ]] || fail "ishlib:find_or_install: missing 1st argument"
  [[ -v "$1" ]] || fail "ishlib:find_or_install: Unbound variable: '$1'"
  [[ -n "${!1}" ]] || fail "ishlib:find_or_install: Empty variable: $1"
  local var="$1"
  local func="${2:-}"
  local val="${!var}"
  local name="${val}"
  shift 2

  if has_command "$val"; then
    local new_val
    new_val="$(which "$val")"
    if [[ "$val" = "$new_val" ]]; then
      debug "ishlib:find_or_install: found $val"
    else
      debug "ishlib:find_or_install: found $val, setting to ${new_val}"
      printf -v "${var}" "%s" "$(which "$val")"
    fi
    return 0
  elif [[ -n $func ]]; then
    debug "ishlib:find_or_install: running $func $var" "$@"
    if $func "$var" "$@"; then
      if ! has_command "${!var}"; then
        warn "ishlib:find_or_install: custom installer for $name reported success, but $var is set to ${!var}, which is not a valid command"
        if is_dry; then return 0; fi
        return 1
      fi
      return 0
    fi
    debug "ishlib:find_or_install: provided installer failed"
  fi
  return 1
}
