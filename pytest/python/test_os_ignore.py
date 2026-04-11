#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

#
# Tests for OS-conditional ignore rules and metadata filtering

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib.environment import (
    detect_os,
    detect_distro,
    detect_os_tags,
    should_skip_for_os,
    should_skip_for_os_from_metadata,
    normalise_os,
    _read_os_release,
    _match_distro_family,
    EnvironmentNamespace,
)
from pyishlib.dotfile_context import DotfileContext
from pyishlib.dotfile_ignore import (
    DotfileIgnore,
    load_ignore_file,
)
from pyishlib.dotfile_applier import DotfileApplier
from pyishlib.ish_config import IshConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(path: Path, content: str = "hello\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# os_info: detect_os
# ---------------------------------------------------------------------------


class TestDetectOs:
    def test_linux(self):
        with patch("pyishlib.environment.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert detect_os() == "linux"

    def test_macos(self):
        with patch("pyishlib.environment.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert detect_os() == "macos"

    def test_windows(self):
        with patch("pyishlib.environment.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert detect_os() == "windows"

    def test_unknown(self):
        with patch("pyishlib.environment.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            with pytest.raises(RuntimeError):
                detect_os()


# ---------------------------------------------------------------------------
# os_info: normalise_os
# ---------------------------------------------------------------------------


class TestNormaliseOs:
    def test_canonical(self):
        assert normalise_os("linux") == "linux"
        assert normalise_os("macos") == "macos"
        assert normalise_os("windows") == "windows"

    def test_aliases(self):
        assert normalise_os("mac") == "macos"
        assert normalise_os("darwin") == "macos"
        assert normalise_os("win") == "windows"
        assert normalise_os("win32") == "windows"

    def test_distro_names(self):
        assert normalise_os("debian") == "debian"
        assert normalise_os("ubuntu") == "debian"
        assert normalise_os("fedora") == "fedora"

    def test_case_insensitive(self):
        assert normalise_os("Linux") == "linux"
        assert normalise_os("MACOS") == "macos"
        assert normalise_os("Windows") == "windows"
        assert normalise_os("Debian") == "debian"

    def test_unknown(self):
        with pytest.raises(ValueError):
            normalise_os("freebsd")


# ---------------------------------------------------------------------------
# detect_distro
# ---------------------------------------------------------------------------


class TestReadOsRelease:
    def test_parses_standard_format(self):
        content = 'ID=ubuntu\nID_LIKE=debian\nVERSION_ID="22.04"\nNAME="Ubuntu"\n'
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__ = lambda s: s
            mock_open.return_value.__exit__ = lambda s, *a: None
            mock_open.return_value.read.return_value = content
            result = _read_os_release()
            assert result["ID"] == "ubuntu"
            assert result["ID_LIKE"] == "debian"
            assert result["VERSION_ID"] == "22.04"
            assert result["NAME"] == "Ubuntu"

    def test_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = _read_os_release()
            assert result == {}


class TestMatchDistroFamily:
    """Test the pattern matching against real-world os-release tokens."""

    def test_debian_itself(self):
        assert _match_distro_family(["debian"]) == "debian"

    def test_ubuntu_id_like(self):
        # Ubuntu: ID=ubuntu, ID_LIKE=debian
        assert _match_distro_family(["debian"]) == "debian"

    def test_mint_id_like(self):
        # Mint: ID=linuxmint, ID_LIKE="ubuntu debian"
        assert _match_distro_family(["ubuntu", "debian"]) == "debian"

    def test_pop_os_id_like(self):
        # Pop!_OS: ID=pop-os, ID_LIKE="ubuntu debian"
        assert _match_distro_family(["ubuntu", "debian"]) == "debian"

    def test_elementary_id_like(self):
        # elementary OS: ID=elementary, ID_LIKE=ubuntu
        assert _match_distro_family(["ubuntu"]) == "debian"

    def test_kali_id_like(self):
        # Kali: ID=kali, ID_LIKE=debian
        assert _match_distro_family(["debian"]) == "debian"

    def test_raspbian_id(self):
        # Raspbian: ID=raspbian, ID_LIKE=debian
        # Also test that raspbian matches via ID as a fallback
        assert _match_distro_family(["raspbian"]) == "debian"

    def test_fedora_itself(self):
        assert _match_distro_family(["fedora"]) == "fedora"

    def test_rhel_id_like(self):
        # RHEL: ID=rhel, ID_LIKE=fedora
        assert _match_distro_family(["fedora"]) == "fedora"

    def test_rhel_id_fallback(self):
        # RHEL without ID_LIKE (older versions)
        assert _match_distro_family(["rhel"]) == "fedora"

    def test_centos_stream_id_like(self):
        # CentOS Stream: ID="centos", ID_LIKE="rhel centos fedora"
        assert _match_distro_family(["rhel", "centos", "fedora"]) == "fedora"

    def test_centos_id_fallback(self):
        assert _match_distro_family(["centos"]) == "fedora"

    def test_rocky_id_like(self):
        # Rocky: ID="rocky", ID_LIKE="rhel centos fedora"
        assert _match_distro_family(["rhel", "centos", "fedora"]) == "fedora"

    def test_alma_id_like(self):
        # AlmaLinux: ID="almalinux", ID_LIKE="rhel centos fedora"
        assert _match_distro_family(["rhel", "centos", "fedora"]) == "fedora"

    def test_fedora_asahi_remix_id(self):
        # Fedora Asahi Remix: ID="fedora-asahi-remix", ID_LIKE=fedora
        # startswith("fedora") matches the compound ID
        assert _match_distro_family(["fedora"]) == "fedora"
        # Also matches via ID as fallback
        assert _match_distro_family(["fedora-asahi-remix"]) == "fedora"

    def test_nobara_id_like(self):
        # Nobara: ID=nobara, ID_LIKE=fedora
        assert _match_distro_family(["fedora"]) == "fedora"

    def test_amazon_linux_id_like(self):
        # Amazon Linux 2023: ID=amzn, ID_LIKE=fedora
        assert _match_distro_family(["fedora"]) == "fedora"

    def test_unknown_distro(self):
        assert _match_distro_family(["gentoo"]) is None
        assert _match_distro_family(["arch"]) is None
        assert _match_distro_family(["void"]) is None

    def test_empty(self):
        assert _match_distro_family([]) is None


class TestDetectDistro:
    def test_not_linux(self):
        with patch("pyishlib.environment.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert detect_distro() is None

    def test_ubuntu(self):
        # Real Ubuntu: ID=ubuntu, ID_LIKE=debian
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "ubuntu", "ID_LIKE": "debian"}
            assert detect_distro() == "debian"

    def test_debian(self):
        # Real Debian: ID=debian (no ID_LIKE)
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "debian"}
            assert detect_distro() == "debian"

    def test_fedora(self):
        # Real Fedora: ID=fedora (no ID_LIKE)
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "fedora"}
            assert detect_distro() == "fedora"

    def test_pop_os(self):
        # Real Pop!_OS: ID=pop-os, ID_LIKE="ubuntu debian"
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "pop-os", "ID_LIKE": "ubuntu debian"}
            assert detect_distro() == "debian"

    def test_fedora_asahi_remix(self):
        # Real Asahi: ID=fedora-asahi-remix, ID_LIKE=fedora
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "fedora-asahi-remix", "ID_LIKE": "fedora"}
            assert detect_distro() == "fedora"

    def test_rocky(self):
        # Real Rocky: ID="rocky", ID_LIKE="rhel centos fedora"
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "rocky", "ID_LIKE": "rhel centos fedora"}
            assert detect_distro() == "fedora"

    def test_almalinux(self):
        # Real AlmaLinux: ID="almalinux", ID_LIKE="rhel centos fedora"
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {
                "ID": "almalinux",
                "ID_LIKE": "rhel centos fedora",
            }
            assert detect_distro() == "fedora"

    def test_linuxmint(self):
        # Real Mint: ID=linuxmint, ID_LIKE="ubuntu debian"
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}
            assert detect_distro() == "debian"

    def test_kali(self):
        # Real Kali: ID=kali, ID_LIKE=debian
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "kali", "ID_LIKE": "debian"}
            assert detect_distro() == "debian"

    def test_centos_stream(self):
        # Real CentOS Stream: ID="centos", ID_LIKE="rhel centos fedora"
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "centos", "ID_LIKE": "rhel centos fedora"}
            assert detect_distro() == "fedora"

    def test_amazon_linux(self):
        # Real Amazon Linux 2023: ID="amzn", ID_LIKE="fedora"
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "amzn", "ID_LIKE": "fedora"}
            assert detect_distro() == "fedora"

    def test_unknown_distro(self):
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {"ID": "gentoo"}
            assert detect_distro() is None

    def test_no_os_release(self):
        with patch("pyishlib.environment.sys") as mock_sys, \
                patch("pyishlib.environment._read_os_release") as mock_read:
            mock_sys.platform = "linux"
            mock_read.return_value = {}
            assert detect_distro() is None


