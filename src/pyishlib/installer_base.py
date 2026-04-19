# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Abstract base class for package installer backends."""

from __future__ import annotations

import logging
import subprocess
from abc import ABC, abstractmethod
from subprocess import CalledProcessError, CompletedProcess
from typing import Any, Iterable, Optional, Sequence

from .command_runner import CommandRunner

log = logging.getLogger(__name__)


class InstallerBase(ABC):
    """Abstract base class for package installer backends.

    Subclasses must set :attr:`INSTALLER_NAME` and implement the two
    abstract methods :meth:`is_pkg_installed` and :meth:`update_pkgs`.
    :meth:`install_pkgs` and :meth:`update_and_install_all` have default
    implementations on the base class — override them only if the
    default argv shape (:meth:`_build_install_cmd`) or sudo requirement
    (:meth:`_needs_sudo_for_install`) cannot express the backend's
    quirks (e.g. winget loops per package).

    Most subclasses also override :meth:`_tool_cmd` and :meth:`_pkg_key`
    to get the default :attr:`available` and :meth:`can_install` behaviour
    for free.  Backends with non-trivial tool detection (e.g. pip) may
    instead override :attr:`available` directly.
    """

    #: Unique backend identifier used by :class:`Installer`.
    INSTALLER_NAME: str

    def __init__(self, runner: CommandRunner) -> None:
        self.runner: CommandRunner = runner
        self._tool_checked: bool = False
        self._tool_available: bool = False

    # -- override in subclasses (unless available / can_install are overridden) --

    def _tool_cmd(self) -> str:
        """Shell command to probe for tool availability (e.g. ``"apt"``)."""
        raise NotImplementedError(f"{type(self).__name__} must implement _tool_cmd()")

    def _pkg_key(self) -> str:
        """Package-dict key for this backend (e.g. ``"apt"``)."""
        raise NotImplementedError(f"{type(self).__name__} must implement _pkg_key()")

    # -- provided by base class ------------------------------------------------

    @property
    def available(self) -> bool:
        """True if the underlying tool is present on the system."""
        if not self._tool_checked:
            self._tool_available = self.runner.which(self._tool_cmd()) is not None
            log.debug("%s available: %s", self.INSTALLER_NAME, self._tool_available)
            self._tool_checked = True
        return self._tool_available

    @property
    def namespace(self):
        """Return a :class:`Namespace` object wiring generic names to this backend."""

        class Namespace:
            """Installer namespace for use by :class:`Installer`."""

            can_install = self.can_install
            install = self.install_pkgs
            install_unless_found = self.install_pkg_unless_found
            is_installed = self.is_pkg_installed
            is_pkg_available = self.is_pkg_available
            update = self.update_pkgs
            update_and_install_all = self.update_and_install_all

        return Namespace()

    def is_pkg_available(self, pkg: Optional[Any] = None) -> bool:
        """Return True if *pkg* is known to the backend's repo/index.

        The default implementation delegates to :meth:`can_install`, which
        means "the tool is present and the package dict has the right key".
        Backends with actual repo-availability checks (e.g. apt, dnf) should
        override this to probe the local package index.
        """
        return self.can_install(pkg)

    def can_install(self, pkg: Optional[Any] = None) -> bool:
        """Return True if this backend can handle *pkg*.

        When *pkg* is ``None``, returns True iff the tool is available.
        When *pkg* is given, also checks that the package dict contains
        the backend's key (e.g. ``"apt"``).
        """
        if pkg is not None and self._pkg_key() not in pkg:
            return False
        return self.available

    def _validate_pkgs(self, pkgs: Sequence[dict]) -> None:
        """Validate *pkgs* is an iterable of installable package dicts."""
        if not isinstance(pkgs, Iterable) or not all(
            isinstance(pkg, dict) for pkg in pkgs
        ):
            raise TypeError("pkgs should be an iterable of dictionaries")
        if not all(self.can_install(p) for p in pkgs):
            raise ValueError(
                f"{self.INSTALLER_NAME}: cannot install one or more packages"
            )

    def _require_available(self) -> None:
        """Raise if the backend tool is not available."""
        if not self.can_install():
            raise RuntimeError(
                f"{self.INSTALLER_NAME}: backend is not available on this system"
            )

    def _run_cmd(
        self,
        cmd: Sequence[str],
        *,
        sudo: bool = False,
        action: str = "running",
    ) -> CompletedProcess:
        """Run *cmd* via :attr:`runner` (sudo if requested).

        Logs a critical message and re-raises on
        :class:`subprocess.CalledProcessError`.  Centralises the
        try/except/log boilerplate that every backend would otherwise
        repeat.
        """
        try:
            return self.runner.run(list(cmd), sudo=sudo)
        except CalledProcessError as e:
            log.critical(
                "%s error %s: %s (cmd: %s)",
                self.INSTALLER_NAME,
                action,
                e,
                " ".join(cmd),
            )
            raise

    def _guard_can_install(self, pkg: dict) -> bool:
        """Log + return False if this backend cannot handle *pkg*.

        Replaces the 5-line preamble that every ``is_pkg_installed``
        implementation used to carry.
        """
        if not self.can_install() or not self.can_install(pkg):
            log.debug("%s not available for %s", self.INSTALLER_NAME, pkg.get("name"))
            return False
        return True

    def _check_pkg_installed_by_output(
        self,
        pkg: dict,
        probe_cmd: Sequence[str],
        *,
        match: Optional[str] = None,
        check: bool = True,
    ) -> bool:
        """Run *probe_cmd* and return True iff *match* appears in stdout.

        Covers the common "run tool, grep output" pattern used by brew,
        cargo, pip, winget.  *match* defaults to ``pkg[self._pkg_key()]``.
        Set ``check=False`` when the probe command may legitimately exit
        non-zero without raising.
        """
        if not self._guard_can_install(pkg):
            return False
        try:
            result = self.runner.run(
                list(probe_cmd),
                check=check,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except CalledProcessError as e:
            log.debug(
                "%s error checking %s: %s",
                self.INSTALLER_NAME,
                pkg.get("name"),
                e,
            )
            return False
        if result.returncode != 0:
            return False
        text = result.stdout
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        needle = match if match is not None else pkg[self._pkg_key()]
        return needle in text

    # -- install-command assembly hooks ----------------------------------------

    def _install_flags(self) -> Sequence[str]:
        """Backend-specific flags for the install command (e.g. ``["install", "-y"]``).

        Default is ``[]`` — subclasses override to customise the argv
        shape produced by :meth:`_build_install_cmd`.
        """
        return []

    def _needs_sudo_for_install(self) -> bool:
        """Return True if this backend requires sudo for install (apt/dnf)."""
        return False

    def _build_install_cmd(self, pkg_names: Sequence[str]) -> Sequence[str]:
        """Assemble the argv for ``install_pkgs``.

        Default: ``[_tool_cmd(), *_install_flags(), *pkg_names]``.
        Backends whose tool invocation is a list (pip's
        ``python -m pip``) override this directly.
        """
        return [self._tool_cmd(), *self._install_flags(), *pkg_names]

    def install_pkg(self, pkg: dict) -> bool:
        """Install a single package (delegates to :meth:`install_pkgs`)."""
        return self.install_pkgs([pkg])

    def install_pkg_unless_found(self, pkg: dict) -> bool:
        """Install *pkg* only if :meth:`is_pkg_installed` returns False."""
        if not self.is_pkg_installed(pkg):
            return self.install_pkg(pkg)
        return True

    # -- default implementations -----------------------------------------------

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install all packages in *pkgs*.

        Default template: validate, build argv via :meth:`_build_install_cmd`,
        run with :meth:`_needs_sudo_for_install`.  Backends with a
        per-package invocation shape (winget) override this directly.
        """
        self._validate_pkgs(pkgs)
        pkg_names: Sequence[str] = [pkg[self._pkg_key()] for pkg in pkgs]
        log.info("Installing with %s: %s", self.INSTALLER_NAME, " ".join(pkg_names))
        res = self._run_cmd(
            self._build_install_cmd(pkg_names),
            sudo=self._needs_sudo_for_install(),
            action="installing",
        )
        return res.returncode == 0

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update the backend, then install *pkgs*.

        Default covers 5/6 built-in backends.  Cargo overrides to inject
        its ``update_or_install_rust()`` step.
        """
        self.update_pkgs()
        self.install_pkgs(pkgs)

    # -- abstract ---------------------------------------------------------------

    @abstractmethod
    def is_pkg_installed(self, pkg: dict) -> bool:
        """Return True if *pkg* is already installed."""

    @abstractmethod
    def update_pkgs(self) -> bool:
        """Update all packages managed by this backend."""
