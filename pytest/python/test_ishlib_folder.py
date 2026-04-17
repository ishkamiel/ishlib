# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.ishlib_folder`."""

import os
import sys
import unittest
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishlib_folder import (  # noqa: E402
    ISHFILES_SUBDIR,
    ISHOLATE_SUBDIR,
    ISHPROJECT_SUBDIR,
    PROJECT_DIR_NAME,
    IshlibFolder,
)

# Skipped on Windows for parity with the rest of the ishproject test
# suite; the primitives here are covered by the Linux matrix.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="ishproject stack is Linux/macOS-targeted; Windows skipped.",
)


class TestIshlibFolderPaths(unittest.TestCase):
    """Path accessors compose ``<root>/.ishlib/<subdir>`` correctly."""

    def test_path_is_root_plus_project_dir(self) -> None:
        folder = IshlibFolder(Path("/tmp/proj"))
        self.assertEqual(folder.path, Path("/tmp/proj") / PROJECT_DIR_NAME)

    def test_subdir_accessors(self) -> None:
        folder = IshlibFolder(Path("/tmp/proj"))
        self.assertEqual(folder.ishfiles_dir, folder.path / ISHFILES_SUBDIR)
        self.assertEqual(folder.isholate_dir, folder.path / ISHOLATE_SUBDIR)
        self.assertEqual(folder.ishproject_dir, folder.path / ISHPROJECT_SUBDIR)

    def test_root_is_resolved_absolute(self) -> None:
        folder = IshlibFolder(Path("./relative/path"))
        self.assertTrue(folder.root.is_absolute())


class TestIshlibFolderDiscovery(unittest.TestCase):
    """``discover_*`` returns a path when it exists, else ``None``."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.folder = IshlibFolder(self.root)

    def test_discover_ishfiles_missing(self) -> None:
        self.assertIsNone(self.folder.discover_ishfiles())

    def test_discover_isholate_missing(self) -> None:
        self.assertIsNone(self.folder.discover_isholate())

    def test_discover_ishproject_missing(self) -> None:
        self.assertIsNone(self.folder.discover_ishproject())

    def test_discover_ishfiles_present(self) -> None:
        self.folder.ishfiles_dir.mkdir(parents=True)
        self.assertEqual(self.folder.discover_ishfiles(), self.folder.ishfiles_dir)

    def test_discover_isholate_present(self) -> None:
        self.folder.isholate_dir.mkdir(parents=True)
        self.assertEqual(self.folder.discover_isholate(), self.folder.isholate_dir)

    def test_discover_ishproject_present(self) -> None:
        self.folder.ishproject_dir.mkdir(parents=True)
        self.assertEqual(self.folder.discover_ishproject(), self.folder.ishproject_dir)

    def test_exists_reflects_disk_state(self) -> None:
        self.assertFalse(self.folder.exists())
        self.folder.path.mkdir()
        self.assertTrue(self.folder.exists())

    def test_from_cwd_uses_current_directory(self) -> None:
        original = Path.cwd()
        try:
            os.chdir(self.root)
            folder = IshlibFolder.from_cwd()
            self.assertEqual(folder.root, self.root.resolve())
        finally:
            os.chdir(original)


if __name__ == "__main__":
    unittest.main()
