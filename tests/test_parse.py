# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
import sys
from pathlib import Path
from textwrap import dedent
from typing import Iterator, Protocol

import pytest
from packaging.markers import Marker

from dev_cmd.errors import InvalidModelError
from dev_cmd.model import Command, Configuration, Group, Task
from dev_cmd.parse import parse_dev_config
from dev_cmd.project import PyProjectToml


class ConfigurationParser(Protocol):
    def __call__(self, content: str, *requested_steps: str) -> Configuration: ...


@pytest.fixture
def parse_config(tmp_path: Path) -> Iterator[ConfigurationParser]:
    def parse(content: str, *requested_steps: str) -> Configuration:
        pyproject_toml = tmp_path / "pyproject.toml"
        pyproject_toml.write_text(content)
        return parse_dev_config(PyProjectToml(pyproject_toml), *requested_steps)[0]

    yield parse


def test_when_hides_command(parse_config: ConfigurationParser) -> None:
    config = parse_config(
        dedent(
            f"""\
            [tool.dev-cmd.commands]
            repl = ["python"]

            [tool.dev-cmd.commands.hidden]
            when = "sys_platform != '{sys.platform}'"
            args = ["python"]
            """
        )
    )
    assert tuple([Command("repl", args=tuple(["python"]))]) == config.commands


def test_when_hides_task(parse_config: ConfigurationParser) -> None:
    config = parse_config(
        dedent(
            f"""\
            [tool.dev-cmd.commands]
            repl = ["python"]

            [tool.dev-cmd.commands.pyver]
            when = "sys_platform == '{sys.platform}'"
            args = ["python", "-V"]

            [tool.dev-cmd.tasks]
            foo = ["pyver", "repl"]

            [tool.dev-cmd.tasks.hidden]
            when = "sys_platform != '{sys.platform}'"
            steps = ["repl"]
            """
        )
    )
    repl = Command("repl", args=tuple(["python"]))
    pyver = Command(
        "pyver", args=("python", "-V"), when=Marker(f"sys_platform == '{sys.platform}'")
    )
    assert (repl, pyver) == config.commands
    assert tuple([Task("foo", steps=Group(members=tuple([pyver, repl])))]) == config.tasks


def test_when_selects_command(parse_config: ConfigurationParser) -> None:
    config = parse_config(
        dedent(
            f"""\
            [tool.dev-cmd.commands.repl-foo]
            when = "sys_platform != '{sys.platform}'"
            name = "repl"
            args = ["python", "-c", "print('foo')"]

            [tool.dev-cmd.commands.repl-bar]
            when = "sys_platform == '{sys.platform}'"
            name = "repl"
            args = ["python", "-c", "print('bar')"]
            """
        )
    )
    assert (
        tuple(
            [
                Command(
                    "repl",
                    args=("python", "-c", "print('bar')"),
                    when=Marker(f"sys_platform == '{sys.platform}'"),
                )
            ]
        )
        == config.commands
    )


def test_when_command_mutex_enforced(parse_config: ConfigurationParser) -> None:
    with pytest.raises(
        InvalidModelError,
        match=re.escape(
            f"The command 'repl-bar' collides with command 'repl-foo'.{os.linesep}"
            f"You can define a command multiple times, but you must ensure the commands all define "
            f"mutually exclusive `when` marker expressions."
        ),
    ):
        parse_config(
            dedent(
                f"""\
                [tool.dev-cmd.commands.repl-foo]
                when = "python_version == '{".".join(map(str, sys.version_info[:2]))}'"
                name = "repl"
                args = ["python", "-c", "print('foo')"]

                [tool.dev-cmd.commands.repl-bar]
                when = "sys_platform == '{sys.platform}'"
                name = "repl"
                args = ["python", "-c", "print('bar')"]
                """
            )
        )


def test_when_selects_task(parse_config: ConfigurationParser) -> None:
    config = parse_config(
        dedent(
            f"""\
            [tool.dev-cmd.commands]
            pyver = ["python", "-V"]
            repl = ["python"]

            [tool.dev-cmd.tasks.mutex-foo]
            when = "sys_platform != '{sys.platform}'"
            name = "mutex"
            steps = ["pyver", "repl"]
            description = "Did not expect foo to be selected."

            [tool.dev-cmd.tasks.mutex-bar]
            when = "sys_platform == '{sys.platform}'"
            name = "mutex"
            steps = ["pyver", "repl"]
            description = "Expected bar to be selected."
            """
        )
    )
    pyver = Command("pyver", args=("python", "-V"))
    repl = Command("repl", args=tuple(["python"]))
    assert (pyver, repl) == config.commands
    assert (
        tuple(
            [
                Task(
                    "mutex",
                    steps=Group(members=tuple([pyver, repl])),
                    when=Marker(f"sys_platform == '{sys.platform}'"),
                    description="Expected bar to be selected.",
                )
            ]
        )
        == config.tasks
    )


def test_when_task_mutex_enforced(parse_config: ConfigurationParser) -> None:
    with pytest.raises(
        InvalidModelError,
        match=re.escape(
            f"The task 'mutex-bar' collides with task 'mutex-foo'.{os.linesep}"
            f"You can define a task multiple times, but you must ensure the tasks all define "
            f"mutually exclusive `when` marker expressions."
        ),
    ):
        parse_config(
            dedent(
                f"""\
                [tool.dev-cmd.commands]
                pyver = ["python", "-V"]
                repl = ["python"]

                [tool.dev-cmd.tasks.mutex-foo]
                when = "sys_platform == '{sys.platform}'"
                name = "mutex"
                steps = ["pyver", "repl"]
                description = "Did not expect foo to be selected."

                [tool.dev-cmd.tasks.mutex-bar]
                when = "sys_platform == '{sys.platform}'"
                name = "mutex"
                steps = ["pyver", "repl"]
                description = "Expected bar to be selected."
                """
            )
        )


def test_discard_empty(parse_config: ConfigurationParser) -> None:
    config = dedent(
        """
        [tool.dev-cmd.commands]
        example = [
            "python",
            {discard_empty = "{-warnings_as_errors?-Werror:}"},
            "-c",
            "print('Hello World!')"
        ]
        """
    )
    assert (
        tuple([Command("example", ("python", "-c", "print('Hello World!')"))])
        == parse_config(config).commands
    )
    assert (
        tuple(
            [
                Command(
                    "example-warnings_as_errors",
                    ("python", "-Werror", "-c", "print('Hello World!')"),
                )
            ]
        )
        == parse_config(config, "example-warnings_as_errors").commands
    )
