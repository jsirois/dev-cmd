# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import itertools
import os
from asyncio.subprocess import Process
from asyncio.tasks import Task as AsyncTask
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator

from dev_cmd import color
from dev_cmd.color import USE_COLOR
from dev_cmd.console import Console
from dev_cmd.errors import ExecutionError, InvalidModelError
from dev_cmd.model import Command, ExitStyle, Group, Task


def _flatten(step: Command | Group | Task) -> Iterator[Command | Group]:
    if isinstance(step, Task):
        for step in step.steps.members:
            yield from _flatten(step)
    else:
        yield step


def _step_prefix(step_name: str) -> str:
    return color.cyan(f"dev-cmd {color.bold(step_name)}]")


@dataclass
class Invocation:
    @classmethod
    def create(
        cls, *steps: Command | Task, grace_period: float, console: Console = Console()
    ) -> Invocation:
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

        return cls(
            steps=tuple(steps),
            accepts_extra_args=accepts_extra_args is not None,
            grace_period=grace_period,
            console=console,
        )

    steps: tuple[Command | Task, ...]
    accepts_extra_args: bool
    grace_period: float
    console: Console
    _in_flight_processes: set[Process] = field(default_factory=set, init=False)

    async def invoke(self, *extra_args: str, exit_style: ExitStyle = ExitStyle.AFTER_STEP) -> None:
        errors: list[ExecutionError] = []
        for task in self.steps:
            if isinstance(task, Command):
                error = await self._invoke_command_sync(task, *extra_args)
            else:
                error = await self._invoke_group(
                    task.name, task.steps, *extra_args, serial=True, exit_style=exit_style
                )
            if error is None:
                continue
            if exit_style in (ExitStyle.IMMEDIATE, ExitStyle.AFTER_STEP):
                await self._terminate_in_flight_processes()
                raise error
            errors.append(error)

        if len(errors) == 1:
            await self._terminate_in_flight_processes()
            raise errors[0]

        if errors:
            await self._terminate_in_flight_processes()
            raise ExecutionError.from_errors(
                step_name=f"dev-cmd {' '.join(step.name for step in self.steps)}",
                total_count=len(self.steps),
                errors=errors,
            )

    async def invoke_parallel(
        self, *extra_args: str, exit_style: ExitStyle = ExitStyle.AFTER_STEP
    ) -> None:
        if error := await self._invoke_group(
            "*",
            Group(
                members=tuple(itertools.chain.from_iterable(_flatten(task) for task in self.steps))
            ),
            *extra_args,
            serial=False,
            exit_style=exit_style,
        ):
            await self._terminate_in_flight_processes()
            raise error

    async def _terminate_in_flight_processes(self) -> None:
        while self._in_flight_processes:
            process = self._in_flight_processes.pop()
            if self.grace_period <= 0:
                process.kill()
                await process.wait()
            else:
                process.terminate()
                _, pending = await asyncio.wait(
                    [asyncio.create_task(process.wait())], timeout=self.grace_period
                )
                if pending:
                    self.console.print(
                        color.yellow(
                            f"Process {process.pid} has not responded to a termination request after "
                            f"{self.grace_period:.2f}s, killing..."
                        )
                    )
                    process.kill()
                    await process.wait()

    async def _invoke_command(
        self, command: Command, *extra_args, **subprocess_kwargs: Any
    ) -> Process | ExecutionError:
        if command.cwd and not os.path.exists(command.cwd):
            return ExecutionError(
                command.name,
                f"The `cwd` for command {command.name!r} does not exist: {command.cwd}",
            )

        args = list(command.args)
        if extra_args and command.accepts_extra_args:
            args.extend(extra_args)

        env = os.environ.copy()
        env.update(command.extra_env)
        if USE_COLOR and not any(color_env in env for color_env in ("PYTHON_COLORS", "NO_COLOR")):
            env.setdefault("FORCE_COLOR", "1")

        process = await asyncio.create_subprocess_exec(
            args[0],
            *args[1:],
            cwd=command.cwd,
            env=env,
            **subprocess_kwargs,
        )
        self._in_flight_processes.add(process)
        return process

    async def _invoke_command_sync(
        self, command: Command, *extra_args, prefix: str | None = None
    ) -> ExecutionError | None:
        prefix = prefix or _step_prefix(command.name)
        await self.console.aprint(
            f"{prefix} {color.magenta(f'Executing {color.bold(command.name)}...')}",
            use_stderr=True,
        )
        process_or_error = await self._invoke_command(command, *extra_args)
        if isinstance(process_or_error, ExecutionError):
            return process_or_error

        returncode = await process_or_error.wait()
        self._in_flight_processes.discard(process_or_error)
        if returncode == 0:
            return None

        return ExecutionError.from_failed_cmd(command, returncode)

    async def _invoke_group(
        self,
        task_name: str,
        group: Group,
        *extra_args: str,
        serial: bool,
        exit_style: ExitStyle = ExitStyle.AFTER_STEP,
    ) -> ExecutionError | None:
        prefix = _step_prefix(task_name)
        if serial:
            serial_errors: list[ExecutionError] = []
            for member in group.members:
                if isinstance(member, Command):
                    error = await self._invoke_command_sync(member, *extra_args, prefix=prefix)
                elif isinstance(member, Task):
                    error = await self._invoke_group(
                        task_name, member.steps, *extra_args, serial=True, exit_style=exit_style
                    )
                else:
                    error = await self._invoke_group(
                        task_name, member, *extra_args, serial=not serial, exit_style=exit_style
                    )
                if error:
                    if exit_style is ExitStyle.IMMEDIATE:
                        return error
                    serial_errors.append(error)

            if len(serial_errors) == 1:
                return serial_errors[0]

            if serial_errors:
                return ExecutionError.from_errors(
                    step_name=task_name, total_count=len(group.members), errors=serial_errors
                )

            return None

        async def invoke_command_captured(
            command: Command,
        ) -> tuple[Command, int, bytes] | ExecutionError:
            proc_or_error = await self._invoke_command(
                command,
                *extra_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            if isinstance(proc_or_error, ExecutionError):
                return proc_or_error

            output, _ = await proc_or_error.communicate()
            self._in_flight_processes.discard(proc_or_error)
            return command, await proc_or_error.wait(), output

        async def iter_tasks(
            item: Command | Task | Group,
        ) -> AsyncIterator[AsyncTask[tuple[Command, int, bytes] | ExecutionError | None]]:
            if isinstance(item, Command):
                yield asyncio.create_task(invoke_command_captured(item))
            elif isinstance(item, Task):
                yield asyncio.create_task(
                    self._invoke_group(
                        task_name, item.steps, *extra_args, serial=True, exit_style=exit_style
                    )
                )
            else:
                yield asyncio.create_task(
                    self._invoke_group(
                        task_name, item, *extra_args, serial=not serial, exit_style=exit_style
                    )
                )

        parallel_steps = " ".join(
            f"{len(member.members)} serial steps" if isinstance(member, Group) else member.name
            for member in group.members
        )
        message = f"Concurrently executing {color.bold(parallel_steps)}..."
        await self.console.aprint(f"{prefix} {color.magenta(message)}", use_stderr=True)

        errors: list[ExecutionError] = []
        for invoked in asyncio.as_completed(
            [r for m in group.members async for r in iter_tasks(m)]
        ):
            result = await invoked
            if result is None:
                continue

            if isinstance(result, ExecutionError):
                if exit_style is ExitStyle.IMMEDIATE:
                    return result
                errors.append(result)
                continue

            cmd, returncode, stdout = result
            cmd_name = color.color(
                cmd.name, fg="magenta" if returncode == 0 else "red", style="bold"
            )
            await self.console.aprint(f"{prefix} {cmd_name}:", use_stderr=True)
            await self.console.aprint(stdout.decode(), end="", use_stderr=True, force=True)
            if returncode != 0:
                error = ExecutionError.from_failed_cmd(cmd, returncode)
                if exit_style is ExitStyle.IMMEDIATE:
                    return error
                errors.append(error)

        if len(errors) == 1:
            return errors[0]

        if errors:
            return ExecutionError.from_errors(
                step_name=task_name,
                total_count=len(group.members),
                errors=tuple(errors),
                parallel=True,
            )

        return None
