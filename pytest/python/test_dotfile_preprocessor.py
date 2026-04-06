#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

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
from pyishlib.ish_metadata import HAS_TOML, remove_metadata_blocks
from pyishlib.dotfile import DotFile
from pyishlib.dotfile_context import DotfileContext
from pyishlib.dotfile_preprocessor import (
    DotFilePreprocessor,
    _RE_DIRECTIVE,
    _RE_VAR_REF,
    _parse_set_directive,
    _substitute_variables,
)
from pyishlib.dotfile_applier import DotfileApplier
from pyishlib.ish_config import IshConfig

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


def _preprocess(content, variables=None):
    """Shorthand: create a DotFile and preprocess it."""
    df, _ = _make_dotfile(content)
    pp = DotFilePreprocessor(variables=variables)
    return pp.preprocess(df), df


# ---------------------------------------------------------------------------
# DotfileContext
# ---------------------------------------------------------------------------


class TestDotfileContext:

    def test_dict_style_access(self):
        ctx = DotfileContext({"foo": "bar"})
        assert ctx["foo"] == "bar"

    def test_dict_style_set(self):
        ctx = DotfileContext()
        ctx["key"] = "val"
        assert ctx["key"] == "val"

    def test_contains(self):
        ctx = DotfileContext({"x": "1"})
        assert "x" in ctx
        assert "y" not in ctx

    def test_attr_access(self):
        ctx = DotfileContext({"hostname": "mybox"})
        assert ctx.hostname == "mybox"

    def test_attr_access_missing_returns_empty(self):
        ctx = DotfileContext()
        assert ctx.missing == ""

    def test_attr_set(self):
        ctx = DotfileContext()
        ctx.editor = "vim"
        assert ctx["editor"] == "vim"

    def test_get_default(self):
        ctx = DotfileContext()
        assert ctx.get("missing", "fallback") == "fallback"

    def test_update(self):
        ctx = DotfileContext({"a": "1"})
        ctx.update({"b": 2, "c": True})
        assert ctx["b"] == "2"
        assert ctx["c"] == "True"

    def test_update_defaults(self):
        ctx = DotfileContext({"a": "1"})
        ctx.update_defaults({"a": "overridden", "b": "2"})
        assert ctx["a"] == "1"  # not overridden
        assert ctx["b"] == "2"

    def test_as_dict(self):
        ctx = DotfileContext({"x": "1"})
        d = ctx.as_dict()
        assert d == {"x": "1"}
        assert isinstance(d, dict)

    def test_repr(self):
        ctx = DotfileContext({"a": "1"})
        assert "DotfileContext" in repr(ctx)
        assert "'a'" in repr(ctx)


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
        assert _RE_DIRECTIVE.match("#@ish") is None

    def test_if_directive(self):
        m = _RE_DIRECTIVE.match("#@ish if ish.hostname == 'mybox'")
        assert m is not None
        assert m.group("command") == "if ish.hostname == 'mybox'"

    def test_fi_directive(self):
        m = _RE_DIRECTIVE.match("#@ish fi")
        assert m is not None
        assert m.group("command") == "fi"


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
        matches = list(
            _RE_VAR_REF.finditer("export HOST=${__ish_host} PORT=${__ish_port}")
        )
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
# Metadata block removal (now in ish_metadata)
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
        result = remove_metadata_blocks(text)
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
        result = remove_metadata_blocks(text)
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
        result = remove_metadata_blocks(text)
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
        result = remove_metadata_blocks(text)
        assert "__ish__" not in result
        assert "def main():" in result

    def test_no_metadata(self):
        text = "just a plain file\n"
        assert remove_metadata_blocks(text) == text


