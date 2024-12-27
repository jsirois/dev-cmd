# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import os
from asyncio.subprocess import Process
from asyncio.tasks import Task as AsyncTask
from dataclasses import dataclass
from subprocess import CalledProcessError
from typing import Any, AsyncIterator

import aioconsole

from dev_cmd import color
from dev_cmd.color import USE_COLOR
from dev_cmd.errors import InvalidModelError, ParallelExecutionError
from dev_cmd.model import Command, Group, Task


@dataclass
class ExtraArgsChecker:
    accepts_extra_args: Command | None = None

    def check_command(self, command: Command) -> None:
        if command.accepts_extra_args:
            if self.accepts_extra_args and self.accepts_extra_args != command:
                raise InvalidModelError(
                    f"The command {command.name!r} accepts extra args, but only one command can "
                    f"accept extra args per invocation and command "
                    f"{self.accepts_extra_args.name!r} already does."
                )
            self.accepts_extra_args = command

    def check_task(self, task: Task) -> None:
        if command := task.accepts_extra_args:
            if self.accepts_extra_args and self.accepts_extra_args != command:
                raise InvalidModelError(
                    f"The task {task.name!r} invokes command {command.name!r} which accepts extra "
                    f"args, but only one command can accept extra args per invocation and command "
                    f"{self.accepts_extra_args.name!r} already does."
                )
            self.accepts_extra_args = command


@dataclass(frozen=True)
class Invocation:
    @classmethod
    def create(cls, *commands_and_tasks: Command | Task) -> Invocation:
        tasks: list[Task] = []
        extra_args_checker = ExtraArgsChecker()
        for command_or_task in commands_and_tasks:
            if isinstance(command_or_task, Command):
                extra_args_checker.check_command(command_or_task)
                tasks.append(Task(name=command_or_task.name, steps=Group(tuple([command_or_task]))))
            else:
                extra_args_checker.check_task(command_or_task)
                tasks.append(command_or_task)

        return cls(
            tasks=tuple(tasks),
            accepts_extra_args=extra_args_checker.accepts_extra_args is not None,
        )

    tasks: tuple[Task, ...]
    accepts_extra_args: bool

    async def _invoke_command(
        self, command: Command, *extra_args, **subprocess_kwargs: Any
    ) -> Process:
        args = list(command.args)
        if extra_args and command.accepts_extra_args:
            args.extend(extra_args)

        if command.cwd and not os.path.exists(command.cwd):
            raise InvalidModelError(
                f"The `cwd` for command {command.name!r} does not exist: {command.cwd}"
            )

        env = os.environ.copy()
        env.update(command.extra_env)
        if USE_COLOR and not any(color_env in env for color_env in ("PYTHON_COLORS", "NO_COLOR")):
            env.setdefault("FORCE_COLOR", "1")

        return await asyncio.create_subprocess_exec(
            args[0],
            *args[1:],
            cwd=command.cwd,
            env=env,
            **subprocess_kwargs,
        )

    async def _invoke_group(
        self, task_name: str, group: Group, *extra_args: str, serial: bool
    ) -> None:
        prefix = color.cyan(f"dev-cmd {color.bold(task_name)}]")
        if serial:
            for member in group.members:
                if isinstance(member, Command):
                    await aioconsole.aprint(
                        f"{prefix} {color.magenta(f'Executing {color.bold(member.name)}...')}",
                        use_stderr=True,
                    )
                    process = await self._invoke_command(member, *extra_args)
                    returncode = await process.wait()
                    if returncode != 0:
                        raise CalledProcessError(returncode=returncode, cmd=member.args)
                elif isinstance(member, Task):
                    await self._invoke_group(task_name, member.steps, *extra_args, serial=True)
                else:
                    await self._invoke_group(task_name, member, *extra_args, serial=not serial)
        else:

            async def invoke_command_captured(command: Command) -> tuple[Command, int, bytes]:
                proc = await self._invoke_command(
                    command,
                    *extra_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                output, _ = await proc.communicate()
                return command, await proc.wait(), output

            async def iter_tasks(
                item: Command | Task | Group,
            ) -> AsyncIterator[AsyncTask[tuple[Command, int, bytes] | None]]:
                if isinstance(item, Command):
                    yield asyncio.create_task(invoke_command_captured(item))
                elif isinstance(item, Task):
                    yield asyncio.create_task(
                        self._invoke_group(task_name, item.steps, *extra_args, serial=True)
                    )
                else:
                    yield asyncio.create_task(
                        self._invoke_group(task_name, item, *extra_args, serial=not serial)
                    )

            parallel_steps = " ".join(
                f"{len(member.members)} serial steps" if isinstance(member, Group) else member.name
                for member in group.members
            )
            message = f"Concurrently executing {color.bold(parallel_steps)}..."
            await aioconsole.aprint(f"{prefix} {color.magenta(message)}", use_stderr=True)
            errors: list[tuple[str, CalledProcessError]] = []
            for invoked in asyncio.as_completed(
                [r for m in group.members async for r in iter_tasks(m)]
            ):
                result = await invoked
                if not result:
                    continue

                cmd, returncode, stdout = result
                if returncode != 0:
                    errors.append(
                        (
                            cmd.name,
                            CalledProcessError(returncode=returncode, cmd=cmd.args),
                        )
                    )
                cmd_name = color.color(
                    cmd.name, fg="magenta" if returncode == 0 else "red", style="bold"
                )
                await aioconsole.aprint(f"{prefix} {cmd_name}:", use_stderr=True)
                await aioconsole.aprint(stdout.decode(), end="", use_stderr=True)
            if errors:
                lines = [
                    f"{len(errors)} of {len(group.members)} parallel commands in {task_name} "
                    f"failed:"
                ]
                lines.extend(f"{cmd}: {error}" for cmd, error in errors)
                raise ParallelExecutionError(os.linesep.join(lines))

    async def invoke(self, *extra_args: str) -> None:
        for task in self.tasks:
            await self._invoke_group(task.name, task.steps, *extra_args, serial=True)

    async def invoke_parallel(self, *extra_args: str) -> None:
        await self._invoke_group("*", Group(self.tasks), *extra_args, serial=False)
