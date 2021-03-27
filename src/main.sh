#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_main_sh:-}" ] && return 0
ish_SOURCED_main_sh=1 # source guard
###############################################################################

#------------------------------------------------------------------------------
ishlib_main() {
  [ -n "${ZSH_SCRIPT+x}" ] && fn="$ZSH_SCRIPT" || fn="$0"

  while [ $# -gt 0 ]; do
    arg="$1"

    case ${arg} in
    -h | --help)
      print_DOCSTRINGs "$fn"
      exit 0
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
  warn "ishlib run directly wihout parameters!"
  say "To print docs:       ./ishlib.sh -h"
  exit 0
}
