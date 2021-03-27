#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_prints_and_prompts_sh:-}" ] && return 0
ish_SOURCED_prints_and_prompts_sh=1 # source guard
./common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
say ...
-------

Prints the given args to stderr, but only if DEBUG=1.

Globals:
  ish_ColorDebug - printed before arguments (e.g., to set color)
  ish_ColorNC - printed after arguments (e.g., to reset color)
Arguments:
  ... - all arguments are printed
Returns:
  0 - always
DOCSTRING
debug() {
  [ -z "${DEBUG:-}" ] || [ "${DEBUG:-}" -ne 1 ] && return 0
  printf >&2 "[DD] %b%b%b\n" "${ish_ColorDebug}" "$*" "${ish_ColorNC}"
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
`ishlib_debug ...`

Passes args to debug, but only if ISHLIB_DEBUG is set to 1.

Globals:
  ISHLIB_DEBUG - does nothing unless this is 1
Arguments:
  ... - all arguments are printed
Returns:
  0 - always
DOCSTRING
ishlib_debug() {
  [ -z "${ISHLIB_DEBUG:-}" ] || [ "${ISHLIB_DEBUG:-}" -ne 1 ] && return 0
  debug "$@"
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
say ...
-------

Prints the given args to stderr.

Globals:
  ish_ColorSay - printed before arguments (e.g., to set color)
  ish_ColorNC - printed after arguments (e.g., to reset color)
Arguments:
  ... - all arguments are printed
Returns:
  0 - always
DOCSTRING
say() {
  printf >&2 "[--] %b%b%b\n" "${ish_ColorSay}" "$*" "${ish_ColorNC}"
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
warn ...
--------

Prints the given args to stderr.

Globals:
  ish_ColorWarn - printed before arguments (e.g., to set color)
  ish_ColorNC - printed after arguments (e.g., to reset color)
Arguments:
  ... - all arguments are printed
Returns:
  0 - always
DOCSTRING
warn() {
  printf >&2 "[WW] %b%b%b\n" "${ish_ColorWarn}" "$*" "${ish_ColorNC}"
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
fail ...
--------

Prints the given args to stderr and then exits with the value 1.

Globals:
  ish_ColorFail - printed before arguments (e.g., to set color)
  ish_ColorNC - printed after arguments (e.g., to reset color)
Arguments:
  ... - all arguments are printed
Returns:
  never returns

DOCSTRING
fail() {
  printf >&2 "[EE] %b%b%b\n" "${ish_ColorFail}" "$*" "${ish_ColorNC}"
  exit 1
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
dry_run ...
--------

Prints the given args to stderr and then exits with the value 1.

Globals:
  ish_ColorDryRun - printed before arguments (e.g., to set color)
  ish_ColorNC - printed after arguments (e.g., to reset color)
Arguments:
  ... - all arguments are printed
Returns:
  never returns

DOCSTRING
dry_run() {
  printf >&2 "[**] %bdry run: %b%b\n" "${ish_ColorDryRun}" "$*" "${ish_ColorNC}"
}
