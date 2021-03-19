#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# Include guard...
[ -n "${ish_SOURCED:-}" ] && return 0
ish_SOURCED=1

ish_Version="0.1"

DEBUG=${DEBUG:-1}

ish_ColorRed='\033[0;31m'
ish_ColorBlue='\033[0;34m'
ish_ColorNC='\033[0m'
ish_ColorDebug="${ish_ColorNC}"
ish_ColorSay="${ish_ColorBlue}"
ish_ColorWarn="${ish_ColorBlue}"
ish_ColorFail="${ish_ColorRed}"

#------------------------------------------------------------------------------
### POSIX compliant functions
#
# The following functions are always exposed when sourcing the library and
# should be POSIX compliant (e.g., work with sh or dash).
#

#### `say(...)`
#
# Prints the given args to stderr, but only if DEBUG=1.
#
debug() {
    [ -z "${DEBUG:-}" ] || [ "${DEBUG:-}" -ne 1 ] && return 0
    printf >&2 "[DD] %b%b%b\n" "${ish_ColorDebug}" "$@" "${ish_ColorNC}"
    return 0
}

#### say(...)
#
# Prints the given args to stderr.
#
say() {
    printf >&2 "[--] %b%b%b\n" "${ish_ColorSay}" "$@" "${ish_ColorNC}"
    return 0
}

#### warn(...)
#
# Prints the given args to stderr.
#
warn() {
    printf >&2 "[WW] %b%b%b\n" "${ish_ColorWarn}" "$@" "${ish_ColorNC}"
    return 0
}

#### fail(..)
#
# Prints an error message and then exists with return value 1.
#
fail() {
    printf >&2 "[EE] %b%b%b\n" "${ish_ColorFail}" "$@" "${ish_ColorNC}"
    exit 1
}

#### downloadFile($url, $dst)
#
# Attempts to download file at $url to $dst, creating the containing directory
# if needed. Will first try curl, then wget, and finally fail if neither is
# awailable.
#
downloadFile() {
    [ -z "$1" ] && warn "downloadFile: bad 1st arg" && return 1
    [ -z "$2" ] && warn "downloadFile: bad 2nd arg" && return 1

    ish_say "downloading ${1} to ${2}"
    mkdir -p "$(dirname "$2")"

    if command -v curl >/dev/null 2>&1; then
        curl --progress-bar -fLo "$2" --create-dirs "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -nv -O "$2" "$1"
    else
        warn "downloadFile: Cannot find curl or wget!" && return 1
    fi
    return 0
}

#### hasCommand $cmd
#
# Checks if a comman exists, either as an executable in the path, or as a shell
# function. Returns 0 if found, 1 otherwise. No output.
#
hasCommand() {
    [ -z "$1" ] && warn "hasCommand: bad 1st arg" && return 1
    if command -v "$1" >/dev/null 2>&1; then return 0; fi
    return 1
}

#### ishlibVersion
#
# Print out the version of ishlib loaded
#
ishlibVersion() {
    say "Using ishlib ${ish_Version} (sh-only)"
}

#------------------------------------------------------------------------------
# Check if we're sourced and print docs if not

# Try to detect if we're being run directly
__sourced=0
if [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
    case $ZSH_EVAL_CONTEXT in *:file) __sourced=1 ;; esac
elif [ -n "${BASH_VERSION:-}" ]; then
    (return 0 2>/dev/null) && __sourced=1
else
    # This is real ugly, but kinda works :/
    __sourced=1
    [ "$0" = "ishlib.sh" ] && __sourced=0
    [ "$0" = "./ishlib.sh" ] && __sourced=0
fi

# Print usage if this is called directly, then exit
if [ "$__sourced" = "0" ]; then
    __PRINT=0
    while read -r line; do
        case $line in
        \#\#\#EOF4SH*)
            __PRINT=0
            ;;
        \#\#*)
            echo "$line" | cut -c 2-
            __PRINT=1
            ;;
        \#*)
            [ ${__PRINT} = 1 ] && echo "$line" | cut -c 3-
            ;;
        *)
            __PRINT=0
            ;;
        esac
    done <"$0"
    exit
fi
unset __sourced

#------------------------------------------------------------------------------
# End here unless we're on Bash or Zsh
if [ -n "${BASH_VERSION:-}" ] || [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
    debug "ishlib: loading bash/zsh extensions"
else
    debug "ishlib: load done, skipped bash/zsh extensions"
    return 0
fi

###EOF4SH

#------------------------------------------------------------------------------
### Bash/Zsh functions
#
# The following functions will be defined only when running bash or zsh.
#

strindex() {
    x="${1%%$2*}"
    [[ "$x" = "$1" ]] && echo -1 || echo "${#x}"
}

findOrInstall() {
    [[ -v "$1" ]] || fail "Unbound variable: $1"
    local var="$1"
    local func="${2:-}"
    local val="${!var}"

    if hasCommand "$val"; then
        debug "Trying to set which"
        printf -v "${var}" "%s" "$(which "$val")"
        return 0
    elif [[ -n $func ]]; then
        val=$("$func" || return 1)
        # shellcheck disable=2181
        if [[ $? -eq 0 ]]; then
            printf -v "${var}" "%s" "$("$func")"
            return 0
        fi
    fi
    return 1
}

dumpVariable() {
    if [[ -v "$1" ]]; then
        debug "$1=${!1}"
    else
        debug "$1 is undefined"
    fi
}

dumpVariables() {
    local vars=("$@")
    for var in "${vars[@]}"; do
        dumpVariable "${var}"
    done
}

unset -f ishlibVersion
ishlibVersion() {
    say "Using ishlib ${ish_Version} (with bash/zsh)"
}

debug "ishlib: load done"
