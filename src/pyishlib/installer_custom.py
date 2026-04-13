#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Custom script-based package installer.

Installs packages by executing user-provided scripts found in an
``ishinstallers/`` folder within the dotfiles directory.  Scripts are
named ``install_<pkg_name>`` (with an optional extension) and go through
the same ``@ish`` directive preprocessing as dotfiles, allowing them to
use ``${__ish_<name>}`` variable substitution and ``#@ish if``
conditionals.

The custom installer integrates with the standard installer framework
and can be selected via the ``custom`` key in package configuration::

    [my-tool]
    custom = "my-tool"
    cmd = "my-tool"

This will look for a script named ``install_my-tool`` (or
``install_my-tool.sh``, ``install_my-tool.py``, etc.) in the
``ishinstallers/`` directory.
"""

import logging
from pathlib import Path
from typing import Any, Iterable, List, Optional

from .command_runner import CommandRunner
from .dotfile_script import DotfileScript
from .environment import detect_distro, detect_os, normalise_os
from .file_preprocessor import FilePreprocessor
from .ish_config import IshConfig

log = logging.getLogger(__name__)

_DEFAULT_INSTALLERS_DIR = "ishinstallers"


class InstallerCustom:
    """Installer backend that runs user-provided install scripts.

    Scripts are looked up in ``<source>/<installers_dir>/`` and named
    ``install_<pkg_name>`` (with optional extension).  Each script is
    preprocessed through the ``@ish`` directive pipeline before execution.

    The dotfiles directory is resolved from ``cfg.get_opt("source")``.
    The directory name is read from ``cfg.get_opt("installers_dir")``.
    Preprocessing variables come from ``cfg.context``.

    Args:
        runner: :class:`CommandRunner` for executing scripts.
        cfg: :class:`IshConfig` providing ``source``, ``installers_dir``,
             and ``context``.  If *None*, a default is created.
    """

    INSTALLER_NAME: str = "custom"

    def __init__(
        self,
        runner: CommandRunner,
        cfg: Optional[IshConfig] = None,
    ) -> None:
        self.runner: CommandRunner = runner
        self._cfg: IshConfig = cfg if cfg is not None else IshConfig()

    @property
    def _dotfiles_dir(self) -> Optional[Path]:
        """The dotfiles source directory from config, or None."""
        source = self._cfg.get_opt("source")
        if source is None:
            return None
        return Path(source).expanduser().resolve()

    @property
    def installers_dir(self) -> Optional[Path]:
        """The installers directory, or None if not configured."""
        dotfiles_dir = self._dotfiles_dir
        if dotfiles_dir is None:
            return None
        name = self._cfg.get_opt("installers_dir", _DEFAULT_INSTALLERS_DIR)
        d = dotfiles_dir / name
        return d if d.is_dir() else None

    @property
    def namespace(self):
        """Get the common Namespace for installer commands."""

        class Namespace:
            """Namespace for custom installer commands."""

            can_install = self.can_use_custom
            install = self.install_custom_pkgs
            install_unless_found = self.install_custom_pkg_unless_found
            is_installed = self.is_custom_pkg_installed
            is_pkg_available = self.can_use_custom
            update = self.update_custom_pkgs
            update_and_install_all = self.update_and_install_all

        return Namespace()

    def can_use_custom(self, pkg: Optional[Any] = None) -> bool:
        """Check if custom installer is available for a package.

        Returns True when the package has a ``custom`` key and a matching
        install script exists in the installers directory.
        """
        if pkg is not None and "custom" not in pkg:
            log.debug("custom not specified for %s", pkg.get("name", "?"))
            return False
        if self.installers_dir is None:
            log.debug("No installers directory configured or found")
            return False
        if pkg is not None:
            script = self._find_script(pkg["custom"])
            if script is None:
                log.debug(
                    "No install script found for %s in %s",
                    pkg["custom"],
                    self.installers_dir,
                )
                return False
        return True

    def _find_script(self, pkg_name: str) -> Optional[Path]:
        """Find the install script for a package.

        Searches the installers directory for a matching script using the
        following precedence (first match wins):

        1. ``install_<pkg>.<current-os>.<ext>``  (e.g. ``linux``, ``darwin``, ``windows``)
        2. ``install_<pkg>.<current-family>.<ext>``  (e.g. ``debian``, ``fedora``)
        3. ``install_<pkg>.unixlike.<ext>``  (matches Linux and macOS)
        4. ``install_<pkg>.<ext>`` (no OS tag):
           - ``.sh`` / ``.bash`` treated as ``unixlike``
           - ``.ps1`` treated as ``windows``
        5. ``install_<pkg>`` (no extension, any OS)

        Returns:
            Path to the matching script, or None if not found.
        """
        if self.installers_dir is None:
            return None

        stem = f"install_{pkg_name}"
        current_os = detect_os()  # "linux", "macos", "windows"
        current_family = detect_distro()  # "debian", "fedora", or None

        # Build ordered list of OS tags to try (most specific first).
        os_tags: List[str] = [current_os]
        if current_family:
            os_tags.append(current_family)
        if current_os in ("linux", "macos"):
            os_tags.append("unixlike")

        all_files = sorted(f for f in self.installers_dir.iterdir() if f.is_file())

        # 1–3: ``install_<pkg>.<ostag>.<ext>`` (ostag in preferred order)
        for tag in os_tags:
            for candidate in all_files:
                parts = candidate.name.split(".")
                # Expect at least 3 parts: install_pkg, <ostag>, ext
                if len(parts) < 3:
                    continue
                # stem part may contain underscores; reconstruct up to last two dots
                candidate_stem = ".".join(parts[:-2])
                candidate_tag = parts[-2]
                if candidate_stem == stem and normalise_os(
                    candidate_tag
                ) == normalise_os(tag):
                    return candidate

        # 4: ``install_<pkg>.<ext>`` with no OS tag — select by extension convention.
        for candidate in all_files:
            parts = candidate.name.split(".")
            if len(parts) != 2:
                continue
            candidate_stem, ext = parts[0], parts[1]
            if candidate_stem != stem:
                continue
            if ext in ("sh", "bash") and current_os in ("linux", "macos"):
                return candidate
            if ext == "ps1" and current_os == "windows":
                return candidate

        # 5: exact name with no extension
        exact = self.installers_dir / stem
        if exact.is_file():
            return exact

        return None

    def is_custom_pkg_installed(self, pkg: Any) -> bool:
        """Check if a custom-installed package is present.

        Custom packages rely on the ``cmd`` field in the package config
        for installation checks.  If no ``cmd`` is specified, this
        always returns False (the package will be re-installed).
        """
        if "cmd" in pkg:
            return self.runner.which(pkg["cmd"]) is not None
        return False

    def install_custom_pkgs(self, pkgs: Iterable[dict]) -> bool:
        """Install packages using custom scripts.

        Each package is installed individually by preprocessing and
        executing its corresponding script.
        """
        pkgs = list(pkgs)
        assert all(isinstance(pkg, dict) for pkg in pkgs), (
            "pkgs should be an iterable of dictionaries"
        )

        for pkg in pkgs:
            self._install_one(pkg)
        return True

    def _install_one(self, pkg: dict) -> None:
        """Install a single package via its custom script.

        Raises:
            FileNotFoundError: If no install script is found.
            subprocess.CalledProcessError: If the script exits non-zero.
        """
        pkg_name = pkg["custom"]
        script_path = self._find_script(pkg_name)
        if script_path is None:
            raise FileNotFoundError(
                f"No install script found for {pkg_name} in {self.installers_dir}"
            )

        log.info("Installing %s via custom script: %s", pkg["name"], script_path)

        preprocessor = FilePreprocessor(variables=self._cfg.context.as_dict())
        script = DotfileScript(
            path=script_path,
            preprocessor=preprocessor,
            runner=self.runner,
        )
        script.execute()

    def install_custom_pkg(self, pkg: dict) -> bool:
        """Install a single package."""
        return self.install_custom_pkgs([pkg])

    def install_custom_pkg_unless_found(self, pkg: dict) -> bool:
        """Install a package unless it is already present."""
        if not self.is_custom_pkg_installed(pkg):
            return self.install_custom_pkg(pkg)
        return True

    def update_custom_pkgs(self) -> bool:
        """Update custom packages (no-op for custom installer)."""
        log.debug("Custom installer has no global update mechanism")
        return True

    def update_and_install_all(self, pkgs: Iterable[dict]) -> bool:
        """Install custom packages (update is a no-op)."""
        return self.install_custom_pkgs(pkgs)
