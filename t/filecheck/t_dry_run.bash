#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

set -e

ISHLIB=$(pwd)
. src/bash/dry_run.bash

case $1 in
test_do_or_dry)
# CHECK: DRY_RUN=1 | bash | test_do_or_dry | dry run.*echo asdf | 0
# CHECK: DRY_RUN=0 | bash | test_do_or_dry | ^asdf$ | 0
# CHECK:           | bash | test_do_or_dry | ^asdf$ | 0
  do_or_dry echo asdf
  ;;
test_do_or_dry_bg)
# CHECK: DRY_RUN=1 | bash | test_do_or_dry_bg | dry run.*echo asdf | 0
# CHECK: DRY_RUN=0 | bash | test_do_or_dry_bg | ^asdf$ | 0
# CHECK:           | bash | test_do_or_dry_bg | ^asdf$ | 0
  proc_pid=''
  do_or_dry_bg proc_pid echo asdf
  [[ -n "$proc_pid" ]] && wait "$proc_pid"
  [[ -n "$proc_pid" ]] || is_dry # We don't get a pid when doing dry run
  ;;
test_do_or_dry_bg_dont_touch)
# Just to check I understand how declare -n works...
# CHECK: DRY_RUN=1 | bash | test_do_or_dry_bg_dont_touch | ^.*dry run.*echo asdf.*$ | 0
# CHECK: DRY_RUN=0 | bash | test_do_or_dry_bg_dont_touch | ^asdf$ | 0
# CHECK:           | bash | test_do_or_dry_bg_dont_touch | ^asdf$ | 0
  pid='DONT_TOUCH'
  proc_pid=''
  do_or_dry_bg proc_pid echo asdf
  [[ -n "$proc_pid" ]]  && wait "$proc_pid"
  [[ $pid = "DONT_TOUCH" ]] || echo "failed pid=$pid"
  ;;
*)
  fail "Bad test case given!"
esac
