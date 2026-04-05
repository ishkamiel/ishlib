# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024-2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import pytest

from pyishlib.ish_metadata import (
    HAS_TOML,
    _extract_embedded,
    _strip_comment_prefix,
    read_metadata,
    scan_directory,
    _cli_main,
)


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestExtractEmbeddedShell(unittest.TestCase):
    """Test extraction of __ISH__ metadata from shell heredoc blocks."""

    def test_basic_heredoc(self):
        text = """\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "backup"
tags = ["backup", "files"]
__ISH__

echo "doing stuff"
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "backup"' in raw

    def test_heredoc_double_quotes(self):
        text = """\
: <<"__ISH__"
[script]
name = "test"
__ISH__
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "test"' in raw

    def test_heredoc_no_quotes(self):
        text = """\
: <<__ISH__
[script]
name = "noquote"
__ISH__
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "noquote"' in raw

    def test_heredoc_with_indentation(self):
        text = """\
#!/usr/bin/env bash
  : <<'__ISH__'
[script]
name = "indented"
__ISH__
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "indented"' in raw


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestExtractEmbeddedPython(unittest.TestCase):
    """Test extraction of __ISH__ metadata from Python assignments."""

    def test_triple_double_quotes(self):
        text = '''\
#!/usr/bin/env python3
__ish__ = """
[script]
name = "process-data"
tags = ["etl", "nightly"]
"""

def main(): ...
'''
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "process-data"' in raw

    def test_triple_single_quotes(self):
        text = """\
__ish__ = '''
[script]
name = "single-quotes"
'''
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "single-quotes"' in raw


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestExtractEmbeddedPowerShell(unittest.TestCase):
    """Test extraction of __ISH__ metadata from PowerShell block comments."""

    def test_powershell_block(self):
        text = """\
<#__ISH__
[script]
name = "deploy"
tags = ["deploy", "prod"]
__ISH__#>

Write-Host "deploying..."
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "deploy"' in raw


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestExtractEmbeddedComment(unittest.TestCase):
    """Test extraction of __ISH__ metadata from comment-prefixed blocks."""

    def test_hash_prefix(self):
        text = """\
# __ISH__
# [script]
# name = "app-config"
# tags = ["config"]
# __ISH__

server:
  port: 8080
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "app-config"' in raw

    def test_double_slash_prefix(self):
        text = """\
// __ISH__
// [script]
// name = "js-app"
// __ISH__

const x = 1;
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "js-app"' in raw

    def test_double_dash_prefix(self):
        text = """\
-- __ISH__
-- [script]
-- name = "sql-migration"
-- __ISH__

SELECT 1;
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "sql-migration"' in raw

    def test_semicolon_prefix(self):
        text = """\
; __ISH__
; [script]
; name = "ini-config"
; __ISH__

[section]
key = value
"""
        raw = _extract_embedded(text)
        assert raw is not None
        assert 'name = "ini-config"' in raw


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestStripCommentPrefix(unittest.TestCase):
    """Test the comment prefix stripping helper."""

    def test_strip_hash(self):
        body = '# [script]\n# name = "test"\n'
        result = _strip_comment_prefix(body, "#")
        assert result == '[script]\nname = "test"\n'

    def test_strip_double_slash(self):
        body = '// [script]\n// name = "test"\n'
        result = _strip_comment_prefix(body, "//")
        assert result == '[script]\nname = "test"\n'

    def test_preserves_empty_lines(self):
        body = "# [a]\n\n# key = 1\n"
        result = _strip_comment_prefix(body, "#")
        assert result == "[a]\n\nkey = 1\n"


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestExtractNoMetadata(unittest.TestCase):
    """Test that files without metadata return None."""

    def test_no_sentinel(self):
        text = """\
#!/usr/bin/env bash
echo "no metadata here"
"""
        assert _extract_embedded(text) is None

    def test_empty_file(self):
        assert _extract_embedded("") is None


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestReadMetadata(unittest.TestCase):
    """Test the read_metadata function with real temp files."""

    def test_read_shell_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("""\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "test-script"
schedule = "daily"
__ISH__

