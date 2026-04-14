#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for _install_self_links() in ishfiles.commands.apply."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from pyishlib.ishfiles.commands.apply import _install_self_links, _SELF_LINK_NAMES


def _make_cfg(source: str, target: str, *, dry_run: bool = False, quiet: bool = False):
    """Build a minimal cfg-like namespace for _install_self_links."""
    opts = {"source": source, "target": target}
    return SimpleNamespace(
        dry_run=dry_run,
        quiet=quiet,
        get_opt=lambda name, default=None: opts.get(name, default),
    )


def _make_source(tmp: Path) -> Path:
    """Create a fake source tree with ishlib/bin/ishfiles and isholate."""
    bin_dir = tmp / "ishlib" / "bin"
    bin_dir.mkdir(parents=True)
    for name in _SELF_LINK_NAMES:
        script = bin_dir / name
        script.write_text(f"#!/usr/bin/env python3\nprint('{name}')\n")
        script.chmod(0o755)
    return tmp


class TestInstallSelfLinksBasic(unittest.TestCase):
    def test_creates_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            target.mkdir()

            cfg = _make_cfg(str(source), str(target))
            ret = _install_self_links(cfg)

            self.assertEqual(ret, 0)
            for name in _SELF_LINK_NAMES:
                link = target / ".local" / "bin" / name
                self.assertTrue(link.is_symlink(), f"{name} symlink not created")
                self.assertTrue(link.exists(), f"{name} symlink target missing")

    def test_symlinks_point_to_correct_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            target.mkdir()

            cfg = _make_cfg(str(source), str(target))
            _install_self_links(cfg)

            for name in _SELF_LINK_NAMES:
                link = target / ".local" / "bin" / name
                expected = source / "ishlib" / "bin" / name
                # Use samefile to avoid platform path-representation differences
                # (e.g. Windows extended \\?\ prefix vs. normal C:\ form).
                self.assertTrue(
                    os.path.samefile(link, expected),
                    f"{name} symlink points to wrong target",
                )

    def test_creates_bin_dir_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            target.mkdir()
            # .local/bin does NOT exist yet

            cfg = _make_cfg(str(source), str(target))
            _install_self_links(cfg)

            self.assertTrue((target / ".local" / "bin").is_dir())

    def test_idempotent_correct_links(self):
        """Running twice with correct links already present is a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            target.mkdir()

            cfg = _make_cfg(str(source), str(target))
            ret1 = _install_self_links(cfg)
            ret2 = _install_self_links(cfg)

            self.assertEqual(ret1, 0)
            self.assertEqual(ret2, 0)
            for name in _SELF_LINK_NAMES:
                link = target / ".local" / "bin" / name
                self.assertTrue(link.is_symlink())

    def test_replaces_stale_symlink(self):
        """A symlink pointing to the wrong target is replaced."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            bin_dst = target / ".local" / "bin"
            bin_dst.mkdir(parents=True)

            # Create a stale symlink for the first tool
            name = _SELF_LINK_NAMES[0]
            stale = tmp_path / "elsewhere" / name
            stale.parent.mkdir()
            stale.write_text("old")
            os.symlink(stale, bin_dst / name)

            cfg = _make_cfg(str(source), str(target))
            ret = _install_self_links(cfg)

            self.assertEqual(ret, 0)
            link = bin_dst / name
            self.assertTrue(link.is_symlink())
            expected = source / "ishlib" / "bin" / name
            self.assertTrue(
                os.path.samefile(link, expected),
                "replaced symlink points to wrong target",
            )

    def test_skips_regular_file_with_warning(self):
        """A regular file at the destination path is left alone (returns 1)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            bin_dst = target / ".local" / "bin"
            bin_dst.mkdir(parents=True)

            name = _SELF_LINK_NAMES[0]
            (bin_dst / name).write_text("I am a real file")

            cfg = _make_cfg(str(source), str(target))
            ret = _install_self_links(cfg)

            # Returns 1 (error) but leaves the file intact
            self.assertEqual(ret, 1)
            self.assertFalse((bin_dst / name).is_symlink())

    def test_missing_source_returns_error(self):
        """If the ishlib/bin directory or script is absent, return 1."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source"
            source.mkdir()
            # No ishlib/bin created
            target = tmp_path / "home"
            target.mkdir()

            cfg = _make_cfg(str(source), str(target))
            ret = _install_self_links(cfg)

            self.assertEqual(ret, 1)


@unittest.skipIf(sys.platform == "win32", "dry_run output uses POSIX ln syntax")
class TestInstallSelfLinksDryRun(unittest.TestCase):
    def test_dry_run_prints_ln_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            target.mkdir()

            cfg = _make_cfg(str(source), str(target), dry_run=True)

            with self.assertLogs("pyishlib", level="INFO") as cm:
                ret = _install_self_links(cfg)

            self.assertEqual(ret, 0)
            log_output = "\n".join(cm.output)
            for name in _SELF_LINK_NAMES:
                self.assertIn(name, log_output)
            self.assertIn("ln -s", log_output)

    def test_dry_run_creates_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = _make_source(tmp_path / "source")
            target = tmp_path / "home"
            target.mkdir()

            cfg = _make_cfg(str(source), str(target), dry_run=True)
            _install_self_links(cfg)

            bin_dst = target / ".local" / "bin"
            self.assertFalse(bin_dst.exists(), "dry_run must not create directories")


if __name__ == "__main__":
    unittest.main()