# ---------------------------------------------------------------------------
# detect_os_tags
# ---------------------------------------------------------------------------


class TestDetectOsTags:
    def test_linux_with_distro(self):
        with patch("pyishlib.environment.detect_os", return_value="linux"), \
                patch("pyishlib.environment.detect_distro", return_value="debian"):
            assert detect_os_tags() == ["linux", "debian"]

    def test_linux_unknown_distro(self):
        with patch("pyishlib.environment.detect_os", return_value="linux"), \
                patch("pyishlib.environment.detect_distro", return_value=None):
            assert detect_os_tags() == ["linux"]

    def test_macos(self):
        with patch("pyishlib.environment.detect_os", return_value="macos"), \
                patch("pyishlib.environment.detect_distro", return_value=None):
            assert detect_os_tags() == ["macos"]


# ---------------------------------------------------------------------------
# EnvironmentNamespace and DotfileContext.env
# ---------------------------------------------------------------------------


class TestEnvironmentNamespace:
    def test_namespace_has_all_checks(self):
        ns = EnvironmentNamespace()
        for name in (
            "is_linux",
            "is_macos",
            "is_windows",
            "is_ubuntu",
            "is_gnome",
            "is_linux_desktop",
            "detect_os",
            "detect_distro",
        ):
            assert callable(getattr(ns, name))

    @patch("pyishlib.environment.sys")
    def test_is_linux_via_namespace(self, mock_sys):
        mock_sys.platform = "linux"
        assert EnvironmentNamespace.is_linux() is True
        mock_sys.platform = "darwin"
        assert EnvironmentNamespace.is_linux() is False

    @patch("pyishlib.environment.sys")
    def test_is_macos_via_namespace(self, mock_sys):
        mock_sys.platform = "darwin"
        assert EnvironmentNamespace.is_macos() is True
        mock_sys.platform = "linux"
        assert EnvironmentNamespace.is_macos() is False

    def test_context_env_attribute(self):
        ctx = DotfileContext()
        assert isinstance(ctx.env, EnvironmentNamespace)

    @patch("pyishlib.environment.sys")
    def test_context_env_is_linux(self, mock_sys):
        """ish.env.is_linux() works in a DotfileContext."""
        mock_sys.platform = "linux"
        ctx = DotfileContext()
        assert ctx.env.is_linux() is True

    def test_context_env_survives_as_dict(self):
        """env is not a string variable — it should not appear in as_dict()."""
        ctx = DotfileContext({"platform": "linux"})
        d = ctx.as_dict()
        assert "env" not in d
        assert "platform" in d


