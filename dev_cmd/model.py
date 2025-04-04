# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Container, Iterable, Mapping, MutableMapping

from packaging.markers import Marker


class Factor(str):
    pass


@dataclass(frozen=True)
class FactorDescription:
    factor: Factor
    default: str | None = None
    description: str | None = None


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
class ExtraRequirements:
    @classmethod
    def create(
        cls,
        reqs: Iterable[str] | None = None,
        pip_req: str | None = None,
        install_opts: Iterable[str] | None = None,
    ) -> ExtraRequirements:
        return cls(
            reqs=tuple(reqs or ["-e", "."]),
            pip_req=pip_req or "pip",
            install_opts=tuple(install_opts) if install_opts else (),
        )

    reqs: tuple[str, ...]
    pip_req: str
    install_opts: tuple[str, ...]


@dataclass(frozen=True)
class PythonConfig:
    input_data: bytes
    input_files: tuple[str, ...]
    requirements_export_command: tuple[str, ...]
    extra_requirements: ExtraRequirements


@dataclass(frozen=True)
class Venv:
    dir: str
    python: str
    bin_path: str
    marker_environment: Mapping[str, str]

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
    source: Any = "<code>"
