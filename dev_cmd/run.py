# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import dataclasses
import functools
import itertools
import os
import sys
import time
from argparse import ArgumentParser
from asyncio import CancelledError
from collections import defaultdict
from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from typing import Any, Collection, DefaultDict, Iterable, Iterator, Mapping

from dev_cmd import __version__, color, parse, venv
from dev_cmd.color import ColorChoice
from dev_cmd.console import Console
from dev_cmd.errors import DevCmdError, ExecutionError, InvalidArgumentError
from dev_cmd.expansion import expand
from dev_cmd.invoke import Invocation
from dev_cmd.model import (
    Command,
    Configuration,
    ExitStyle,
    Group,
    Python,
    PythonConfig,
    Task,
    Venv,
    VenvConfig,
)
from dev_cmd.parse import parse_dev_config
from dev_cmd.placeholder import DEFAULT_ENVIRONMENT
from dev_cmd.project import find_pyproject_toml

DEFAULT_EXIT_STYLE = ExitStyle.AFTER_STEP
DEFAULT_GRACE_PERIOD = 5.0


def _iter_commands(
    steps: Iterable[Command | Group | Task], seen: set[Command] | None = None
) -> Iterator[Command]:
    seen = seen if seen is not None else set()
    for step in steps:
        if isinstance(step, Command):
            if step not in seen:
                seen.add(step)
                yield step
        elif isinstance(step, Task):
            for command in _iter_commands(step.steps.members, seen=seen):
                yield command
        else:
            for command in _iter_commands(step.members, seen=seen):
                yield command


def _ensure_venvs(
    steps: Iterable[Command | Task], pythons_configs: Iterable[PythonConfig]
) -> Mapping[VenvConfig, Venv]:
    venv_configs_to_requesting_commands: DefaultDict[VenvConfig, list[Command]] = defaultdict(list)
    for command in _iter_commands(steps):
        if command.python:
            venv_configs_to_requesting_commands[
                VenvConfig(python=command.python, dependency_group=command.dependency_group)
            ].append(command)

    if venv_configs_to_requesting_commands and not pythons_configs:
        missing_pythons = "\n".join(
            (
                f"+ {venv_config.python!r} requested by: "
                f"{' '.join(repr(rc.name) for rc in requesting_commands)}"
            )
            for venv_config, requesting_commands in venv_configs_to_requesting_commands.items()
        )
        raise InvalidArgumentError(
            f"Some of your configured commands requested custom pythons but you have not "
            f"configured any `[[tool.dev-cmd.python]]` entries.\n"
            f"See: https://github.com/jsirois/dev-cmd/blob/main/README.md#custom-pythons\n"
            f"\n"
            f"The missing pythons are:\n"
            f"{missing_pythons}"
        )

    def ensure_venv(venv_config: VenvConfig, *, quiet: bool) -> Venv:
        requesting_commands = venv_configs_to_requesting_commands[venv_config]
        python_config = parse.select_python_config(venv_config.python, pythons_configs, quiet=quiet)
        if not python_config:
            commands = "\n".join(f"+ {rc.name}" for rc in requesting_commands)
            raise InvalidArgumentError(
                f"The following commands requested a custom Python of {venv_config.python!r} but "
                f"none of the configured `[[tool.dev-cmd.python]]` entries apply:\n"
                f"{commands}"
            )
        return venv.ensure(venv_config=venv_config, python_config=python_config, quiet=quiet)

    if len(venv_configs_to_requesting_commands) == 1:
        venv_config, requesting_commands = venv_configs_to_requesting_commands.popitem()
        return {venv_config: ensure_venv(venv_config, quiet=False)}

    pool = ThreadPool()
    try:
        pythons = list(venv_configs_to_requesting_commands)
        return dict(zip(pythons, pool.map(functools.partial(ensure_venv, quiet=True), pythons)))
    finally:
        pool.close()
        pool.join()


