#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Scenario: an ishscript with `run_when = "once"` runs on the first
# invocation and is skipped on the second.

set -eu
. "$ISHLIB_LIB"

it_sandbox_dirs

mkdir -p "$(it_source_path)/ishscripts"
sentinel="$ISHLIB_SANDBOX/sentinel"

# A shell script with __ISH__ TOML metadata declaring run_when = "once".
# Each successful run appends an "x" to the sentinel file so the scenario
# can count invocations.
cat > "$(it_source_path)/ishscripts/00_once.sh" <<EOF
#!/usr/bin/env bash
: <<'__ISH__'
run_when = "once"
__ISH__
printf 'x' >> "\$ISHLIB_SANDBOX/sentinel"
EOF

# First run -- script must execute, sentinel becomes "x".
it_run_ishfiles runscripts
it_assert_file_equals "$sentinel" "x"

# Second run -- run_when=once must skip the script, sentinel unchanged.
it_run_ishfiles runscripts
it_assert_file_equals "$sentinel" "x"

# --force <name> re-runs the named script even with run_when=once,
# so the sentinel becomes "xx".
it_run_ishfiles runscripts --force 00_once.sh
it_assert_file_equals "$sentinel" "xx"

it_log "ok"
