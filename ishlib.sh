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
# ishlib 2021-03-27.1720.da9a5f4

This is a collection of various scripts and tricks collected along the years.

The script is meant to be sourced elsewhere, but can be invoked as
`./ishlib.sh -h` flag to show the same documentation as below. The source
files in `./src` need not be manually used, they are already in `ishlib.sh`.

The documentation contains references to original sources where available,
but in practice this has been accumulated along the years, so many sources
are likely listed. Feel free to drop me a note if you notice some source or
acknowledgement that is missing.

## Known bugs and issues

- Documentation for `dry_run` is wrong.

## Documentation

### POSIX-compliant functions
################################################################DOCSTRING

DEBUG=${DEBUG:-0}
DRY_RUN=${DRY_RUN:-0}

ISHLIB_DEBUG=${DEBUG:-0}

export ish_VERSION_NAME="ishlib"
export ish_VERSION_NUMBER="2021-03-27.1720.da9a5f4"
export ish_VERSION_VARIANT="POSIX"

export TERM_COLOR_NC='\e[0m'
export TERM_COLOR_BLACK='\e[0;30m'
export TERM_COLOR_GRAY='\e[1;30m'
export TERM_COLOR_RED='\e[0;31m'
export TERM_COLOR_LIGHT_RED='\e[1;31m'
export TERM_COLOR_GREEN='\e[0;32m'
export TERM_COLOR_LIGHT_GREEN='\e[1;32m'
export TERM_COLOR_BROWN='\e[0;33m'
export TERM_COLOR_YELLOW='\e[1;33m'
export TERM_COLOR_BLUE='\e[0;34m'
export TERM_COLOR_LIGHT_BLUE='\e[1;34m'
export TERM_COLOR_PURPLE='\e[0;35m'
export TERM_COLOR_LIGHT_PURPLE='\e[1;35m'
export TERM_COLOR_CYAN='\e[0;36m'
export TERM_COLOR_LIGHT_Cyan='\e[1;36m'
export TERM_COLOR_LIGHT_GRAY='\e[0;37m'
export TERM_COLOR_WHITE='\e[1;37m'

# shellcheck disable=SC2034
ish_ColorNC='\033[0m'
# shellcheck disable=SC2034
ish_ColorDebug="${TERM_COLOR_NC}"
# shellcheck disable=SC2034
ish_ColorSay="${TERM_COLOR_BLUE}"
# shellcheck disable=SC2034
ish_ColorWarn="${TERM_COLOR_PURPLE}"
# shellcheck disable=SC2034
ish_ColorFail="${TERM_COLOR_RED}"
# shellcheck disable=SC2034
ish_ColorDryRun="${TERM_COLOR_BROWN}"

# shellcheck disable=SC2034
ish_DOCSTRING='################################################################DOCSTRING'

# shellcheck disable=SC2034
ish_DebugTag="ishlib:"

: <<'################################################################DOCSTRING'

`ishlib_version`

Print out the version of ishlib loaded.

################################################################DOCSTRING
ishlib_version() {
  say "${ish_VERSION_NAME} ${ish_VERSION_NUMBER} (${ish_VERSION_VARIANT})"
  return 0
}

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

: <<'################################################################DOCSTRING'
`print_docstrings file [options]`

Prints out specific docstrings found in the given file. Default is to just
print the here-documents as they are. However, the script can optionally try
to convert to plain text or markdown. Note that the conversion relies very
specific and largely undocumented conventions followed in ishlib.sh, and will
likely misbehave in other contexts.

Arguments:
--markdown - Attempt to produce markdown
file - the file to read for here-documents
--text-only - Attempt to remove markdown notations
--tag TAG - use the given TAG for docstrings (default is DOCSTIRNG)
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
    if [ "$line" = ": <<'${_tag}'" ]; then
      ishlib_debug "${_t} found matching start of here-document"
      [ "${_do_newlines}" = 1 ] && [ ${_newline} = 0 ] && echo && _newline=1
      _print=paragraph
    elif [ "$line" = "$_tag" ]; then
      _print=0
    elif [ ${_print} != 0 ]; then
      _prev=$_print
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
      elif has_prefix "$line" '`'; then
        # FIXME: This will match too much!
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

      # Markdown specific formatting
      if [ $_format = "markdown" ]; then
        # End listitems
        if [ $_prev = "listitem" ] && [ $_print != "listitem" ]; then
          # _newline=1
          # printf "\n"
          printf "%s\n\n" '```'
        fi
      fi

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

