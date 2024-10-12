#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_prints_and_prompts_sh:-}" ] && return 0
ish_SOURCED_prints_and_prompts_sh=1 # source guard

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"

: <<'DOCSTRING'

#### Print and debug helpers

The print functions all follow the same pattern, i.e, they print a short tag
followed by the all arguments colorized as specified by global color tags.
At present, all printouts are to sdtderr. All functions return 0, or in
case of failure, never returns.

DOCSTRING

: <<'DOCSTRING'
`say ...`
DOCSTRING
say() {
  printf >&2 "[--] %b%b%b\n" "${ish_ColorSay}" "$*" "${ish_ColorNC}"
  return 0
}

: <<'DOCSTRING'
`warn ...`
DOCSTRING
warn() {
  if [ -z "${BASH_VERSION:-}" ]; then
    printf >&2 "[WW] %b%b%b\n" "${ish_ColorWarn}" "$*" "${ish_ColorNC}"
  else
    #shellcheck disable=SC3044
    printf >&2 "[WW] %b%b (at %b)%b\n" "${ish_ColorWarn}" \
      "$*" \
      "$(caller 0 | awk -F' ' '{print $3 ", line " $1}')" \
      "${ish_ColorNC}"
  fi

  return 0
}

: <<'DOCSTRING'
`fail ...`

Prints the args and then calls `exit 1`
DOCSTRING
fail() {
  if [ -z "${BASH_VERSION:-}" ]; then
    printf >&2 "[EE] %b%b%b\n" "${ish_ColorFail}" "$*" "${ish_ColorNC}"
  else
    #shellcheck disable=SC3044
    printf >&2 "[EE] %b%b (at %b)%b\n" "${ish_ColorFail}" \
      "$*" \
      "$(caller 0 | awk -F' ' '{print $3 ", line " $1}')" \
      "${ish_ColorNC}"
  fi
  exit 1
}

: <<'DOCSTRING'
`say_dry_run ...`

Prints the args with the dry_run tag, mainly for internal use.
DOCSTRING
say_dry_run() {
  printf >&2 "[**] %bdry run: %b%b\n" "${ish_ColorDryRun}" "$*" "${ish_ColorNC}"
}

: <<'DOCSTRING'
`debug ...`

Globals:
  DEBUG - does nothing unless DEBUG=1
DOCSTRING
debug() {
  [ -z "${DEBUG:-}" ] || [ "${DEBUG:-}" -ne 1 ] && return 0
  printf >&2 "[DD] %b%b%b\n" "${ish_ColorDebug}" "$*" "${ish_ColorNC}"
  return 0
}

: <<'DOCSTRING'
`ishlib_debug ...`

Globals:
  DEBUG        - does nothing unless DEBUG=1
  ISHLIB_DEBUG - does nothing unless this is 1
DOCSTRING
ishlib_debug() {
  [ -z "${ISHLIB_DEBUG:-}" ] || [ "${ISHLIB_DEBUG:-}" -ne 1 ] && return 0
  debug "$@"
  return 0
}
