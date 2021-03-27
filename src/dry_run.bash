#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_dry_run_bash:-}" ] && return 0
ish_SOURCED_dry_run_bash=1 # source guard
. common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
do_or_dry cmd ...
DOCSTRING
do_or_dry() {
  local cmd=$1
  shift
  local args=("$@")

  debug "ishlib:do_or_dry: cwd=$(if is_dry; then echo "\$(pwd)"; else pwd; fi), running $cmd" "${args[@]}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    dry_run "$cmd" "${args[@]}"
    return 0
  else
    $cmd "${args[@]}"
    return $?
  fi
}

#------------------------------------------------------------------------------
: <<'DOCSTRINg'
do_or_dry_bg pid cmd ...
DOCSTRINg
do_or_dry_bg() {
    declare -n _ish_tmp_pid=$1
    local cmd=$2
    shift 2
    local args=("$@")

    debug "ishlib:do_or_dry_bg: cwd=$(if is_dry; then echo "\$(pwd)"; else pwd; fi), running $cmd" "${args[@]}" "\\adsf&"
    if is_dry; then
        dry_run "$cmd" "${args[@]}" "&"
        _ish_tmp_pid=""
        return 0
    else
        $cmd "${args[@]}" &
        _ish_tmp_pid=$!
        debug "ishlib:do_or_dry_bg: started $_ish_tmp_pid!"
        return 0
    fi
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
do_or_dry cmd ...
DOCSTRING
is_dry() {
  [[ "${DRY_RUN:-}" = 1 ]] && return 0
  return 1
}
