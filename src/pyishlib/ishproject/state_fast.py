# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Stdlib-only implementation of ``ishproject state``.

This module is the single implementation behind both the full CLI
(:class:`~pyishlib.ishproject.commands.state.StateCommand`) and the
launcher fast path, which runs this file *by path* with
``python3 -S -I state_fast.py [-R]`` so that neither the ``pyishlib``
package ``__init__`` nor any third-party module is imported.  That keeps
a prompt render close to the cost of the interpreter plus a few ``git``
calls.

Because it must work when run as a bare script it has **no relative
imports** and uses only the standard library (Python 3.9+).  It is also
deliberately sparing with *which* stdlib modules it imports: ``re``,
``typing`` and ``hashlib`` each cost milliseconds at startup, so config
parsing and branch sanitising are done by hand, ``typing`` is only
imported for type checkers, and ``hashlib`` is imported on first use.

The branch and worktree resolution mirrors
:class:`~pyishlib.ishproject.config.IshprojectConfig`; a parity test
(``TestStateFastParity``) keeps the two in sync.
"""

from __future__ import annotations

import os
import sys

# ``typing`` is imported only for annotations; avoid its import cost at runtime.
TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import List, Optional, Sequence, Tuple

DEFAULT_PREFIX = "ishlib"
DEFAULT_POSTFIX = "ishproject"
DIRTY_SYMBOL = "±"  # ±

_PROJECT_DIR = ".ishlib"
_TOOL_DIR = "ishproject"
_RECURSE_FLAGS = ("-R", "--recurse-submodules")
_GIT_DIR_VARS = ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY")
_SAFE_FS_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r"}


def _git(cwd: str, *args: str) -> Optional[Tuple[int, str]]:
    """Run ``git -C cwd args``; return ``(returncode, stdout)``.

    Git-dir override variables are removed from the environment, stderr
    is discarded, and ``None`` is returned when git cannot be executed.

    Where available this uses ``os.posix_spawnp`` and a pipe directly:
    importing :mod:`subprocess` drags in ``locale``, ``re`` and ``enum``
    and costs several milliseconds on every prompt render.  Platforms
    without ``posix_spawnp`` fall back to :mod:`subprocess`.
    """
    argv = ["git", "-C", cwd, *args]
    env = {k: v for k, v in os.environ.items() if k not in _GIT_DIR_VARS}
    if not hasattr(os, "posix_spawnp"):
        import subprocess

        try:
            res = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except OSError:
            return None
        return res.returncode, res.stdout

    rfd, wfd = os.pipe()
    try:
        pid = os.posix_spawnp(
            "git",
            argv,
            env,
            file_actions=[
                (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0),
                (os.POSIX_SPAWN_DUP2, wfd, 1),
            ],
        )
    except OSError:
        os.close(rfd)
        os.close(wfd)
        return None
    os.close(wfd)
    chunks = []
    try:
        while True:
            chunk = os.read(rfd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(rfd)
        _, status = os.waitpid(pid, 0)
    return (
        os.waitstatus_to_exitcode(status),
        b"".join(chunks).decode("utf-8", "replace"),
    )


def _parse_string(value: str) -> Optional[str]:
    """Parse the TOML basic (``"..."``) or literal (``'...'``) string at the
    start of *value*; anything after the closing quote (e.g. a comment) is
    ignored.  Returns ``None`` if *value* does not start with a valid string.
    """
    if not value:
        return None
    quote = value[0]
    if quote == "'":
        end = value.find("'", 1)
        return value[1:end] if end != -1 else None
    if quote != '"':
        return None
    out = []
    i = 1
    while i < len(value):
        ch = value[i]
        if ch == "\\":
            i += 1
            if i >= len(value):
                return None
            out.append(_ESCAPES.get(value[i], "\\" + value[i]))
        elif ch == '"':
            return "".join(out)
        else:
            out.append(ch)
        i += 1
    return None


def read_config(path: Optional[str] = None) -> Tuple[str, str]:
    """Return ``(prefix, postfix)`` from the ishproject TOML config.

    Only the two ``[ishproject]`` string keys are read, with a tiny
    line parser, so ``tomllib``/``tomli`` (and ``re``) are never
    imported.  A missing or unreadable file yields the defaults.
    """
    if path is None:
        path = os.path.join(
            os.path.expanduser("~"), ".config", "ishlib", "ishproject.toml"
        )
    values = {"prefix": DEFAULT_PREFIX, "postfix": DEFAULT_POSTFIX}
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return values["prefix"], values["postfix"]

    in_section = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("["):
            close = line.find("]")
            name = line[1:close].strip() if close != -1 else ""
            in_section = name == "ishproject"
            continue
        if not in_section:
            continue
        key, sep, rest = line.partition("=")
        key = key.strip()
        if not sep or key not in values:
            continue
        parsed = _parse_string(rest.strip())
        if parsed is not None:
            values[key] = parsed
    return values["prefix"], values["postfix"]


def _inspect(path: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return ``(toplevel, current_branch)`` for the repo containing *path*.

    ``current_branch`` is ``None`` for a detached HEAD.  Returns ``None``
    when *path* is not inside a git working tree.  One ``git`` call in
    the common case; an unborn branch (no commits yet) falls back to
    ``symbolic-ref``.
    """
    res = _git(path, "rev-parse", "--show-toplevel", "--abbrev-ref", "HEAD")
    if res is not None and res[0] == 0:
        lines = res[1].splitlines()
        if len(lines) >= 2:
            branch = lines[1].strip()
            return os.path.realpath(lines[0]), (
                None if branch in ("", "HEAD") else branch
            )

    top = _git(path, "rev-parse", "--show-toplevel")
    if top is None or top[0] != 0 or not top[1].strip():
        return None
    sym = _git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = sym[1].strip() if sym is not None and sym[0] == 0 else ""
    return os.path.realpath(top[1].strip()), (branch or None)


