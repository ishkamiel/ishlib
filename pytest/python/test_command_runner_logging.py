# -*- coding: utf-8 -*-
#
# Author: Hans Liljestrand <hans@liljestrand.dev>
# Copyright (C) 2024 Hans Liljestrand <hans@liljestrand.dev>
#
# Distributed under terms of the MIT license.

import sys
import os
from unittest.mock import patch
import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from pyishlib import CommandRunner


class TestCommandRunnerLogging:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.runner = CommandRunner()

    @patch.object(CommandRunner, "_print_cmd")
    def test_run(self, mock_method):
        command = ["echo", "Hello, World!"]
        result = self.runner.run(command, capture_output=True)

        # Make sure we actually ran stuff
        assert result.returncode == 0

    @patch.object(CommandRunner, "_print_cmd")
    def test_run_print(self, mock_method):
        command = ["echo", "Hello, World!"]
        result = self.runner.run(command, capture_output=True)

        # Make sure we printed the command via _print_cmd
        mock_method.assert_called_with(command)

    @patch.object(CommandRunner, "_print_cmd")
    def test_run_print_and_run(self, mock_method):
        command = ["echo", "Hello, World!"]
        result = self.runner.run(command, capture_output=True)

        # Make sure we printed and ran the command
        mock_method.assert_called_with(command)
        assert hasattr(result, "stdout") and result.stdout == b"Hello, World!\n"

    @patch.object(CommandRunner, "_print_cmd")
    def test_run_dry_run_1(self, mock_method):
        self.runner.dry_run = True
        command = ["echo", "Hello, World!"]
        result = self.runner.run(command, capture_output=True)

        # Expect dry-run to fake success
        assert result.returncode == 0
        # And print out the command
        mock_method.assert_called_with(command)
        # But not actually run it
        assert not hasattr(result, "sdtout") or result.stdout == b"\n"

    @patch.object(CommandRunner, "_print_cmd")
    def test_run_dry_run_2(self, mock_method):
        runner = CommandRunner(dry_run=True)
        command = ["echo", "Hello, World!"]

        result = self.runner.run(command)
        # Expect dry-run to fake success
        assert result.returncode == 0
        # And print out the command
        mock_method.assert_called_with(command)
        # But not actually run it
        assert not hasattr(result, "sdtout") or result.stdout == b"\n"

    # @patch.object(CommandRunner, '_print_cmd')
    # def test_run_sudo(self, mock_method):
    #     command = ["echo", "Hello, World!"]
    #     result = self.runner.run(command, sudo = True)
    #     self.assertEqual(result, None)
    #     mock_method.assert_called_with(["sudo*", command])

    # Add more test cases for each public function in command_runner


if __name__ == "__main__":
    pytest.main()
