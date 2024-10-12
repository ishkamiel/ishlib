#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_download_file_sh:-}" ] && return 0
ish_SOURCED_download_file_sh=1 # source guard

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"

: <<'DOCSTRING'
`download_file url dst`

Attempts to download file at $url to $dst, creating the containing directory
if needed. Will first try curl, then wget, and finally fail if neither is
available.

Arguments:
  url - the URL to download
  dst - the filename to save to
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
