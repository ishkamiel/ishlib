# -*- coding: utf-8 -*-
#
# Tests for dotfile preprocessing directives and variable substitution

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.ish_metadata import HAS_TOML
from pyishlib.dotfile import DotFile
from pyishlib.dotfile_preprocessor import (
    _RE_DIRECTIVE,
    _RE_VAR_REF,
    _parse_set_directive,
    _remove_metadata_blocks,
    _substitute_variables,
    preprocess,
)
from pyishlib.dotfile_applier import DotfileApplier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_dotfile(content: str) -> tuple:
    """Create a temp DotFile with the given content.  Returns (DotFile, tmpdir)."""
    tmpdir = tempfile.mkdtemp()
    src_dir = Path(tmpdir) / "src"
    tgt_dir = Path(tmpdir) / "tgt"
    src_dir.mkdir()
    tgt_dir.mkdir()
    src_file = src_dir / "dot_bashrc"
    src_file.write_text(content, encoding="utf-8")
    df = DotFile(src_file, Path("dot_bashrc"), tgt_dir)
    return df, tmpdir


# ---------------------------------------------------------------------------
# Regex pattern tests
# ---------------------------------------------------------------------------


class TestDirectivePattern:

    def test_hash_directive(self):
        m = _RE_DIRECTIVE.match("#@ish set foo=bar")
        assert m is not None
        assert m.group("prefix") == "#"
        assert m.group("command") == "set foo=bar"

    def test_double_slash_directive(self):
        m = _RE_DIRECTIVE.match("//@ish set foo=bar")
        assert m is not None
        assert m.group("prefix") == "//"
        assert m.group("command") == "set foo=bar"

    def test_double_dash_directive(self):
        m = _RE_DIRECTIVE.match("--@ish set foo=bar")
        assert m is not None
        assert m.group("prefix") == "--"
        assert m.group("command") == "set foo=bar"

    def test_semicolon_directive(self):
        m = _RE_DIRECTIVE.match(";@ish set foo=bar")
        assert m is not None
        assert m.group("prefix") == ";"

    def test_percent_directive(self):
        m = _RE_DIRECTIVE.match("%@ish set foo=bar")
        assert m is not None
        assert m.group("prefix") == "%"

    def test_indented_directive(self):
        m = _RE_DIRECTIVE.match("  #@ish set foo=bar")
        assert m is not None
        assert m.group("indent") == "  "
        assert m.group("command") == "set foo=bar"

    def test_not_a_directive(self):
        assert _RE_DIRECTIVE.match("# regular comment") is None
        assert _RE_DIRECTIVE.match("echo hello") is None
        assert _RE_DIRECTIVE.match("#@ ish set foo=bar") is None

    def test_no_space_before_command(self):
        # At least one space required after @ish
        assert _RE_DIRECTIVE.match("#@ish") is None


class TestVarRefPattern:

    def test_simple_var(self):
        m = _RE_VAR_REF.search("${__ish_hostname}")
        assert m is not None
        assert m.group("name") == "hostname"

    def test_underscore_var(self):
        m = _RE_VAR_REF.search("${__ish_my_var_1}")
        assert m is not None
        assert m.group("name") == "my_var_1"

    def test_in_context(self):
        matches = list(_RE_VAR_REF.finditer("export HOST=${__ish_host} PORT=${__ish_port}"))
        assert len(matches) == 2
        assert matches[0].group("name") == "host"
        assert matches[1].group("name") == "port"

    def test_not_a_var(self):
        assert _RE_VAR_REF.search("${HOME}") is None
        assert _RE_VAR_REF.search("${__ish}") is None
        assert _RE_VAR_REF.search("$__ish_foo") is None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestParseSetDirective:

    def test_basic(self):
        result = _parse_set_directive("set foo=bar")
        assert result == ("foo", "bar")

    def test_spaces_around_equals(self):
        result = _parse_set_directive("set foo = bar")
        assert result == ("foo", "bar")

    def test_value_with_spaces(self):
        result = _parse_set_directive("set greeting=hello world")
        assert result == ("greeting", "hello world")

    def test_underscore_name(self):
        result = _parse_set_directive("set my_var_2=value")
        assert result == ("my_var_2", "value")

    def test_not_set(self):
        assert _parse_set_directive("get foo") is None

    def test_invalid_name(self):
        assert _parse_set_directive("set 2bad=value") is None


