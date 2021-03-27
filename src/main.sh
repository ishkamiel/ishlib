#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_main_sh:-}" ] && return 0
ish_SOURCED_main_sh=1 # source guard
. common.sh
###############################################################################

ishlib_main() {
  [ -n "${ZSH_SCRIPT+x}" ] && fn="$ZSH_SCRIPT" || fn="$0"

  _target=
  _help_format=--text-only

  while [ $# -gt 0 ]; do
    arg="$1"

    case ${arg} in
    -h | --help)
      _target="help"
      shift
      ;;
    --markdown)
      _help_format=--markdown
      shift
      ;;
    -d)
      export DEBUG=1
      export ISHLIB_DEBUG=1
      shift
      ;;
    *)
      warn "Unknown option: $1"
      shift
      ;;
    esac
  done

  if [ "${_target}" = help ]; then
      print_docstrings "$fn" ${_help_format} --tag "${ish_DOCSTRING}"
      exit 0
  fi

  warn "ishlib run directly wihout parameters!"
  say "To print docs:       ./ishlib.sh -h"
  exit 0
}
