# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Tests that replicate the GitHub docs/wiki CI jobs.

Runs the same commands as ``.github/workflows/docs.yml`` and
``.github/workflows/wiki.yml`` so local failures are caught before pushing.

All tests in this module are skipped:

- on Windows (``ishlib.sh`` requires bash), and
- when ``griffe`` is not installed (it lives in ``requirements-dev.txt``).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_ISHLIB_SH = _REPO_ROOT / "ishlib.sh"
_SRC_DOCS_DIR = _REPO_ROOT / "src" / "docs"

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

_IS_WIN = sys.platform == "win32"
_HAS_GRIFFE = importlib.util.find_spec("griffe") is not None

_SKIP_WIN = unittest.skipIf(_IS_WIN, "ishlib.sh requires bash; skipped on Windows")
_SKIP_GRIFFE = unittest.skipIf(not _HAS_GRIFFE, "griffe not installed (pip install griffe)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(*args, **kwargs):
    """Run a subprocess from the repo root, returning CompletedProcess."""
    return subprocess.run(
        args,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        **kwargs,
    )


def _generate_shell_docs(out_file: Path) -> None:
    """Run ``./ishlib.sh -h --markdown | head -n -1`` → *out_file*."""
    result = subprocess.run(
        ["bash", str(_ISHLIB_SH), "-h", "--markdown"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"ishlib.sh -h --markdown failed:\n{result.stderr}"
    lines = result.stdout.splitlines()
    # head -n -1 drops the last line (trailing blank / script epilogue)
    content = "\n".join(lines[:-1]) + "\n" if lines else ""
    out_file.write_text(content, encoding="utf-8")


def _run_build_pydocs(out_dir: Path) -> None:
    """Run build_pydocs.py as a subprocess writing output to *out_dir*."""
    result = _run(
        sys.executable,
        str(_SCRIPTS_DIR / "build_pydocs.py"),
        "--out-dir", str(out_dir),
    )
    assert result.returncode == 0, (
        f"build_pydocs.py failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _run_build_wiki(gen_docs_dir: Path, out_dir: Path) -> None:
    """Run build_wiki.py as a subprocess with redirected input/output dirs."""
    result = _run(
        sys.executable,
        str(_SCRIPTS_DIR / "build_wiki.py"),
        "--src-docs-dir", str(_SRC_DOCS_DIR),
        "--gen-docs-dir", str(gen_docs_dir),
        "--out", str(out_dir),
    )
    assert result.returncode == 0, (
        f"build_wiki.py failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


@_SKIP_WIN
class TestShellDocsGeneration(unittest.TestCase):
    """ishlib.sh -h --markdown produces the expected shell reference."""

    def test_markdown_flag_exits_zero(self):
        result = _run("bash", str(_ISHLIB_SH), "-h", "--markdown")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_markdown_output_is_nonempty(self):
        result = _run("bash", str(_ISHLIB_SH), "-h", "--markdown")
        self.assertGreater(len(result.stdout.strip()), 0)

    def test_shell_md_file_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ishlib_shell.md"
            _generate_shell_docs(out)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 0)

    def test_shell_md_contains_function_docs(self):
        """The generated file should contain markdown headings."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ishlib_shell.md"
            _generate_shell_docs(out)
            content = out.read_text(encoding="utf-8")
            self.assertIn("#", content, "No markdown headings found")


@_SKIP_WIN
@_SKIP_GRIFFE
class TestPydocsBuild(unittest.TestCase):
    """build_pydocs.py generates well-formed output."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pyishlib_out = Path(self._tmp.name) / "pyishlib"

    def tearDown(self):
        self._tmp.cleanup()

    def test_exits_zero(self):
        result = _run(
            sys.executable,
            str(_SCRIPTS_DIR / "build_pydocs.py"),
            "--out-dir", str(self.pyishlib_out),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_index_md_created(self):
        _run_build_pydocs(self.pyishlib_out)
        self.assertTrue((self.pyishlib_out / "index.md").is_file())

    def test_module_pages_created(self):
        _run_build_pydocs(self.pyishlib_out)
        pages = [p for p in self.pyishlib_out.iterdir()
                 if p.suffix == ".md" and p.name != "index.md"]
        self.assertGreater(len(pages), 0, "No per-module pages generated")

    def test_index_references_modules(self):
        _run_build_pydocs(self.pyishlib_out)
        index = (self.pyishlib_out / "index.md").read_text(encoding="utf-8")
        self.assertIn("pyishlib", index)

    def test_known_modules_present(self):
        """Key modules that must always have docs pages."""
        _run_build_pydocs(self.pyishlib_out)
        for name in ("userio", "environment", "dotfile_ignore"):
            self.assertTrue(
                (self.pyishlib_out / f"{name}.md").is_file(),
                f"Missing page for {name}",
            )


@_SKIP_WIN
@_SKIP_GRIFFE
class TestWikiBuild(unittest.TestCase):
    """build_wiki.py produces the expected wiki structure."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.docs_dir = self.tmp / "docs"
        self.docs_dir.mkdir()
        self.wiki_out = self.tmp / "wiki"

        # Build prerequisites
        _generate_shell_docs(self.docs_dir / "ishlib_shell.md")
        _run_build_pydocs(self.docs_dir / "pyishlib")

    def tearDown(self):
        self._tmp.cleanup()

    def test_exits_zero(self):
        result = _run(
            sys.executable,
            str(_SCRIPTS_DIR / "build_wiki.py"),
            "--src-docs-dir", str(_SRC_DOCS_DIR),
            "--gen-docs-dir", str(self.docs_dir),
            "--out", str(self.wiki_out),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_home_md_created(self):
        _run_build_wiki(self.docs_dir, self.wiki_out)
        self.assertTrue((self.wiki_out / "Home.md").is_file())

    def test_sidebar_created(self):
        _run_build_wiki(self.docs_dir, self.wiki_out)
        self.assertTrue((self.wiki_out / "_Sidebar.md").is_file())

    def test_shell_reference_page(self):
        _run_build_wiki(self.docs_dir, self.wiki_out)
        self.assertTrue((self.wiki_out / "ishlib_shell.md").is_file())

    def test_pyishlib_index_page(self):
        _run_build_wiki(self.docs_dir, self.wiki_out)
        self.assertTrue((self.wiki_out / "pyishlib.md").is_file())

    def test_ishfiles_page(self):
        _run_build_wiki(self.docs_dir, self.wiki_out)
        self.assertTrue((self.wiki_out / "ishfiles.md").is_file())

    def test_sidebar_contains_links(self):
        _run_build_wiki(self.docs_dir, self.wiki_out)
        sidebar = (self.wiki_out / "_Sidebar.md").read_text(encoding="utf-8")
        self.assertIn("Home", sidebar)
        self.assertIn("ishfiles", sidebar)

    def test_pyishlib_module_pages_copied(self):
        """Per-module pyishlib pages should appear with the pyishlib- prefix."""
        _run_build_wiki(self.docs_dir, self.wiki_out)
        prefixed = list(self.wiki_out.glob("pyishlib-*.md"))
        self.assertGreater(len(prefixed), 0, "No pyishlib-*.md pages in wiki output")


@_SKIP_WIN
@_SKIP_GRIFFE
class TestFullPipelineSubprocess(unittest.TestCase):
    """End-to-end: run exactly the commands from docs.yml and wiki.yml."""

    def test_complete_docs_and_wiki_pipeline(self):
        """Mirror the exact CI steps in one test."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            wiki_out = tmp_path / "wiki-staging"

            # CI step: ./ishlib.sh -h --markdown | head -n -1 > docs/ishlib_shell.md
            _generate_shell_docs(docs_dir / "ishlib_shell.md")
            self.assertTrue((docs_dir / "ishlib_shell.md").is_file())

            # CI step: ./scripts/build_pydocs.py
            _run_build_pydocs(docs_dir / "pyishlib")
            self.assertTrue((docs_dir / "pyishlib" / "index.md").is_file())

            # CI step: ./scripts/build_wiki.py --out wiki-staging
            _run_build_wiki(docs_dir, wiki_out)
            self.assertTrue((wiki_out / "Home.md").is_file())
            self.assertTrue((wiki_out / "_Sidebar.md").is_file())
            self.assertTrue((wiki_out / "ishlib_shell.md").is_file())
            self.assertTrue((wiki_out / "pyishlib.md").is_file())


if __name__ == "__main__":
    unittest.main()
