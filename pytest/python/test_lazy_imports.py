# SPDX-License-Identifier: MIT
# Copyright (C) 2026 Hans Liljestrand <hans@liljestrand.dev>
"""Guards for lazy importing: starting ishproject must stay cheap.

Importing ``pyishlib`` (or the ishproject CLI) must not drag in the
installer/dotfile stack or the ishfiles CLI.  These run in a fresh
interpreter so the check is not polluted by modules other tests loaded.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"


def _loaded_modules(code: str) -> set:
    """Run *code* in a fresh interpreter; return the names in ``sys.modules``.

    ``pytest/conftest.py`` strips PYTHONPATH from ``os.environ``, so it
    is set explicitly here.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_SRC_DIR)
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; {code}; print('\\n'.join(sorted(sys.modules)))",
        ],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    return set(res.stdout.split())


class TestLazyImports(unittest.TestCase):
    def test_importing_ishproject_cli_skips_ishfiles_and_yaml(self) -> None:
        loaded = _loaded_modules("import pyishlib.ishproject.cli")
        self.assertNotIn("pyishlib.ishfiles.cli", loaded)
        self.assertNotIn("pyishlib.ishfiles.applier", loaded)
        self.assertNotIn("yaml", loaded)

    def test_importing_package_is_lazy(self) -> None:
        loaded = _loaded_modules("import pyishlib")
        self.assertNotIn("pyishlib.command_runner", loaded)
        self.assertNotIn("pyishlib.dotfile_applier", loaded)

    def test_lazy_package_attributes_still_resolve(self) -> None:
        import pyishlib

        from pyishlib.command_runner import CommandRunner

        self.assertIs(pyishlib.CommandRunner, CommandRunner)
        self.assertIn("IshConfig", dir(pyishlib))
        with self.assertRaises(AttributeError):
            pyishlib.does_not_exist  # noqa: B018

    def test_lazy_ishfiles_wrappers_forward(self) -> None:
        from pyishlib.ishproject import _ishfiles_lazy

        with patch("pyishlib.ishfiles.cli.main", return_value=7) as m:
            self.assertEqual(_ishfiles_lazy.ishfiles_main(["x"]), 7)
        m.assert_called_once_with(["x"])
        self.assertEqual(_ishfiles_lazy.ishfiles_build_parser().prog, "ishfiles")


if __name__ == "__main__":
    unittest.main()
