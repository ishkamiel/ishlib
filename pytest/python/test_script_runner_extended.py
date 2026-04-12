#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.
"""Tests for run_when gating, stage ordering, and tag filtering in script_runner."""

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

from pyishlib.ishfiles.script_runner import find_scripts, scan_scripts, run_scanned_scripts
from pyishlib.ishfiles.script_state import ScriptState
from pyishlib.ish_config import IshConfig
from pyishlib.dotfile_context import DotfileContext


def _make_cfg(source: str, target: str = None, data_template: dict = None):
    """Build a minimal IshConfig-like object for tests."""
    cfg = IshConfig(
        dry_run=True,
        defaults={"source": source, "target": target or source},
    )
    cfg.set_constant("scripts_dir", "ishscripts")
    if data_template is not None:
        cfg.data_template = data_template
    return cfg


def _write_script(scripts_dir: Path, name: str, content: str, metadata: str = "") -> Path:
    """Write a script file with optional __ISH__ metadata block."""
    scripts_dir.mkdir(parents=True, exist_ok=True)
    full = ""
    if metadata:
        full = f"# __ISH__\n# {metadata}\n# __ISH_END__\n"
    full += content
    p = scripts_dir / name
    p.write_text(full, encoding="utf-8")
    return p


def _write_toml_script(scripts_dir: Path, name: str, toml_block: str, body: str = "") -> Path:
    """Write a script with a shell-heredoc __ISH__ metadata block."""
    scripts_dir.mkdir(parents=True, exist_ok=True)
    # Use the shell heredoc format recognised by ish_metadata.read_metadata.
    meta_section = f": <<'__ISH__'\n{toml_block}\n__ISH__\n"
    content = "#!/bin/sh\n" + meta_section + (body or "echo ok\n")
    p = scripts_dir / name
    p.write_text(content, encoding="utf-8")
    return p