# ---------------------------------------------------------------------------
# os_info: should_skip_for_os
# ---------------------------------------------------------------------------


class TestShouldSkipForOs:
    def test_no_rules(self):
        assert should_skip_for_os(current_os="linux") is False

    def test_only_on_match(self):
        assert should_skip_for_os(only_on=["linux"], current_os="linux") is False

    def test_only_on_no_match(self):
        assert should_skip_for_os(only_on=["linux"], current_os="macos") is True

    def test_only_on_multiple(self):
        assert (
            should_skip_for_os(only_on=["linux", "macos"], current_os="macos") is False
        )
        assert (
            should_skip_for_os(only_on=["linux", "macos"], current_os="windows") is True
        )

    def test_ignore_on_match(self):
        assert should_skip_for_os(ignore_on=["windows"], current_os="windows") is True

    def test_ignore_on_no_match(self):
        assert should_skip_for_os(ignore_on=["windows"], current_os="linux") is False

    def test_ignore_on_multiple(self):
        assert (
            should_skip_for_os(ignore_on=["windows", "macos"], current_os="macos")
            is True
        )

    def test_both_rules(self):
        # only_on=["linux", "macos"], ignore_on=["macos"]
        # On macos: only_on passes (macos in list), but ignore_on skips
        assert (
            should_skip_for_os(
                only_on=["linux", "macos"],
                ignore_on=["macos"],
                current_os="macos",
            )
            is True
        )

    def test_distro_only_on_debian_on_ubuntu(self):
        """Ubuntu (linux,debian) should match only_on=["debian"]."""
        assert (
            should_skip_for_os(only_on=["debian"], current_os="linux,debian") is False
        )

    def test_distro_only_on_debian_on_fedora(self):
        """Fedora (linux,fedora) should NOT match only_on=["debian"]."""
        assert should_skip_for_os(only_on=["debian"], current_os="linux,fedora") is True

    def test_distro_only_on_linux_on_ubuntu(self):
        """Ubuntu (linux,debian) should match only_on=["linux"]."""
        assert should_skip_for_os(only_on=["linux"], current_os="linux,debian") is False

    def test_distro_ignore_on_fedora_on_fedora(self):
        """Fedora (linux,fedora) should match ignore_on=["fedora"]."""
        assert (
            should_skip_for_os(ignore_on=["fedora"], current_os="linux,fedora") is True
        )

    def test_distro_ignore_on_debian_on_fedora(self):
        """Fedora (linux,fedora) should NOT match ignore_on=["debian"]."""
        assert (
            should_skip_for_os(ignore_on=["debian"], current_os="linux,fedora") is False
        )

    def test_bad_only_on_value_does_not_crash(self):
        """A typo in only_on should warn and not skip (non-fatal)."""
        assert should_skip_for_os(only_on=["linxu"], current_os="linux") is False

    def test_bad_ignore_on_value_does_not_crash(self):
        """A typo in ignore_on should warn and not skip (non-fatal)."""
        assert should_skip_for_os(ignore_on=["lindows"], current_os="windows") is False


