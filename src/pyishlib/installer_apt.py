#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Helper library for apt package installing tasks"""

import logging
import subprocess
from typing import Any, Optional, Sequence

from .installer_base import InstallerBase

log = logging.getLogger(__name__)


class InstallerApt(InstallerBase):
    """Helper class for managing apt packages"""

    INSTALLER_NAME: str = "apt"

    def _tool_cmd(self) -> str:
        return "apt"

    def _pkg_key(self) -> str:
        return "apt"

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if an apt package is installed.

        Handles transitional and virtual packages by first checking the
        literal package name via ``dpkg-query``, then falling back to
        ``apt-cache showpkg`` to find providing packages (e.g.
        ``gnome-extensions-app`` → ``gnome-shell-extension-prefs``).
        """
        if not self.can_install() or not self.can_install(pkg):
            log.debug("apt not available for %s", pkg.get("name"))
            return False

        apt_name = pkg["apt"]

        if self._dpkg_is_installed(apt_name):
            return True

        for provider in self._apt_reverse_provides(apt_name):
            if self._dpkg_is_installed(provider):
                log.debug("Package %s installed via provider %s", pkg["name"], provider)
                return True

        return False

    def is_pkg_available(self, pkg: Optional[Any] = None) -> bool:
        """Return True if *pkg* is known to the local apt index.

        Uses ``apt-cache showpkg`` to check whether the package has any
        versions in the index (real package) or any Reverse Provides
        (virtual/transitional package whose providers exist in the index).
        Returns False if apt is unavailable or the package is unknown.
        """
        if pkg is None or not self.can_install() or not self.can_install(pkg):
            return False

        try:
            result = self.runner.run(
                ["apt-cache", "--no-generate", "showpkg", pkg["apt"]],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                return False
            return _showpkg_has_versions_or_providers(
                result.stdout.decode("utf-8", errors="replace")
            )
        except Exception:
            return False

    def _dpkg_is_installed(self, pkg_name: str) -> bool:
        """Return True if dpkg reports *pkg_name* as installed."""
        try:
            result = self.runner.run(
                ["dpkg-query", "-W", "--showformat=${Status}\n", pkg_name],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return "install ok installed" in result.stdout.decode(
                "utf-8", errors="replace"
            )
        except Exception:
            return False

    def _apt_reverse_provides(self, pkg_name: str) -> list:
        """Return package names that ``Provides: <pkg_name>`` in the apt index."""
        try:
            result = self.runner.run(
                ["apt-cache", "--no-generate", "showpkg", pkg_name],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0:
                return []
            return _parse_reverse_provides(
                result.stdout.decode("utf-8", errors="replace")
            )
        except Exception:
            return []

    def install_pkgs(self, pkgs: Sequence[dict]) -> bool:
        """Install a list of apt packages"""
        self._validate_pkgs(pkgs)

        pkg_list: Sequence[str] = [pkg["apt"] for pkg in pkgs]

        log.info("Installing with apt: %s", " ".join(pkg_list))
        res = self._run_cmd(
            ["apt", "install", "-y", *pkg_list], sudo=True, action="installing"
        )
        return res.returncode == 0

    def update_pkgs(self) -> bool:
        """Update all installed apt packages"""
        self._require_available()

        log.info("Updating apt packages")
        self._run_cmd(["apt", "update"], sudo=True, action="updating")
        self._run_cmd(["apt", "upgrade", "-y"], sudo=True, action="updating")
        return True

    def update_and_install_all(self, pkgs: Sequence[dict]) -> None:
        """Update apt packages, then install new apt pkgs"""
        self.update_pkgs()
        self.install_pkgs(pkgs)


# ---------------------------------------------------------------------------
# Module-level helpers (used by InstallerApt methods above)
# ---------------------------------------------------------------------------


def _parse_reverse_provides(showpkg_output: str) -> list:
    """Parse the ``Reverse Provides:`` section of ``apt-cache showpkg`` output.

    Returns a list of package names that provide the queried virtual package.
    """
    providers: list = []
    in_section = False
    for line in showpkg_output.splitlines():
        if line.startswith("Reverse Provides:"):
            in_section = True
            rest = line[len("Reverse Provides:") :].strip()
            if rest:
                providers.append(rest.split()[0])
            continue
        if in_section:
            stripped = line.strip()
            if not stripped:
                break
            providers.append(stripped.split()[0])
    return providers


def _showpkg_has_versions_or_providers(showpkg_output: str) -> bool:
    """Return True if ``apt-cache showpkg`` output shows a real or virtual package.

    A real package has entries in its ``Versions:`` section.
    A virtual/transitional package has entries in ``Reverse Provides:``.
    Either signals that ``apt install`` can resolve the name.
    """
    in_section = False
    for line in showpkg_output.splitlines():
        if line.startswith(("Versions:", "Reverse Provides:")):
            in_section = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                return True
            continue
        if line.startswith(
            ("Reverse Depends:", "Dependencies", "Provides:", "Package:")
        ):
            in_section = False
            continue
        if in_section and line.strip():
            return True
    return False