class TestSubstituteVariables:

    def test_single_replacement(self):
        text = "host=${__ish_hostname}"
        result = _substitute_variables(text, {"hostname": "mybox"})
        assert result == "host=mybox"

    def test_multiple_replacements(self):
        text = "${__ish_user}@${__ish_host}"
        result = _substitute_variables(text, {"user": "alice", "host": "srv"})
        assert result == "alice@srv"

    def test_undefined_left_intact(self):
        text = "val=${__ish_missing}"
        result = _substitute_variables(text, {})
        assert result == "val=${__ish_missing}"

    def test_no_vars(self):
        text = "no variables here"
        result = _substitute_variables(text, {"foo": "bar"})
        assert result == "no variables here"


# ---------------------------------------------------------------------------
# Metadata block removal
# ---------------------------------------------------------------------------


class TestRemoveMetadataBlocks:

    def test_remove_shell_heredoc(self):
        text = """\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "test"
__ISH__

echo "hello"
"""
        result = _remove_metadata_blocks(text)
        assert "__ISH__" not in result
        assert 'echo "hello"' in result
        assert "#!/usr/bin/env bash" in result

    def test_remove_comment_block(self):
        text = """\
# __ISH__
# [script]
# name = "test"
# __ISH__

server:
  port: 8080
"""
        result = _remove_metadata_blocks(text)
        assert "__ISH__" not in result
        assert "server:" in result

    def test_remove_double_slash_comment_block(self):
        text = """\
// __ISH__
// [script]
// name = "test"
// __ISH__

const x = 1;
"""
        result = _remove_metadata_blocks(text)
        assert "__ISH__" not in result
        assert "const x = 1;" in result

    def test_remove_python_assign(self):
        text = '''\
__ish__ = """
[script]
name = "test"
"""

def main():
    pass
'''
        result = _remove_metadata_blocks(text)
        assert "__ish__" not in result
        assert "def main():" in result

    def test_no_metadata(self):
        text = "just a plain file\n"
        assert _remove_metadata_blocks(text) == text


