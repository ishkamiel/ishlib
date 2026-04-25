# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject init`` -- bootstrap the default ishproject worktree."""

from __future__ import annotations

import argparse
import copy
import logging
import subprocess
import sys
from pathlib import Path
from typing import List

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError
from ...ish_config import IshConfig
from ...ishlib_folder import PROJECT_DIR_NAME, IshlibFolder
from ...userio import prompt_string
from .._precommit import allow_missing_precommit_config
from ..config import IshprojectConfig
from .apply import ApplyCommand

log = logging.getLogger(__name__)


class _RemoteError(Exception):
    """Sentinel: remote resolution failed; caller returns 1."""


class _NotConfigured(Exception):
    """Sentinel: repo has no ishproject branch and ``--create`` was not given.

    Distinguished from a real failure so recursion can classify it as a
    skip rather than an error.  Carrying this via an exception (rather
    than an int sentinel) avoids collisions with arbitrary non-zero exit
    codes from the forwarded ``ishfiles apply`` call.
    """


def _repo_tag(root: Path) -> str:
    """Return a short ``[<path>]`` prefix for log messages about *root*."""
    try:
        return f"[{root.relative_to(Path.cwd())}]"
    except ValueError:
        return f"[{root}]"


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


def _resolve_remote(repo: GitRepo, args: argparse.Namespace, root: Path) -> str:
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
    tag = _repo_tag(root)
    if args.remote is not None:
        reply = args.remote
    else:
        if repo.remote_exists("origin"):
            return "origin"
        if not sys.stdin.isatty():
            log.error(
                "%s No `origin` remote configured and no --remote flag given. "
                "Pass --remote <name|url> to specify the remote.",
                tag,
            )
            raise _RemoteError()
        reply = prompt_string(
            "Remote for ishproject branch (existing remote name or URL)",
            default="",
            name="remote",
        )
        if not reply:
            log.error("%s No remote specified; aborting.", tag)
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
                "%s Remote `ishproject` is already set to %s; refusing to "
                "overwrite with %s.",
                tag,
                existing,
                reply,
            )
            raise _RemoteError()
        repo.add_remote("ishproject", reply)
        return "ishproject"

    log.error(
        "%s Remote %r is not configured in this repo and does not look like a URL.",
        tag,
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
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help=(
                "After initialising the worktree, run `ishproject apply` so "
                "any dotfiles already present on the branch are installed "
                "into the project. No-op when the worktree is empty."
            ),
        )
        parser.add_argument(
            "--recurse-submodules",
            action="store_true",
            default=False,
            help=(
                "After initialising the top-level repo, run `ishproject init` "
                "in every initialised submodule (recursively). Submodules use "
                "their own `origin`; --remote is not forwarded. --create, "
                "--apply, and --dry-run are forwarded."
            ),
        )

    def run(self) -> int:
        cfg: IshprojectConfig = self.cfg.ishproject_cfg
        branch = cfg.default_branch
        root = Path.cwd()
        recurse = bool(getattr(self.cfg, "recurse_submodules", False))

        skipped: List[str] = []
        failures: List[str] = []
        parent_not_configured = False
        rc = 0
        try:
            rc = self._init_one(self.cfg, cfg, branch, root)
        except _NotConfigured:
            parent_not_configured = True

        if not recurse:
            # Standalone callers asked about one specific repo. "Not
            # configured" is still a non-success outcome (so the shell
            # exit is non-zero), but the user already got an info-level
            # message from `_init_project_worktree` explaining exactly
            # what happened.
            if parent_not_configured:
                return 1
            return rc

        if parent_not_configured:
            skipped.append(str(root))
        elif rc != 0:
            failures.append(str(root))

        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            return 1 if failures else 0

        child_args = copy.copy(self.cfg)
        child_args.remote = None
        child_args.recurse_submodules = False

        for sub in repo.list_submodules(recursive=True):
            log.info("ishproject init in submodule %s", sub)
            try:
                sub_rc = self._init_one(child_args, cfg, branch, sub)
            except _NotConfigured:
                skipped.append(str(sub))
                continue
            if sub_rc != 0:
                failures.append(str(sub))

        if skipped:
            log.info(
                "ishproject not configured in %d repo(s) (no %s branch): %s",
                len(skipped),
                branch,
                ", ".join(skipped),
            )
        if failures:
            log.error(
                "ishproject init failed in %d repo(s): %s",
                len(failures),
                ", ".join(failures),
            )
            return 1
        return 0

    def _init_one(
        self,
        args: argparse.Namespace,
        cfg: IshprojectConfig,
        branch: str,
        root: Path,
    ) -> int:
        """Init + optional apply for a single repo root."""
        rc = self._init_project_worktree(args, cfg, branch, root)
        if rc != 0:
            return rc
        if args.apply:
            return self._apply_project_dotfiles(args, cfg, branch, root)
        return 0

    def _init_project_worktree(
        self,
        args: argparse.Namespace,
        cfg: IshprojectConfig,
        branch: str,
        root: Path,
    ) -> int:
        """Ensure the ishproject worktree exists at ``.ishlib/ishproject``.

        Idempotent: a no-op when the worktree is already present. Otherwise
        wires up the branch via one of three paths (local branch, remote
        tracking, or ``--create`` orphan) and appends ``/.ishlib/`` to the
        project repo's exclude. Returns 0 on success, 1 on failure.
        """
        runner = CommandRunner(cfg=IshConfig(dry_run=args.dry_run))

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
            remote_name = _resolve_remote(repo, args, root)
        except _RemoteError:
            return 1

        try:
            repo.fetch(remote_name)
        except subprocess.CalledProcessError:
            log.error(
                "%s Failed to fetch from %s; aborting.",
                _repo_tag(root),
                remote_name,
            )
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
            log.info(
                "%s ishproject not configured (no %s branch on %s); "
                "pass --create to bootstrap.",
                _repo_tag(root),
                branch,
                remote_name,
            )
            raise _NotConfigured()

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
                "%s Orphan branch %s created locally but push to %s failed. "
                "Fix the remote and run: git -C %s push -u %s %s",
                _repo_tag(root),
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

    def _apply_project_dotfiles(
        self,
        args: argparse.Namespace,
        cfg: IshprojectConfig,
        branch: str,
        root: Path,
    ) -> int:
        """Forward to ``ishfiles apply`` on the freshly-initialised worktree.

        Called only when ``--apply`` was set and the init step succeeded.
        The nested ``ApplyCommand`` inherits *init*'s parsed args as its
        ``self.cfg``, so ``forward_explicit_globals`` reconstructs
        ``-n/-v/-q/--debug/--log-file`` from init's ``_ish_explicit`` set
        and the nested ``setup_logging()`` keeps the same verbosity and
        file sink.  Skipped with a log message when the worktree does
        not exist (e.g. ``--dry-run`` did not materialise it).
        """
        source, _target = cfg.resolve_project_paths(root, branch=branch)
        if not source.is_dir():
            log.info("Skipping --apply: worktree not created (dry-run)")
            return 0
        apply_cmd = ApplyCommand()
        apply_cmd.cfg = args
        return apply_cmd.run_project_apply(cfg, rest=(), root=root, branch=branch)
