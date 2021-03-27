#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_has_command_sh:-}" ] && return 0
ish_SOURCED_has_command_sh=1 # source guard
# shellcheck source=common.sh
./common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
has_command cmd
---------------

Checks if a comman exists, either as an executable in the path, or as a shell
function. Returns 0 if found, 1 otherwise. No output.

Arguments:
  cmd - name of binary or function to check for
Returns:
  0 - if command was found
  1 - if command not found
  2 - if argument was missing
DOCSTRING
has_command() {
  [ -z "$1" ] && warn "has_command: bad 1st arg" && return 2
  if command -v "$1" >/dev/null 2>&1; then return 0; fi
  return 1
}
