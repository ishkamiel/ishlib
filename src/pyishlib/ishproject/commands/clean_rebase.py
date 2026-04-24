# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""``ishproject clean-rebase`` -- strip managed files from recent history."""

from __future__ import annotations

import argparse
import logging
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from ...cli_command import CliCommand
from ...command_runner import CommandRunner
from ...git_repo import GitRepo, NotAGitRepoError, _clean_git_env
from ...ish_config import IshConfig
from ...ishfiles.cli import build_parser as ishfiles_build_parser
from ...ishfiles.cli import main as ishfiles_main
from ...ishlib_folder import PROJECT_DIR_NAME
from .._precommit import allow_missing_precommit_config
from ..config import IshprojectConfig

log = logging.getLogger(__name__)


class CleanRebaseCommand(CliCommand):
    """Rewrite ``<base>..HEAD`` to strip ishproject-managed paths."""

    NAME = "clean-rebase"
    HELP = "Strip ishproject-managed files from recent commits"
    DESCRIPTION = (
        "Rewrites history from `<base>..HEAD` on the current branch, "
        "removing every file tracked on `ish/ishproject` from every "
        "commit in the range. Before rewriting, any edits to managed "
        "files that landed in that range are preserved by committing "
        "them onto `ish/ishproject` (pull --rebase, non-force push). "
        "After the rewrite the files are restored to the working tree "
        "via `ishfiles apply` and re-added to `.git/info/exclude`. The "
        "previous HEAD is saved to refs/ishproject/clean-rebase-backup-"
        "<timestamp> before the rewrite. Push with --force-with-lease."
    )

    @staticmethod
    def TARGET_MAIN(argv):
        return ishfiles_main(argv)

    @staticmethod
    def TARGET_BUILD_PARSER():
        return ishfiles_build_parser()

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "base",
            help="Commit-ish marking the last commit to KEEP unchanged.",
        )
        parser.add_argument(
            "--no-sync-ishproject",
            action="store_true",
            default=False,
            help=(
                "Skip preserving managed-file edits onto the "
                "ish/ishproject branch (edits in the range are lost)."
            ),
        )

    def run(self) -> int:
        cfg: IshprojectConfig = self.cfg.ishproject_cfg
        runner = CommandRunner(cfg=IshConfig(dry_run=self.cfg.dry_run))
        root = Path.cwd()

        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            log.error(
                "ishproject clean-rebase must be run from a git repository root: %s",
                root,
            )
            return 1
        repo.runner = runner

        branch = cfg.resolve_active_branch(root)
        source, target = cfg.resolve_project_paths(root, branch=branch)
        if not source.is_dir():
            log.error(
                "Project dotfiles directory does not exist: %s "
                "(run `ishproject init` first)",
                source,
            )
            return 1

        try:
            source_repo = GitRepo.discover(source)
            managed = source_repo.list_tracked_files()
        except (NotAGitRepoError, subprocess.CalledProcessError):
            log.error("Failed to list files on %s", source)
            return 1
        if not managed:
            log.warning("No files tracked on ish/ishproject; nothing to do.")
            return 0

        # ---- Phase 1: safety + setup -----------------------------------
        base_sha = _resolve_commit(target, self.cfg.base)
        if base_sha is None:
            log.error("Base %r is not a valid commit-ish", self.cfg.base)
            return 1

        if not _is_ancestor(target, base_sha, "HEAD"):
            log.error("Base %s is not an ancestor of HEAD", self.cfg.base)
            return 1

        if _worktree_has_uncommitted_changes(target):
            log.error(
                "Working tree has uncommitted changes; commit or stash "
                "them before rewriting history (reset --hard would "
                "discard them)."
            )
            return 1

        merges = _list_merges(target, base_sha)
        if merges:
            log.error(
                "Range %s..HEAD contains %d merge commit(s); linearise "
                "first or rewrite them manually.",
                self.cfg.base,
                len(merges),
            )
            return 1

        head_sha = _resolve_commit(target, "HEAD")
        if head_sha is None:
            log.error("Could not resolve HEAD")
            return 1

        backup_ref = f"refs/ishproject/clean-rebase-backup-{int(time.time())}"
        try:
            runner.git(
                ["update-ref", backup_ref, head_sha],
                work_dir=target,
            )
        except subprocess.CalledProcessError:
            log.error("Failed to create backup ref %s", backup_ref)
            return 1
        log.info("Saved backup ref: %s -> %s", backup_ref, head_sha[:12])

        # ---- Phase 2: preserve edits on ish/ishproject -----------------
        if not self.cfg.no_sync_ishproject:
            rc = _sync_edits_to_ishproject(
                target=target, source=source, managed=managed, runner=runner
            )
            if rc != 0:
                return rc

        # ---- Phase 3: rewrite main history -----------------------------
        commits = _rev_list_reverse(target, base_sha, "HEAD")
        log.info("Rewriting %d commit(s) from %s..HEAD", len(commits), self.cfg.base)

        try:
            runner.git(
                ["reset", "--hard", base_sha],
                work_dir=target,
            )
        except subprocess.CalledProcessError:
            log.error("Failed to reset to %s; backup ref: %s", base_sha, backup_ref)
            return 1

        managed_set = set(managed)
        new_head = base_sha
        for sha in commits:
            try:
                new_head = _rewrite_commit(
                    target=target,
                    sha=sha,
                    parent=new_head,
                    managed=managed_set,
                    runner=runner,
                )
            except subprocess.CalledProcessError as exc:
                log.error(
                    "Failed to rewrite commit %s: %s; backup ref: %s",
                    sha[:12],
                    exc,
                    backup_ref,
                )
                return 1

        if new_head != base_sha:
            try:
                runner.git(
                    ["reset", "--hard", new_head],
                    work_dir=target,
                )
            except subprocess.CalledProcessError:
                log.error(
                    "Failed to move branch to %s; backup ref: %s",
                    new_head[:12],
                    backup_ref,
                )
                return 1

        # Restore managed files to the working tree. Common flags on
        # this command (``--dry-run``, ``-v``, ``-q``, ``--debug``,
        # ``--log-file``) are forwarded by :meth:`passthrough` via
        # ``forward_explicit_globals``, so dry-run stays side-effect
        # free and logging verbosity matches.
        apply_rc = self.passthrough(
            "apply",
            (),
            global_args=["--source", str(source), "--target", str(target)],
        )
        if apply_rc != 0:
            log.warning(
                "`ishfiles apply` returned %d; managed files may not have "
                "been restored. Backup ref: %s",
                apply_rc,
                backup_ref,
            )

        # Re-add the worktree and per-file exclude entries.
        repo.ensure_exclude_pattern(f"/{PROJECT_DIR_NAME}/")
        for rel in managed:
            try:
                repo.ensure_path_excluded(target / rel)
            except ValueError as exc:
                log.warning("Could not re-exclude %s: %s", rel, exc)

        log.info(
            "Rewrite complete. Backup ref: %s. Push with "
            "`git push --force-with-lease`.",
            backup_ref,
        )
        return 0