# ---------------------------------------------------------------------------
# Full preprocessing (requires TOML support)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestPreprocess:

    def test_strip_metadata_from_output(self):
        result, _ = _preprocess("""\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "mybash"
__ISH__

echo "hello"
""")
        assert "__ISH__" not in result
        assert 'echo "hello"' in result

    def test_metadata_stored_on_dotfile(self):
        _, df = _preprocess("""\
#!/usr/bin/env bash
: <<'__ISH__'
[script]
name = "mybash"
__ISH__

echo "hello"
""")
        assert df.metadata is not None
        assert df.metadata["script"]["name"] == "mybash"

    def test_set_directive_and_substitution(self):
        result, _ = _preprocess("""\
#!/usr/bin/env bash
#@ish set hostname=mybox
export HOSTNAME=${__ish_hostname}
""")
        assert "#@ish" not in result
        assert "export HOSTNAME=mybox" in result

    def test_passed_variables(self):
        result, _ = _preprocess(
            "export EDITOR=${__ish_editor}\n",
            variables={"editor": "vim"},
        )
        assert "export EDITOR=vim" in result

    def test_metadata_vars_section(self):
        result, _ = _preprocess("""\
#!/usr/bin/env bash
: <<'__ISH__'
[vars]
theme = "dark"
__ISH__

THEME=${__ish_theme}
""")
        assert "THEME=dark" in result
        assert "__ISH__" not in result

    def test_directive_overrides_metadata_vars(self):
        result, _ = _preprocess("""\
#!/usr/bin/env bash
: <<'__ISH__'
[vars]
theme = "dark"
__ISH__

#@ish set theme=light
THEME=${__ish_theme}
""")
        assert "THEME=light" in result

    def test_passed_vars_override_metadata_vars(self):
        result, _ = _preprocess(
            """\
#!/usr/bin/env bash
: <<'__ISH__'
[vars]
theme = "dark"
__ISH__

THEME=${__ish_theme}
""",
            variables={"theme": "solarized"},
        )
        assert "THEME=solarized" in result

    def test_directive_overrides_passed_vars(self):
        result, _ = _preprocess(
            """\
#@ish set editor=emacs
EDITOR=${__ish_editor}
""",
            variables={"editor": "vim"},
        )
        assert "EDITOR=emacs" in result

    def test_undefined_var_left_intact(self):
        result, _ = _preprocess("VAL=${__ish_undefined}\n")
        assert "VAL=${__ish_undefined}" in result

    def test_multiple_directives(self):
        result, _ = _preprocess("""\
#@ish set user=alice
#@ish set host=srv
CONN=${__ish_user}@${__ish_host}
""")
        assert "CONN=alice@srv" in result
        assert "#@ish" not in result

    def test_slash_comment_directive(self):
        result, _ = _preprocess("""\
//@ish set port=8080
const PORT = "${__ish_port}";
""")
        assert "//@ish" not in result
        assert 'const PORT = "8080";' in result

    def test_dash_comment_directive(self):
        result, _ = _preprocess("""\
--@ish set schema=public
SELECT * FROM ${__ish_schema}.users;
""")
        assert "--@ish" not in result
        assert "SELECT * FROM public.users;" in result

    def test_no_directives_no_vars_passthrough(self):
        original = "#!/usr/bin/env bash\necho hello\n"
        result, _ = _preprocess(original)
        assert result == original

    def test_preserves_non_directive_comments(self):
        result, _ = _preprocess("""\
#!/usr/bin/env bash
# This is a regular comment
#@ish set foo=bar
# Another regular comment
echo ${__ish_foo}
""")
        assert "# This is a regular comment" in result
        assert "# Another regular comment" in result
        assert "#@ish" not in result
        assert "echo bar" in result


