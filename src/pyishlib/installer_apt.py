# SPDX-License-Identifier: MIT
# Copyright (C) 2025-2026 Hans Liljestrand <hans@liljestrand.dev>
"""Helper library for apt package installing tasks"""

import logging
import subprocess
from typing import Any, Optional, Sequence

from .installer_base import InstallerBase
from .version_check import meets_min_version

log = logging.getLogger(__name__)


class InstallerApt(InstallerBase):
    """Helper class for managing apt packages"""

    INSTALLER_NAME: str = "apt"

    def _tool_cmd(self) -> str:
        return "apt"

    def _pkg_key(self) -> str:
        return "apt"

    def _install_flags(self) -> Sequence[str]:
        return ["install", "-y"]

    def _needs_sudo_for_install(self) -> bool:
        return True

    def is_pkg_installed(self, pkg: dict) -> bool:
        """Check if an apt package is installed.

        Handles transitional and virtual packages by first checking the
        literal package name via ``dpkg-query``, then falling back to
        ``apt-cache showpkg`` to find providing packages (e.g.
        ``gnome-extensions-app`` → ``gnome-shell-extension-prefs``).

        When ``min_version`` is set on the package, the installed
        version is read via ``dpkg-query`` and compared.  An installed
        package below ``min_version`` is treated as not installed so
        ``apt install`` runs and pulls a newer candidate.
        """
        if not self._guard_can_install(pkg):
            return False

        apt_name = pkg["apt"]
        min_version = pkg.get("min_version")

        if self._dpkg_is_installed(apt_name):
            return self._version_ok(pkg, apt_name, min_version)

        for provider in self._apt_reverse_provides(apt_name):
            if self._dpkg_is_installed(provider):
                log.debug("Package %s installed via provider %s", pkg["name"], provider)
                return self._version_ok(pkg, provider, min_version)

        return False

    def _version_ok(
        self, pkg: dict, dpkg_name: str, min_version: Optional[str]
    ) -> bool:
        """Return True if *dpkg_name*'s installed version satisfies *min_version*.

        With *min_version* unset, returns True (installed is enough).
        """
        if min_version is None:
            return True
        ver = self._dpkg_version(dpkg_name)
        if ver is None:
            log.debug(
                "Could not read dpkg version for %s; treating as not installed",
                pkg["name"],
            )
            return False
        if meets_min_version(ver, min_version):
            return True
        log.debug(
            "Package %s installed at %s, below min_version %s",
            pkg["name"],
            ver,
            min_version,
        )
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

    def _dpkg_version(self, pkg_name: str) -> Optional[str]:
        """Return the installed version of *pkg_name* per dpkg, or None.

        The Debian epoch (e.g. ``2:`` in ``2:14.1.0-1``) is stripped so
        the returned string matches the upstream version that
        ``min_version`` is most likely declared against.
        """
        try:
            result = self.runner.run(
                ["dpkg-query", "-W", "--showformat=${Version}", pkg_name],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        ver = result.stdout.decode("utf-8", errors="replace").strip()
        if not ver:
            return None
        if ":" in ver:
            ver = ver.split(":", 1)[1]
        return ver

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

    def update_pkgs(self) -> bool:
        """Update all installed apt packages"""
        self._require_available()

        log.info("Updating apt packages")
        self._run_cmd(["apt", "update"], sudo=True, action="updating")
        self._run_cmd(["apt", "upgrade", "-y"], sudo=True, action="updating")
        return True


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
