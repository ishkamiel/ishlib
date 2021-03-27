#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_docstrings_sh:-}" ] && return 0
ish_SOURCED_docstrings_sh=1 # source guard
./common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
print_DOCSTRINGs
----------------

Prints out documentation (i.e., the anonymous DOCSTRINGs).

Arguments:
  -
Returns:
  0

DOCSTRING
print_DOCSTRINGs() {
  _old_IFS="$IFS"
  IFS=''
  _ishlib_print=0
  _ishlib_newline=1
  _ishlib_indent=''
  while read -r line; do
    if [ "$line" = ': <<'\''DOCSTRING'\''' ]; then
      [ ${_ishlib_newline} = 0 ] && echo && _ishlib_newline=1
      _ishlib_print=1
      _ishlib_indent=''
    elif [ "$line" = 'DOCSTRING' ]; then
      _ishlib_print=0
      _ishlib_indent=''
    else
      if [ ${_ishlib_print} != 0 ]; then
        if has_prefix "$line" "----"; then
          _ishlib_print=2
        elif has_prefix "$line" "===="; then
          _ishlib_print=1
        elif has_prefix "$line" "Globals:"; then
          _ishlib_indent='  '
          _ishlib_print=3
        elif has_prefix "$line" "Arguments:"; then
          _ishlib_indent='  '
          _ishlib_print=3
        elif has_prefix "$line" "Returns:"; then
          _ishlib_indent='  '
          _ishlib_print=3
        fi

        [ "$line" = '' ] && _ishlib_newline=1 || _ishlib_newline=0
        printf '%s%s\n' "$_ishlib_indent" "$line"

        case $_ishlib_print in
        2) _ishlib_indent='  ' ;;
        3) _ishlib_indent='    ' ;;
        *) _ishlib_indent='' ;;
        esac
      fi
    fi
  done <"$1"
  IFS="${_old_IFS}"
  unset _old_IFSs
  unset _ishblib_print
  unset _ishblib_newline
  unset _ishblib_indent
  return 0
}
