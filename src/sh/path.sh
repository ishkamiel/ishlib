#! /usr/bin/env sh
# SPDX-License-Identifier: MIT
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
[ -n "${ish_SOURCED_src_sh_path_sh:-}" ] && return 0
ish_SOURCED_src_sh_path_sh=1 # source guard

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"

: <<'DOCSTRING'
`ish_prepend_to_path`

Add path to beginning of  $PATH unless it already exists.

DOCSTRING
ish_prepend_to_path() {
  case ":$PATH:" in
    *":$1:"*) ;;
    *) PATH="$1${PATH:+:$PATH}" ;;
  esac
}