def _run(
    config: Configuration,
    *steps: str,
    skips: Collection[str] = (),
    console: Console = Console(),
    parallel: bool = False,
    timings: bool = False,
    extra_args: tuple[str, ...] = (),
    exit_style_override: ExitStyle | None = None,
    grace_period_override: float | None = None,
) -> None:
    grace_period = grace_period_override or config.grace_period or DEFAULT_GRACE_PERIOD

    available_cmds = {cmd.name: cmd for cmd in config.commands}
    available_tasks = {task.name: task for task in config.tasks}

    missing_skips = sorted(
        skip for skip in skips if skip not in available_cmds and skip not in available_tasks
    )
    if missing_skips:
        if len(missing_skips) == 1:
            missing_skips_list = missing_skips[0]
        else:
            missing_skips_list = f"{', '.join(missing_skips[:-1])} and {missing_skips[-1]}"
        raise InvalidArgumentError(
            f"You requested skips of {missing_skips_list} which do not correspond to any "
            f"configured command or task names."
        )

    if steps:
        try:
            invocation = Invocation.create(
                *(available_tasks.get(step) or available_cmds[step] for step in steps),
                skips=skips,
                grace_period=grace_period,
                extra_args=extra_args,
                timings=timings,
                console=console,
            )
        except KeyError as e:
            print(e, file=sys.stderr)
            raise InvalidArgumentError(
                os.linesep.join(
                    (
                        f"A requested step is not defined in {config.source}: {e}",
                        "",
                        f"Available tasks: {' '.join(sorted(available_tasks))}",
                        f"Available commands: {' '.join(sorted(available_cmds))}",
                    )
                )
            )
    elif config.default:
        invocation = Invocation.create(
            config.default,
            skips=skips,
            grace_period=grace_period,
            extra_args=extra_args,
            timings=timings,
            console=console,
        )
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

    if not tuple(invocation.iter_commands()):
        raise InvalidArgumentError(
            "All steps in this invocation of `dev-cmd` were deactivated by `when` markers leaving "
            "nothing to run."
        )
    invocation = dataclasses.replace(
        invocation, venvs=_ensure_venvs(invocation.steps, config.pythons)
    )

    exit_style = exit_style_override or config.exit_style or DEFAULT_EXIT_STYLE
    return asyncio.run(
        invocation.invoke_parallel(*extra_args, exit_style=exit_style)
        if parallel
        else invocation.invoke(*extra_args, exit_style=exit_style)
    )


