# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for _install_launchers() in ishfiles.commands.apply."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pathlib import Path  # noqa: E402

from pyishlib.ishfiles.commands.apply import _install_launchers  # noqa: E402
from pyishlib.tools import TOOLS  # noqa: E402


def _make_cfg(source: str, target: str, *, dry_run: bool = False):
    opts = {"source": source, "target": target}
    return SimpleNamespace(
        dry_run=dry_run,
        get_opt=lambda name, default=None: opts.get(name, default),
    )


class TestInstallLaunchers(unittest.TestCase):
    def test_calls_install_all_with_correct_paths(self):
        with patch.object(Path, "is_dir", return_value=True), patch(
            "pyishlib.ishfiles.commands.apply._install_launchers_impl"
        ) as mock_install:
            mock_install.return_value = 0
            cfg = _make_cfg("/fake/source", "/fake/target")
            _install_launchers(cfg)

        mock_install.assert_called_once_with(
            dest_dir=Path("/fake/target/.local/bin"),
            source_dir=Path("/fake/source/ishlib/src"),
            dry_run=False,
        )

    def test_passes_dry_run(self):
        with patch.object(Path, "is_dir", return_value=True), patch(
            "pyishlib.ishfiles.commands.apply._install_launchers_impl"
        ) as mock_install:
            mock_install.return_value = 0
            cfg = _make_cfg("/fake/source", "/fake/target", dry_run=True)
            _install_launchers(cfg)

        mock_install.assert_called_once_with(
            dest_dir=Path("/fake/target/.local/bin"),
            source_dir=Path("/fake/source/ishlib/src"),
            dry_run=True,
        )

    def test_returns_install_all_return_value(self):
        for expected_ret in (0, 1):
            with patch.object(Path, "is_dir", return_value=True), patch(
                "pyishlib.ishfiles.commands.apply._install_launchers_impl"
            ) as mock_install:
                mock_install.return_value = expected_ret
                cfg = _make_cfg("/fake/source", "/fake/target")
                ret = _install_launchers(cfg)
            self.assertEqual(ret, expected_ret)

    def test_missing_source_dir_returns_nonzero(self):
        """When ishlib/src does not exist, _install_launchers must not call install_all."""
        with patch.object(Path, "is_dir", return_value=False), patch(
            "pyishlib.ishfiles.commands.apply._install_launchers_impl"
        ) as mock_install:
            cfg = _make_cfg("/fake/source", "/fake/target")
            ret = _install_launchers(cfg)
        mock_install.assert_not_called()
        self.assertEqual(ret, 1)

    def test_all_registered_tools_covered(self):
        """install_all is called once and covers all registered tools via the registry."""
        with patch.object(Path, "is_dir", return_value=True), patch(
            "pyishlib.ishfiles.commands.apply._install_launchers_impl"
        ) as mock_install:
            mock_install.return_value = 0
            cfg = _make_cfg("/src", "/tgt")
            _install_launchers(cfg)

        # install_all is called once; it loops over all tools internally.
        self.assertEqual(mock_install.call_count, 1)
        # Sanity: all known tool names are in the registry.
        tool_names = {t.name for t in TOOLS}
        self.assertIn("ishfiles", tool_names)
        self.assertIn("isholate", tool_names)
        self.assertIn("ishproject", tool_names)


if __name__ == "__main__":
    unittest.main()
