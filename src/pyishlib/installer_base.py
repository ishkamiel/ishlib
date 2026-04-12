#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Abstract base class for package installer backends."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from subprocess import CalledProcessError, CompletedProcess
from typing import Any, Iterable, Optional, Sequence

from .command_runner import CommandRunner

log = logging.getLogger(__name__)


class InstallerBase(ABC):
    """Abstract base class for package installer backends.

    Subclasses must set :attr:`INSTALLER_NAME` and implement the four
    abstract methods: :meth:`is_pkg_installed`, :meth:`install_pkgs`,
    :meth:`update_pkgs`, and :meth:`update_and_install_all`.

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
            update = self.update_pkgs
            update_and_install_all = self.update_and_install_all

        return Namespace()

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

    def install_pkg(self, pkg: dict) -> bool:
        """Install a single package (delegates to :meth:`install_pkgs`)."""
        return self.install_pkgs([pkg])

    def install_pkg_unless_found(self, pkg: dict) -> bool:
        """Install *pkg* only if :meth:`is_pkg_installed` returns False."""
        if not self.is_pkg_installed(pkg):
            return self.install_pkg(pkg)
        return True

    # -- abstract ---------------------------------------------------------------

    @abstractmethod
    def is_pkg_installed(self, pkg: dict) -> bool:
        """Return True if *pkg* is already installed."""

    @abstractmethod
    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install all packages in *pkgs*.  Returns True on success."""

    @abstractmethod
    def update_pkgs(self) -> bool:
        """Update all packages managed by this backend."""

    @abstractmethod
    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update the backend and install any new packages in *pkgs*."""
