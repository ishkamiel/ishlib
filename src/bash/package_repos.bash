#!/usr/bin/env bash
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
#
[ -n "${ish_SOURCED_package_repos_bash:-}" ] && return 0
ish_SOURCED_package_repos_bash=1 # source guard

# shellcheck source=common.bash
. "$ISHLIB/src/bash/common.bash"
# shellcheck source=../sh/prints_and_prompts.sh
. "$ISHLIB/src/sh/prints_and_prompts.sh"

: <<'DOCSTRING'
`ish_apt_add_ppa ppa`

Add an Ubuntu PPA (idempotent). Skips if the PPA is already present.
Runs `add-apt-repository -y` and `apt-get update`.

Respects `DRY_RUN`.

Arguments:
  ppa - the PPA string, e.g. "ppa:agornostal/ulauncher"

Returns:
  0 - on success or if already present
  1 - if add-apt-repository fails
DOCSTRING
ish_apt_add_ppa() {
  local _ppa="$1"
  local _ppa_name="${_ppa#ppa:}"

  if grep -rqs "${_ppa_name}" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
    ish_say "PPA already present: ${_ppa}"
    return 0
  fi

  ish_say "Adding PPA: ${_ppa}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run sudo add-apt-repository -y "${_ppa}"
    ish_say_dry_run sudo apt-get update -q
    return 0
  fi

  if ! sudo add-apt-repository -y "${_ppa}"; then
    ish_warn "Failed to add PPA: ${_ppa}"
    return 1
  fi
  sudo apt-get update -q
}

: <<'DOCSTRING'
`ish_apt_add_key url [keyring_name]`

Download and install a GPG signing key (idempotent).
The key is dearmored and stored in `/etc/apt/keyrings/<keyring_name>.gpg`.
If `keyring_name` is omitted, a name is derived from the URL basename.

Respects `DRY_RUN`.

Arguments:
  url          - URL to fetch the armored GPG key from
  keyring_name - (optional) stem for the keyring file under /etc/apt/keyrings/

Returns:
  0 - on success or if the keyring file already exists
  1 - if the download or dearmor step fails
DOCSTRING
ish_apt_add_key() {
  local _url="$1"
  local _name="${2:-}"
  if [[ -z "${_name}" ]]; then
    _name="$(basename "${_url}" | sed 's/\.[^.]*$//')"
  fi
  local _dest="/etc/apt/keyrings/${_name}.gpg"

  if [[ -f "${_dest}" ]]; then
    ish_say "GPG key already present: ${_dest}"
    return 0
  fi

  ish_say "Adding GPG key to ${_dest}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run sudo mkdir -p /etc/apt/keyrings
    ish_say_dry_run "curl -sSL ${_url} | gpg --dearmor | sudo tee ${_dest}"
    ish_say_dry_run sudo chmod a+r "${_dest}"
    return 0
  fi

  sudo mkdir -p /etc/apt/keyrings
  if ! curl -sSL "${_url}" | gpg --dearmor | sudo tee "${_dest}" > /dev/null; then
    ish_warn "Failed to fetch/dearmor GPG key from ${_url}"
    return 1
  fi
  sudo chmod a+r "${_dest}"
}

: <<'DOCSTRING'
`ish_apt_add_repo name deb_line`

Write an apt source list entry (idempotent).
Creates `/etc/apt/sources.list.d/<name>.list` with `deb_line` as content.
Skips if the file already exists, then runs `apt-get update`.

Respects `DRY_RUN`.

Arguments:
  name     - stem for the .list file under /etc/apt/sources.list.d/
  deb_line - the full `deb [...]` line to write

Returns:
  0 - on success or if the file already exists
  1 - if writing the file fails
DOCSTRING
ish_apt_add_repo() {
  local _name="$1"
  local _deb_line="$2"
  local _list_file="/etc/apt/sources.list.d/${_name}.list"

  if [[ -f "${_list_file}" ]]; then
    ish_say "apt repo already present: ${_list_file}"
    return 0
  fi

  ish_say "Adding apt repo: ${_list_file}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run "echo '${_deb_line}' | sudo tee \"${_list_file}\""
    ish_say_dry_run sudo apt-get update -q
    return 0
  fi

  if ! echo "${_deb_line}" | sudo tee "${_list_file}" > /dev/null; then
    ish_warn "Failed to write apt repo file: ${_list_file}"
    return 1
  fi
  sudo apt-get update -q
}

: <<'DOCSTRING'
`ish_apt_update_once`

Run `apt-get update` at most once per session.
Uses a sentinel file in `$XDG_RUNTIME_DIR` (or `/tmp`) to coalesce multiple
calls from different scripts within the same ishfiles run.

Respects `DRY_RUN`.

Returns:
  0 - always
DOCSTRING
ish_apt_update_once() {
  local _sentinel="${XDG_RUNTIME_DIR:-/tmp}/ishfiles-apt-updated-$$"
  if [[ -f "${_sentinel}" ]]; then
    ish_say "apt-get update already done this session"
    return 0
  fi

  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run sudo apt-get update -q
    return 0
  fi

  sudo apt-get update -q
  touch "${_sentinel}"
}

: <<'DOCSTRING'
`ish_dnf_import_key url [key_name]`

Import a GPG key into rpm (idempotent).
`key_name` is a substring used to check whether the key is already imported
via `rpm -q gpg-pubkey`. If omitted, the check is skipped (key always imported).

Respects `DRY_RUN`.

Arguments:
  url      - URL of the GPG key to import via `rpm --import`
  key_name - (optional) substring to match in rpm gpg-pubkey summary output

Returns:
  0 - on success or if already imported
  1 - if rpm --import fails
DOCSTRING
ish_dnf_import_key() {
  local _url="$1"
  local _name="${2:-}"

  if [[ -n "${_name}" ]]; then
    if rpm -q gpg-pubkey --qf '%{summary}\n' 2>/dev/null | grep -qi "${_name}"; then
      ish_say "GPG key '${_name}' already imported"
      return 0
    fi
  fi

  ish_say "Importing GPG key from ${_url}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run sudo rpm --import "${_url}"
    return 0
  fi

  if ! sudo rpm --import "${_url}"; then
    ish_warn "Failed to import GPG key from ${_url}"
    return 1
  fi
}

: <<'DOCSTRING'
`ish_dnf_add_repo name content`

Write a dnf .repo file (idempotent).
Creates `/etc/yum.repos.d/<name>.repo` with `content` as the file body.
Skips if the file already exists.

Respects `DRY_RUN`.

Arguments:
  name    - stem for the .repo file under /etc/yum.repos.d/
  content - full content to write into the repo file

Returns:
  0 - on success or if the file already exists
  1 - if writing the file fails
DOCSTRING
ish_dnf_add_repo() {
  local _name="$1"
  local _content="$2"
  local _repo_file="/etc/yum.repos.d/${_name}.repo"

  if [[ -f "${_repo_file}" ]]; then
    ish_say "dnf repo already present: ${_repo_file}"
    return 0
  fi

  ish_say "Adding dnf repo: ${_repo_file}"
  if [[ "${DRY_RUN:-}" = 1 ]]; then
    ish_say_dry_run "printf '%s\\n' '...' | sudo tee ${_repo_file}"
    return 0
  fi

  if ! printf '%s\n' "${_content}" | sudo tee "${_repo_file}" > /dev/null; then
    ish_warn "Failed to write dnf repo file: ${_repo_file}"
    return 1
  fi
}