@dataclass(frozen=True)
class Options:
    steps: tuple[str, ...]
    skips: frozenset[str]
    list: bool
    quiet: bool
    parallel: bool
    timings: bool
    extra_args: tuple[str, ...]
    python: str | None = None
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
        "-l",
        "--list",
        default=False,
        action="store_true",
        help="List the commands and tasks that can be run.",
    )
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
        "-s",
        "--skip",
        dest="skips",
        action="append",
        default=[],
        help=(
            "After calculating all steps to run given the command line args, remove these steps, "
            "whether they be command names or task names from that list."
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
    parser.add_argument(
        "-t",
        "--timings",
        action="store_true",
        help="Emit timing information for each command run.",
    )

    if venv.AVAILABLE:
        parser.add_argument(
            "--py",
            "--python",
            dest="python",
            help=(
                "Select an older python to run `dev-cmd` against. The value can be a full path to "
                "the exact CPython or PyPy binary to use or just the binary name; e.g.: pypy3.10,"
                "in which case the interpreter will be looked up on the PATH. You can omit the "
                "python prefix for a PATH search and it will be filled in; i.e.: 3.12 will be "
                "expanded to python3.12 and then looked up on the PATH. Finally, you can even omit "
                "the dot in the version; i.e. 38 will expand to python3.8 and then looked up on "
                "the PATH."
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
        "steps",
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
        if "--" == arg and extra_args is None:
            extra_args = []
        elif extra_args is not None:
            extra_args.append(arg)
        else:
            args.append(arg)

    options = parser.parse_args(args)
    color.set_color(ColorChoice(options.color))

    steps = tuple(itertools.chain.from_iterable(expand(step) for step in options.steps))
    parallel = options.parallel and len(steps) > 1
    if options.parallel and not parallel and not options.quiet:
        single_task = repr(steps[0]) if steps else "the default"
        print(
            color.yellow(
                f"A parallel run of top-level tasks was requested but only one was requested, "
                f"{single_task}; so proceeding with a normal run."
            )
        )

    return Options(
        steps=steps,
        skips=frozenset(options.skips),
        list=options.list,
        quiet=options.quiet,
        parallel=parallel,
        timings=options.timings,
        extra_args=tuple(extra_args) if extra_args is not None else (),
        python=getattr(options, "python", None),
        exit_style=options.exit_style,
        grace_period=options.grace_period,
    )


def _list(
    console,  # type: Console
    config,  # type: Configuration
):
    # type: (...) -> Any

    console.print(f"{color.cyan('Commands')}:")
    hidden_command_count = len(tuple(command for command in config.commands if command.hidden))
    if hidden_command_count > 0:
        subject = "command is" if hidden_command_count == 1 else "commands are"
        print(color.color(f"({hidden_command_count} {subject} hidden.)", fg="gray"))
    seen: set[str] = set()
    for command in config.commands:
        command = command.base or command
        if command.name in seen:
            continue
        seen.add(command.name)
        if command.hidden:
            continue
        rendered_command_name = color.color(command.name, fg="magenta", style="bold")
        if config.default == command:
            rendered_command_name = f"* {rendered_command_name}"
        if command.accepts_extra_args:
            extra_args_help = color.magenta(f" (-- extra {command.args[0]} args ...)")
            rendered_command_name = f"{rendered_command_name}{extra_args_help}"
        if command.description:
            console.print(f"{rendered_command_name}:")
            console.print(f"    {color.color(command.description, fg='gray')}")
        elif command.factor_descriptions:
            console.print(f"{rendered_command_name}:")
        else:
            console.print(rendered_command_name)
        for factor_description in command.factor_descriptions:
            flag_value = factor_description.flag_value
            factor_desc_header = f"    -{factor_description.factor}"
            if flag_value:
                factor_desc_header += "?"

            rendered_factor = color.magenta(factor_desc_header)
            default = factor_description.default
            extra_info = ""
            if flag_value is not None:
                extra_info = f"{flag_value} "
                substituted_flag_value = DEFAULT_ENVIRONMENT.substitute(flag_value).value
                if substituted_flag_value != flag_value:
                    extra_info += f"(currently {substituted_flag_value}) "
            if default is not None:
                substituted_default = DEFAULT_ENVIRONMENT.substitute(default).value
                if substituted_default != default:
                    extra_info += f"[default: {default} (currently {substituted_default})]"
                else:
                    extra_info += f"[default: {default}]"
            else:
                extra_info += "[required]"
            if factor_description.description:
                desc_lines = factor_description.description.splitlines()
                console.print(f"{rendered_factor}: {color.color(desc_lines[0], fg='gray')}")
                for extra_line in desc_lines[1:]:
                    console.print(
                        f"{' ' * len(factor_desc_header)}  {color.color(extra_line, fg='gray')}"
                    )
                console.print(
                    f"{' ' * len(factor_desc_header)}  {color.color(extra_info, fg='gray')}"
                )
            else:
                console.print(f"{rendered_factor}: {color.color(extra_info, fg='gray')}")
    if config.tasks:
        console.print()
        console.print(f"{color.cyan('Tasks')}:")
        hidden_task_count = len(tuple(task for task in config.tasks if task.hidden))
        if hidden_task_count > 0:
            subject = "task is" if hidden_task_count == 1 else "tasks are"
            print(color.color(f"({hidden_task_count} {subject} hidden.)", fg="gray"))
        for task in config.tasks:
            if task.hidden:
                continue
            rendered_task_name = color.color(task.name, fg="magenta", style="bold")
            if config.default == task:
                rendered_task_name = f"* {rendered_task_name}"
            if extra_args_cmds := tuple(task.accepts_extra_args()):
                extra_args_help = color.magenta(
                    f" (-- extra {extra_args_cmds[0].args[0]} args ...)"
                )
                rendered_task_name = f"{rendered_task_name}{extra_args_help}"
            if task.description:
                console.print(f"{rendered_task_name}: ")
                console.print(f"    {color.color(task.description, fg='gray')}")
            else:
                console.print(rendered_task_name)


def main() -> Any:
    start = time.time()
    options = _parse_args()
    console = Console(quiet=options.quiet)
    python = Python(options.python) if options.python else None
    try:
        pyproject_toml = find_pyproject_toml()
        config, steps = parse_dev_config(pyproject_toml, *options.steps, requested_python=python)
    except DevCmdError as e:
        return 1 if console.quiet else f"{color.red('Configuration error')}: {color.yellow(str(e))}"

    if options.list:
        return _list(console, config)

    success = False
    try:
        _run(
            config,
            *steps,
            skips=options.skips,
            console=console,
            parallel=options.parallel,
            timings=options.timings,
            extra_args=options.extra_args,
            exit_style_override=options.exit_style,
            grace_period_override=options.grace_period,
        )
        success = True
    except DevCmdError as e:
        if console.quiet:
            return 1
        return f"{color.red('Configuration error')}: {color.yellow(str(e))}"
    except OSError as e:
        if console.quiet:
            return 1
        return f"{color.color('Failed to launch a command', fg='red', style='bold')}: {color.red(str(e))}"
    except ExecutionError as e:
        if console.quiet:
            return e.exit_code
        prefix = f"{color.red('dev-cmd')} {color.color(e.step_name, fg='red', style='bold')}"
        return f"{prefix}] {color.red(e.message)}"
    except (CancelledError, KeyboardInterrupt):
        if console.quiet:
            return 1
        return f"{color.red('dev-cmd')}] {color.color('Cancelled', fg='red', style='bold')}"
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
