# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess
import sys
from pathlib import Path, PurePath
from textwrap import dedent

import colors
import pytest
from pytest import MonkeyPatch


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
                "dev-cmd @ {project_dir.as_posix()}",
            ]
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


def test_exec_python(script: PurePath, pyproject_toml: Path) -> None:
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
            args=["uv", "run", "dev-cmd", "test", "--", "Slartibartfast", "42"],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
    )


def test_exec_script(script: PurePath, pyproject_toml: Path) -> None:
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
        colors.magenta("Ford Marvin")
        == subprocess.run(
            args=["uv", "run", "dev-cmd", "test", "--", "magenta:", "Ford", "Marvin"],
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
    )
