#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_strstr_bash:-}" ] && return 0
ish_SOURCED_strstr_bash=1 # source guard

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"

: <<'DOCSTRING'
substr string start [end] [--var result_var]
DOCSTRING
substr() {
  _t="${ish_DebugTag}substr:"
  _ishlib_str=
  _ishlib_start=
  _ishlib_end=
  _ishlib_var=
  _ishlib_res=0

  while [ $# -gt 0 ]; do
    case "$1" in
    --var)
      _ishlib_var="$2"
      shift 2
      ;;
    *)
      if [ "${_ishlib_res}" -eq 0 ]; then
        _ishlib_res=1
        _ishlib_str="$1"
      elif [ "${_ishlib_res}" -eq 1 ]; then
        _ishlib_res=2
        _ishlib_start="$1"
      elif [ "${_ishlib_res}" -eq 2 ]; then
        _ishlib_res=3
        _ishlib_end="$1"
      else
        ish_warn "${_t} too many arguments!"
        return 1
      fi
      shift 1
      ;;
    esac
  done

  if [ "${_ishlib_res}" -lt 2 ]; then
    ish_warn "${_t} too few arguments ${_ishlib_res}!"
    return 1
  fi

  if [ -n "${_ishlib_var+x}" ] && [ -z "${_ishlib_var+x}" ]; then
    ish_warn "${_t} ${_ishlib_var} is not a bound variable"
    return 1
  fi

  _ishlib_res="$(echo "${_ishlib_str}" | cut -c"${_ishlib_start}-${_ishlib_end:-}")"

  if [ -n "${_ishlib_var+x}" ]; then
    eval "${_ishlib_var}=\"${_ishlib_res}\""
  else
    printf "%s" "${_ishlib_res}"
  fi

  unset _ishlib_str
  unset _ishlib_start
  unset _ishlib_end
  unset _ishlib_var
  unset _ishlib_res
  return 0
}

: <<'DOCSTRING'
`strlen string [--var result_var]`
DOCSTRING
strlen() {
  ish_warn "Just use \${\#var}"
  _ishlib_str=
  _ishlib_var=
  _ishlib_res=

  while [ $# -gt 0 ]; do
    case "$1" in
    --var)
      _ishlib_var="$2"
      shift 2
      ;;
    *)
      [ -z "${_ishlib_str}" ] || (ish_warn "bad arguments to strlen" && return 1)
      _ishlib_str="$1"
      sfhit
      ;;
    esac
  done

  _ishlib_res="$#variable"

  if [ -n "${_ishlib_var}" ]; then
    eval "${_ishlib_var}=\"${_ishlib_res}\""
  else
    printf "%s" "${_ishlib_res}"
  fi

  unset _ishlib_str
  unset _ishlib_var
  unset _ishlib_res
  return 0
}
