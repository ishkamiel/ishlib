#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021-2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_dry_run_bash:-}" ] && return 0
ish_SOURCED_dry_run_bash=1 # source guard

# shellcheck source=common.bash
. "$ISHLIB/src/bash/common.bash"
# shellcheck source=../sh/prints_and_prompts.sh
. "$ISHLIB/src/sh/prints_and_prompts.sh"

: <<'DOCSTRING'
`do_or_dry [--bg [--pid=pid_var]] cmd [args...]`

TODO: merge do_or_dry_bg here using the above cmdline args

DOCSTRING
do_or_dry() {
  local cmd=$1
  local t="${ish_DebugTag}do_or_dry:"
  shift
  local args=("$@")

  ishlib_debug "$t cwd=$(if is_dry; then echo "\$(pwd)"; else pwd; fi), running $cmd" "${args[@]}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run "$cmd" "${args[@]}"
  else
    if ! $cmd "${args[@]}"; then
      ish_warn "$t (caller $(caller 0 | awk -F' ' '{ print $3 " line " $1}')) failed to run: $cmd" "${args[@]}"
      return 1
    fi
  fi
  return 0
}


: <<'DOCSTRING'
`do_or_dry_bg pid_var cmd [args...]`

TODO: merge do_or_dry_bg here using the above cmdline args

DOCSTRING
do_or_dry_bg() {
    declare -n pid=$1
    local cmd=$2
    shift 2
    local args=("$@")

    ishlib_debug "ishlib:do_or_dry_bg: cwd=$(if is_dry; then echo "\$(pwd)"; else pwd; fi), running $cmd" "${args[@]}" "\\adsf&"
    if is_dry; then
        ish_say_dry_run "$cmd" "${args[@]}" "&"
        pid=""
        return 0
    else
        $cmd "${args[@]}" &
        pid=$!
        ishlib_debug "ishlib:do_or_dry_bg: started $pid!"
        return 0
    fi
}

: <<'DOCSTRING'
`is_dry`

Just a convenience function for checking DRY_RUN in constructs like:
`if is_dry; then ...; fi`.

Returns:
  0       - if $DRY_RUN is 1
  1       - if $DRY_RUN is not 1
DOCSTRING
is_dry() {
  [[ "${DRY_RUN:-}" = 1 ]] && return 0
  return 1
}

ish_run() {
  local dry_run=${DRY_RUN:-0}
  local quiet=0

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -f|--force)
        dry_run=0
        shift
        ;;
      -n|--dry-run)
        dry_run=1
        shift
        ;;
      -q|--quiet)
        quiet=1
        shift
        ;;
      --)
        shift
        break
        ;;
      -*)
        ish_warn "Invalid option: $1" >&2
        return 1
        ;;
      *)
        break
        ;;
    esac
  done

  local cmd=( "$@" )

  ishlib_debug "ish_run: dry_run=$dry_run, quiet=$quiet, cmd=" "${cmd[@]}"

  [[ $quiet -eq 0 ]] && echo "${cmd[*]}"
  [[ $dry_run -eq 1 ]] || "${cmd[@]}"
}