#------------------------------------------------------------------------------
: <<'DOCSTRING'
has_prefix str prefx

Source: 

Arguments:
  str - string to look into
  prefix - the prefix to check for
Returns:
  0 - if prefix is found
  1 - if prefix isn't found

DOCSTRING
has_prefix() {
  case "$1" in "$2"*) return 0 ;; esac
  return 1
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
download_file $url $dst
-----------------------

Attempts to download file at $url to $dst, creating the containing directory
if needed. Will first try curl, then wget, and finally fail if neither is
awailable.

Arguments:
  url - the URL to download
  dsg - the filename to store the download at
Returns: 
  0 - on success
  1 - bad arguments given
  2 - when neither curl nor wget was found
  x - error code from curl/wget

DOCSTRING
download_file() {
  [ -z "$1" ] && warn "downloadFile: bad 1st arg" && return 1
  [ -z "$2" ] && warn "downloadFile: bad 2nd arg" && return 1

  say "downloading ${1} to ${2}"
  mkdir -p "$(dirname "$2")"

  if command -v curl >/dev/null 2>&1; then
    if [ "${DRY_RUN:-0}" = 1 ]; then
      dry_run curl --progress-bar -fLo "$2" --create-dirs "$1"
      return 0
    else
      curl --progress-bar -fLo "$2" --create-dirs "$1"
      return $?
    fi
  elif command -v wget >/dev/null 2>&1; then
    if [ "${DRY_RUN:-0}" = 1 ]; then
      dry_run wget -nv -O "$2" "$1"
      return 0
    else
      wget -nv -O "$2" "$1"
      return $?
    fi
  fi
  warn "downloadFile: Cannot find curl or wget!" && return 2
}

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

: <<'################################################################DOCSTRING'
`substr string start [end] [--var result_var]`
################################################################DOCSTRING
substr() {
  _t="${ish_DebugTag}substr:"
  _ishlib_str=
  _ishlib_start=
  _ishlib_end=
  _ishlib_var=
  _ishlib_res=0

  while [ $# -gt 0 ]; do
    case "$1" in
    --var)
      _ishlib_var="$2"
      shift 2
      ;;
    *)
      if [ "${_ishlib_res}" -eq 0 ]; then
        _ishlib_res=1
        _ishlib_str="$1"
      elif [ "${_ishlib_res}" -eq 1 ]; then
        _ishlib_res=2
        _ishlib_start="$1"
      elif [ "${_ishlib_res}" -eq 2 ]; then
        _ishlib_res=3
        _ishlib_end="$1"
      else
        warn "${_t} too many arguments!"
        return 1
      fi
      shift 1
      ;;
    esac
  done

  if [ "${_ishlib_res}" -lt 2 ]; then
    warn "${_t} too few arguments ${_ishlib_res}!"
    return 1
  fi

  if [ -n "${_ishlib_var+x}" ] && [ -z "${_ishlib_var+x}" ]; then
    warn "${_t} ${_ishlib_var} is not a bound variable"
    return 1
  fi

  _ishlib_res="$(echo "${_ishlib_str}" | cut -c"${_ishlib_start}-${_ishlib_end:-}")"

  if [ -n "${_ishlib_var+x}" ]; then
    eval "${_ishlib_var}=\"${_ishlib_res}\""
  else
    printf "%s" "${_ishlib_res}"
  fi

  unset _ishlib_str
  unset _ishlib_start
  unset _ishlib_end
  unset _ishlib_var
  unset _ishlib_res
  return 0
}

: <<'################################################################DOCSTRING'
`strlen string [--var result_var]`
################################################################DOCSTRING
strlen() {
  warn "Just use \${\#var}"
  _ishlib_str=
  _ishlib_var=
  _ishlib_res=

  while [ $# -gt 0 ]; do
    case "$1" in
    --var)
      _ishlib_var="$2"
      shift 2
      ;;
    *)
      [ -z "${_ishlib_str}" ] || (warn "bad arguments to strlen" && return 1)
      _ishlib_str="$1"
      sfhit
      ;;
    esac
  done

  _ishlib_res="$#variable"

  if [ -n "${_ishlib_var}" ]; then
    eval "${_ishlib_var}=\"${_ishlib_res}\""
  else
    printf "%s" "${_ishlib_res}"
  fi

  unset _ishlib_str
  unset _ishlib_var
  unset _ishlib_res
  return 0
}

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

