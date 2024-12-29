# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import os
import sys
import time
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Any, Iterable

from dev_cmd import __version__, color
from dev_cmd.color import ColorChoice
from dev_cmd.console import Console
from dev_cmd.errors import DevCmdError, ExecutionError, InvalidArgumentError
from dev_cmd.invoke import Invocation
from dev_cmd.model import Configuration, ExitStyle
from dev_cmd.parse import parse_dev_config
from dev_cmd.project import find_pyproject_toml

DEFAULT_EXIT_STYLE = ExitStyle.AFTER_STEP
DEFAULT_GRACE_PERIOD = 5.0


def _run(
    config: Configuration,
    *names: str,
    console: Console = Console(),
    parallel: bool = False,
    extra_args: Iterable[str] = (),
    exit_style_override: ExitStyle | None = None,
    grace_period_override: float | None = None,
) -> None:
    grace_period = grace_period_override or config.grace_period or DEFAULT_GRACE_PERIOD
    if names:
        available_cmds = {cmd.name: cmd for cmd in config.commands}
        available_tasks = {task.name: task for task in config.tasks}
        try:
            invocation = Invocation.create(
                *(available_tasks.get(name) or available_cmds[name] for name in names),
                console=console,
                grace_period=grace_period,
            )
        except KeyError as e:
            raise InvalidArgumentError(
                os.linesep.join(
                    (
                        f"A requested task is not defined in {config.source}: {e}",
                        "",
                        f"Available tasks: {' '.join(sorted(available_tasks))}",
                        f"Available commands: {' '.join(sorted(available_cmds))}",
                    )
                )
            )
    elif config.default:
        invocation = Invocation.create(config.default, console=console, grace_period=grace_period)
    else:
        raise InvalidArgumentError(
            os.linesep.join(
                (
                    f"usage: {sys.argv[0]} task|cmd [task|cmd...]",
                    "",
                    f"Available tasks: {' '.join(sorted(task.name for task in config.tasks))}",
                    f"Available commands: {' '.join(sorted(cmd.name for cmd in config.commands))}",
                )
            )
        )

    if extra_args and not invocation.accepts_extra_args:
        raise InvalidArgumentError(
            f"The following extra args were passed but none of the selected commands accept extra "
            f"arguments: {extra_args}"
        )

    exit_style = exit_style_override or config.exit_style or DEFAULT_EXIT_STYLE
    return asyncio.run(
        invocation.invoke_parallel(*extra_args, exit_style=exit_style)
        if parallel
        else invocation.invoke(*extra_args, exit_style=exit_style)
    )


@dataclass(frozen=True)
class Options:
    tasks: tuple[str, ...]
    quiet: bool
    parallel: bool
    extra_args: tuple[str, ...]
    exit_style: ExitStyle | None = None
    grace_period: float | None = None


def _parse_args() -> Options:
    parser = ArgumentParser(
        description=(
            "A simple command runner to help running development tools easily and consistently."
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help=(
            "Do not output information about the commands `dev-cmd` is running; just show output "
            "from the commands run themselves."
        ),
    )
    parser.add_argument(
        "-p",
        "--parallel",
        action="store_true",
        help=(
            "Run all the top level command and task names passed in parallel. Has no effect unless "
            "there are two or more top level commands or tasks requested."
        ),
    )

    exit_style_group = parser.add_mutually_exclusive_group()
    exit_style_group.add_argument(
        "-k",
        "--keep-going",
        dest="exit_style",
        action="store_const",
        const=ExitStyle.END,
        help=(
            "Normally, `dev-cmd` exits with an error code after the first task step with an "
            "errored command completes. You can choose to `-k` / `--keep-going` to run all steps "
            "to the end before exiting. This option is mutually exclusive with "
            "`-X` / `--exit-style`."
        ),
    )
    exit_style_group.add_argument(
        "-X",
        "--exit-style",
        dest="exit_style",
        type=ExitStyle,
        choices=list(ExitStyle),
        default=None,
        help=(
            "When to exit a `dev-cmd` invocation that encounters command errors. Normally, "
            "`dev-cmd` exits with an error code after the first task step with an errored command "
            "completes. This option is mutually exclusive with `-k` / `--keep-going`."
        ),
    )

    parser.add_argument(
        "--grace-period",
        type=float,
        default=None,
        help=(
            "The amount of time in fractional seconds to wait for terminated commands to exit "
            f"before killing them forcefully: {DEFAULT_GRACE_PERIOD} seconds by default. If set to "
            f"zero or a negative value, commands are always killed forcefully with no grace "
            f"period. This setting comes into play when the `--exit-style` is either "
            f"{ExitStyle.AFTER_STEP.value!r} or {ExitStyle.IMMEDIATE.value!r}."
        ),
    )
    parser.add_argument(
        "--color",
        type=ColorChoice,
        choices=list(ColorChoice),
        default=ColorChoice.AUTO,
        help=(
            "When to color `dev-cmd` output. By default an appropriate color mode is "
            "'auto'-detected, but color use can be forced 'always' on or 'never' on."
        ),
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
    if options.parallel and not parallel and not options.quiet:
        single_task = repr(options.tasks[0]) if options.tasks else "the default"
        print(
            color.yellow(
                f"A parallel run of top-level tasks was requested but only one was requested, "
                f"{single_task}; so proceeding with a normal run."
            )
        )

    return Options(
        tasks=tuple(options.tasks),
        quiet=options.quiet,
        parallel=parallel,
        extra_args=tuple(extra_args) if extra_args is not None else (),
        exit_style=options.exit_style,
        grace_period=options.grace_period,
    )


def main() -> Any:
    start = time.time()
    success = False
    options = _parse_args()
    console = Console(quiet=options.quiet)
    try:
        pyproject_toml = find_pyproject_toml()
        config = parse_dev_config(pyproject_toml)
        _run(
            config,
            *options.tasks,
            console=console,
            parallel=options.parallel,
            extra_args=options.extra_args,
            exit_style_override=options.exit_style,
            grace_period_override=options.grace_period,
        )
        success = True
    except DevCmdError as e:
        return 1 if console.quiet else f"{color.red('Configuration error')}: {color.yellow(str(e))}"
    except OSError as e:
        if console.quiet:
            return 1
        return f"{color.color('Failed to launch a command', fg='red', style='bold')}: {color.red(str(e))}"
    except ExecutionError as e:
        if console.quiet:
            return e.exit_code
        prefix = f"{color.red('dev-cmd')} {color.color(e.step_name, fg='red', style='bold')}"
        return f"{prefix}] {color.red(e.message)}"
    finally:
        if not console.quiet:
            summary_color = "green" if success else "red"
            status = color.color(
                "Success" if success else "Failure", fg=summary_color, style="bold"
            )
            timing = color.color(f"in {time.time() - start:.3f}s", fg=summary_color)
            console.print(f"{color.cyan('dev-cmd')}] {status} {timing}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
