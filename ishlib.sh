#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

# Include guard...
[ -n "${ish_SOURCED:-}" ] && return 0
ish_SOURCED=1

ish_ColorRed='\033[0;31m'
ish_ColorBlue='\033[0;34m'
ish_ColorNC='\033[0m'
ish_ColorDebug="${ish_ColorNC}"
ish_ColorSay="${ish_ColorBlue}"
ish_ColorWarn="${ish_ColorBlue}"
ish_ColorFail="${ish_ColorRed}"

ish_DieOnFail=${ish_DieOnFail:-1}

# POSIX compliant stuff

debug() {
    [ -z "${DEBUG:-}" ] || [ "${DEBUG:-}" -ne 1 ] && return 0
    if [ -n "${BASH_VERSION:-}" ] || [ -n "${ZSH_VERSION:-}" ]; then
        # shellcheck disable=SC2039
        echo -e "[DD] ${ish_ColorDebug}$1${ish_ColorNC}" >&2
        return 0
    fi
    # echo >&2 "[DD] $1"
    printf >&2 "[DD] %b%b%b\n" "${ish_ColorDebug}" "$@" "${ish_ColorNC}"
    # printf >&2 "\b"
    return 0
}

say() {
    # if [ -n "${BASH_VERSION:-}" ] || [ -n "${ZSH_VERSION:-}" ]; then
    #     # shellcheck disable=SC2039
    #     echo -e >&2 "[--] ${ish_ColorSay}$1${ish_ColorNC}"
    #     return 0
    # fi
    printf >&2 "[--] %b%b%b\n" "${ish_ColorSay}" "$@" "${ish_ColorNC}"
    # echo "[--] $1"
    return 0
}

warn() {
    if [ -n "${BASH_VERSION:-}" ] || [ -n "${ZSH_VERSION:-}" ]; then
        # shellcheck disable=SC2039
        echo -e "[WW] ${ish_ColorWarn}$1${ish_ColorNC}" >&2
        return 0
    fi
    echo "[WW] $1"
    return 0
}

fail() {
    if [ -n "${BASH_VERSION:-}" ] || [ -n "${ZSH_VERSION:-}" ]; then
        # shellcheck disable=SC2039
        echo -e "[!!] ${ish_ColorFail}${1}${ish_ColorNC}" >&2
    else
        echo >&2 "[!!] $1"
    fi
    [ -n "${ish_DieOnFail}" ] && ([ -n "${2}" ] && exit "${2}") || exit 1
    return 1
}

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

hasCommand() {
    [ -z "$1" ] && warn "hasCommand: bad 1st arg" && return 1
    if command -v "$1" >/dev/null 2>&1; then return 0; fi
    return 1
}

# Non POSIX-compliant stuff

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

debug "ishlib loaded"
