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
`print_docstrings file [options]`

Prints out specific docstrings found in the given file. Default is to just
print the here-documents as they are. However, the script can optionally try
to convert to plain text or markdown. Note that the conversion relies very
specific and largely undocumented conventions followed in ishlib.sh, and will
likely misbehave in other contexts.

Arguments:
  file - the file to read for here-documents
Options:
  --markdown - Attempt to produce markdown
  --text-only - Attempt to remove markdown notations
  --tag TAG - use the given TAG for docstrings (default is DOCSTIRNG)
  --no-newlines - prevent insertion of newlines
Returns:
  0

DOCSTRING
print_docstrings() {
  fail "work in progress, not implemented"
  _t="{ish_DebugTag}print_docstring:";

  _ishlib_filename=''
  _ishlib_do_newlines=1
  _ishlib_tag='DOCSTRING'

  while [ $# -gt 0 ]; do
    case "$1" in
    --markdown)
      warn "Not ipmlemented"
      shift
      ;;
    --text-only)
      warn "Not implemented"
      shift
      ;;
    --tag)
      _ishlib_tag="$2"
      shift 2
      ;;
    --no-newlines)
      _ishlib_do_newlines=0
      shift
      ;;
    *)
      if [ -n "${_ishlib_filename}" ]; then
        warn "${_t} multiple filenames given: ${_ishlib_filename} and ${1}"
        return 1
      fi
      _ishlib_filename="$1"
      shift;
      ;;
    esac
  done

  ishlib_debug "${_t} reading ${_ishlib_filename}"

  _old_IFS="$IFS"
  IFS=''
  _ishlib_print=0
  _ishlib_newline=1
  _ishlib_indent=''

  while read -r line; do
    if [ "$line" = ": <<'\''${_ishlib_tag}'\''" ]; then
      [ "${_ishlib_do_newlines}" = 1 ] && [ ${_ishlib_newline} = 0 ] && echo && _ishlib_newline=1
      _ishlib_print=1
      _ishlib_indent=''
    elif [ "$line" = "$_ishlib_tag" ]; then
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
  done <"${_ishlib_filename}"
  # Restore IFS
  IFS="${_old_IFS}"
  # Unset our "local" variables
  unset _old_IFSs
  unset _ishblib_print
  unset _ishblib_newline
  unset _ishblib_indent
  unset _ishlib_filename
  unset _ishlib_do_newlines
  unset _ishlib_tag
  return 0
}


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
