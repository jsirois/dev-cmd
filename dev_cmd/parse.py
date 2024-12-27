# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Container, Iterator, Mapping, cast

from dev_cmd.errors import InvalidModelError
from dev_cmd.model import Command, Dev, Group, Task
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
        extra_env: list[tuple[str, str]] = []
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
                extra_env.append((key, val))

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
        yield Command(
            name, args, extra_env=tuple(extra_env), cwd=cwd, accepts_extra_args=accepts_extra_args
        )


def _parse_group(
    task: str,
    group: list[Any],
    all_task_names: Container[str],
    tasks_defined_so_far: Mapping[str, Task],
    commands: Mapping[str, Command],
) -> Group:
    members: list[Command | Task | Group] = []
    for index, member in enumerate(group):
        if isinstance(member, str):
            try:
                members.append(commands.get(member) or tasks_defined_so_far[member])
            except KeyError:
                if member in all_task_names:
                    raise InvalidModelError(
                        f"The [tool.dev-cmd.tasks] step `{task}[{index}]` forward-references task "
                        f"{member!r}. Tasks can only reference other tasks that are defined "
                        f"earlier in the file"
                    )
                raise InvalidModelError(
                    os.linesep.join(
                        (
                            f"The [tool.dev-cmd.tasks] step `{task}[{index}]` is not the name of a "
                            f"defined command or task: {member!r}",
                            "",
                            f"Available tasks: {' '.join(sorted(tasks_defined_so_far)) if tasks_defined_so_far else '<None>'}",
                            f"Available commands: {' '.join(sorted(commands))}",
                        )
                    )
                )
        elif isinstance(member, list):
            members.append(
                _parse_group(
                    task=f"{task}[{index}]",
                    group=member,
                    all_task_names=all_task_names,
                    tasks_defined_so_far=tasks_defined_so_far,
                    commands=commands,
                )
            )
        else:
            raise InvalidModelError(
                f"Expected value at [tool.dev-cmd.tasks] `{task}`[{index}] to be a string "
                f"or a list of strings, but given: {member} of type {type(member)}."
            )
    return Group(members=tuple(members))


def _parse_tasks(tasks: dict[str, Any] | None, commands: Mapping[str, Command]) -> Iterator[Task]:
    if not tasks:
        return

    tasks_by_name: dict[str, Task] = {}
    for name, group in tasks.items():
        if name in commands:
            raise InvalidModelError(
                f"The task {name!r} collides with command {name!r}. Tasks and commands share the "
                f"same namespace and the names must be unique."
            )
        if not isinstance(group, list):
            raise InvalidModelError(
                f"Expected value at [tool.dev-cmd.tasks] `{name}` to be a list containing "
                f"strings or lists of strings, but given: {group} of type {type(group)}."
            )
        task = Task(
            name=name,
            steps=_parse_group(
                task=name,
                group=group,
                all_task_names=frozenset(tasks),
                tasks_defined_so_far=tasks_by_name,
                commands=commands,
            ),
        )
        tasks_by_name[name] = task
        yield task


def _parse_default(
    default: Any, commands: Mapping[str, Command], tasks: Mapping[str, Task]
) -> Command | Task | None:
    if not default:
        if len(commands) == 1:
            return next(iter(commands.values()))
        return None

    if not isinstance(default, str):
        raise InvalidModelError(
            f"Expected default to be a string but given: {default} of type {type(default)}."
        )

    try:
        return tasks.get(default) or commands[default]
    except KeyError:
        raise InvalidModelError(
            os.linesep.join(
                (
                    f"The default {default!r} is not the name of a defined command or task.",
                    "",
                    f"Available tasks: {' '.join(sorted(tasks)) if tasks else '<None>'}",
                    f"Available commands: {' '.join(sorted(commands))}",
                )
            )
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
        cmd.name: cmd
        for cmd in _parse_commands(
            pop_dict("commands", path="[tool.dev-cmd.commands]"),
            project_dir=pyproject_toml.path.parent,
        )
    }
    if not commands:
        raise InvalidModelError(
            "No commands are defined in the [tool.dev-cmd.commands] table. At least one must be "
            "configured to use the dev task runner."
        )

    tasks = {
        task.name: task
        for task in _parse_tasks(pop_dict("tasks", path="[tool.dev-cmd.tasks]"), commands)
    }
    default = _parse_default(dev_cmd_data.pop("default", None), commands, tasks)

    if dev_cmd_data:
        raise InvalidModelError(
            f"Unexpected configuration keys in the [tool.dev-cmd] table: {' '.join(dev_cmd_data)}"
        )

    return Dev(
        commands=tuple(commands.values()),
        tasks=tuple(tasks.values()),
        default=default,
        source=pyproject_toml.path,
    )
