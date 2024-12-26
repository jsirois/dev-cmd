# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import os
import sys
from argparse import ArgumentParser
from asyncio.subprocess import Process
from functools import cache
from subprocess import CalledProcessError
from typing import Any, Iterable

import aioconsole
from colors import colors

from dev_cmd import __version__
from dev_cmd.errors import DevError, InvalidArgumentError, InvalidModelError, ParallelExecutionError
from dev_cmd.model import Command, Dev, Invocation
from dev_cmd.parse import parse_dev_config
from dev_cmd.project import find_pyproject_toml


@cache
def _is_color() -> bool:
    # Used in Python 3.13+
    python_colors = os.environ.get("PYTHON_COLORS")
    if python_colors in ("0", "1"):
        return python_colors == "1"

    # A common convention; see: https://no-color.org/
    if "NO_COLOR" in os.environ:
        return False

    # A less common convention; see: https://force-color.org/
    if "FORCE_COLOR" in os.environ:
        return True

    return sys.stderr.isatty() and "dumb" != os.environ.get("TERM")


async def _invoke_command(
    command: Command, extra_args: Iterable[str] = (), **subprocess_kwargs: Any
) -> Process:
    args = list(command.args)
    if extra_args and command.accepts_extra_args:
        args.extend(extra_args)

    if not os.path.exists(command.cwd):
        raise InvalidModelError(
            f"The `cwd` for command {command.name!r} does not exist: {command.cwd}"
        )

    env = dict(command.env)
    if _is_color() and not any(
        color_env in env for color_env in ("PYTHON_COLORS", "NO_COLOR", "FORCE_COLOR")
    ):
        env["FORCE_COLOR"] = "1"

    return await asyncio.create_subprocess_exec(
        args[0],
        *args[1:],
        cwd=command.cwd,
        env=env,
        **subprocess_kwargs,
    )


async def _invoke(invocation: Invocation, extra_args: Iterable[str] = ()) -> None:
    for task, commands in invocation.tasks.items():
        prefix = colors.cyan(f"dev-cmd {colors.bold(task)}]")
        for command in commands:
            if isinstance(command, Command):
                await aioconsole.aprint(
                    f"{prefix} {colors.magenta(f'Executing {colors.bold(command.name)}...')}",
                    use_stderr=True,
                )
                process = await _invoke_command(command, extra_args)
                returncode = await process.wait()
                if returncode != 0:
                    raise CalledProcessError(returncode=returncode, cmd=command.args)
            else:
                message = colors.magenta(
                    f"Parallelizing {len(command)} commands: "
                    f"{colors.bold(' '.join(cmd.name for cmd in command))}"
                )
                await aioconsole.aprint(f"{prefix} {message}...", use_stderr=True)

                async def invoke(_cmd: Command) -> tuple[Command, int, bytes]:
                    proc = await _invoke_command(
                        _cmd,
                        extra_args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    output, _ = await proc.communicate()
                    return _cmd, await proc.wait(), output

                errors: list[tuple[str, CalledProcessError]] = []
                for invoked in asyncio.as_completed(map(invoke, command)):
                    cmd, returncode, stdout = await invoked
                    if returncode != 0:
                        errors.append(
                            (
                                cmd.name,
                                CalledProcessError(returncode=returncode, cmd=cmd.args),
                            )
                        )
                    cmd_name = colors.color(
                        cmd.name, fg="magenta" if returncode == 0 else "red", style="bold"
                    )
                    await aioconsole.aprint(f"{prefix} {cmd_name}:", use_stderr=True)
                    await aioconsole.aprint(stdout.decode(), end="", use_stderr=True)
                if errors:
                    lines = [f"{len(errors)} of {len(command)} parallel commands in {task} failed:"]
                    lines.extend(f"{cmd}: {error}" for cmd, error in errors)
                    raise ParallelExecutionError(os.linesep.join(lines))


def _run(dev: Dev, *tasks: str, extra_args: Iterable[str] = ()) -> None:
    if tasks:
        try:
            invocation = Invocation.create(
                *[(task, (dev.tasks.get(task) or [dev.commands[task]])) for task in tasks]
            )
        except KeyError as e:
            raise InvalidArgumentError(
                os.linesep.join(
                    (
                        f"A requested task is not defined in {dev.source}: {e}",
                        "",
                        f"Available tasks: {' '.join(sorted(dev.tasks))}",
                        f"Available commands: {' '.join(sorted(dev.commands))}",
                    )
                )
            )
    elif dev.default:
        name, commands = dev.default
        invocation = Invocation.create((name, commands))
    else:
        raise InvalidArgumentError(
            os.linesep.join(
                (
                    f"usage: {sys.argv[0]} task|cmd [task|cmd...]",
                    "",
                    f"Available tasks: {' '.join(sorted(dev.tasks))}",
                    f"Available commands: {' '.join(sorted(dev.commands))}",
                )
            )
        )

    if extra_args and not invocation.accepts_extra_args:
        raise InvalidArgumentError(
            f"The following extra args were passed but none of the selected commands accept extra "
            f"arguments: {extra_args}"
        )

    return asyncio.run(_invoke(invocation, extra_args))


def _parse_args() -> tuple[list[str], list[str]]:
    parser = ArgumentParser(
        description=(
            "A simple command runner to help running development tools easily and consistently."
        )
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "tasks",
        nargs="*",
        metavar="cmd|task",
        help=(
            "One or more names of commands or tasks to run that are defined in the "
            "[tool.dev-cmd] section of `pyproject.toml`. If no tasks are passed and a "
            "[tool.dev-cmd] `default` is defined or there is only one command defined, that is run."
        ),
    )

    args: list[str] = []
    extra_args: list[str] | None = None
    for arg in sys.argv[1:]:
        if "--" == arg:
            extra_args = []
        elif extra_args is not None:
            extra_args.append(arg)
        else:
            args.append(arg)

    options = parser.parse_args(args)
    return options.tasks, extra_args if extra_args is not None else []


def main() -> Any:
    tasks, extra_args = _parse_args()
    try:
        pyproject_toml = find_pyproject_toml()
        dev = parse_dev_config(pyproject_toml)
        return _run(dev, *tasks, extra_args=extra_args)
    except DevError as e:
        return f"{colors.red('Configuration error')}: {colors.yellow(str(e))}"
    except (OSError, CalledProcessError, ParallelExecutionError) as e:
        return colors.red(str(e))


if __name__ == "__main__":
    sys.exit(main())
