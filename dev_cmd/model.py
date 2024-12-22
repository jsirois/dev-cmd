# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from dev_cmd.errors import InvalidModelError


@dataclass(frozen=True)
class Command:
    name: str
    env: Mapping[str, str]
    args: Tuple[str, ...]
    accepts_extra_args: bool


@dataclass(frozen=True)
class Dev:
    commands: Mapping[str, Command]
    aliases: Mapping[str, Tuple[Command, ...]]
    default: Optional[Tuple[str, Tuple[Command, ...]]] = None
    source: Any = "<code>"


@dataclass(frozen=True)
class Invocation:
    @classmethod
    def create(cls, *tasks: Tuple[str, Iterable[Command]]) -> Invocation:
        _tasks: Dict[str, Tuple[Command, ...]] = {}
        accepts_extra_args: Optional[Command] = None
        for task, commands in tasks:
            _tasks[task] = tuple(commands)
            for command in commands:
                if command.accepts_extra_args:
                    if accepts_extra_args is not None:
                        raise InvalidModelError(
                            f"The command {command.name!r} accepts extra args, but only one "
                            f"command can accept extra args per invocation and command "
                            f"{accepts_extra_args.name!r} already does."
                        )
                    accepts_extra_args = command

        return cls(tasks=_tasks, accepts_extra_args=accepts_extra_args is not None)

    tasks: Mapping[str, Tuple[Command, ...]]
    accepts_extra_args: bool
