# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.launchers`."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.launchers import install_all, render_launcher  # noqa: E402
from pyishlib.tools import TOOLS, get as get_tool  # noqa: E402


class TestRenderLauncher(unittest.TestCase):
    def setUp(self):
        self.tool = get_tool("ishfiles")
        self.source_dir = Path("/fake/src")
        self.content = render_launcher(self.tool, self.source_dir)

    def test_shebang(self):
        self.assertEqual(self.content.splitlines()[0], "#!/usr/bin/env bash")

    def test_contains_tool_name(self):
        self.assertIn(self.tool.name, self.content)

    def test_contains_module(self):
        self.assertIn(self.tool.module, self.content)

    def test_contains_source_dir(self):
        self.assertIn(str(self.source_dir), self.content)

    def test_no_placeholders_remain(self):
        for placeholder in ("__TOOL_NAME__", "__TOOL_MODULE__", "__SOURCE_DIR__"):
            self.assertNotIn(placeholder, self.content)

    def test_all_registered_tools(self):
        for tool in TOOLS:
            content = render_launcher(tool, self.source_dir)
            self.assertIn(tool.name, content)
            self.assertIn(tool.module, content)


class TestInstallAll(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = Path(self._tmp.name) / "bin"
        self.source = Path("/fake/src")

    def test_creates_launchers(self):
        ret = install_all(dest_dir=self.dest, source_dir=self.source)
        self.assertEqual(ret, 0)
        for tool in TOOLS:
            self.assertTrue((self.dest / tool.name).is_file(), f"{tool.name} not created")

    def test_launchers_are_executable(self):
        install_all(dest_dir=self.dest, source_dir=self.source)
        for tool in TOOLS:
            launcher = self.dest / tool.name
            mode = launcher.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{tool.name} not user-executable")

    def test_idempotent(self):
        install_all(dest_dir=self.dest, source_dir=self.source)
        mtimes1 = {t.name: (self.dest / t.name).stat().st_mtime for t in TOOLS}
        install_all(dest_dir=self.dest, source_dir=self.source)
        mtimes2 = {t.name: (self.dest / t.name).stat().st_mtime for t in TOOLS}
        for tool in TOOLS:
            self.assertEqual(
                mtimes1[tool.name],
                mtimes2[tool.name],
                f"{tool.name} was unnecessarily re-written",
            )

    def test_replaces_symlinks(self):
        self.dest.mkdir(parents=True)
        for tool in TOOLS:
            (self.dest / tool.name).symlink_to("/nonexistent")
        ret = install_all(dest_dir=self.dest, source_dir=self.source)
        self.assertEqual(ret, 0)
        for tool in TOOLS:
            launcher = self.dest / tool.name
            self.assertFalse(launcher.is_symlink(), f"{tool.name} is still a symlink")
            self.assertTrue(launcher.is_file(), f"{tool.name} not a file after replace")

    def test_dry_run_creates_no_files(self):
        ret = install_all(dest_dir=self.dest, source_dir=self.source, dry_run=True)
        self.assertEqual(ret, 0)
        self.assertFalse(self.dest.exists(), "dry_run must not create directories")

    def test_error_on_unwritable_dest(self):
        self.dest.mkdir(parents=True)
        self.dest.chmod(0o555)
        try:
            ret = install_all(dest_dir=self.dest, source_dir=self.source)
            self.assertEqual(ret, 1)
        finally:
            self.dest.chmod(0o755)

    def test_bakes_source_dir(self):
        install_all(dest_dir=self.dest, source_dir=self.source)
        for tool in TOOLS:
            content = (self.dest / tool.name).read_text()
            self.assertIn(str(self.source), content)


if __name__ == "__main__":
    unittest.main()
