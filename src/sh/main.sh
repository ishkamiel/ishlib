#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_main_sh:-}" ] && return 0
ish_SOURCED_main_sh=1 # source guard

# shellcheck source=common.sh
. "$ISHLIB/src/sh/common.sh"

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
    --html)
      _help_format=html
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
      if [ ${_help_format} = 'html' ]; then
        cat <<EOF
<!DOCTYPE html>
<html>
<head>
<title>${ish_VERSION_NAME}</title>
<script>
window.onload = function(e) {
  const code = document.querySelectorAll("code");
  [...code].forEach(el => el.textContent = el.textContent.replace(/^\n/,''));
}
</script>
<style>
#content {
  max-width: 70em;
  margin-left: auto;
  margin-right: auto;
}
code {
  font-family: monospace;
  white-space: pre;
}
code::first-line {
  font-size: 0px;
}
h4 code {
  font-family: monospace;
  font-size: 110%;
}
</style>
</head>
<body>
<div id="content">
EOF

        print_docstrings "$fn" --markdown --tag "${ish_DOCSTRING}" | markdown
        cat <<EOF
</div>
</body>
</html>
EOF
      else
        print_docstrings "$fn" ${_help_format} --tag "${ish_DOCSTRING}"
      fi

      exit 0
  fi

  warn "ishlib run directly without parameters!"
  say "To print docs:       ./ishlib.sh -h"
  exit 0
}
