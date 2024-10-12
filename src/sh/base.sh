#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED:-}" ] && return 0
ish_SOURCED=1 # source guard

: <<'DOCSTRING'
__ISHLIB_README__

### POSIX-compliant functions
DOCSTRING

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"
# shellcheck source=main.sh
. "$ISHLIB/src/sh/main.sh"
# shellcheck source=docstrings.sh
. "$ISHLIB/src/sh/docstrings.sh"
# shellcheck source=prints_and_prompts.sh
. "$ISHLIB/src/sh/prints_and_prompts.sh"
# shellcheck source=has_prefix.sh
. "$ISHLIB/src/sh/has_prefix.sh"
# shellcheck source=download_file.sh
. "$ISHLIB/src/sh/download_file.sh"
# shellcheck source=has_command.sh
. "$ISHLIB/src/sh/has_command.sh"
# shellcheck source=substr.sh
. "$ISHLIB/src/sh/substr.sh"
# shellcheck source=path.sh
. "$ISHLIB/src/sh/path.sh"

# End here unless we're on bash, and enter main if directly run
if [ -z "${BASH_VERSION:-}" ] && [ -z "${ZSH_EVAL_CONTEXT:-}" ]; then
  ish_debug "ishlib: load done (sh-only)"
  # Call ishlib_main if called stand-alone
  [ "$0" = "ishlib.sh" ] && ishlib_main "$@"
  case "$0" in */ishlib.sh) ishlib_main "$@" ;; esac
  return 0 # Stop processing rest of file
fi
###EOF4SH # this is just for testing

: <<'DOCSTRING'
### Bash-only functions
DOCSTRING

# shellcheck source=../bash/common.bash
. "$ISHLIB/src/bash/common.bash"
# shellcheck source=../bash/array_from_ssv.bash
. "$ISHLIB/src/bash/array_from_ssv.bash"
# shellcheck source=../bash/strstr.bash
. "$ISHLIB/src/bash/strstr.bash"
# shellcheck source=../bash/find_or_install.bash
. "$ISHLIB/src/bash/find_or_install.bash"
# shellcheck source=../bash/dumps_and_asserts.bash
. "$ISHLIB/src/bash/dumps_and_asserts.bash"
# shellcheck source=../bash/dry_run.bash
. "$ISHLIB/src/bash/dry_run.bash"
# shellcheck source=../bash/git.bash
. "$ISHLIB/src/bash/git.bash"
# shellcheck source=../bash/bash_tricks.bash
. "$ISHLIB/src/bash/bash_tricks.bash"

ish_debug "ishlib: load done (bash extensions)"
# Entering main if we are being directly run
if [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
  _ishlib_sourced=0
  case $ZSH_EVAL_CONTEXT in *:file) _ishlib_sourced=1 ;; esac
  [ "$_ishlib_sourced" = 0 ] && ishlib_main "$@"
  unset _ishlib_sourced
elif [ -n "${BASH_VERSION:-}" ]; then
  (return 0 2>/dev/null) || ishlib_main "$@"
fi
