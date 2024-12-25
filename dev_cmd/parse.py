# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator, Mapping, cast

from dev_cmd.errors import InvalidModelError
from dev_cmd.model import Command, Dev
from dev_cmd.project import PyProjectToml


def _assert_list_str(obj: Any, *, path: str) -> list[str]:
    if not isinstance(obj, list) or not all(isinstance(item, str) for item in obj):
        raise InvalidModelError(
            f"Expected value at {path} to be a list of strings, but given: {obj} of type "
            f"{type(obj)}."
        )
    return cast("list[str]", obj)


def _assert_dict_str_keys(obj: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or not all(isinstance(key, str) for key in obj):
        raise InvalidModelError(
            f"Expected value at {path} to be a dict with string keys, but given: {obj} of type "
            f"{type(obj)}."
        )
    return cast("dict[str, Any]", obj)


def _parse_commands(commands: dict[str, Any] | None, project_dir: Path) -> Iterator[Command]:
    if not commands:
        raise InvalidModelError(
            "There must be at least one entry in the [tool.dev-cmd.commands] table to run "
            "`dev-cmd`."
        )

    for name, data in commands.items():
        env = os.environ.copy()
        if isinstance(data, list):
            args = tuple(_assert_list_str(data, path=f"[tool.dev-cmd.commands] `{name}`"))
            cwd = project_dir
            accepts_extra_args = False
        else:
            command = _assert_dict_str_keys(data, path=f"[tool.dev-cmd.commands.{name}]")

            for key, val in _assert_dict_str_keys(
                command.pop("env", {}), path=f"[tool.dev-cmd.commands.{name}] `env`"
            ).items():
                if not isinstance(val, str):
                    raise InvalidModelError(
                        f"The env variable {key} must be a string, but given: {val} of type "
                        f"{type(val)}."
                    )
                env[key] = val

            try:
                args = tuple(
                    _assert_list_str(
                        command.pop("args"), path=f"[tool.dev-cmd.commands.{name}] `args`"
                    )
                )
            except KeyError:
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] table must define an `args` list."
                )

            cwd = Path(command.pop("cwd", project_dir))
            if not cwd.is_absolute():
                cwd = project_dir / cwd
            cwd = cwd.resolve()
            if not project_dir == Path(os.path.commonpath((project_dir, cwd))):
                raise InvalidModelError(
                    f"The resolved path of [tool.dev-cmd.commands.{name}] `cwd` lies outside the "
                    f"project: {cwd}"
                )

            accepts_extra_args = command.pop("accepts-extra-args", False)
            if not isinstance(accepts_extra_args, bool):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `accepts-extra-args` value must be either "
                    f"`true` or `false`, given: {accepts_extra_args} of type "
                    f"{type(accepts_extra_args)}."
                )
            if data:
                raise InvalidModelError(
                    f"Unexpected configuration keys in the [tool.dev-cmd.commands.{name}] table: "
                    f"{' '.join(data)}"
                )
        yield Command(name, env, args, cwd, accepts_extra_args=accepts_extra_args)


def _parse_tasks(
    tasks: dict[str, Any] | None,
) -> Iterator[tuple[str, tuple[str | tuple[str, ...], ...]]]:
    if not tasks:
        return

    def iter_commands(task: str, obj: Any) -> Iterator[str | tuple[str, ...]]:
        if not isinstance(commands, list):
            raise InvalidModelError(
                f"Expected value at [tool.dev-cmd.tasks] `{task}` to be a list containing "
                f"strings or lists of strings, but given: {obj} of type {type(obj)}."
            )

        for index, item in enumerate(obj):
            if isinstance(item, str):
                yield item
            elif isinstance(item, list):
                if not all(isinstance(element, str) for element in item):
                    raise InvalidModelError(
                        f"Expected value at [tool.dev-cmd.tasks] `{task}`[{index}] to be a list "
                        f"of strings, but given list with at least one non-string item: {item}."
                    )
                yield tuple(item)
            else:
                raise InvalidModelError(
                    f"Expected value at [tool.dev-cmd.tasks] `{task}`[{index}] to be a string "
                    f"or a list of strings, but given: {item} of type {type(item)}."
                )

    for task, commands in tasks.items():
        yield task, tuple(iter_commands(task, commands))


