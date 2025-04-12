# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePath
from typing import Any, Container, Iterator, Mapping, MutableMapping

from packaging.markers import Marker


class Factor(str):
    pass


@dataclass(frozen=True)
class FactorDescription:
    factor: Factor
    flag_value: str | None = None
    default: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Python:
    @classmethod
    def parse(cls, value: str, from_py_factor: bool) -> Python:
        # Allow -py factors to indicate pypy succinctly, matching tox behavior:
        # +       -pypy (-py:py) -> pypy
        # +     -pypy3 (-py:py3) -> pypy3
        # + -pypy310 (-py:py310) -> pypy3.10
        if not value or not from_py_factor or not re.match(r"^py(\d{1,3}|\d\.\d{1,2})?$", value):
            return cls(value)
        return cls("py" + value, implementation_name="pypy")

    spec: str
    implementation_name: str = "python"

    def resolve(self) -> str:
        def _expand(match: re.Match[str]) -> str:
            version = match[1]
            if len(version) > 1 and "." not in version:
                version = f"{version[0]}.{version[1:]}"
            return f"{self.implementation_name}{version}"

        return re.sub(
            rf"^(?:{self.implementation_name})?(\d{{1,3}}|\d\.\d{{1,2}})$", _expand, self.spec
        )

    def __str__(self) -> str:
        return self.spec


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]
    extra_env: tuple[tuple[str, str], ...] = ()
    cwd: PurePath | None = None
    accepts_extra_args: bool = False
    hidden: bool = False
    description: str | None = None
    when: Marker | None = None
    dependency_group: str | None = None
    python: Python | None = field(default=None, compare=False)
    factor_descriptions: tuple[FactorDescription, ...] = field(default=(), compare=False)
    base: Command | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Group:
    members: tuple[Command | Task | Group, ...]

    def iter_commands(self, skips: Container[str]) -> Iterator[Command]:
        for member in self.members:
            if isinstance(member, Command):
                if member.name not in skips:
                    yield member
            else:
                for command in member.iter_commands(skips):
                    yield command


@dataclass(frozen=True)
class Task:
    name: str
    steps: Group
    hidden: bool = False
    description: str | None = None
    when: Marker | None = None

    def accepts_extra_args(self, skips: Container[str] = ()) -> Iterator[Command]:
        for command in self.iter_commands(skips):
            if command.accepts_extra_args:
                yield command

    def iter_commands(self, skips: Container[str]) -> Iterator[Command]:
        if self.name not in skips:
            for command in self.steps.iter_commands(skips):
                yield command


class ExitStyle(Enum):
    AFTER_STEP = "after-step"
    IMMEDIATE = "immediate"
    END = "end"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CacheKeyInputs:
    pyproject_data: Mapping[str, Any]
    envs: Mapping[str, str | None]
    paths: tuple[str, ...]


@dataclass(frozen=True)
class PythonConfig:
    when: Marker | None
    cache_key_inputs: CacheKeyInputs
    thirdparty_export_command: Command
    thirdparty_pip_install_opts: tuple[str, ...]
    pip_requirement: str
    extra_requirements: tuple[str, ...] | str
    extra_requirements_pip_install_opts: tuple[str, ...]
    finalize_command: Command | None


@dataclass(frozen=True)
class Venv:
    dir: str
    python: str
    marker_environment: Mapping[str, str]

    @property
    def bin_path(self) -> str:
        return os.path.dirname(self.python)

    def update_path(self, env: MutableMapping[str, str]) -> None:
        path = env.pop("PATH", None)
        env["PATH"] = (self.bin_path + os.pathsep + path) if path else self.bin_path


@dataclass(frozen=True)
class VenvConfig:
    python: Python
    dependency_group: str | None = None


@dataclass(frozen=True)
class Configuration:
    commands: tuple[Command, ...]
    tasks: tuple[Task, ...]
    default: Command | Task | None = None
    exit_style: ExitStyle | None = None
    grace_period: float | None = None
    venv: Venv | None = None
    pythons: tuple[PythonConfig, ...] = ()
    source: Any = "<code>"
