#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_git_bash:-}" ] && return 0
ish_SOURCED_git_bash=1 # source guard

# shellcheck source=common.bash
. "$ISHLIB/src/bash/common.bash"

: <<'DOCSTRING'
`git_clone_or_update [-b branch] [--update-submodules] url dir`

Arguments:
  url                   - the git remote URL
  dir                   - The destianation directory
  --update_submodules   - Run submodule update after clone
  -b|--branch branch      - Specify branch to checkout / update
  -c|--commit           - Also checkokut specific commit
Globals:
  bin_git               - Path to git (default : git)
  DRY_RUN               - Respects dry-run flag
Returns:
  0 - on success
  1 - on failure
DOCSTRING
git_clone_or_update() {
  local t="ishlib:git_clone_or_update:"

  local bin_git=${bin_git:-git}
  has_command "${bin_git}" || (ish_warn "$t cannot find ${bin_git}" && return 1)

  local url=""
  local dir=""
  local branch=""
  local commit=""
  local update_submodules=0

  local bad_args=0
  local positional=()
  while [[ $# -gt 0 ]]; do
    arg="$1"

    case ${arg} in
    -b | --branch)
      branch="$2"
      shift 2
      ;;
    -c | --commit)
      commit="$2"
      shift 2
      ;;
    --update-submodules)
      update_submodules=1
      shift
      ;;
    *)
      if [[ -z "${url}" ]]; then
        url="$1"
        shift
      elif [[ -z "${dir}" ]]; then
        dir="$1"
        shift
      else
        ish_warn "$t unknown argument $1"
        bad_args=$((bad_args + 1))
        shift
      fi
      ;;
    esac
  done
  set -- "${positional[@]}" # restore positional parameters
  [[ $bad_args -eq 0 ]] || return 1

  if [[ ! -e "${dir}/.git" ]]; then
    local git_args=()
    [[ -n "$branch" ]] && git_args+=("-b" "$branch")
    git_args+=("$url" "$dir")

    ish_debug "$t cloning ${url} to ${dir}"
    do_or_dry mkdir -p "${dir}" || (ish_warn "$t failed to enter $dir" && return 1)
    do_or_dry "$bin_git" clone "${git_args[@]}" || (ish_warn "$t git clone failed" && return 1)

    if [[ "${update_submodules}" = "1" ]]; then
      ish_debug "$t initializing submodules"
      do_or_dry pushd "${dir}" || (ish_warn "$t failed to pusd ${dir}" && return 1)
      do_or_dry "$bin_git" submodule update --init --recursive || (ish_warn "$t submodule update failed" && return 1)
      do_or_dry popd || (ish_warn "$t filed to popd" && return 1)
    fi
  else
    ish_debug "$t updating ${dir}"

    do_or_dry pushd "${dir}" || (ish_warn "$t failed to pusd ${dir}" && return 1)

    if [[ -n "$branch" ]]; then
      do_or_dry "$bin_git" checkout "$branch" || (ish_warn "$t checkout $branch failed" && return 1)
    fi

    do_or_dry "$bin_git" pull || (ish_warn "$t failted to git pull ${dir}" && return 1)
    do_or_dry popd || (ish_warn "$t filed to popd" && return 1)
  fi

  if [[ -n "${commit}" ]]; then
    ish_debug "${t} checking out ${commit}"
    do_or_dry pushd "${dir}" || (ish_warn "$t failed to pusd ${dir}" && return 1)
    do_or_dry "$bin_git" checkout "${commit}" || (ish_warn "$t failed to checkout ${commit} in ${dir}" && return 1)
    do_or_dry popd || (ish_warn "$t filed to popd" && return 1)
  fi

  return 0
}
