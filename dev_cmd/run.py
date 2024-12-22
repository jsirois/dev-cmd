# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
import sys
from argparse import ArgumentParser
from subprocess import CalledProcessError
from typing import Any, Iterable, List, Optional, Tuple

from colors import colors

from dev_cmd import __version__
from dev_cmd.errors import DevError, InvalidArgumentError
from dev_cmd.model import Dev, Invocation
from dev_cmd.parse import parse_dev_config
from dev_cmd.project import find_pyproject_toml


def _run(dev: Dev, *tasks: str, extra_args: Iterable[str] = ()) -> None:
    if tasks:
        try:
            invocation = Invocation.create(
                *[(task, (dev.aliases.get(task) or [dev.commands[task]])) for task in tasks]
            )
        except KeyError as e:
            raise InvalidArgumentError(
                os.linesep.join(
                    (
                        f"A requested task is not defined in {dev.source}: {e}",
                        "",
                        f"Available aliases: {' '.join(sorted(dev.aliases))}",
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
                    f"usage: {sys.argv[0]} alias|cmd [alias|cmd...]",
                    "",
                    f"Available aliases: {' '.join(sorted(dev.aliases))}",
                    f"Available commands: {' '.join(sorted(dev.commands))}",
                )
            )
        )

    if extra_args and not invocation.accepts_extra_args:
        raise InvalidArgumentError(
            f"The following extra args were passed but none of the selected commands accept extra "
            f"arguments: {extra_args}"
        )

    for task, commands in invocation.tasks.items():
        prefix = colors.cyan(f"dev run {colors.bold(task)}]")
        for command in commands:
            print(
                f"{prefix} {colors.magenta(f'Executing {colors.bold(command.name)}...')}",
                file=sys.stderr,
            )
            args = list(command.args)
            if extra_args and command.accepts_extra_args:
                args.extend(extra_args)

            subprocess.run(args, env=command.env, check=True)


def _parse_args() -> Tuple[List[str], List[str]]:
    parser = ArgumentParser(
        description=(
            "A simple command runner to help running development tools easily and consistently."
        )
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "tasks",
        nargs="*",
        metavar="cmd|alias",
        help=(
            "One or more names of commands or aliases to run that are defined in the "
            "[tool.dev-cmd] section of `pyproject.toml`. If no tasks are passed and a "
            "[tool.dev-cmd.default] is defined or there is only one command defined, that is run."
        ),
    )

    args: List[str] = []
    extra_args: Optional[List[str]] = None
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
        return colors.yellow(str(e))
    except (OSError, CalledProcessError) as e:
        return colors.red(str(e))


if __name__ == "__main__":
    sys.exit(main())