def _parse_default(
    default: Any,
    commands: Mapping[str, Command],
    tasks: Mapping[str, tuple[Command | tuple[Command, ...], ...]],
) -> tuple[str, tuple[Command | tuple[Command, ...], ...]] | None:
    if not default:
        if len(commands) == 1:
            name, command = next(iter(commands.items()))
            return name, tuple([command])
        return None

    if not isinstance(default, str):
        raise InvalidModelError(
            f"Expected default to be a string but given: {default} of type {type(default)}."
        )

    try:
        return default, (tasks.get(default) or tuple([commands[default]]))
    except KeyError:
        raise InvalidModelError(
            f"The default {default!r} is not the name of a defined command or task."
        )


def parse_dev_config(pyproject_toml: PyProjectToml) -> Dev:
    pyproject_data = pyproject_toml.parse()
    try:
        dev_cmd_data = _assert_dict_str_keys(
            pyproject_data["tool"]["dev-cmd"], path="[tool.dev-cmd]"
        )  # type: ignore[index]
    except KeyError as e:
        raise InvalidModelError(
            f"The commands, tasks and defaults run-dev acts upon must be defined in the "
            f"[tool.dev-cmd] table in {pyproject_toml}: {e}"
        )

    def pop_dict(key: str, *, path: str) -> dict[str, Any] | None:
        data = dev_cmd_data.pop(key, None)
        return _assert_dict_str_keys(data, path=path) if data else None

    commands = {
        command.name: command
        for command in _parse_commands(
            pop_dict("commands", path="[tool.dev-cmd.commands]"),
            project_dir=pyproject_toml.path.parent,
        )
    }
    tasks: dict[str, tuple[Command | tuple[Command, ...], ...]] = {}
    for task, cmds in _parse_tasks(pop_dict("tasks", path="[tool.dev-cmd.tasks]")):
        if task in commands:
            raise InvalidModelError(
                f"The task name {task!r} conflicts with a command of the same name."
            )
        task_cmds: list[Command | tuple[Command, ...]] = []
        for index, cmd in enumerate(cmds):
            if isinstance(cmd, str):
                if cmd in commands:
                    task_cmds.append(commands[cmd])
                elif cmd in tasks:
                    task_cmds.extend(tasks[cmd])
                else:
                    raise InvalidModelError(
                        f"The task {cmd!r} defined in task {task!r} is neither a command nor a "
                        f"previously defined task."
                    )
            else:
                parallel_cmds: list[Command] = []
                for parallel_cmd in cmd:
                    if parallel_cmd in commands:
                        parallel_cmds.append(commands[parallel_cmd])
                    elif parallel_cmd in tasks:
                        raise InvalidModelError(
                            f"Expected value at [tool.dev-cmd.tasks] `{task}`[{index}] to be a "
                            f"list of command names, but {parallel_cmd!r} is an task."
                        )
                    else:
                        raise InvalidModelError(
                            f"Expected value at [tool.dev-cmd.tasks] `{task}`[{index}] to be a "
                            f"list of command names, but {parallel_cmd!r} is doesn't correspond "
                            f"with any defined command."
                        )
                task_cmds.append(tuple(parallel_cmds))
        tasks[task] = tuple(task_cmds)

    default = _parse_default(dev_cmd_data.pop("default", None), commands, tasks)

    if dev_cmd_data:
        raise InvalidModelError(
            f"Unexpected configuration keys in the [tool.dev-cmd] table: {' '.join(dev_cmd_data)}"
        )
    if not commands:
        raise InvalidModelError(
            "No commands are defined in the [tool.dev-cmd.commands] table. At least one must be "
            "configured to use the dev task runner."
        )

    return Dev(commands=commands, tasks=tasks, default=default, source=pyproject_toml.path)
