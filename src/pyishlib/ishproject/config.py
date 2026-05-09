# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Config loading and branch resolution for ishproject.

The per-user config lives at ``~/.config/ishlib/ishproject.toml`` and
declares the ``prefix`` / ``postfix`` used when composing ishproject
branch names. When the file is missing the first ishproject invocation
prompts the user for both values (via
:meth:`~pyishlib.ish_config.IshConfig.bootstrap`) and writes the file.

The config is surfaced through :class:`IshprojectConfig`, an
:class:`~pyishlib.ish_config.IshConfig` subclass that owns all
ishproject-specific branch / worktree resolution logic as methods. The
same lookup chain (constants > args > conf > defaults) that ishfiles
uses backs ``cfg.prefix`` / ``cfg.postfix`` via ``get_opt``.

Branch resolution for any given repo goes:

1. Compose ``<prefix>/<current_branch>/<postfix>``. If that branch
   exists locally, use it -- this is the branch-specific override.
2. Otherwise fall back to the default ``<prefix>/<postfix>`` branch.

Every ishproject branch gets its own worktree path under ``.ishlib/``:
the default branch maps to ``.ishlib/ishproject`` for backward
compatibility, while branch-specific variants live at
``.ishlib/ishproject-<sanitized>-<hash>``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple, cast

from ..git_repo import GitRepo, NotAGitRepoError
from ..ish_config import IshConfig
from ..ishlib_folder import IshlibFolder

BranchExistsFn = Callable[[str], bool]

log = logging.getLogger(__name__)

DEFAULT_PREFIX = "ishlib"
DEFAULT_POSTFIX = "ishproject"

_SCHEMA: Path = (
    Path(__file__).resolve().parent.parent / "schema" / "ishproject_config.json"
)


class IshprojectConfig(IshConfig):
    """:class:`IshConfig` specialized for ishproject.

    Owns every ishproject-specific derivation from the loaded
    ``prefix`` / ``postfix`` values so commands never reach back into
    module-level helpers to interpret config.
    """

    # -- prefix / postfix accessors -----------------------------------------
    @property
    def prefix(self) -> str:
        return str(self.get_opt("prefix"))

    @property
    def postfix(self) -> str:
        return str(self.get_opt("postfix"))

    # -- branch name derivation --------------------------------------------
    @property
    def default_branch(self) -> str:
        """The ``<prefix>/<postfix>`` branch used when no override exists."""
        return f"{self.prefix}/{self.postfix}"

    def branch_for(self, current_branch: Optional[str]) -> str:
        """Candidate ``<prefix>/<current>/<postfix>`` for *current_branch*.

        Falls back to :attr:`default_branch` when *current_branch* is
        ``None`` (e.g. detached HEAD).
        """
        if not current_branch:
            return self.default_branch
        return f"{self.prefix}/{current_branch}/{self.postfix}"

    def resolve_branch(
        self,
        branch_exists: BranchExistsFn,
        current_branch: Optional[str],
    ) -> str:
        """Return the ishproject branch name for the current repo state.

        *branch_exists* is a callable ``(name) -> bool`` (typically
        ``lambda name: repo.branch_exists(name, local_only=True)``) so
        the resolver stays decoupled from :class:`GitRepo` for testing.
        """
        candidate = self.branch_for(current_branch)
        if candidate != self.default_branch and branch_exists(candidate):
            return candidate
        return self.default_branch

    def resolve_active_branch(self, root: Path) -> str:
        """Resolve the active ishproject branch for the repo at *root*.

        Falls back to :attr:`default_branch` when *root* is not a git
        repo, so wrappers can still point at the default worktree
        layout.
        """
        try:
            repo = GitRepo.discover(root, require_root=True)
        except NotAGitRepoError:
            return self.default_branch
        return self.resolve_branch(
            lambda name: repo.branch_exists(name, local_only=True),
            repo.current_branch(),
        )

    # -- worktree path derivation ------------------------------------------
    def worktree_path(self, folder: IshlibFolder, branch: str) -> Path:
        """Return the worktree path under ``.ishlib/`` for *branch*.

        The default branch keeps the historical ``.ishlib/ishproject``
        layout; branch-specific variants use
        ``.ishlib/ishproject-<sanitized>-<hash>`` so each branch gets
        a unique working tree. The readable segment is derived from
        the branch's middle component (``<current>`` in
        ``<prefix>/<current>/<postfix>``); the trailing hash is 8
        hex chars of sha256 over the full branch name so that distinct
        branches collapsing to the same sanitized segment (e.g.
        ``feature/x`` vs. ``feature_x``) still resolve to different
        directories.
        """
        tool_dir = folder.tool_dir("ishproject")
        if branch == self.default_branch:
            return tool_dir
        segment = _sanitize_branch(self._middle_segment(branch))
        digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:8]
        return folder.path / f"{tool_dir.name}-{segment}-{digest}"

    def resolve_project_paths(
        self,
        root: Path,
        branch: Optional[str] = None,
    ) -> Tuple[Path, Path]:
        """Return ``(source, target)`` for ishproject at *root*.

        ``target`` is the project root. ``source`` is the worktree for
        *branch* (default: :attr:`default_branch`) resolved via
        :meth:`worktree_path`.
        """
        folder = IshlibFolder(root)
        resolved_branch = branch or self.default_branch
        return self.worktree_path(folder, resolved_branch), folder.root

    def iter_initialised_submodules(
        self, parent_repo: GitRepo
    ) -> Iterator[Tuple[GitRepo, Path, Path]]:
        """Yield ``(sub_repo, source, target)`` for each ready submodule.

        "Ready" means the submodule is initialised (so
        :meth:`GitRepo.iter_submodule_repos` already yielded it), the
        ishproject branch resolved for the submodule exists in its
        locally-known refs (no fetches), and the worktree directory is
        present on disk. Submodules failing either gate are silently
        skipped so callers can iterate without per-submodule
        conditionals — same gate ``status`` uses to decide whether a
        submodule contributes a section to the report.
        """
        for sub_repo in parent_repo.iter_submodule_repos():
            sub_root = sub_repo.work_tree
            sub_branch = self.resolve_active_branch(sub_root)
            sub_source, sub_target = self.resolve_project_paths(
                sub_root, branch=sub_branch
            )
            if not sub_repo.branch_exists(sub_branch):
                continue
            if not sub_source.is_dir():
                continue
            yield sub_repo, sub_source, sub_target

    # -- helpers -----------------------------------------------------------
    def _middle_segment(self, branch: str) -> str:
        """Extract the ``<current>`` part of ``<prefix>/<current>/<postfix>``.

        Falls back to *branch* unchanged when the branch does not match
        the configured prefix/postfix (e.g. user-typed custom branch
        name).
        """
        prefix = f"{self.prefix}/"
        postfix = f"/{self.postfix}"
        if branch.startswith(prefix) and branch.endswith(postfix):
            return branch[len(prefix) : -len(postfix)]
        return branch