# ---------------------------------------------------------------------------
# Helpers (module-level, no CLI state)
# ---------------------------------------------------------------------------


def _git(target: Path, args: List[str], **kwargs) -> subprocess.CompletedProcess:
    """Run ``git -C <target> <args>`` via subprocess.run with clean env."""
    return subprocess.run(
        ["git", "-C", str(target), *args],
        env=_clean_git_env(),
        **kwargs,
    )


def _resolve_commit(target: Path, commitish: str) -> Optional[str]:
    result = _git(
        target,
        ["rev-parse", "--verify", f"{commitish}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _is_ancestor(target: Path, ancestor: str, descendant: str) -> bool:
    result = _git(
        target,
        ["merge-base", "--is-ancestor", ancestor, descendant],
        check=False,
    )
    return result.returncode == 0


def _list_merges(target: Path, base_sha: str) -> List[str]:
    result = _git(
        target,
        ["rev-list", "--merges", f"{base_sha}..HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


def _worktree_has_uncommitted_changes(target: Path) -> bool:
    """True if anything outside the ``.ishlib/`` worktree is dirty.

    Managed files are NOT excepted: phase 3 does ``git reset --hard``,
    which would silently discard any uncommitted edits to them. The
    caller must commit (or run ``ishproject merge``) before rewriting.
    Entries inside ``.ishlib/`` are skipped because that subtree is the
    ishproject worktree itself and lives on a different branch.
    """
    result = _git(
        target,
        ["status", "--porcelain=v1", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    # --porcelain=v1 -z format:
    #   XY<space>PATH\0                       (most entries)
    #   XY<space>NEWPATH\0ORIGPATH\0          (rename / copy, X in {R, C})
    entries = [e for e in result.stdout.split("\x00") if e]
    i = 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) < 3:
            i += 1
            continue
        xy = entry[:2]
        paths = [entry[3:]]
        i += 1
        if xy.startswith("R") or xy.startswith("C"):
            if i < len(entries):
                paths.append(entries[i])
                i += 1
        for path in paths:
            if path.startswith(f"{PROJECT_DIR_NAME}/"):
                continue
            return True
    return False


def _rev_list_reverse(target: Path, base_sha: str, head: str) -> List[str]:
    result = _git(
        target,
        ["rev-list", "--reverse", f"{base_sha}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]


def _tree_files(target: Path, sha: str) -> List[str]:
    result = _git(
        target,
        ["ls-tree", "-r", "--name-only", "-z", sha],
        check=True,
        capture_output=True,
        text=True,
    )
    return [p for p in result.stdout.split("\x00") if p]


def _commit_metadata(target: Path, sha: str) -> Tuple[dict, str]:
    """Return (env-with-author-committer, message) for *sha*."""
    sep = "\x1f"
    result = _git(
        target,
        ["log", "-1", f"--pretty=%an{sep}%ae{sep}%aI{sep}%cn{sep}%ce{sep}%cI", sha],
        check=True,
        capture_output=True,
        text=True,
    )
    line = result.stdout.rstrip("\n")
    parts = line.split(sep)
    if len(parts) != 6:
        raise RuntimeError(f"unexpected pretty output for {sha}: {line!r}")
    an, ae, ad, cn, ce, cd = parts
    msg = _git(
        target,
        ["log", "-1", "--pretty=%B", sha],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    env = _clean_git_env()
    env.update(
        {
            "GIT_AUTHOR_NAME": an,
            "GIT_AUTHOR_EMAIL": ae,
            "GIT_AUTHOR_DATE": ad,
            "GIT_COMMITTER_NAME": cn,
            "GIT_COMMITTER_EMAIL": ce,
            "GIT_COMMITTER_DATE": cd,
        }
    )
    return env, msg


def _rewrite_commit(
    target: Path,
    sha: str,
    parent: str,
    managed: set,
    runner: CommandRunner,
) -> str:
    """Rewrite *sha* atop *parent* with managed files stripped.

    Uses ``read-tree`` + ``update-index --force-remove`` + ``write-tree``
    + ``commit-tree`` so there are no cherry-pick conflicts. Returns the
    new commit SHA.
    """
    if runner.dry_run:
        log.info("dry-run: would rewrite %s on top of %s", sha[:12], parent[:12])
        return parent

    # Load the tree of <sha> into the index.
    _git(target, ["read-tree", sha], check=True)

    tree_files = set(_tree_files(target, sha))
    to_remove = sorted(managed & tree_files)
    if to_remove:
        # update-index --force-remove works on multiple files in one call.
        _git(
            target,
            ["update-index", "--force-remove", "--", *to_remove],
            check=True,
        )

    new_tree = _git(
        target,
        ["write-tree"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    env, msg = _commit_metadata(target, sha)
    result = subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "-c",
            "commit.gpgsign=false",
            "-c",
            "tag.gpgsign=false",
            "commit-tree",
            new_tree,
            "-p",
            parent,
            "-F",
            "-",
        ],
        input=msg,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def _sync_edits_to_ishproject(
    *,
    target: Path,
    source: Path,
    managed: List[str],
    runner: CommandRunner,
) -> int:
    """Phase 2: commit main-HEAD edits onto ish/ishproject; pull+push.

    Returns 0 on success or when nothing needs syncing, 1 on failure
    (with the source branch rolled back to its pre-phase-2 state).
    """
    # Determine which managed files differ between main HEAD and the
    # ish/ishproject worktree.
    differing: List[str] = []
    for rel in managed:
        head_bytes = _show_head_bytes(target, rel)
        src_file = source / rel
        src_bytes = src_file.read_bytes() if src_file.is_file() else None
        if head_bytes == src_bytes:
            continue
        differing.append(rel)

    if not differing:
        log.info("No managed-file edits to sync onto ish/ishproject.")
        return 0

    if runner.dry_run:
        log.info(
            "dry-run: would sync %d file(s) onto ish/ishproject: %s",
            len(differing),
            ", ".join(differing),
        )
        return 0

    # Save source HEAD so we can roll back on any failure.
    saved = _resolve_commit(source, "HEAD")
    if saved is None:
        log.error("ish/ishproject worktree has no HEAD to snapshot")
        return 1

    try:
        # Copy HEAD-version of each differing file into <source>.
        for rel in differing:
            head_bytes = _show_head_bytes(target, rel)
            dest = source / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if head_bytes is None:
                # File was deleted on main; remove from source too.
                if dest.is_file():
                    dest.unlink()
            else:
                dest.write_bytes(head_bytes)

        # Use --force so managed paths are staged even though local
        # exclude rules (from the shared .git/info/exclude) would
        # otherwise cause git add to skip them here.
        runner.git(["add", "--force", "--", *differing], work_dir=source)

        diff_cached = _git(
            source,
            ["diff", "--cached", "--quiet"],
            check=False,
        )
        if diff_cached.returncode == 0:
            log.info("ish/ishproject already matches main HEAD; no sync needed.")
            return 0

        head_sha = _resolve_commit(target, "HEAD")
        short = (head_sha or "")[:12]
        with allow_missing_precommit_config():
            runner.git(
                [
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    "tag.gpgsign=false",
                    "commit",
                    "-m",
                    f"ishproject: sync edits from {short}",
                ],
                work_dir=source,
            )
        log.info("Committed %d file(s) onto ish/ishproject", len(differing))
    except subprocess.CalledProcessError as exc:
        log.error("Failed to prepare sync commit on ish/ishproject: %s", exc)
        _rollback_source(source, saved)
        return 1

    upstream = _resolve_upstream(source)
    if upstream is None:
        log.warning(
            "ish/ishproject has no upstream; sync commit is local-only. "
            "Push it manually when you have one configured."
        )
        return 0

    try:
        runner.git(["pull", "--rebase"], work_dir=source)
    except subprocess.CalledProcessError:
        log.error(
            "ish/ishproject rebase over %s failed; rolling back sync commit.",
            upstream,
        )
        _git(source, ["rebase", "--abort"], check=False)
        _rollback_source(source, saved)
        return 1

    try:
        runner.git(["push"], work_dir=source)
    except subprocess.CalledProcessError:
        log.error(
            "Push to %s was rejected; rolling back sync commit.",
            upstream,
        )
        _rollback_source(source, saved)
        return 1

    return 0


def _show_head_bytes(target: Path, rel: str) -> Optional[bytes]:
    """Return the bytes of HEAD:<rel>, or None if not tracked in HEAD."""
    result = subprocess.run(
        ["git", "-C", str(target), "cat-file", "-p", f"HEAD:{rel}"],
        check=False,
        capture_output=True,
        env=_clean_git_env(),
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _resolve_upstream(source: Path) -> Optional[str]:
    result = _git(
        source,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    up = result.stdout.strip()
    return up or None


def _rollback_source(source: Path, saved: str) -> None:
    subprocess.run(
        ["git", "-C", str(source), "reset", "--hard", saved],
        check=False,
        env=_clean_git_env(),
    )