# ---------------------------------------------------------------------------
# os_info: should_skip_for_os_from_metadata
# ---------------------------------------------------------------------------


class TestShouldSkipFromMetadata:
    def test_none_metadata(self):
        assert should_skip_for_os_from_metadata(None) is False

    def test_empty_metadata(self):
        assert should_skip_for_os_from_metadata({}) is False

    def test_only_on_list(self):
        meta = {"only_on": ["linux"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False
        assert should_skip_for_os_from_metadata(meta, current_os="macos") is True

    def test_only_on_string(self):
        meta = {"only_on": "linux"}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False
        assert should_skip_for_os_from_metadata(meta, current_os="windows") is True

    def test_ignore_on_list(self):
        meta = {"ignore_on": ["windows"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False
        assert should_skip_for_os_from_metadata(meta, current_os="windows") is True

    def test_ignore_on_string(self):
        meta = {"ignore_on": "windows"}
        assert should_skip_for_os_from_metadata(meta, current_os="windows") is True

    def test_metadata_with_other_keys(self):
        meta = {"vars": {"foo": "bar"}, "only_on": ["linux"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux") is False

    def test_only_on_debian_on_ubuntu(self):
        meta = {"only_on": ["debian"]}
        assert (
            should_skip_for_os_from_metadata(meta, current_os="linux,debian") is False
        )

    def test_only_on_debian_on_fedora(self):
        meta = {"only_on": ["debian"]}
        assert should_skip_for_os_from_metadata(meta, current_os="linux,fedora") is True

    def test_ignore_on_fedora_on_fedora(self):
        meta = {"ignore_on": "fedora"}
        assert should_skip_for_os_from_metadata(meta, current_os="linux,fedora") is True


# ---------------------------------------------------------------------------
# DotfileIgnore: OS-conditional sections in ignore file
# ---------------------------------------------------------------------------


class TestIgnoreFileSections:
    def test_global_only(self):
        with tempfile.TemporaryDirectory() as d:
            _make_file(Path(d) / ".dotfileignore", "*.bak\ntemp_*\n")
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert pats == ["*.bak", "temp_*"]
            assert only_on == {}
            assert ignore_on == {}

    def test_only_on_section(self):
        with tempfile.TemporaryDirectory() as d:
            content = "*.bak\n\n[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert pats == ["*.bak"]
            assert only_on == {"linux": ["linux-conf"]}
            assert ignore_on == {}

    def test_ignore_on_section(self):
        with tempfile.TemporaryDirectory() as d:
            content = "[ignore_on.windows]\nunix-tool\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert pats == []
            assert only_on == {}
            assert ignore_on == {"windows": ["unix-tool"]}

    def test_multiple_sections(self):
        with tempfile.TemporaryDirectory() as d:
            content = (
                "*.bak\n"
                "[only_on.linux]\nlinux-only\n"
                "[only_on.macos]\nmac-only\n"
                "[ignore_on.windows]\nno-win\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert pats == ["*.bak"]
            assert only_on == {"linux": ["linux-only"], "macos": ["mac-only"]}
            assert ignore_on == {"windows": ["no-win"]}

    def test_comments_in_sections(self):
        with tempfile.TemporaryDirectory() as d:
            content = (
                "[only_on.linux]\n# This is a comment\nlinux-conf\n\nanother-linux\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert pats == []
            assert only_on == {"linux": ["linux-conf", "another-linux"]}

    def test_unknown_os_warning(self):
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.freebsd]\nsome-pattern\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert pats == []
            assert only_on == {}
            assert ignore_on == {}

    def test_os_aliases(self):
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.mac]\nmac-conf\n[ignore_on.win]\nno-win\n"
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert only_on == {"macos": ["mac-conf"]}
            assert ignore_on == {"windows": ["no-win"]}

    def test_distro_sections(self):
        with tempfile.TemporaryDirectory() as d:
            content = (
                "[only_on.debian]\ndebian-pkg\n"
                "[only_on.fedora]\nfedora-pkg\n"
                "[ignore_on.ubuntu]\nno-ubuntu\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)
            pats, only_on, ignore_on = load_ignore_file(Path(d) / ".dotfileignore")
            assert only_on == {
                "debian": ["debian-pkg"],
                "fedora": ["fedora-pkg"],
            }
            # "ubuntu" normalises to "debian"
            assert ignore_on == {"debian": ["no-ubuntu"]}

    def test_missing_file(self):
        pats, only_on, ignore_on = load_ignore_file(Path("/nonexistent"))
        assert pats == []
        assert only_on == {}
        assert ignore_on == {}


# ---------------------------------------------------------------------------
# DotfileIgnore: is_ignored with OS rules
# ---------------------------------------------------------------------------


class TestDotfileIgnoreOs:
    def test_only_on_current_os(self):
        """Patterns under [only_on.linux] should NOT be ignored on linux."""
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="linux")
            assert not di.is_ignored("linux-conf")

    def test_only_on_other_os(self):
        """Patterns under [only_on.linux] SHOULD be ignored on macos."""
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="macos")
            assert di.is_ignored("linux-conf")

    def test_ignore_on_current_os(self):
        """Patterns under [ignore_on.windows] SHOULD be ignored on windows."""
        with tempfile.TemporaryDirectory() as d:
            content = "[ignore_on.windows]\nwin-only-tool\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="windows")
            assert di.is_ignored("win-only-tool")

    def test_ignore_on_other_os(self):
        """Patterns under [ignore_on.windows] should NOT be ignored on linux."""
        with tempfile.TemporaryDirectory() as d:
            content = "[ignore_on.windows]\nwin-only-tool\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="linux")
            assert not di.is_ignored("win-only-tool")

    def test_global_still_works(self):
        """Global patterns should still be applied regardless of OS."""
        with tempfile.TemporaryDirectory() as d:
            content = "*.bak\n[only_on.linux]\nlinux-conf\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="linux")
            assert di.is_ignored("file.bak")
            assert not di.is_ignored("linux-conf")

    def test_default_patterns_still_work(self):
        """Default patterns (.git etc.) should still be applied."""
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), current_os="linux")
            assert di.is_ignored(".git")

    def test_patterns_property_includes_os(self):
        """The patterns property should include OS-effective patterns."""
        with tempfile.TemporaryDirectory() as d:
            content = "[only_on.linux]\nlinux-only\n"
            _make_file(Path(d) / ".dotfileignore", content)
            di = DotfileIgnore(Path(d), current_os="macos")
            assert "linux-only" in di.patterns

    def test_complex_scenario(self):
        """Multiple sections with different OSes."""
        with tempfile.TemporaryDirectory() as d:
            content = (
                "*.tmp\n"
                "[only_on.linux]\nlinux-app\n"
                "[only_on.macos]\nmac-app\n"
                "[ignore_on.windows]\nunix-tool\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)

            # On linux: ignore *.tmp, mac-app (only_on.macos); keep linux-app, unix-tool
            di = DotfileIgnore(Path(d), current_os="linux")
            assert di.is_ignored("file.tmp")
            assert not di.is_ignored("linux-app")
            assert di.is_ignored("mac-app")
            assert not di.is_ignored("unix-tool")

            # On macos: ignore *.tmp, linux-app; keep mac-app, unix-tool
            di = DotfileIgnore(Path(d), current_os="macos")
            assert di.is_ignored("linux-app")
            assert not di.is_ignored("mac-app")
            assert not di.is_ignored("unix-tool")

            # On windows: ignore *.tmp, linux-app, mac-app, unix-tool
            di = DotfileIgnore(Path(d), current_os="windows")
            assert di.is_ignored("linux-app")
            assert di.is_ignored("mac-app")
            assert di.is_ignored("unix-tool")

    def test_distro_hierarchical(self):
        """Distro-level sections work with hierarchical OS tags."""
        with tempfile.TemporaryDirectory() as d:
            content = (
                "[only_on.debian]\ndebian-pkg\n"
                "[only_on.linux]\nlinux-tool\n"
                "[ignore_on.fedora]\nno-fedora\n"
            )
            _make_file(Path(d) / ".dotfileignore", content)

            # Ubuntu (linux,debian): keep debian-pkg, keep linux-tool,
            # don't ignore no-fedora
            di = DotfileIgnore(Path(d), current_os="linux,debian")
            assert not di.is_ignored("debian-pkg")
            assert not di.is_ignored("linux-tool")
            assert not di.is_ignored("no-fedora")

            # Fedora (linux,fedora): ignore debian-pkg (only_on.debian),
            # keep linux-tool, ignore no-fedora
            di = DotfileIgnore(Path(d), current_os="linux,fedora")
            assert di.is_ignored("debian-pkg")
            assert not di.is_ignored("linux-tool")
            assert di.is_ignored("no-fedora")

            # macOS: ignore debian-pkg, ignore linux-tool, don't ignore no-fedora
            di = DotfileIgnore(Path(d), current_os="macos")
            assert di.is_ignored("debian-pkg")
            assert di.is_ignored("linux-tool")
            assert not di.is_ignored("no-fedora")

    def test_os_tags_property(self):
        with tempfile.TemporaryDirectory() as d:
            di = DotfileIgnore(Path(d), current_os="linux,debian")
            assert di.os_tags == ["linux", "debian"]
            assert di.current_os == "linux"


# ---------------------------------------------------------------------------
# DotfileApplier: metadata OS filtering
# ---------------------------------------------------------------------------


class TestApplierOsFiltering:
    def test_prepare_skips_only_on_mismatch(self):
        """Files with only_on metadata not matching current OS are skipped."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            # File with only_on=["macos"] metadata
            _make_file(
                Path(src) / "dot_mac_conf",
                '# __ISH__\n# only_on = ["macos"]\n# __ISH__\ncontent\n',
            )
            _make_file(Path(src) / "dot_bashrc", "export FOO=bar\n")

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            with patch(
                "pyishlib.dotfile_applier.should_skip_for_os_from_metadata"
            ) as mock_skip:
                # First call for dot_bashrc -> don't skip
                # Second call for dot_mac_conf -> skip
                def side_effect(meta):
                    if meta and meta.get("only_on") == ["macos"]:
                        return True
                    return False

                mock_skip.side_effect = side_effect
                prepared = applier.prepare(dotfiles)

            names = [df.translated.name for df in prepared]
            assert ".bashrc" in names
            assert ".mac_conf" not in names

    def test_prepare_keeps_only_on_match(self):
        """Files with only_on metadata matching current OS are kept."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_linux_conf",
                '# __ISH__\n# only_on = ["linux"]\n# __ISH__\ncontent\n',
            )

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            with patch(
                "pyishlib.dotfile_applier.should_skip_for_os_from_metadata",
                return_value=False,
            ):
                prepared = applier.prepare(dotfiles)

            assert len(prepared) == 1

    def test_prepare_skips_ignore_on_match(self):
        """Files with ignore_on metadata matching current OS are skipped."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as tgt:
            _make_file(
                Path(src) / "dot_unix_tool",
                '# __ISH__\n# ignore_on = ["windows"]\n# __ISH__\ncontent\n',
            )

            applier = DotfileApplier(
                source_dir=Path(src),
                target_dir=Path(tgt),
                cfg=IshConfig(dry_run=True),
            )
            dotfiles = applier.discover()
            with patch(
                "pyishlib.dotfile_applier.should_skip_for_os_from_metadata",
                return_value=True,
            ):
                prepared = applier.prepare(dotfiles)

            assert len(prepared) == 0


if __name__ == "__main__":
    pytest.main()
