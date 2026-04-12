#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for the custom script-based installer backend

import os
import sys
import tempfile
import logging
from pathlib import Path

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.installer import Installer
from pyishlib.installer_custom import InstallerCustom
from pyishlib.command_runner import CommandRunner
from pyishlib.ish_config import IshConfig
from pyishlib.file_preprocessor import FilePreprocessor
from pyishlib.dotfile_script import DotfileScript


def make_runner(which_returns=None, cfg=None):
    """Create a CommandRunner with a mocked which method."""
    if cfg is None:
        cfg = IshConfig(dry_run=True)
    runner = CommandRunner(cfg=cfg)

    def mock_which(cmd):
        if which_returns is None:
            return None
        return which_returns.get(cmd, None)

    runner.which = mock_which
    return runner


def make_cfg(source=None, **kwargs):
    """Create an IshConfig with source set for InstallerCustom tests."""
    defaults = {}
    if source is not None:
        defaults["source"] = str(source)
    return IshConfig(dry_run=True, defaults=defaults, **kwargs)


# ---------------------------------------------------------------------------
# InstallerCustom unit tests
# ---------------------------------------------------------------------------


class TestInstallerCustom:
    def test_installer_name(self):
        custom = InstallerCustom(make_runner())
        assert custom.INSTALLER_NAME == "custom"

    def test_can_use_custom_no_dotfiles_dir(self):
        custom = InstallerCustom(make_runner())
        pkg = {"name": "test", "custom": "test"}
        assert custom.can_use_custom(pkg) is False

    def test_can_use_custom_no_custom_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "test", "apt": "test"}
            assert custom.can_use_custom(pkg) is False

    def test_can_use_custom_no_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "test", "custom": "nonexistent"}
            assert custom.can_use_custom(pkg) is False

    def test_can_use_custom_with_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool"
            script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "mytool", "custom": "mytool"}
            assert custom.can_use_custom(pkg) is True

    def test_can_use_custom_with_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool.sh"
            script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "mytool", "custom": "mytool"}
            assert custom.can_use_custom(pkg) is True

    def test_can_use_custom_no_pkg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            assert custom.can_use_custom() is True

    def test_can_use_custom_no_installers_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # No ishinstallers subdir created
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            assert custom.can_use_custom() is False

    def test_is_custom_pkg_installed_with_cmd(self):
        runner = make_runner({"mytool": "/usr/bin/mytool"})
        custom = InstallerCustom(runner)
        pkg = {"name": "mytool", "custom": "mytool", "cmd": "mytool"}
        assert custom.is_custom_pkg_installed(pkg) is True

    def test_is_custom_pkg_installed_no_cmd(self):
        custom = InstallerCustom(make_runner())
        pkg = {"name": "mytool", "custom": "mytool"}
        assert custom.is_custom_pkg_installed(pkg) is False

    def test_is_custom_pkg_installed_cmd_not_found(self):
        custom = InstallerCustom(make_runner({}))
        pkg = {"name": "mytool", "custom": "mytool", "cmd": "mytool"}
        assert custom.is_custom_pkg_installed(pkg) is False

    def test_namespace_has_required_methods(self):
        custom = InstallerCustom(make_runner())
        ns = custom.namespace
        assert hasattr(ns, "can_install")
        assert hasattr(ns, "install")
        assert hasattr(ns, "is_installed")
        assert hasattr(ns, "update")

    def test_find_script_exact_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool"
            script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            found = custom._find_script("mytool")
            assert found.resolve() == script.resolve()

    def test_find_script_with_extension(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool.sh"
            script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            found = custom._find_script("mytool")
            assert found.resolve() == script.resolve()

    def test_find_script_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            assert custom._find_script("nonexistent") is None

    def test_find_script_prefers_exact_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            exact = installers / "install_mytool"
            exact.write_text("#!/bin/sh\necho exact\n", encoding="utf-8")
            with_ext = installers / "install_mytool.sh"
            with_ext.write_text("#!/bin/sh\necho ext\n", encoding="utf-8")
            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            found = custom._find_script("mytool")
            assert found.resolve() == exact.resolve()

    def test_update_custom_pkgs_noop(self):
        custom = InstallerCustom(make_runner())
        assert custom.update_custom_pkgs() is True

    def test_install_unless_found_already_installed(self):
        runner = make_runner({"mytool": "/usr/bin/mytool"})
        custom = InstallerCustom(runner)
        pkg = {"name": "mytool", "custom": "mytool", "cmd": "mytool"}
        assert custom.install_custom_pkg_unless_found(pkg) is True


# ---------------------------------------------------------------------------
# InstallerCustom registration tests
# ---------------------------------------------------------------------------


class TestInstallerCustomRegistration:
    def test_custom_registered_in_installer(self):
        cfg = IshConfig(dry_run=True, log_level=logging.DEBUG)
        runner = CommandRunner(cfg=cfg)
        runner.which = lambda cmd: None
        installer = Installer(cfg=cfg, runner=runner)
        assert "custom" in installer._backends
        assert isinstance(installer.get_backend("custom"), InstallerCustom)

    def test_custom_backend_count(self):
        cfg = IshConfig(dry_run=True, log_level=logging.DEBUG)
        runner = CommandRunner(cfg=cfg)
        runner.which = lambda cmd: None
        installer = Installer(cfg=cfg, runner=runner)
        assert len(installer._backends) == 7  # apt, dnf, cargo, pip, brew, winget, custom

    def test_get_installer_with_custom(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool"
            script.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")

            cfg = IshConfig(
                dry_run=True,
                log_level=logging.DEBUG,
                defaults={"source": tmpdir},
            )
            runner = CommandRunner(cfg=cfg)
            runner.which = lambda cmd: None
            installer = Installer(cfg=cfg, runner=runner)
            pkg = {"name": "mytool", "custom": "mytool"}
            result = installer.get_installer(pkg)
            assert result == "custom"


# ---------------------------------------------------------------------------
# FilePreprocessor unit tests
# ---------------------------------------------------------------------------


class TestFilePreprocessor:
    def test_preprocess_file_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.sh"
            f.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            pp = FilePreprocessor()
            text, meta = pp.preprocess_file(f)
            assert "echo hello" in text
            assert meta is None

    def test_preprocess_file_with_directives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.sh"
            f.write_text(
                "#!/bin/sh\n#@ish set name=world\necho ${__ish_name}\n",
                encoding="utf-8",
            )
            pp = FilePreprocessor()
            text, _ = pp.preprocess_file(f)
            assert "echo world" in text
            assert "#@ish" not in text

    def test_preprocess_file_with_variables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.sh"
            f.write_text("echo ${__ish_greeting}\n", encoding="utf-8")
            pp = FilePreprocessor(variables={"greeting": "hi"})
            text, _ = pp.preprocess_file(f)
            assert "echo hi" in text

    def test_preprocess_file_with_conditionals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "test.sh"
            f.write_text(
                "#@ish if ish.os == 'linux'\necho linux\n#@ish fi\n",
                encoding="utf-8",
            )
            pp = FilePreprocessor(variables={"os": "linux"})
            text, _ = pp.preprocess_file(f)
            assert "echo linux" in text

    def test_preprocess_text_basic(self):
        pp = FilePreprocessor(variables={"x": "1"})
        text = pp.preprocess_text("val=${__ish_x}\n")
        assert text == "val=1\n"

    def test_context_shared(self):
        pp = FilePreprocessor()
        with tempfile.TemporaryDirectory() as tmpdir:
            f1 = Path(tmpdir) / "first.sh"
            f1.write_text("#@ish set color=red\n", encoding="utf-8")
            f2 = Path(tmpdir) / "second.sh"
            f2.write_text("COLOR=${__ish_color}\n", encoding="utf-8")
            pp.preprocess_file(f1)
            text, _ = pp.preprocess_file(f2)
            assert "COLOR=red" in text


# ---------------------------------------------------------------------------
# DotfileScript unit tests
# ---------------------------------------------------------------------------


class TestDotfileScript:
    def test_preprocess_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "install_test"
            f.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            script = DotfileScript(f)
            text = script.preprocess()
            assert "echo hello" in text

    def test_preprocess_with_directives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "install_test"
            f.write_text(
                "#!/bin/sh\n#@ish set pkg=mylib\necho installing ${__ish_pkg}\n",
                encoding="utf-8",
            )
            pp = FilePreprocessor()
            script = DotfileScript(f, preprocessor=pp)
            text = script.preprocess()
            assert "echo installing mylib" in text

    def test_preprocess_with_variables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "install_test"
            f.write_text("#!/bin/sh\necho ${__ish_target}\n", encoding="utf-8")
            pp = FilePreprocessor(variables={"target": "/usr/local"})
            script = DotfileScript(f, preprocessor=pp)
            text = script.preprocess()
            assert "echo /usr/local" in text

    def test_preprocess_file_not_found(self):
        script = DotfileScript(Path("/nonexistent/install_test"))
        with pytest.raises(FileNotFoundError):
            script.preprocess()

    def test_detect_interpreter_sh(self):
        assert DotfileScript._detect_interpreter("#!/bin/sh\necho hi") == []

    def test_detect_interpreter_bash(self):
        assert DotfileScript._detect_interpreter("#!/usr/bin/env bash\necho hi") == []

    def test_detect_interpreter_python(self):
        result = DotfileScript._detect_interpreter("#!/usr/bin/env python3\nimport os")
        assert "python3" in result[-1]

    def test_detect_interpreter_no_shebang(self):
        assert DotfileScript._detect_interpreter("echo hi") == ["/bin/sh"]

    def test_execute_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "install_test"
            f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            runner = CommandRunner(cfg=IshConfig(dry_run=True))
            script = DotfileScript(f, runner=runner)
            assert script.execute() is True

    def test_metadata_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            f = Path(tmpdir) / "install_test"
            f.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
            script = DotfileScript(f)
            assert script.metadata is None
            script.preprocess()
            # No metadata in this script
            assert script.metadata is None


# ---------------------------------------------------------------------------
# Integration: InstallerCustom with real scripts (dry-run)
# ---------------------------------------------------------------------------


class TestInstallerCustomIntegration:
    def test_install_pkg_dry_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool"
            script.write_text("#!/bin/sh\necho installing mytool\n", encoding="utf-8")

            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "mytool", "custom": "mytool"}
            assert custom.install_custom_pkg(pkg) is True

    def test_install_pkg_with_preprocessing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool"
            script.write_text(
                "#!/bin/sh\n#@ish set ver=1.0\necho ${__ish_ver}\n",
                encoding="utf-8",
            )

            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "mytool", "custom": "mytool"}
            assert custom.install_custom_pkg(pkg) is True

    def test_install_pkg_with_context_variables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            script = installers / "install_mytool"
            script.write_text(
                "#!/bin/sh\necho installing to ${__ish_prefix}\n",
                encoding="utf-8",
            )

            cfg = make_cfg(source=tmpdir)
            cfg.context.set("prefix", "/opt")
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "mytool", "custom": "mytool"}
            assert custom.install_custom_pkg(pkg) is True

    def test_install_pkg_no_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()

            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkg = {"name": "mytool", "custom": "mytool"}
            with pytest.raises(FileNotFoundError):
                custom.install_custom_pkg(pkg)

    def test_install_multiple_pkgs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            installers = Path(tmpdir) / "ishinstallers"
            installers.mkdir()
            for name in ("tool1", "tool2"):
                script = installers / f"install_{name}"
                script.write_text(
                    f"#!/bin/sh\necho installing {name}\n", encoding="utf-8"
                )

            cfg = make_cfg(source=tmpdir)
            custom = InstallerCustom(make_runner(cfg=cfg), cfg=cfg)
            pkgs = [
                {"name": "tool1", "custom": "tool1"},
                {"name": "tool2", "custom": "tool2"},
            ]
            assert custom.install_custom_pkgs(pkgs) is True


if __name__ == "__main__":
    pytest.main()
