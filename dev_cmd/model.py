# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Container, Mapping, MutableMapping

from packaging.markers import Marker


class Factor(str):
    pass


@dataclass(frozen=True)
class FactorDescription:
    factor: Factor
    default: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Python:
    spec: str

    def resolve(self) -> str:
        return re.sub(r"^\d(\.\d{1,2})?$", r"python\g<0>", self.spec)

    def __str__(self) -> str:
        return self.spec


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]
    extra_env: tuple[tuple[str, str], ...] = ()
    cwd: PurePath | None = None
    accepts_extra_args: bool = False
    base: Command | None = None
    hidden: bool = False
    description: str | None = None
    factor_descriptions: tuple[FactorDescription, ...] = ()
    when: Marker | None = None
    python: Python | None = None


@dataclass(frozen=True)
class Group:
    members: tuple[Command | Task | Group, ...]

    def accepts_extra_args(self, skips: Container[str]) -> Command | None:
        for member in self.members:
            if isinstance(member, Command):
                if member.accepts_extra_args and member.name not in skips:
                    return member
            elif command := member.accepts_extra_args(skips):
                return command
        return None


@dataclass(frozen=True)
class Task:
    name: str
    steps: Group
    hidden: bool = False
    description: str | None = None
    when: Marker | None = None

    def accepts_extra_args(self, skips: Container[str] = ()) -> Command | None:
        if self.name in skips:
            return None
        return self.steps.accepts_extra_args(skips)


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
class Configuration:
    commands: tuple[Command, ...]
    tasks: tuple[Task, ...]
    default: Command | Task | None = None
    exit_style: ExitStyle | None = None
    grace_period: float | None = None
    venv: Venv | None = None
    pythons: tuple[PythonConfig, ...] = ()
    source: Any = "<code>"
