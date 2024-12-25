# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Iterable, Mapping

from dev_cmd.errors import InvalidModelError


@dataclass(frozen=True)
class Command:
    name: str
    env: Mapping[str, str]
    args: tuple[str, ...]
    cwd: PurePath
    accepts_extra_args: bool


@dataclass(frozen=True)
class Dev:
    commands: Mapping[str, Command]
    tasks: Mapping[str, tuple[Command | tuple[Command, ...], ...]]
    default: tuple[str, tuple[Command | tuple[Command, ...], ...]] | None = None
    source: Any = "<code>"


@dataclass
class ExtraArgsChecker:
    accepts_extra_args: Command | None = None

    def check(self, *commands: Command) -> None:
        for command in commands:
            if command.accepts_extra_args:
                if self.accepts_extra_args is not None:
                    raise InvalidModelError(
                        f"The command {command.name!r} accepts extra args, but only one "
                        f"command can accept extra args per invocation and command "
                        f"{self.accepts_extra_args.name!r} already does."
                    )
                self.accepts_extra_args = command


@dataclass(frozen=True)
class Invocation:
    @classmethod
    def create(cls, *tasks: tuple[str, Iterable[Command | Iterable[Command]]]) -> Invocation:
        _tasks: dict[str, tuple[Command | tuple[Command, ...], ...]] = {}
        extra_args_checker = ExtraArgsChecker()
        for task, commands in tasks:
            task_cmds: list[Command | tuple[Command, ...]] = []
            for command in commands:
                if isinstance(command, Command):
                    extra_args_checker.check(command)
                    task_cmds.append(command)
                else:
                    extra_args_checker.check(*command)
                    task_cmds.append(tuple(command))
            _tasks[task] = tuple(task_cmds)

        return cls(
            tasks=_tasks, accepts_extra_args=extra_args_checker.accepts_extra_args is not None
        )

    tasks: Mapping[str, tuple[Command | tuple[Command, ...], ...]]
    accepts_extra_args: bool
