# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests for :mod:`pyishlib.ishlib_folder`."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishlib_folder import PROJECT_DIR_NAME, IshlibFolder  # noqa: E402
from pyishlib.tools import TOOLS  # noqa: E402

# Skipped on Windows for parity with the rest of the ishproject test
# suite; the primitives here are covered by the Linux matrix.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="ishproject stack is Linux/macOS-targeted; Windows skipped.",
)


class TestIshlibFolderPaths(unittest.TestCase):
    """Path accessors compose ``<root>/.ishlib/<subdir>`` correctly."""

    def test_path_is_root_plus_project_dir(self) -> None:
        # IshlibFolder resolves symlinks; on macOS /tmp -> /private/tmp so we
        # compare against the resolved root rather than the raw input path.
        folder = IshlibFolder(Path("/tmp/proj"))
        self.assertEqual(folder.path, Path("/tmp/proj").resolve() / PROJECT_DIR_NAME)

    def test_tool_dir_for_all_registered_tools(self) -> None:
        folder = IshlibFolder(Path("/tmp/proj"))
        for tool in TOOLS:
            expected = folder.path / tool.subdir
            self.assertEqual(folder.tool_dir(tool.name), expected)

    def test_root_is_resolved_absolute(self) -> None:
        folder = IshlibFolder(Path("./relative/path"))
        self.assertTrue(folder.root.is_absolute())

    def test_tool_dir_unknown_raises(self) -> None:
        folder = IshlibFolder(Path("/tmp/proj"))
        with self.assertRaises(ValueError):
            folder.tool_dir("notarealtool")


class TestIshlibFolderDiscovery(unittest.TestCase):
    """``discover_tool`` returns a path when it exists, else ``None``."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.folder = IshlibFolder(self.root)

    def test_discover_tool_missing(self) -> None:
        for tool in TOOLS:
            self.assertIsNone(self.folder.discover_tool(tool.name))

    def test_discover_tool_present(self) -> None:
        for tool in TOOLS:
            d = self.folder.tool_dir(tool.name)
            d.mkdir(parents=True, exist_ok=True)
            self.assertEqual(self.folder.discover_tool(tool.name), d)
            d.rmdir()

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
