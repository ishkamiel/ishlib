#! /usr/bin/env sh
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

set -e

export ISHLIB=$(pwd)
. src/sh/prints_and_prompts.sh

A() {
  B
}

B() {
  C
}

C() {
  ish_fail "failed in function"
}

do_a_warn() {
  ish_warn "warning"
}

case $1 in
# CHECK: DEBUG=1 | sh | test_fail | Hello World | 1
# CHECK: DEBUG=1 | bash | test_fail | Hello World | 1
# CHECK: DEBUG=1 | zsh | test_fail | Hello World | 1
test_fail)
  ish_fail "Hello World"
  ;;
# CHECK: DEBUG=1 | sh | test_fail_abc | failed in function | 1
# CHECK: DEBUG=1 | bash | test_fail_abc | failed in function | 1
# CHECK: DEBUG=1 | zsh | test_fail_abc | failed in function | 1
# CHECK: DEBUG=1 | bash | test_fail_abc | failed in function.*t_prints_and_prompts.sh, line| 1
test_fail_abc)
  A
  ;;
# CHECK: DEBUG=1 | sh | test_debug | Hello World | 0
# CHECK: DEBUG=1 | bash | test_debug | Hello World | 0
# CHECK: DEBUG=1 | zsh | test_debug | Hello World | 0
# CHECK: DEBUG=0 | sh | test_debug | | 0
# CHECK: DEBUG=0 | bash | test_debug | | 0
# CHECK: DEBUG=0 | zsh | test_debug | | 0
# CHECK: | sh | test_debug | | 0
# CHECK: | bash | test_debug | | 0
# CHECK: | zsh | test_debug | | 0
test_debug)
  ish_debug "Hello World"
  ;;
# CHECK: DEBUG=1 | sh | test_warn | warning| 0
# CHECK: DEBUG=1 | bash | test_warn | warning | 0
# CHECK: DEBUG=1 | zsh | test_warn | warning | 0
# CHECK: DEBUG=0 | sh | test_warn | warning | 0
# CHECK: DEBUG=0 | bash | test_warn | warning | 0
# CHECK: DEBUG=0 | zsh | test_warn | warning | 0
# CHECK: | sh | test_warn | warning | 0
# CHECK: | bash | test_warn | warning | 0
# CHECK: | zsh | test_warn | warning | 0
# CHECK: DEBUG=1 | bash | test_warn | warning.*t_prints_and_prompts.sh, line| 0
test_warn)
  do_a_warn
  ;;
*)
  ish_fail "Bad test case given!"
esac
