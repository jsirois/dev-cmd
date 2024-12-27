# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import PurePath
from typing import Any


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]
    extra_env: tuple[tuple[str, str], ...] = ()
    cwd: PurePath | None = None
    accepts_extra_args: bool = False


@dataclass(frozen=True)
class Group:
    members: tuple[Command | Task | Group, ...]

    @cached_property
    def accepts_extra_args(self) -> Command | None:
        for member in self.members:
            if member.accepts_extra_args:
                if isinstance(member, Command):
                    return member
                else:
                    return member.accepts_extra_args
        return None


@dataclass(frozen=True)
class Task:
    name: str
    steps: Group

    @cached_property
    def accepts_extra_args(self) -> Command | None:
        return self.steps.accepts_extra_args


@dataclass(frozen=True)
class Dev:
    commands: tuple[Command, ...]
    tasks: tuple[Task, ...]
    default: Command | Task | None = None
    source: Any = "<code>"