echo "hello"
""")
            f.flush()
            try:
                meta = read_metadata(f.name)
                assert meta is not None
                assert meta["script"]["name"] == "test-script"
                assert meta["script"]["schedule"] == "daily"
            finally:
                os.unlink(f.name)

    def test_read_python_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('''\
__ish__ = """
[script]
name = "py-tool"
tags = ["etl"]
"""
''')
            f.flush()
            try:
                meta = read_metadata(f.name)
                assert meta is not None
                assert meta["script"]["name"] == "py-tool"
                assert meta["script"]["tags"] == ["etl"]
            finally:
                os.unlink(f.name)

    def test_read_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_file = Path(tmpdir) / "binary.dat"
            sidecar_file = Path(tmpdir) / "binary.dat.ish"
            main_file.write_bytes(b"\x00\x01\x02\x03")
            sidecar_file.write_text(
                '[script]\nname = "binary-tool"\n', encoding="utf-8"
            )
            meta = read_metadata(main_file)
            assert meta is not None
            assert meta["script"]["name"] == "binary-tool"

    def test_read_no_metadata(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("just some text\n")
            f.flush()
            try:
                meta = read_metadata(f.name)
                assert meta is None
            finally:
                os.unlink(f.name)

    def test_embedded_takes_priority_over_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            main_file = Path(tmpdir) / "script.sh"
            sidecar_file = Path(tmpdir) / "script.sh.ish"
            main_file.write_text(
                """\
: <<'__ISH__'
[script]
name = "embedded"
__ISH__
""",
                encoding="utf-8",
            )
            sidecar_file.write_text('[script]\nname = "sidecar"\n', encoding="utf-8")
            meta = read_metadata(main_file)
            assert meta is not None
            assert meta["script"]["name"] == "embedded"

    def test_invalid_toml_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("""\
: <<'__ISH__'
this is [not valid toml
__ISH__
""")
            f.flush()
            try:
                with self.assertRaises(Exception):
                    read_metadata(f.name)
            finally:
                os.unlink(f.name)


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestScanDirectory(unittest.TestCase):
    """Test the scan_directory function."""

    def test_scan_finds_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with metadata
            sh_file = Path(tmpdir) / "a.sh"
            sh_file.write_text(
                """\
: <<'__ISH__'
[script]
name = "shell-script"
__ISH__
""",
                encoding="utf-8",
            )

            py_file = Path(tmpdir) / "b.py"
            py_file.write_text(
                '''\
__ish__ = """
[script]
name = "python-script"
"""
''',
                encoding="utf-8",
            )

            # Create file without metadata
            txt_file = Path(tmpdir) / "c.txt"
            txt_file.write_text("no metadata\n", encoding="utf-8")

            results = list(scan_directory(tmpdir))
            assert len(results) == 2
            names = {m["script"]["name"] for _, m in results}
            assert names == {"shell-script", "python-script"}

    def test_scan_with_extension_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sh_file = Path(tmpdir) / "a.sh"
            sh_file.write_text(
                ": <<'__ISH__'\n[script]\nname = \"sh\"\n__ISH__\n",
                encoding="utf-8",
            )
            py_file = Path(tmpdir) / "b.py"
            py_file.write_text(
                '__ish__ = """\n[script]\nname = "py"\n"""\n',
                encoding="utf-8",
            )

            results = list(scan_directory(tmpdir, extensions={".sh"}))
            assert len(results) == 1
            assert results[0][1]["script"]["name"] == "sh"

    def test_scan_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "sub"
            subdir.mkdir()
            sh_file = subdir / "nested.sh"
            sh_file.write_text(
                ": <<'__ISH__'\n[script]\nname = \"nested\"\n__ISH__\n",
                encoding="utf-8",
            )

            results = list(scan_directory(tmpdir, recursive=True))
            assert len(results) == 1
            assert results[0][1]["script"]["name"] == "nested"

    def test_scan_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / "sub"
            subdir.mkdir()
            sh_file = subdir / "nested.sh"
            sh_file.write_text(
                ": <<'__ISH__'\n[script]\nname = \"nested\"\n__ISH__\n",
                encoding="utf-8",
            )

            results = list(scan_directory(tmpdir, recursive=False))
            assert len(results) == 0


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestCliMain(unittest.TestCase):
    """Test the CLI entry point."""

    def test_cli_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("""\
: <<'__ISH__'
[script]
name = "cli-test"
__ISH__
""")
            f.flush()
            try:
                ret = _cli_main(["read", f.name])
                assert ret == 0
            finally:
                os.unlink(f.name)

    def test_cli_read_no_metadata(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("no metadata\n")
            f.flush()
            try:
                ret = _cli_main(["read", f.name])
                assert ret == 1
            finally:
                os.unlink(f.name)

    def test_cli_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sh_file = Path(tmpdir) / "a.sh"
            sh_file.write_text(
                ": <<'__ISH__'\n[script]\nname = \"scan-test\"\n__ISH__\n",
                encoding="utf-8",
            )
            ret = _cli_main(["scan", tmpdir])
            assert ret == 0

    def test_cli_scan_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ret = _cli_main(["scan", tmpdir])
            assert ret == 1


if __name__ == "__main__":
    unittest.main()
