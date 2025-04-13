# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import os
import sys
import time
from asyncio import CancelledError
from asyncio.subprocess import Process
from asyncio.tasks import Task as AsyncTask
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Container, Iterator, Mapping

from dev_cmd import color
from dev_cmd.color import USE_COLOR
from dev_cmd.console import Console
from dev_cmd.errors import ExecutionError, InvalidModelError
from dev_cmd.model import Command, ExitStyle, Group, Task, VenvConfig
from dev_cmd.venv import Venv


def _step_prefix(step_name: str | None, serial: bool) -> str:
    if serial and not step_name:
        return f"{color.cyan('dev-cmd')}]"
    return color.cyan(f"dev-cmd {color.bold(step_name or '*')}]")


@asynccontextmanager
async def _guarded_stdin() -> AsyncIterator[None]:
    # N.B.: This allows interactive async processes to properly read from stdin.
    # TODO(John Sirois): Come to understand why this works.
    sys.stdin = os.devnull
    try:
        yield
    finally:
        sys.stdin = sys.__stdin__


@dataclass
class Invocation:
    @classmethod
    def create(
        cls,
        *steps: Command | Task,
        skips: Container[str],
        grace_period: float,
        timings: bool = False,
        console: Console = Console(),
    ) -> Invocation:
        accepts_extra_args: Command | None = None
        for step in steps:
            if step.name in skips:
                continue
            if isinstance(step, Command):
                if not step.accepts_extra_args:
                    continue
                if accepts_extra_args and accepts_extra_args not in (step.base, step):
                    raise InvalidModelError(
                        f"The command {step.name!r} accepts extra args, but only one command can "
                        f"accept extra args per invocation and command "
                        f"{accepts_extra_args.name!r} already does."
                    )
                accepts_extra_args = step.base or step
            elif commands := tuple(step.accepts_extra_args(skips)):
                for command in commands:
                    if accepts_extra_args and accepts_extra_args not in (command.base, command):
                        raise InvalidModelError(
                            f"The task {step.name!r} invokes command {command.name!r} which accepts extra "
                            f"args, but only one command can accept extra args per invocation and command "
                            f"{accepts_extra_args.name!r} already does."
                        )
                    accepts_extra_args = command.base or command

        return cls(
            steps=tuple(step for step in steps if step.name not in skips),
            skips=skips,
            accepts_extra_args=accepts_extra_args is not None,
            grace_period=grace_period,
            timings=timings,
            venvs={},
            console=console,
        )

    steps: tuple[Command | Task, ...]
    skips: Container[str]
    accepts_extra_args: bool
    grace_period: float
    timings: bool
    venvs: Mapping[VenvConfig, Venv]
    console: Console
    _in_flight_processes: dict[Process, Command] = field(default_factory=dict, init=False)

    def iter_commands(self) -> Iterator[Command]:
        for step in self.steps:
            if step.name in self.skips:
                continue
            elif isinstance(step, Command):
                yield step
            else:
                for command in step.iter_commands(self.skips):
                    yield command

    @asynccontextmanager
    async def _guarded_ctrl_c(self) -> AsyncIterator[None]:
        try:
            yield
        except (CancelledError, KeyboardInterrupt):
            await self._terminate_in_flight_processes()
            raise

    async def invoke(self, *extra_args: str, exit_style: ExitStyle = ExitStyle.AFTER_STEP) -> None:
        async with _guarded_stdin(), self._guarded_ctrl_c():
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
        async with _guarded_stdin(), self._guarded_ctrl_c():
            if error := await self._invoke_group(
                None, Group(members=self.steps), *extra_args, serial=False, exit_style=exit_style
            ):
                await self._terminate_in_flight_processes()
                raise error

    async def _terminate_in_flight_processes(self) -> None:
        while self._in_flight_processes:
            process, command = self._in_flight_processes.popitem()
            await self.console.aprint(
                color.color(
                    f"Terminating in-flight process {process.pid} of {command.name}...", fg="gray"
                )
            )
            if self.grace_period <= 0:
                process.kill()
                await process.wait()
            else:
                process.terminate()
                _, pending = await asyncio.wait(
                    [asyncio.create_task(process.wait())], timeout=self.grace_period
                )
                if pending:
                    await self.console.aprint(
                        color.yellow(
                            f"Process {process.pid} has not responded to a termination request after "
                            f"{self.grace_period:.2f}s, killing..."
                        )
                    )
                    process.kill()
                    await process.wait()

    def _python_for_command(self, command: Command) -> str:
        if command.python:
            return self.venvs[
                VenvConfig(python=command.python, dependency_group=command.dependency_group)
            ].python
        return sys.executable

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
        if command.python:
            self.venvs[
                VenvConfig(
                    python=command.python,
                    dependency_group=command.dependency_group,
                )
            ].update_path(env)

        if args[0].endswith(".py"):
            args.insert(0, self._python_for_command(command))
        elif "python" == args[0]:
            args[0] = self._python_for_command(command)

        process = await asyncio.create_subprocess_exec(
            args[0],
            *args[1:],
            cwd=command.cwd,
            env=env,
            **subprocess_kwargs,
        )
        self._in_flight_processes[process] = command
        return process

    async def _invoke_command_sync(
        self, command: Command, *extra_args, prefix: str | None = None
    ) -> ExecutionError | None:
        prefix = prefix or _step_prefix(step_name=None, serial=True)
        await self.console.aprint(
            f"{prefix} {color.magenta(f'Executing {color.bold(command.name)}...')}",
            use_stderr=True,
        )
        start = time.time()
        command_name_color = "red"
        try:
            process_or_error = await self._invoke_command(command, *extra_args)
            if isinstance(process_or_error, ExecutionError):
                return process_or_error

            returncode = await process_or_error.wait()
            self._in_flight_processes.pop(process_or_error, None)
            if returncode == 0:
                command_name_color = "magenta"
                return None

            return ExecutionError.from_failed_cmd(command, returncode)
        finally:
            if self.timings:
                timing = color.color(f"took {time.time() - start:.3f}s", fg="gray")
                await self.console.aprint(
                    f"{prefix} {color.color(f'{color.bold(command.name)} {timing}', fg=command_name_color)}"
                )

    async def _invoke_group(
        self,
        task_name: str | None,
        group: Group,
        *extra_args: str,
        serial: bool,
        exit_style: ExitStyle = ExitStyle.AFTER_STEP,
    ) -> ExecutionError | None:
        prefix = _step_prefix(task_name, serial)
        start = time.time()
        if serial:
            serial_errors: list[ExecutionError] = []
            for member in group.members:
                if isinstance(member, Command):
                    if member.name in self.skips:
                        continue
                    error = await self._invoke_command_sync(member, *extra_args, prefix=prefix)
                elif isinstance(member, Task):
                    if member.name in self.skips:
                        continue
                    error = await self._invoke_group(
                        member.name, member.steps, *extra_args, serial=True, exit_style=exit_style
                    )
                else:
                    group_serial = not serial
                    group_name: str | None = None
                    if task_name:
                        group_name = task_name if group_serial else f"*{task_name}"

                    error = await self._invoke_group(
                        group_name,
                        member,
                        *extra_args,
                        serial=group_serial,
                        exit_style=exit_style,
                    )
                if error:
                    if exit_style is ExitStyle.IMMEDIATE:
                        return error
                    serial_errors.append(error)

            if self.timings:
                timing = color.color(f"took {time.time() - start:.3f}s", fg="gray")
                await self.console.aprint(f"{prefix} {timing}")

            if len(serial_errors) == 1:
                return serial_errors[0]

            if serial_errors:
                return ExecutionError.from_errors(
                    step_name=task_name, total_count=len(group.members), errors=serial_errors
                )

            return None

        async def invoke_command_captured(
            command: Command,
        ) -> tuple[Command, int, bytes, float] | ExecutionError:
            command_start = time.time()
            proc_or_error = await self._invoke_command(
                command,
                *extra_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            if isinstance(proc_or_error, ExecutionError):
                return proc_or_error

            command_output, _ = await proc_or_error.communicate()
            command_elapsed = time.time() - command_start
            self._in_flight_processes.pop(proc_or_error, None)
            return command, await proc_or_error.wait(), command_output, command_elapsed

        async def iter_tasks(
            item: Command | Task | Group,
        ) -> AsyncIterator[AsyncTask[tuple[Command, int, bytes, float] | ExecutionError | None]]:
            if isinstance(item, Command):
                if item.name not in self.skips:
                    yield asyncio.create_task(invoke_command_captured(item))
            elif isinstance(item, Task):
                if item.name not in self.skips:
                    yield asyncio.create_task(
                        self._invoke_group(
                            item.name, item.steps, *extra_args, serial=True, exit_style=exit_style
                        )
                    )
            else:
                async_group_serial = not serial
                async_group_name: str | None = None
                if task_name:
                    async_group_name = task_name if async_group_serial else f"*{task_name}"

                yield asyncio.create_task(
                    self._invoke_group(
                        async_group_name,
                        item,
                        *extra_args,
                        serial=async_group_serial,
                        exit_style=exit_style,
                    )
                )

        parallel_steps = " ".join(
            f"{len(member.members)} serial steps" if isinstance(member, Group) else member.name
            for member in group.members
            if isinstance(member, Group) or member.name not in self.skips
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

            cmd, returncode, output, elapsed = result
            cmd_name = color.color(
                cmd.name, fg="magenta" if returncode == 0 else "red", style="bold"
            )
            if self.timings:
                await self.console.aprint(
                    f"{prefix} {cmd_name} {color.color(f'took {elapsed:.3f}s', fg='gray')}:",
                    use_stderr=True,
                )
            else:
                await self.console.aprint(f"{prefix} {cmd_name}:", use_stderr=True)
            await self.console.aprint(
                output.decode(errors="replace"), end="", use_stderr=True, force=True
            )
            if returncode != 0:
                error = ExecutionError.from_failed_cmd(cmd, returncode)
                if exit_style is ExitStyle.IMMEDIATE:
                    return error
                errors.append(error)

        if self.timings:
            timing = color.color(f"took {time.time() - start:.3f}s", fg="gray")
            await self.console.aprint(f"{prefix} {timing}")

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
