#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import os
import pytest
import subprocess

all_shells = ["bash", "dash", "sh", "zsh"]
poisix_only_shells = ["sh", "dash"]
shellcheck_shells = ["bash", "sh"]
ishlib_bash_variant = 'export ish_VERSION_VARIANT="POSIX+bash"'


def rel_path(path):
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return (script_dir.parent / path).resolve()


def get_src_files():
    src_folder = rel_path("src")
    return list(Path(src_folder).rglob("*.sh")) + list(Path(src_folder).rglob("*.bash"))


def run_check_call(*args):
    subprocess.check_call([str(i) for i in args])


def run_check_output(*args):
    print(f"Running: {args}")
    return subprocess.check_output(
        [str(i) for i in args], stderr=subprocess.STDOUT, text=True
    )


def gen_file(tmp_path, content):
    tmp_file = Path(tmp_path) / f"test.sh"
    tmp_file.write_text(content)
    return tmp_file


def run_script_content(shell, tmp_path, script_content):
    tmp_file = gen_file(tmp_path, script_content)
    run_check_call(shell, tmp_file)


def gen_script_and_check_output(shell, tmp_path, script_content):
    tmp_file = gen_file(tmp_path, script_content)
    try:
        return run_check_output(shell, tmp_file)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"\n{shell} {tmp_file}\n{e.output}")


@pytest.fixture
def all_src_files():
    return get_src_files()


@pytest.fixture
def project_root():
    return rel_path(".")


@pytest.fixture
def src_folder():
    return rel_path("src")


@pytest.fixture
def ishlib():
    return rel_path("ishlib.sh")


@pytest.fixture
def sh_only():
    return poisix_only_shells