# ---------------------------------------------------------------------------
# Full preprocessing (requires TOML support)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestPreprocess:

    def test_strip_metadata_from_output(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "mybash"
__ISH__

echo "hello"
""")
        result = preprocess(df)
        assert "__ISH__" not in result
        assert 'echo "hello"' in result

    def test_metadata_stored_on_dotfile(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "mybash"
__ISH__

echo "hello"
""")
        preprocess(df)
        assert df.metadata is not None
        assert df.metadata["script"]["name"] == "mybash"

    def test_set_directive_and_substitution(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
#@ish set hostname=mybox
export HOSTNAME=${__ish_hostname}
""")
        result = preprocess(df)
        assert "#@ish" not in result
        assert "export HOSTNAME=mybox" in result

    def test_passed_variables(self):
        df, _ = _make_dotfile("""\
export EDITOR=${__ish_editor}
""")
        result = preprocess(df, variables={"editor": "vim"})
        assert "export EDITOR=vim" in result

    def test_metadata_vars_section(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
: <<'__ISH__'
[vars]
theme = "dark"
__ISH__

THEME=${__ish_theme}
""")
        result = preprocess(df)
        assert "THEME=dark" in result
        assert "__ISH__" not in result

    def test_directive_overrides_metadata_vars(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
: <<'__ISH__'
[vars]
theme = "dark"
__ISH__

#@ish set theme=light
THEME=${__ish_theme}
""")
        result = preprocess(df)
        assert "THEME=light" in result

    def test_passed_vars_override_metadata_vars(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
: <<'__ISH__'
[vars]
theme = "dark"
__ISH__

THEME=${__ish_theme}
""")
        result = preprocess(df, variables={"theme": "solarized"})
        assert "THEME=solarized" in result

    def test_directive_overrides_passed_vars(self):
        df, _ = _make_dotfile("""\
#@ish set editor=emacs
EDITOR=${__ish_editor}
""")
        result = preprocess(df, variables={"editor": "vim"})
        assert "EDITOR=emacs" in result

    def test_undefined_var_left_intact(self):
        df, _ = _make_dotfile("""\
VAL=${__ish_undefined}
""")
        result = preprocess(df)
        assert "VAL=${__ish_undefined}" in result

    def test_multiple_directives(self):
        df, _ = _make_dotfile("""\
#@ish set user=alice
#@ish set host=srv
CONN=${__ish_user}@${__ish_host}
""")
        result = preprocess(df)
        assert "CONN=alice@srv" in result
        assert "#@ish" not in result

    def test_slash_comment_directive(self):
        df, _ = _make_dotfile("""\
//@ish set port=8080
const PORT = "${__ish_port}";
""")
        result = preprocess(df)
        assert '//@ish' not in result
        assert 'const PORT = "8080";' in result

    def test_dash_comment_directive(self):
        df, _ = _make_dotfile("""\
--@ish set schema=public
SELECT * FROM ${__ish_schema}.users;
""")
        result = preprocess(df)
        assert "--@ish" not in result
        assert "SELECT * FROM public.users;" in result

    def test_no_directives_no_vars_passthrough(self):
        original = "#!/usr/bin/env bash\necho hello\n"
        df, _ = _make_dotfile(original)
        result = preprocess(df)
        assert result == original

    def test_preserves_non_directive_comments(self):
        df, _ = _make_dotfile("""\
#!/usr/bin/env bash
# This is a regular comment
#@ish set foo=bar
# Another regular comment
echo ${__ish_foo}
""")
        result = preprocess(df)
        assert "# This is a regular comment" in result
        assert "# Another regular comment" in result
        assert "#@ish" not in result
        assert "echo bar" in result


# ---------------------------------------------------------------------------
# Integration: DotfileApplier.prepare() with preprocessing
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestApplierPreprocessIntegration:

    def test_prepare_strips_metadata(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                """\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "mybash"
__ISH__

echo "hello"
""",
            )
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            staged_content = dotfiles[0].staged.read_text()
            assert "__ISH__" not in staged_content
            assert 'echo "hello"' in staged_content

    def test_prepare_stores_metadata(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                """\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "mybash"
__ISH__

echo "hello"
""",
            )
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            assert dotfiles[0].metadata is not None
            assert dotfiles[0].metadata["script"]["name"] == "mybash"

    def test_prepare_substitutes_variables(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                """\
#@ish set hostname=mybox
export HOST=${__ish_hostname}
""",
            )
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            staged_content = dotfiles[0].staged.read_text()
            assert "export HOST=mybox" in staged_content

    def test_prepare_with_constructor_variables(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                "export EDITOR=${__ish_editor}\n",
            )
            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                variables={"editor": "vim"},
            )
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            staged_content = dotfiles[0].staged.read_text()
            assert "export EDITOR=vim" in staged_content

    def test_prepare_binary_fallback(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            binary_file = Path(src) / "dot_binary"
            binary_file.write_bytes(b"\x00\x01\x02\xff\xfe")

            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            assert dotfiles[0].staged.read_bytes() == b"\x00\x01\x02\xff\xfe"

    def test_sidecar_ignored_during_discover(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(Path(src) / "dot_bashrc", "echo hello\n")
            _make_file(
                Path(src) / "dot_bashrc.ish",
                '[script]\nname = "sidecar"\n',
            )
            applier = DotfileApplier(source_dir=Path(src), target_dir=Path(tgt))
            dotfiles = applier.discover()

            names = [df.source.name for df in dotfiles]
            assert "dot_bashrc" in names
            assert "dot_bashrc.ish" not in names


if __name__ == "__main__":
    pytest.main()
