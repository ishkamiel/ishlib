#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Regression guard for the integration harness: prove that the host
# filesystem is read-only inside the bubblewrap namespace and that
# only the per-scenario sandbox is writable.  If this scenario passes
# but actual host paths got modified, the sandbox is broken.

set -eu
. "$ISHLIB_LIB"
it_sandbox_dirs

# /etc must be read-only.
if touch /etc/_isolation_probe 2>/dev/null; then
    it_die "host /etc was writable inside the sandbox; isolation is broken"
fi

# A stray hardcoded $HOME write must not corrupt the real home: bwrap
# sets HOME inside the sandbox, and even an absolute /home/<user>/...
# write hits the read-only host root.
if touch "$HOME/_isolation_probe" 2>/dev/null; then
    # The write succeeded -- confirm it landed inside the sandbox.
    case "$HOME" in
        "$ISHLIB_SANDBOX"/*) : ;;
        *) it_die "HOME=$HOME is outside the sandbox" ;;
    esac
fi

# The sandbox itself must be writable -- the harness is useless otherwise.
touch "$ISHLIB_SANDBOX/writable" || it_die "sandbox dir is not writable"

it_log "ok"