export ish_VERSION_VARIANT="POSIX+bash"

#------------------------------------------------------------------------------
: <<'DOCSTRING'
array_from_ssv var str
----------------------

Read space-separated values into an array variable.

Arguments:
  var - the name of an array varialbe to populate
  str - the string to split
Returns:
  0 - on success
  1 - on failure

DOCSTRING
array_from_ssv() {
  # Create a local reference
  declare -n _ish_tmp="${1}"
  # Then allows us to populate local variables...
  for e in ${*:2}; do
    _ish_tmp+=("$e")
  done
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
strstr haystack needle [pos_var]
--------------------------------

Finds needle in given haystack, if pos_var is given, then also stores the
position of the found variable into ${!pos_var}.

Arguments: 
    haystack - the string to look in
    needle - the string to search for
    pos_var - name of a variable for positionli
Side-effects:
    ${!pos_var} - set to -1 on fail, otherwise to the position of needle
Returns:
    0 - if needle was found
    1 - otherwise

DOCSTRING
strstr() {
  local x="${1%%$2*}"
  if [[ "$x" = "$1" ]]; then
    [[ -n "${3+x}" ]] && printf -v "$3" "%s" "-1"
    return 1
  fi
  [[ -n "${3+x}" ]] && printf -v "$3" "%s" "${#x}"
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
find_or_install var [installer [installer args]]
-----------------------------

Tries to find and set path for command defined by the variable named var,
i.e., ${!var}. Will also update the var variable with a full path if
applicable.

Arguments:
  var - name of variable holding command
  installer - optional installer function
  install_path - where the installer will install the binary
Side effects:
  ${!var} - the variable named by var is set to the found or installed cmd
Returns:
  0 - if cmd found or installed
  1 - if cmd not found, nor successfully installed

DOCSTRING
find_or_install() {
  [[ -n "$1" ]] || fail "ishlib:find_or_install: missing 1st argument"
  [[ -n "${1+x}" ]] || fail "ishlib:find_or_install: Unbound variable: '$1'"
  [[ -n "${!1}" ]] || fail "ishlib:find_or_install: Empty variable: $1"
  local var="$1"
  local func="${2:-}"
  local val="${!var}"
  local name="${val}"
  shift 2

  if has_command "$val"; then
    local new_val
    new_val="$(which "$val")"
    if [[ "$val" = "$new_val" ]]; then
      debug "ishlib:find_or_install: found $val"
    else
      debug "ishlib:find_or_install: found $val, setting to ${new_val}"
      printf -v "${var}" "%s" "$(which "$val")"
    fi
    return 0
  elif [[ -n $func ]]; then
    debug "ishlib:find_or_install: running $func $var" "$@"
    if $func "$var" "$@"; then
      if ! has_command "${!var}"; then
        warn "ishlib:find_or_install: custom installer for $name reported success, but $var is set to ${!var}, which is not a valid command"
        if is_dry; then return 0; fi
        return 1
      fi
      return 0
    fi
    debug "ishlib:find_or_install: provided installer failed"
  fi
  return 1
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
dump var1 [var2 var3 ...]
-----------------

Will call dumpVariable for each member of vars.

Globals:
Arguments:
  varN - name of a variable to dump
Returns:
  0 - if all varN were bound
  n - number of unbound varN encountered
DOCSTRING
dump() {
  local vars=("$@")
  local unbound=0
  for var in "${vars[@]}"; do
    if [[ -n "${var+x}" ]]; then
      debug "$var=${!var}"
    else
      debug "$var is unbound"
      unbound=$((unbound + 1))
    fi
  done
  return $unbound
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
do_or_dry cmd ...
DOCSTRING
do_or_dry() {
  local cmd=$1
  shift
  local args=("$@")

  debug "ishlib:do_or_dry: cwd=$(if is_dry; then echo "\$(pwd)"; else pwd; fi), running $cmd" "${args[@]}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    dry_run "$cmd" "${args[@]}"
    return 0
  else
    $cmd "${args[@]}"
    return $?
  fi
}

#------------------------------------------------------------------------------
: <<'DOCSTRINg'
do_or_dry_bg pid cmd ...
DOCSTRINg
do_or_dry_bg() {
    declare -n _ish_tmp_pid=$1
    local cmd=$2
    shift 2
    local args=("$@")

    debug "ishlib:do_or_dry_bg: cwd=$(if is_dry; then echo "\$(pwd)"; else pwd; fi), running $cmd" "${args[@]}" "\\adsf&"
    if is_dry; then
        dry_run "$cmd" "${args[@]}" "&"
        _ish_tmp_pid=""
        return 0
    else
        $cmd "${args[@]}" &
        _ish_tmp_pid=$!
        debug "ishlib:do_or_dry_bg: started $_ish_tmp_pid!"
        return 0
    fi
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
do_or_dry cmd ...
DOCSTRING
is_dry() {
  [[ "${DRY_RUN:-}" = 1 ]] && return 0
  return 1
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
git_clone_or_update url dir

Arguments:
  url - the git repository remote
  dir - the local directory for the repository
Globals:
  bin_git - if specified, will use the given command in place of git
Returns:
  0 - on success
  x - on failure, either 1 or return value of git
DOCSTRING
git_clone_or_update() {
  local t="ishlib:git_clone_or_update:"
  local url="$1"
  local dir="$2"
  local branch=""
  local update_submodules=0
  shift 2

  local bad_args=0
  local positional=()
  while [[ $# -gt 0 ]]; do
    arg="$1"

    case ${arg} in
    -b | --branch)
      branch="$2"
      shift 2
      ;;
    --update-submodules)
      update_submodules=1
      shift
      ;;
    *)
      warn "$t unknown argument $1"
      bad_args=$((bad_args + 1))
      shift
      ;;
    esac
  done
  set -- "${positional[@]}" # restore positional parameters
  [[ $bad_args -eq 0 ]] || return 1

  local bin_git=${bin_git:-git}

  has_command "${bin_git}" || (warn "$t cannot find ${bin_git}" && return 1)

  if [[ ! -e "${dir}/.git" ]]; then
    local git_args=()
    [[ -n "$branch" ]] && git_args+=("-b" "$branch")
    git_args+=("$url" "$dir")

    debug "$t cloning ${url} to ${dir}"
    do_or_dry mkdir -p "${dir}" || (warn "$t failed to enter $dir" && return 1)
    do_or_dry "$bin_git" clone "${git_args[@]}" || (warn "$t git clone failed" && return 1)

    if [[ "${update_submodules}" = "1" ]]; then
      debug "$t initializing submodules"
      do_or_dry pushd "${dir}" || (warn "$t failed to pusd ${dir}" && return 1)
      do_or_dry "$bin_git" submodule update --init --recursive || (warn "$t submodule update failed" && return 1)
      do_or_dry popd || (warn "$t filed to popd" && return 1)
    fi
  else
    debug "$t updating ${dir}"

    do_or_dry pushd "${dir}" || (warn "$t failed to pusd ${dir}" && return 1)

    if [[ -n "$branch" ]]; then
      do_or_dry "$bin_git" checkout "$branch" || (warn "$t checkout $branch failed" && return 1)
    fi

    do_or_dry "$bin_git" pull || (warn "ishlib:git_clone_or_update" && return 1)
    do_or_dry popd || (warn "$t filed to popd" && return 1)
  fi
  return 0
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
copy_function src dst
----------------------

Copies the src function to a new function named dst.

Source: https://stackoverflow.com/a/18839557

Arguments:
  src - the name to rename from
  dst - the name to rename to
Returns:
  0 - on success
  1 - on failure

DOCSTRING
copy_function() {
  test -n "$(declare -f "$1")" || return 1
  eval "${_/$1/$2}" || return 1
}

#------------------------------------------------------------------------------
: <<'DOCSTRING'
rename_function src dst
-----------------------

Renames the src function to dst.

Source: https://stackoverflow.com/a/18839557

Arguments:
  src - the name to rename from
  dst - the name to rename to
Returns:
  0 - on success
  1 - on failure

DOCSTRING
rename_function() {
  copy_function "$@" || return 1
  unset -f "$1"
  return 0
}

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
