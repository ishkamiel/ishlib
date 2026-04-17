# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Shared launcher helper for ishlib Python CLIs (ishfiles, isholate, ...).
# Sourced by the thin wrappers in bin/. See CLAUDE.md §Entry scripts.
# shellcheck shell=bash

_ishlib_pick_python() {
    local repo_root="$1" c pyenv_root pyenv_ver

    # ISHLIB_PYTHON
    if [ -n "${ISHLIB_PYTHON:-}" ] && [ -x "$ISHLIB_PYTHON" ]; then
        printf '%s\n' "$ISHLIB_PYTHON"; return 0
    fi

    # pyenv default
    if command -v pyenv >/dev/null 2>&1; then
        pyenv_root=$(pyenv root 2>/dev/null || true)
        pyenv_ver=$(pyenv global 2>/dev/null | head -n1 || true)
        if [ -n "$pyenv_root" ] && [ -n "$pyenv_ver" ] && [ "$pyenv_ver" != "system" ]; then
            c="$pyenv_root/versions/$pyenv_ver/bin/python3"
            if [ -x "$c" ]; then printf '%s\n' "$c"; return 0; fi
        fi
    fi

    # # project pyenv
    # c="$repo_root/.venv/bin/python3"
    # if [ -x "$c" ]; then printf '%s\n' "$c"; return 0; fi

    # system python
    if [ -x /usr/bin/python3 ]; then printf '%s\n' /usr/bin/python3; return 0; fi
    c=$(command -v python3 2>/dev/null || true)
    if [ -n "$c" ] && [ -x "$c" ]; then printf '%s\n' "$c"; return 0; fi
    return 1
}

# Usage: ishlib_launch <tool-name> <python-module> <bin-dir> [args...]
ishlib_launch() {
    local tool="$1" module="$2" bin_dir="$3"
    shift 3
    local repo_root py
    repo_root=$(cd -P "$bin_dir/.." && pwd)

    unset PYTHONHOME
    unset VIRTUAL_ENV
    export PYTHONNOUSERSITE=1

    if ! py=$(_ishlib_pick_python "$repo_root"); then
        printf '%s: could not find a usable python3 interpreter\n' "$tool" >&2
        exit 127
    fi

    if [ -n "${PYTHONPATH:-}" ]; then
        export PYTHONPATH="$repo_root/src:$PYTHONPATH"
    else
        export PYTHONPATH="$repo_root/src"
    fi

    exec "$py" -m "$module" "$@"
}