class TestFindScriptsOrdering(unittest.TestCase):
    """find_scripts() returns scripts in lexical (numeric-prefix) order."""

    def test_lexical_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            scripts_dir.mkdir()
            for name in ("99_last.sh", "10_middle.sh", "00_first.sh"):
                (scripts_dir / name).write_text("#!/bin/sh\n", encoding="utf-8")

            cfg = _make_cfg(tmp)
            found = find_scripts(cfg, Path(tmp))
            names = [p.name for p in found]
            assert names == ["00_first.sh", "10_middle.sh", "99_last.sh"]

    def test_hidden_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            scripts_dir.mkdir()
            (scripts_dir / "visible.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            (scripts_dir / ".hidden.sh").write_text("#!/bin/sh\n", encoding="utf-8")

            cfg = _make_cfg(tmp)
            found = find_scripts(cfg, Path(tmp))
            names = [p.name for p in found]
            assert "visible.sh" in names
            assert ".hidden.sh" not in names

    def test_no_scripts_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_cfg(tmp)
            found = find_scripts(cfg, Path(tmp))
            assert found == []


class TestRunWhenGating(unittest.TestCase):
    """run_when=once and run_when=onchange are enforced by run_scanned_scripts."""

    def _make_state(self, tmp):
        return ScriptState(Path(tmp) / ".config" / "ishfiles" / "script-state.json")

    def test_run_always_runs_every_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            script = _write_toml_script(
                scripts_dir, "always.sh", 'run_when = "always"'
            )
            cfg = _make_cfg(tmp)
            state = self._make_state(tmp)
            state.record("always.sh", script.read_text())
            # Even though recorded, run_when=always should not skip
            # In dry_run mode we count "[dry-run]" prints
            printed = []
            import builtins

            orig = builtins.print

            def capture(*args, **kwargs):
                printed.append(" ".join(str(a) for a in args))
                orig(*args, **kwargs)

            builtins.print = capture
            try:
                run_scanned_scripts(cfg, [script], script_state=state)
            finally:
                builtins.print = orig
            dry_run_lines = [l for l in printed if "dry-run" in l]
            assert len(dry_run_lines) == 1

    def test_run_once_skipped_after_first_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            script = _write_toml_script(
                scripts_dir, "once.sh", 'run_when = "once"'
            )
            cfg = _make_cfg(tmp)
            state = self._make_state(tmp)
            state.record("once.sh", "anything")

            printed = []
            import builtins

            orig = builtins.print

            def capture(*args, **kwargs):
                printed.append(" ".join(str(a) for a in args))

            builtins.print = capture
            try:
                run_scanned_scripts(cfg, [script], script_state=state)
            finally:
                builtins.print = orig

            assert any("skip/once" in l for l in printed)
            assert not any("dry-run" in l for l in printed)

    def test_run_once_runs_when_not_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            script = _write_toml_script(
                scripts_dir, "once.sh", 'run_when = "once"'
            )
            cfg = _make_cfg(tmp)
            state = self._make_state(tmp)
            # No prior recording

            printed = []
            import builtins

            orig = builtins.print

            def capture(*args, **kwargs):
                printed.append(" ".join(str(a) for a in args))

            builtins.print = capture
            try:
                run_scanned_scripts(cfg, [script], script_state=state)
            finally:
                builtins.print = orig

            assert any("dry-run" in l for l in printed)

    def test_force_scripts_overrides_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            script = _write_toml_script(
                scripts_dir, "once.sh", 'run_when = "once"'
            )
            cfg = _make_cfg(tmp)
            state = self._make_state(tmp)
            state.record("once.sh", "anything")

            printed = []
            import builtins

            orig = builtins.print

            def capture(*args, **kwargs):
                printed.append(" ".join(str(a) for a in args))

            builtins.print = capture
            try:
                run_scanned_scripts(
                    cfg, [script], script_state=state, force_scripts=["once.sh"]
                )
            finally:
                builtins.print = orig

            # Should be forced to run (dry-run)
            assert any("dry-run" in l for l in printed)

    def test_run_onchange_skipped_when_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            body = "#!/bin/sh\necho hi\n"
            toml_meta = 'run_when = "onchange"'
            script = _write_toml_script(scripts_dir, "onchange.sh", toml_meta, body)
            cfg = _make_cfg(tmp)
            state = self._make_state(tmp)
            # Record the preprocessed content (same as what run_scanned_scripts uses)
            from pyishlib.file_preprocessor import FilePreprocessor
            pp = FilePreprocessor()
            preprocessed, _ = pp.preprocess_file(script)
            state.record("onchange.sh", preprocessed)

            printed = []
            import builtins

            orig = builtins.print

            def capture(*args, **kwargs):
                printed.append(" ".join(str(a) for a in args))

            builtins.print = capture
            try:
                run_scanned_scripts(cfg, [script], script_state=state)
            finally:
                builtins.print = orig

            assert any("skip/unchanged" in l for l in printed)


class TestScanScriptsTagFilter(unittest.TestCase):
    """scan_scripts respects tags from __ISH__ metadata."""

    def test_script_without_tags_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            _write_toml_script(scripts_dir, "no_tags.sh", "")
            cfg = _make_cfg(tmp, data_template={})
            kept, _ = scan_scripts(cfg)
            assert any(p.name == "no_tags.sh" for p in kept)

    def test_script_with_matching_bool_tag_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            _write_toml_script(
                scripts_dir, "work.sh", 'tags = ["isWork"]'
            )
            cfg = _make_cfg(tmp, data_template={"isWork": {"type": "bool"}})
            cfg.context.set("isWork", "true")
            kept, _ = scan_scripts(cfg)
            assert any(p.name == "work.sh" for p in kept)

    def test_script_with_non_matching_bool_tag_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = Path(tmp) / "ishscripts"
            _write_toml_script(
                scripts_dir, "work.sh", 'tags = ["isWork"]'
            )
            cfg = _make_cfg(tmp, data_template={"isWork": {"type": "bool"}})
            cfg.context.set("isWork", "false")
            kept, _ = scan_scripts(cfg)
            assert not any(p.name == "work.sh" for p in kept)


if __name__ == "__main__":
    unittest.main()
