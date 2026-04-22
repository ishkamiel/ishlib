# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject init`` -- bootstrap the default ishproject worktree."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ishlib_folder import PROJECT_DIR_NAME, IshlibFolder
from ...userio import prompt_string
from .._precommit import allow_missing_precommit_config
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


class _RemoteError(Exception):
    """Sentinel: remote resolution failed; caller returns 1."""


def _looks_like_url(s: str) -> bool:
    if Path(s).is_absolute():  # absolute path (POSIX or Windows)
        return True
    if s.startswith("./") or s.startswith("../"):  # relative filesystem path
        return True
    if "://" in s:
        return True
    # git@host:path — require a colon after the @
    if s.startswith("git@") and ":" in s[4:]:
        return True
    return False


def _resolve_remote(repo: GitRepo, args: argparse.Namespace) -> str:
    """Determine which remote to use for the ishproject branch.

    Resolution order:
    1. ``--remote <name|url>`` flag.
    2. If ``origin`` exists in the repo, return ``"origin"`` immediately.
    3. Prompt the user (interactive) or error (non-interactive).

    A URL answer causes an ``ishproject`` remote to be added to the repo.
    Returns the resolved remote name.

    Raises:
        _RemoteError: when resolution cannot proceed (caller returns 1).
    """
    if args.remote is not None:
        reply = args.remote
    else:
        if repo.remote_exists("origin"):
            return "origin"
        if not sys.stdin.isatty():
            log.error(
                "No `origin` remote configured and no --remote flag given. "
                "Pass --remote <name|url> to specify the remote."
            )
            raise _RemoteError()
        reply = prompt_string(
            "Remote for ishproject branch (existing remote name or URL)",
            default="",
            name="remote",
        )
        if not reply:
            log.error("No remote specified; aborting.")
            raise _RemoteError()

    # Name of an already-configured remote?
    if reply in repo.list_remotes():
        return reply

    # URL → add as an `ishproject` remote.
    if _looks_like_url(reply):
        if repo.remote_exists("ishproject"):
            existing = repo.remote_url("ishproject")
            if existing == reply:
                return "ishproject"  # idempotent re-run
            log.error(
                "Remote `ishproject` is already set to %s; refusing to "
                "overwrite with %s.",
                existing,
                reply,
            )
            raise _RemoteError()
        repo.add_remote("ishproject", reply)
        return "ishproject"

    log.error(
        "Remote %r is not configured in this repo and does not look like a URL.",
        reply,
    )
    raise _RemoteError()


class InitCommand(CliCommand):
    """Initialise the default ishproject worktree."""

    NAME = "init"
    HELP = "Initialise the default ishproject worktree under .ishlib/"
    DESCRIPTION = (
        "If cwd is a git-repo root, sets up the default ishproject branch "
        "(<prefix>/<postfix>, from ~/.config/ishlib/ishproject.toml) as a "
        "worktree at .ishlib/ishproject. When the branch is remote-only a "
        "local tracking branch is created automatically. With --create an "
        "empty orphan branch is bootstrapped and pushed to the resolved "
        "remote. Always appends .ishlib/ to .git/info/exclude."
    )

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--create",
            action="store_true",
            default=False,
            help=(
                "When the branch does not exist locally or on the resolved "
                "remote, create an empty orphan branch, check it out as the "
                "worktree, and push it to the remote."
            ),
        )
        parser.add_argument(
            "--remote",
            metavar="NAME_OR_URL",
            default=None,
            help=(
                "Remote for the ishproject branch. Accepts an existing remote "
                "name or a URL (a new `ishproject` remote is added for URLs). "
                "Defaults to `origin` when unspecified. Required in "
                "non-interactive sessions when no `origin` remote is configured."
            ),
        )

    def run(self, args: argparse.Namespace) -> int:
        cfg: IshprojectConfig = args.ishproject_cfg
        branch = cfg.default_branch

        runner = CommandRunner(cfg=IshConfig(dry_run=args.dry_run))
        root = Path.cwd()

        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            log.error(
                "ishproject init must be run from a git repository root: %s",
                root,
            )
            return 1
        repo.runner = runner

        folder = IshlibFolder(root)
        source = cfg.worktree_path(folder, branch)

        if source.is_dir():
            log.info("Project dotfiles already present at %s", source)
            repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
            return 0

        # Local branch already exists — wire it up directly; no remote needed.
        if repo.branch_exists(branch, local_only=True):
            if not runner.dry_run:
                folder.path.mkdir(parents=True, exist_ok=True)
            try:
                repo.add_worktree(source, branch=branch)
            except subprocess.CalledProcessError:
                return 1
            log.info("Created worktree: %s -> branch %s", source, branch)
            repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
            return 0

        # From here a remote is needed: fetch to refresh refs, then decide.
        try:
            remote_name = _resolve_remote(repo, args)
        except _RemoteError:
            return 1

        try:
            repo.fetch(remote_name)
        except subprocess.CalledProcessError:
            log.error("Failed to fetch from %s; aborting.", remote_name)
            return 1

        carriers = repo.remotes_with_branch(branch)
        if carriers:
            # Branch exists on at least one remote — create a local tracking branch.
            tracked_from = remote_name if remote_name in carriers else carriers[0]
            if tracked_from != remote_name:
                log.info(
                    "Branch %s not on %s; tracking from %s instead.",
                    branch,
                    remote_name,
                    tracked_from,
                )
            try:
                repo.create_tracking_branch(branch, tracked_from)
                if not runner.dry_run:
                    folder.path.mkdir(parents=True, exist_ok=True)
                repo.add_worktree(source, branch=branch)
            except subprocess.CalledProcessError:
                return 1
            log.info(
                "Tracking %s from %s; worktree at %s",
                branch,
                tracked_from,
                source,
            )
            repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
            return 0

        if not args.create:
            log.error(
                "Branch %s not found locally or on remote %s after fetch. "
                "Pass --create to bootstrap an empty orphan branch.",
                branch,
                remote_name,
            )
            return 1

        # Orphan path: create locally then push to validate the remote.
        if not runner.dry_run:
            folder.path.mkdir(parents=True, exist_ok=True)
        try:
            with allow_missing_precommit_config():
                repo.create_orphan_worktree(
                    source,
                    branch,
                    message="Initialise ishproject branch",
                )
        except subprocess.CalledProcessError:
            return 1
        try:
            repo.runner.git(
                ["push", "-u", remote_name, branch],
                work_dir=source,
            )
        except subprocess.CalledProcessError:
            log.error(
                "Orphan branch %s created locally but push to %s failed. "
                "Fix the remote and run: git -C %s push -u %s %s",
                branch,
                remote_name,
                source,
                remote_name,
                branch,
            )
            return 1
        log.info(
            "Created orphan branch %s, pushed to %s, worktree at %s",
            branch,
            remote_name,
            source,
        )
        repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
        return 0
