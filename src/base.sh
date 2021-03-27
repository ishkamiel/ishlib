#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED:-}" ] && return 0
ish_SOURCED=1 # source guard

: <<'################################################################DOCSTRING'
__ISHLIB_README__

### POSIX-compliant functions
################################################################DOCSTRING

. common.sh
. main.sh
. docstrings.sh
. prints_and_prompts.sh
. has_prefix.sh
. download_file.sh
. has_command.sh
. substr.sh

# End here unless we're on bash, and enter main if directly run
if [ -z "${BASH_VERSION:-}" ] && [ -z "${ZSH_EVAL_CONTEXT:-}" ]; then
  debug "ishlib: load done (sh-only)"
  # Call ishlib_main if called stand-alone
  [ "$0" = "ishlib.sh" ] && ishlib_main "$@"
  case "$0" in */ishlib.sh) ishlib_main "$@" ;; esac
  return 0 # Stop processing rest of file
fi
###EOF4SH # this is just for testing

: <<'DOCSTRING'
### Bash-only functions
DOCSTRING

. common.bash
. array_from_ssv.bash
. strstr.bash
. find_or_install.bash
. dumps_and_asserts.bash
. dry_run.bash
. git.bash
. bash_tricks.bash

debug "ishlib: load done (bash extensions)"
# Entering main if we are being directly run
if [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
  _ishlib_sourced=0
  case $ZSH_EVAL_CONTEXT in *:file) _ishlib_sourced=1 ;; esac
  [ "$_ishlib_sourced" = 0 ] && ishlib_main "$@"
  unset _ishlib_sourced
elif [ -n "${BASH_VERSION:-}" ]; then
  (return 0 2>/dev/null) || ishlib_main "$@"
fi
