# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePath
from textwrap import dedent

import colors
import pytest
from pytest import MonkeyPatch


@pytest.fixture(scope="session", autouse=True)
def dev_cmd_workspace_cache_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.getbasetemp().parent / ".dev-cmd"


@pytest.fixture(autouse=True)
def set_dev_cmd_workspace_cache_dir(monkeypatch: MonkeyPatch, dev_cmd_workspace_cache_dir: Path):
    monkeypatch.setenv("DEV_CMD_WORKSPACE_CACHE_DIR", dev_cmd_workspace_cache_dir.as_posix())


@pytest.fixture
def project_dir() -> PurePath:
    return PurePath(
        subprocess.run(
            args=["git", "rev-parse", "--show-toplevel"],
            cwd=PurePath(__file__).parent,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
    )


@pytest.fixture
def pyproject_toml(monkeypatch: MonkeyPatch, tmp_path: Path, project_dir: PurePath) -> Path:
    monkeypatch.chdir(tmp_path)

    # Setting these silences spurious warnings using uv under uv in tests.
    monkeypatch.setenv("UV_LINK_MODE", "copy")
    monkeypatch.delenv("VIRTUAL_ENV")

    dev_cmd_with_old_pythons_req = f"dev-cmd[old-pythons] @ file://{project_dir.as_posix()}"

    pyproject_toml_file = tmp_path / "pyproject.toml"
    pyproject_toml_file.write_text(
        dedent(
            f"""
            [project]
            name = "script-test"
            version = "0.1.0"
            requires-python = "=={".".join(map(str, sys.version_info[:3]))}"

            [dependency-groups]
            dev = [
                "ansicolors",
                "{dev_cmd_with_old_pythons_req}",
                "ruff",
            ]

            [[tool.dev-cmd.python]]
            # Let all the test cases share the same cache keys since requirements are hard coded
            # here and the tests only append commands and tasks.
            pyproject-cache-keys = []

            3rdparty-export-command = [
                "uv", "export", "-q",
                "--no-emit-project",
                "--no-emit-package", "dev-cmd",
                "-o", "{{requirements.txt}}",
            ]
            extra-requirements = ["{dev_cmd_with_old_pythons_req}"]
            """
        )
    )
    return pyproject_toml_file


@pytest.fixture
def script(tmp_path: Path) -> PurePath:
    script = tmp_path / "script.py"
    script.write_text(
        dedent(
            """\
            import sys

            import colors


            if sys.argv[1].endswith(":"):
                color = sys.argv[1][:-1]
                args = sys.argv[2:]
            else:
                color = "cyan"
                args = sys.argv[1:]
            print(colors.color(" ".join(args), fg=color))
            """
        )
    )
    return script


python_args = pytest.mark.parametrize(
    "python_args",
    [
        pytest.param([], id="ambient"),
        pytest.param(["--python", sys.executable], id="custom"),
    ],
)


@python_args
def test_exec_python(script: PurePath, pyproject_toml: Path, python_args: list[str]) -> None:
    with pyproject_toml.open("a") as fp:
        fp.write(
            dedent(
                f"""
                [tool.dev-cmd.commands.test]
                args = ["python", "{script.as_posix()}"]
                accepts-extra-args = true
                """
            )
        )

    assert (
        colors.cyan("Slartibartfast 42")
        == subprocess.run(
            args=["uv", "run", "dev-cmd"] + python_args + ["test", "--", "Slartibartfast", "42"],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
    )


@python_args
def test_exec_script(script: PurePath, pyproject_toml: Path, python_args: list[str]) -> None:
    with pyproject_toml.open("a") as fp:
        fp.write(
            dedent(
                f"""
                [tool.dev-cmd.commands.test]
                args = ["{script.as_posix()}"]
                accepts-extra-args = true
                """
            )
        )

    assert (
        colors.magenta("Ford Marvin -- Zaphod")
        == subprocess.run(
            args=["uv", "run", "dev-cmd"]
            + python_args
            + [
                "test",
                "--",
                "magenta:",
                "Ford",
                "Marvin",
                "--",
                "Zaphod",
            ],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
    )


@python_args
def test_exec_binary(script: PurePath, pyproject_toml: Path, python_args: list[str]) -> None:
    with pyproject_toml.open("a") as fp:
        fp.write(
            dedent(
                f"""
                [tool.dev-cmd.commands]
                check-fmt = ["ruff", "format", "--check", "{script.as_posix()}"]
                """
            )
        )
    subprocess.run(args=["uv", "run", "dev-cmd"] + python_args + ["check-fmt"], check=True)
