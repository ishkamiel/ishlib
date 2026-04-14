#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for the mergejson_ branch in the ishfiles diff command.

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.dotfile_applier import DotfileApplier
from pyishlib.ishfiles.commands.diff import _show_diff


def _make_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestShowDiffMergejson:
    def test_show_diff_reordered_target_prints_nothing(self, capsys):
        """Reordered-only target: change_type is None, _show_diff emits nothing."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"a": 1, "b": 2}\n',
            )
            _make_file(
                Path(tgt) / "settings.json",
                '{\n  "b": 2,\n  "a": 1\n}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.prepare(applier.discover())
            assert len(dotfiles) == 1

            # The change_type is None here, and our diff command only calls
            # _show_diff for entries returned by get_changes().  Exercising
            # it directly still must not raise and must produce no output.
            _show_diff(dotfiles[0])
            captured = capsys.readouterr()
            assert captured.out == ""

    def test_show_diff_real_change_emits_output(self, capsys):
        """A real semantic difference produces a non-empty diff.

        The ``---`` header must reference the real target path rather
        than the temporary canonical-form file we create internally, so
        users see a meaningful diff.
        """
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"a": 2}\n',
            )
            target = _make_file(
                Path(tgt) / "settings.json",
                '{"a": 1}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.prepare(applier.discover())
            changes = applier.get_changes(dotfiles)
            assert len(changes) == 1

            _show_diff(changes[0])
            captured = capsys.readouterr()
            assert captured.out != ""
            # The real target path should appear in the diff header,
            # not a /tmp/... path from our canonical-form temp file.
            assert str(target) in captured.out

    def test_show_diff_new_file(self, capsys):
        """A new mergejson target emits a new-file diff."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "mergejson_settings.json",
                '{"a": 1}\n',
            )

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.prepare(applier.discover())
            changes = applier.get_changes(dotfiles)
            assert len(changes) == 1

            _show_diff(changes[0])
            captured = capsys.readouterr()
            assert captured.out != ""