def load_config(
    config_path: Optional[Path] = None,
    *,
    interactive: Optional[bool] = None,
) -> IshprojectConfig:
    """Load the ishproject config, prompting to create it if absent.

    *config_path* defaults to ``~/.config/ishlib/ishproject.toml``,
    evaluated at call time (not at import time) so the value reflects the
    process's current ``HOME``.  Pass an explicit path to redirect for
    testing.

    When *interactive* is ``None`` the value is derived from
    ``sys.stdin.isatty()``. A non-interactive session with a missing
    config file silently falls back to :data:`DEFAULT_PREFIX` /
    :data:`DEFAULT_POSTFIX` rather than writing anything to disk.

    Returns an :class:`IshprojectConfig` where ``cfg.prefix`` and
    ``cfg.postfix`` resolve to the effective values and
    ``cfg.get_opt("config_file")`` returns *config_path*.
    """
    if config_path is None:
        config_path = Path.home() / ".config" / "ishlib" / "ishproject.toml"
    IshprojectConfig.bootstrap(
        config_path,
        section="ishproject",
        prompts=[
            ("prefix", "ishproject branch prefix", DEFAULT_PREFIX),
            ("postfix", "ishproject branch postfix", DEFAULT_POSTFIX),
        ],
        interactive=interactive,
    )

    # IshConfig.from_toml is annotated as returning IshConfig, but builds
    # the instance via ``cls(...)`` so the runtime type matches the caller
    # (here IshprojectConfig). Cast to keep the subclass type visible to
    # mypy without changing the base class signature.
    cfg = cast(
        IshprojectConfig,
        IshprojectConfig.from_toml(
            toml_path=config_path,
            schema=_SCHEMA,
            defaults={
                "prefix": DEFAULT_PREFIX,
                "postfix": DEFAULT_POSTFIX,
            },
        ),
    )
    cfg.set_constant("config_file", config_path)
    return cfg


_UNSAFE_FS_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_branch(segment: str) -> str:
    """Replace filesystem-unfriendly characters in *segment* with ``_``.

    Empty result falls back to ``"branch"`` so the worktree path always
    carries a meaningful suffix.
    """
    safe = _UNSAFE_FS_CHARS.sub("_", segment)
    return safe or "branch"
