#! /usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2021 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_git_bash:-}" ] && return 0
ish_SOURCED_git_bash=1 # source guard
. common.sh
###############################################################################

#------------------------------------------------------------------------------
: <<'DOCSTRING'
git_clone_or_update url dir

Arguments:
  url - the git repository remote
  dir - the local directory for the repository
Globals:
  bin_git - if specified, will use the given command in place of git
Returns:
  0 - on success
  x - on failure, either 1 or return value of git
DOCSTRING
git_clone_or_update() {
  local t="ishlib:git_clone_or_update:"
  local url="$1"
  local dir="$2"
  local branch=""
  local update_submodules=0
  shift 2

  local bad_args=0
  local positional=()
  while [[ $# -gt 0 ]]; do
    arg="$1"

    case ${arg} in
    -b | --branch)
      branch="$2"
      shift 2
      ;;
    --update-submodules)
      update_submodules=1
      shift
      ;;
    *)
      warn "$t unknown argument $1"
      bad_args=$((bad_args + 1))
      shift
      ;;
    esac
  done
  set -- "${positional[@]}" # restore positional parameters
  [[ $bad_args -eq 0 ]] || return 1

  local bin_git=${bin_git:-git}

  has_command "${bin_git}" || (warn "$t cannot find ${bin_git}" && return 1)

  if [[ ! -e "${dir}/.git" ]]; then
    local git_args=()
    [[ -n "$branch" ]] && git_args+=("-b" "$branch")
    git_args+=("$url" "$dir")

    debug "$t cloning ${url} to ${dir}"
    do_or_dry mkdir -p "${dir}" || (warn "$t failed to enter $dir" && return 1)
    do_or_dry "$bin_git" clone "${git_args[@]}" || (warn "$t git clone failed" && return 1)

    if [[ "${update_submodules}" = "1" ]]; then
      debug "$t initializing submodules"
      do_or_dry pushd "${dir}" || (warn "$t failed to pusd ${dir}" && return 1)
      do_or_dry "$bin_git" submodule update --init --recursive || (warn "$t submodule update failed" && return 1)
      do_or_dry popd || (warn "$t filed to popd" && return 1)
    fi
  else
    debug "$t updating ${dir}"

    do_or_dry pushd "${dir}" || (warn "$t failed to pusd ${dir}" && return 1)

    if [[ -n "$branch" ]]; then
      do_or_dry "$bin_git" checkout "$branch" || (warn "$t checkout $branch failed" && return 1)
    fi

    do_or_dry "$bin_git" pull || (warn "ishlib:git_clone_or_update" && return 1)
    do_or_dry popd || (warn "$t filed to popd" && return 1)
  fi
  return 0
}