# ---------------------------------------------------------------------------
# Conditional directives (if / elif / else / fi)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not HAS_TOML,
    reason="toml support not available (needs Python 3.11+ or tomli)",
)
class TestConditionals:

    def test_if_true(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'linux'
echo linux
#@ish fi
""",
            variables={"platform": "linux"},
        )
        assert "echo linux" in result
        assert "#@ish" not in result

    def test_if_false(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
echo mac
#@ish fi
""",
            variables={"platform": "linux"},
        )
        assert "echo mac" not in result

    def test_if_else(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
echo mac
#@ish else
echo other
#@ish fi
""",
            variables={"platform": "linux"},
        )
        assert "echo mac" not in result
        assert "echo other" in result

    def test_if_elif_else(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
echo mac
#@ish elif ish.platform == 'linux'
echo linux
#@ish else
echo other
#@ish fi
""",
            variables={"platform": "linux"},
        )
        assert "echo mac" not in result
        assert "echo linux" in result
        assert "echo other" not in result

    def test_elif_first_true(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
echo mac
#@ish elif ish.platform == 'linux'
echo linux
#@ish fi
""",
            variables={"platform": "darwin"},
        )
        assert "echo mac" in result
        assert "echo linux" not in result

    def test_elif_no_match_falls_to_else(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
echo mac
#@ish elif ish.platform == 'linux'
echo linux
#@ish else
echo unknown
#@ish fi
""",
            variables={"platform": "windows"},
        )
        assert "echo mac" not in result
        assert "echo linux" not in result
        assert "echo unknown" in result

    def test_nested_if(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'linux'
#@ish if ish.desktop == 'gnome'
echo gnome linux
#@ish fi
#@ish fi
""",
            variables={"platform": "linux", "desktop": "gnome"},
        )
        assert "echo gnome linux" in result

    def test_nested_if_outer_false(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
#@ish if ish.desktop == 'gnome'
echo gnome mac
#@ish fi
#@ish fi
""",
            variables={"platform": "linux", "desktop": "gnome"},
        )
        assert "echo gnome mac" not in result

    def test_missing_var_in_expression(self):
        # Missing var returns "" which is falsy
        result, _ = _preprocess("""\
#@ish if ish.nonexistent
echo should not appear
#@ish fi
echo always
""")
        assert "echo should not appear" not in result
        assert "echo always" in result

    def test_truthiness_of_nonempty_string(self):
        result, _ = _preprocess(
            """\
#@ish if ish.editor
echo has editor
#@ish fi
""",
            variables={"editor": "vim"},
        )
        assert "echo has editor" in result

    def test_complex_expression(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'linux' and ish.shell == 'zsh'
echo linux zsh
#@ish fi
""",
            variables={"platform": "linux", "shell": "zsh"},
        )
        assert "echo linux zsh" in result

    def test_set_inside_true_branch(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'linux'
#@ish set pkg_mgr=apt
#@ish fi
PKG=${__ish_pkg_mgr}
""",
            variables={"platform": "linux"},
        )
        assert "PKG=apt" in result

    def test_set_inside_false_branch_ignored(self):
        result, _ = _preprocess(
            """\
#@ish if ish.platform == 'darwin'
#@ish set pkg_mgr=brew
#@ish fi
PKG=${__ish_pkg_mgr}
""",
            variables={"platform": "linux"},
        )
        # pkg_mgr never set, so reference left intact
        assert "PKG=${__ish_pkg_mgr}" in result

    def test_slash_comment_conditionals(self):
        result, _ = _preprocess(
            """\
//@ish if ish.env == 'prod'
const DEBUG = false;
//@ish else
const DEBUG = true;
//@ish fi
""",
            variables={"env": "dev"},
        )
        assert "const DEBUG = true;" in result
        assert "const DEBUG = false;" not in result

    def test_surrounding_lines_preserved(self):
        result, _ = _preprocess(
            """\
before
#@ish if ish.x == 'y'
inside
#@ish fi
after
""",
            variables={"x": "n"},
        )
        assert "before" in result
        assert "inside" not in result
        assert "after" in result

    def test_invalid_expression_treated_as_false(self):
        result, _ = _preprocess("""\
#@ish if this is not valid python !!!
echo should not appear
#@ish fi
echo always
""")
        assert "echo should not appear" not in result
        assert "echo always" in result


# ---------------------------------------------------------------------------
# Preprocessor state sharing across files
# ---------------------------------------------------------------------------


class TestPreprocessorState:

    def test_context_shared_across_files(self):
        """Variables set in one file are visible in the next."""
        pp = DotFilePreprocessor()

        tmpdir = tempfile.mkdtemp()
        src = Path(tmpdir) / "src"
        tgt = Path(tmpdir) / "tgt"
        src.mkdir()
        tgt.mkdir()

        f1 = src / "dot_first"
        f1.write_text("#@ish set shared_var=hello\nFIRST\n", encoding="utf-8")
        df1 = DotFile(f1, Path("dot_first"), tgt)

        f2 = src / "dot_second"
        f2.write_text("VAL=${__ish_shared_var}\n", encoding="utf-8")
        df2 = DotFile(f2, Path("dot_second"), tgt)

        pp.preprocess(df1)
        result = pp.preprocess(df2)
        assert "VAL=hello" in result

    def test_context_property(self):
        pp = DotFilePreprocessor(variables={"x": "1"})
        assert isinstance(pp.context, DotfileContext)
        assert pp.context["x"] == "1"


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
            cfg = IshConfig()
            cfg.context.set("editor", "vim")
            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=cfg,
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

    def test_prepare_conditionals(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_bashrc",
                """\
#@ish if ish.platform == 'linux'
export BROWSER=firefox
#@ish else
export BROWSER=safari
#@ish fi
""",
            )
            cfg = IshConfig()
            cfg.context.set("platform", "linux")
            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=cfg,
            )
            dotfiles = applier.discover()
            dotfiles = applier.prepare(dotfiles)

            staged_content = dotfiles[0].staged.read_text()
            assert "export BROWSER=firefox" in staged_content
            assert "export BROWSER=safari" not in staged_content


if __name__ == "__main__":
    pytest.main()
