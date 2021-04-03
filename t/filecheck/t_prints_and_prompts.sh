#! /usr/bin/env sh

set -e

# shellcheck source=../../src/prints_and_prompts.sh
. src/prints_and_prompts.sh

A() {
  B
}

B() {
  C
}

C() {
  fail "failed in function"
}

do_a_warn() {
  warn "varning"
}

case $1 in
# CHECK: DEBUG=1 | sh | test_fail | Hello World | 1
# CHECK: DEBUG=1 | bash | test_fail | Hello World | 1
# CHECK: DEBUG=1 | zsh | test_fail | Hello World | 1
test_fail)
  fail "Hello World"
  ;;
# CHECK: DEBUG=1 | sh | test_fail_abc | failed in function | 1
# CHECK: DEBUG=1 | bash | test_fail_abc | failed in function | 1
# CHECK: DEBUG=1 | zsh | test_fail_abc | failed in function | 1
# CHECK: DEBUG=1 | bash | test_fail_abc | failed in function.*t_prints_and_prompts.sh, line 17| 1
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
  debug "Hello World"
  ;;
# CHECK: DEBUG=1 | sh | test_warn | varning| 0
# CHECK: DEBUG=1 | bash | test_warn | varning | 0
# CHECK: DEBUG=1 | zsh | test_warn | varning | 0
# CHECK: DEBUG=0 | sh | test_warn | varning | 0
# CHECK: DEBUG=0 | bash | test_warn | varning | 0
# CHECK: DEBUG=0 | zsh | test_warn | varning | 0
# CHECK: | sh | test_warn | varning | 0
# CHECK: | bash | test_warn | varning | 0
# CHECK: | zsh | test_warn | varning | 0
# CHECK: DEBUG=1 | bash | test_warn | varning.*t_prints_and_prompts.sh, line 21| 0
test_warn)
  do_a_warn
  ;;
*)
  fail "Bad test case given!"
esac
