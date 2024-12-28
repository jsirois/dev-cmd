# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import itertools
import os
from asyncio.subprocess import Process
from asyncio.tasks import Task as AsyncTask
from dataclasses import dataclass
from subprocess import CalledProcessError
from typing import Any, AsyncIterator, Iterator

import aioconsole

from dev_cmd import color
from dev_cmd.color import USE_COLOR
from dev_cmd.errors import InvalidModelError, ParallelExecutionError
from dev_cmd.model import Command, Group, Task


def _flatten(step: Command | Group | Task) -> Iterator[Command | Group]:
    if isinstance(step, Task):
        for step in step.steps.members:
            yield from _flatten(step)
    else:
        yield step


async def _invoke_command(command: Command, *extra_args, **subprocess_kwargs: Any) -> Process:
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


def _step_prefix(step_name: str) -> str:
    return color.cyan(f"dev-cmd {color.bold(step_name)}]")


async def _invoke_command_sync(command: Command, *extra_args, prefix: str | None = None):
    prefix = prefix or _step_prefix(command.name)
    await aioconsole.aprint(
        f"{prefix} {color.magenta(f'Executing {color.bold(command.name)}...')}",
        use_stderr=True,
    )
    process = await _invoke_command(command, *extra_args)
    returncode = await process.wait()
    if returncode != 0:
        raise CalledProcessError(returncode=returncode, cmd=command.args)


async def _invoke_group(task_name: str, group: Group, *extra_args: str, serial: bool) -> None:
    prefix = _step_prefix(task_name)
    if serial:
        for member in group.members:
            if isinstance(member, Command):
                await _invoke_command_sync(member, *extra_args, prefix=prefix)
            elif isinstance(member, Task):
                await _invoke_group(task_name, member.steps, *extra_args, serial=True)
            else:
                await _invoke_group(task_name, member, *extra_args, serial=not serial)
        return

    async def invoke_command_captured(command: Command) -> tuple[Command, int, bytes]:
        proc = await _invoke_command(
            command, *extra_args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
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
                _invoke_group(task_name, item.steps, *extra_args, serial=True)
            )
        else:
            yield asyncio.create_task(
                _invoke_group(task_name, item, *extra_args, serial=not serial)
            )

    parallel_steps = " ".join(
        f"{len(member.members)} serial steps" if isinstance(member, Group) else member.name
        for member in group.members
    )
    message = f"Concurrently executing {color.bold(parallel_steps)}..."
    await aioconsole.aprint(f"{prefix} {color.magenta(message)}", use_stderr=True)
    errors: list[tuple[str, CalledProcessError]] = []
    for invoked in asyncio.as_completed([r for m in group.members async for r in iter_tasks(m)]):
        result = await invoked
        if not result:
            continue

        cmd, returncode, stdout = result
        if returncode != 0:
            errors.append((cmd.name, CalledProcessError(returncode=returncode, cmd=cmd.args)))
        cmd_name = color.color(cmd.name, fg="magenta" if returncode == 0 else "red", style="bold")
        await aioconsole.aprint(
            os.linesep.join((f"{prefix} {cmd_name}:", stdout.decode())), end="", use_stderr=True
        )
    if errors:
        lines = [f"{len(errors)} of {len(group.members)} parallel commands in {task_name} failed:"]
        lines.extend(f"{cmd}: {error}" for cmd, error in errors)
        raise ParallelExecutionError(os.linesep.join(lines))


@dataclass(frozen=True)
class Invocation:
    @classmethod
    def create(cls, *steps: Command | Task) -> Invocation:
        accepts_extra_args: Command | None = None
        for step in steps:
            if isinstance(step, Command):
                if not step.accepts_extra_args:
                    continue
                if accepts_extra_args and accepts_extra_args != step:
                    raise InvalidModelError(
                        f"The command {step.name!r} accepts extra args, but only one command can "
                        f"accept extra args per invocation and command "
                        f"{accepts_extra_args.name!r} already does."
                    )
                accepts_extra_args = step
            elif command := step.accepts_extra_args:
                if accepts_extra_args and accepts_extra_args != step:
                    raise InvalidModelError(
                        f"The task {step.name!r} invokes command {command.name!r} which accepts extra "
                        f"args, but only one command can accept extra args per invocation and command "
                        f"{accepts_extra_args.name!r} already does."
                    )
                accepts_extra_args = command

        return cls(steps=tuple(steps), accepts_extra_args=accepts_extra_args is not None)

    steps: tuple[Command | Task, ...]
    accepts_extra_args: bool

    async def invoke(self, *extra_args: str) -> None:
        for task in self.steps:
            if isinstance(task, Command):
                await _invoke_command_sync(task, *extra_args)
            else:
                await _invoke_group(task.name, task.steps, *extra_args, serial=True)

    async def invoke_parallel(self, *extra_args: str) -> None:
        await _invoke_group(
            "*",
            Group(
                members=tuple(itertools.chain.from_iterable(_flatten(task) for task in self.steps))
            ),
            *extra_args,
            serial=False,
        )