def _local_branch_exists(root: str, branch: str) -> bool:
    res = _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    return res is not None and res[0] == 0


def resolve_branch(root: str, current: Optional[str], prefix: str, postfix: str) -> str:
    """Mirror of :meth:`IshprojectConfig.resolve_branch` for repo *root*."""
    default = f"{prefix}/{postfix}"
    if not current:
        return default
    candidate = f"{prefix}/{current}/{postfix}"
    if candidate != default and _local_branch_exists(root, candidate):
        return candidate
    return default


def worktree_path(root: str, branch: str, prefix: str, postfix: str) -> str:
    """Mirror of :meth:`IshprojectConfig.worktree_path` as a string path."""
    if branch == f"{prefix}/{postfix}":
        return os.path.join(root, _PROJECT_DIR, _TOOL_DIR)
    head, tail = f"{prefix}/", f"/{postfix}"
    middle = branch
    if branch.startswith(head) and branch.endswith(tail):
        middle = branch[len(head) : -len(tail)]
    segment = "".join(c if c in _SAFE_FS_CHARS else "_" for c in middle) or "branch"
    import hashlib  # deferred: only per-branch worktrees need the digest

    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:8]
    return os.path.join(root, _PROJECT_DIR, f"{_TOOL_DIR}-{segment}-{digest}")


def _count_changes(source: str) -> int:
    """Number of ``git status --porcelain`` entries in the worktree at *source*.

    Zero when *source* is missing or is not itself a git root (a bare
    directory must not fall through to the enclosing repository).
    """
    if not os.path.isdir(source) or not os.path.exists(os.path.join(source, ".git")):
        return 0
    res = _git(source, "status", "--porcelain=v1", "-z")
    if res is None or res[0] != 0 or not res[1]:
        return 0
    count = 0
    skip_next = False
    for token in res[1].split("\x00"):
        if not token:
            continue
        if skip_next:
            skip_next = False
            continue
        if len(token) < 3 or token[2] != " ":
            continue
        count += 1
        # Rename/copy: the next token is the origin path, not an entry.
        if token[0] in ("R", "C"):
            skip_next = True
    return count


def _submodules(root: str) -> List[str]:
    """Absolute paths of initialised submodules (recursive) under *root*.

    ``git submodule foreach`` runs a shell and is comparatively slow, so
    it is skipped outright for repos without a ``.gitmodules`` file --
    which cannot have submodules.
    """
    if not os.path.exists(os.path.join(root, ".gitmodules")):
        return []
    res = _git(
        root,
        "submodule",
        "foreach",
        "--recursive",
        "--quiet",
        'printf "%s\\n" "$toplevel/$sm_path"',
    )
    if res is None or res[0] != 0:
        return []
    return [ln for ln in (s.strip() for s in res[1].splitlines()) if ln]


def _dirty_for(path: str, prefix: str, postfix: str) -> int:
    info = _inspect(path)
    if info is None:
        return 0
    top, current = info
    branch = resolve_branch(top, current, prefix, postfix)
    return _count_changes(worktree_path(top, branch, prefix, postfix))


def count_dirty(
    cwd: str,
    *,
    recurse: bool = False,
    prefix: str = DEFAULT_PREFIX,
    postfix: str = DEFAULT_POSTFIX,
) -> int:
    """Total uncommitted-change count for the ishproject worktree(s) at *cwd*.

    With *recurse*, initialised submodules that have an ishproject
    worktree are folded into the same total.
    """
    info = _inspect(cwd)
    if info is None:
        return 0
    top, current = info
    branch = resolve_branch(top, current, prefix, postfix)
    total = _count_changes(worktree_path(top, branch, prefix, postfix))
    if recurse:
        for sub in _submodules(top):
            if os.path.isdir(sub):
                total += _dirty_for(sub, prefix, postfix)
    return total


def format_token(count: int) -> str:
    """Return the prompt token for *count* (empty when nothing changed)."""
    return f"{DIRTY_SYMBOL}{count}" if count > 0 else ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the launcher fast path; always exits 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    recurse = any(a in _RECURSE_FLAGS for a in args)
    try:
        cwd = os.getcwd()
    except OSError:
        return 0
    prefix, postfix = read_config()
    count = count_dirty(cwd, recurse=recurse, prefix=prefix, postfix=postfix)
    token = format_token(count)
    if token:
        # Write bytes so a non-UTF-8 stdout encoding (C locale) cannot raise.
        sys.stdout.buffer.write((token + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
