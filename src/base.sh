#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED:-}" ] && return 0
ish_SOURCED=1 # source guard

. common.sh
. main.sh
. docstrings.sh
. prints_and_prompts.sh
. has_prefix.sh
. download_file.sh
. has_command.sh

#------------------------------------------------------------------------------
: <<'DOCSTRING'
ishlibVersion
-------------

Print out the version of ishlib loaded. Is redefined for bash.

Arguments:
  -
Returns:
  0

DOCSTRING
ishlibVersion() {
  say "Using ishlib ${ish_Version} (sh-only)"
  return 0
}

#------------------------------------------------------------------------------
# End here unless we're on bash
if [ -z "${BASH_VERSION:-}" ] && [ -z "${ZSH_EVAL_CONTEXT:-}" ]; then

  debug "ishlib: load done (sh-only)"

  # Call ishlib_main if called stand-alone
  [ "$0" = "ishlib.sh" ] && ishlib_main "$@"
  case "$0" in */ishlib.sh) ishlib_main "$@" ;; esac

  # Stop processing rest of file
  return 0
fi
# The following token is used to generate a POSIX-only file for testing
###EOF4SH

#------------------------------------------------------------------------------
: <<'DOCSTRING'
Bash-only functions
==================

DOCSTRING

. common.bash
. array_from_ssv.bash
. strstr.bash
. find_or_install.bash
. dumps_and_asserts.bash
. dry_run.bash
. git.bash
. bash_tricks.bash

#------------------------------------------------------------------------------
# non-POSIX version, see doc for POSIX version above
unset -f ishlibVersion
ishlibVersion() {
  say "ishlib: using ishlib ${ish_Version} (with bash extensions)"
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
Author and license
==================

Author: Hans Liljestrand <hans@liljestrand.dev>
Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>

Distributed under terms of the MIT license.

DOCSTRING

#------------------------------------------------------------------------------
# End of the bash extension, finish and enter main if appropriate

debug "ishlib: load done (bash extensions)"

if [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
  _ishlib_sourced=0
  case $ZSH_EVAL_CONTEXT in *:file) _ishlib_sourced=1 ;; esac
  [ "$_ishlib_sourced" = 0 ] && ishlib_main "$@"
  unset _ishlib_sourced
elif [ -n "${BASH_VERSION:-}" ]; then
  (return 0 2>/dev/null) || ishlib_main "$@"
fi
