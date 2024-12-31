# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Container


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

    def accepts_extra_args(self, skips: Container[str]) -> Command | None:
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
class Configuration:
    commands: tuple[Command, ...]
    tasks: tuple[Task, ...]
    default: Command | Task | None = None
    exit_style: ExitStyle | None = None
    grace_period: float | None = None
    source: Any = "<code>"
