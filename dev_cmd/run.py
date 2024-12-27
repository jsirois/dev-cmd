# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import os
import sys
from argparse import ArgumentParser
from subprocess import CalledProcessError
from typing import Any, Iterable

from dev_cmd import __version__, color
from dev_cmd.color import ColorChoice
from dev_cmd.errors import DevError, InvalidArgumentError, ParallelExecutionError
from dev_cmd.invoke import Invocation
from dev_cmd.model import Dev
from dev_cmd.parse import parse_dev_config
from dev_cmd.project import find_pyproject_toml


def _run(dev: Dev, *names: str, parallel: bool = False, extra_args: Iterable[str] = ()) -> None:
    if names:
        available_cmds = {cmd.name: cmd for cmd in dev.commands}
        available_tasks = {task.name: task for task in dev.tasks}
        try:
            invocation = Invocation.create(
                *(available_tasks.get(name) or available_cmds[name] for name in names),
            )
        except KeyError as e:
            raise InvalidArgumentError(
                os.linesep.join(
                    (
                        f"A requested task is not defined in {dev.source}: {e}",
                        "",
                        f"Available tasks: {' '.join(sorted(available_tasks))}",
                        f"Available commands: {' '.join(sorted(available_cmds))}",
                    )
                )
            )
    elif dev.default:
        invocation = Invocation.create(dev.default)
    else:
        raise InvalidArgumentError(
            os.linesep.join(
                (
                    f"usage: {sys.argv[0]} task|cmd [task|cmd...]",
                    "",
                    f"Available tasks: {' '.join(sorted(task.name for task in dev.tasks))}",
                    f"Available commands: {' '.join(sorted(cmd.name for cmd in dev.commands))}",
                )
            )
        )

    if extra_args and not invocation.accepts_extra_args:
        raise InvalidArgumentError(
            f"The following extra args were passed but none of the selected commands accept extra "
            f"arguments: {extra_args}"
        )

    return asyncio.run(
        invocation.invoke_parallel(*extra_args) if parallel else invocation.invoke(*extra_args)
    )


def _parse_args() -> tuple[list[str], bool, list[str]]:
    parser = ArgumentParser(
        description=(
            "A simple command runner to help running development tools easily and consistently."
        )
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "-p",
        "--parallel",
        action="store_true",
        help=(
            "Run all the top level command and task names passed in parallel. Has no effect unless "
            "there are two or more top level commands or tasks requested."
        ),
    )
    parser.add_argument(
        "--color",
        choices=[choice.value for choice in ColorChoice],
        default=ColorChoice.AUTO.value,
        help="When to color output.",
    )
    parser.add_argument(
        "tasks",
        nargs="*",
        metavar="cmd|task",
        help=(
            "One or more names of `commands` or `tasks` to run that are defined in the "
            "[tool.dev-cmd] section of `pyproject.toml`. If no command or task names are passed "
            "and a [tool.dev-cmd] `default` is defined or there is only one command defined, that "
            "is run."
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
    color.set_color(ColorChoice(options.color))

    parallel = options.parallel and len(options.tasks) > 1
    if options.parallel and not parallel:
        single_task = repr(options.tasks[0]) if options.tasks else "the default"
        print(
            color.yellow(
                f"A parallel run of top-level tasks was requested but only one was requested, "
                f"{single_task}; so proceeding with a normal run."
            )
        )

    return options.tasks, parallel, extra_args if extra_args is not None else []


def main() -> Any:
    tasks, parallel, extra_args = _parse_args()
    try:
        pyproject_toml = find_pyproject_toml()
        dev = parse_dev_config(pyproject_toml)
        return _run(dev, *tasks, parallel=parallel, extra_args=extra_args)
    except DevError as e:
        return f"{color.red('Configuration error')}: {color.yellow(str(e))}"
    except (OSError, CalledProcessError, ParallelExecutionError) as e:
        return color.red(str(e))


if __name__ == "__main__":
    sys.exit(main())
