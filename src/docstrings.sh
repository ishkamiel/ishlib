#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_docstrings_sh:-}" ] && return 0
ish_SOURCED_docstrings_sh=1 # source guard
. common.sh
###############################################################################

: <<'################################################################DOCSTRING'
`print_docstrings file [options]`

Prints out specific docstrings found in the given file. Default is to just
print the here-documents as they are. However, the script can optionally try
to convert to plain text or markdown. Note that the conversion relies very
specific and largely undocumented conventions followed in ishlib.sh, and will
likely misbehave in other contexts.

Arguments:
file          - the file to read for here-documents
--markdown    - Attempt to produce markdown
--text-only   - Attempt to remove markdown notations
--tag TAG     - use the given TAG for docstrings (default is DOCSTIRNG)
--no-newlines - prevent insertion of newlines
Returns:
  0

################################################################DOCSTRING
print_docstrings() {
  _t="${ish_DebugTag}print_docstring:"

  _filename=''
  _do_newlines=1
  _tag='DOCSTRING'
  _format=

  while [ $# -gt 0 ]; do
    case "$1" in
    --markdown)
      _format="markdown"
      shift
      ;;
    --text-only)
      _format="text"
      shift
      ;;
    --tag)
      _tag="$2"
      shift 2
      ;;
    --no-newlines)
      _do_newlines=0
      shift
      ;;
    *)
      if [ -n "${_filename}" ]; then
        warn "${_t} multiple filenames given: ${_filename} and ${1}"
        return 1
      fi
      _filename="$1"
      shift
      ;;
    esac
  done

  ishlib_debug "${_t} reading ${_filename}"
  ishlib_debug "${_t} printing here-documents tagged with '${_tag}'"

  _old_IFS="$IFS"
  IFS=''
  _print=0
  _newline=1
  _prev=nothing

  while read -r line; do
    _prev2=${_prev}
    _prev=${_print}
    if [ "$line" = ": <<'${_tag}'" ]; then
      ishlib_debug "${_t} found matching start of here-document"
      [ "${_do_newlines}" = 1 ] && [ ${_newline} = 0 ] && echo && _newline=1
      _print=paragraph
    elif [ "$line" = "$_tag" ]; then
      _print=0
    elif [ ${_print} != 0 ]; then
      # First see if we need to update what we're printing
      if has_prefix "$line" "# "; then
        _print="h1"
        [ "${_format}" = 'text' ] && substr --var line "${line}" 3
      elif has_prefix "$line" "## "; then
        _print="h2"
        [ "${_format}" = 'text' ] && substr --var line "${line}" 4
      elif has_prefix "$line" "### "; then
        _print="h3"
        [ "${_format}" = 'text' ] && substr --var line "${line}" 5
      elif has_prefix "$line" "#### "; then
        _print="h4"
        [ "${_format}" = 'text' ] && substr --var line "${line}" 6
      elif has_prefix "$line" '`' && [ "${_prev2}" = "0" ]; then
        # Only catch these at beginning of docstring!
        _print="funcheader"
      elif has_prefix "$line" "Globals:"; then
        _print="listheader"
      elif has_prefix "$line" "Arguments:"; then
        _print="listheader"
      elif has_prefix "$line" "Returns:"; then
        _print="listheader"
      elif [ "$line" = '' ]; then
        _print="newline"
      fi
    fi

    # Markdown specific formatting
    if [ $_format = "markdown" ]; then
      # End listitems
      if [ $_prev = "listitem" ] && [ $_print != "listitem" ]; then
        # _newline=1
        # printf "\n"
        printf "%s\n\n" '```'
      fi
    fi

    if [ "$_prev" != 0 ] && [ "${_print}" != 0 ]; then
      # Then do the printing
      case $_print in
      newline)
        # Skip consqutive newlines, unless this behavior is disables
        if [ ${_do_newlines} = 0 ] || [ ${_newline} = 0 ]; then
          printf "\n"
        fi
        ;;
      listitem)
        # Indent listitems
        [ "${_format}" = 'text' ] && printf '    %s\n' "$line"
        # [ "${_format}" = 'markdown' ] && printf '%s %s\n' '-' "$line"
        [ "${_format}" = 'markdown' ] && printf '    %s  \n' "$line"
        ;;
      listheader)
        [ "${_format}" = 'text' ] && printf '%s\n' "$line"
        [ "${_format}" = 'markdown' ] && printf '##### %s\n' "$line"
        ;;
      funcheader)
        [ "${_format}" = 'text' ] && printf '%s\n' "$line"
        [ "${_format}" = 'markdown' ] && printf '#### %s\n' "$line"
        ;;
      *)
        # Otherwise just print as is
        printf '%s\n' "$line"
        ;;
      esac

      _newline=0 # Set this to 0 here, but set back to 1 later

      case $_print in
      listheader)
        _print=listitem # listitems after a listheader
        # Need to add a new line for markdown before the items
        [ "${_format}" = 'markdown' ] && printf "\n%s\n" '```'
        ;;
      listitem)
        # Assume listitems continue
        ;;
      newline)
        _print=paragraph # Assume pragraph after newline
        _newline=1       # Make sure we remember we had a newline
        ;;
      *)
        _print=paragraph # By default, assume paragrpah is next
        ;;
      esac
    fi
  done <"${_filename}"
  # Restore IFS
  IFS="${_old_IFS}"
  # Unset our "local" variables
  unset _t
  unset _old_IFSs
  unset _print
  unset _newline
  unset _filename
  unset _do_newlines
  unset _tag
  unset _format
  unset _prev
  ishlib_debug "${_t} done"
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
