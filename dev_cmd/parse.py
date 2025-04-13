# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Container, Dict, Iterable, Iterator, List, Mapping, Set, cast

from packaging.markers import InvalidMarker, Marker

from dev_cmd import venv
from dev_cmd.errors import InvalidArgumentError, InvalidModelError
from dev_cmd.expansion import expand
from dev_cmd.model import (
    CacheKeyInputs,
    Command,
    Configuration,
    ExitStyle,
    Factor,
    FactorDescription,
    Group,
    Python,
    PythonConfig,
    Task,
)
from dev_cmd.placeholder import DEFAULT_ENVIRONMENT, Substitution
from dev_cmd.project import PyProjectToml


def _assert_list_str(obj: Any, *, path: str) -> list[str]:
    if not isinstance(obj, list) or not all(isinstance(item, str) for item in obj):
        raise InvalidModelError(
            f"Expected value at {path} to be a list of strings, but given: {obj} of type "
            f"{type(obj)}."
        )
    return cast(List[str], obj)


class DiscardEmpty(str):
    pass


def _assert_list_str_or_discard(obj: Any, *, path: str) -> list[str | DiscardEmpty]:
    if not isinstance(obj, list):
        raise InvalidModelError(
            f"Expected value at {path} to be a list of strings and discards, but given: {obj} of "
            f"type {type(obj)}."
        )
    result: list[str | DiscardEmpty] = []
    for index, item in enumerate(obj):
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            count = len(item)
            if count == 0:
                raise InvalidModelError(
                    f"Expected value at {path} to be a list of strings and discards, but the list "
                    f"item at index {index} is an empty table."
                )
            value = item.pop("discard_empty", None)
            if value and not isinstance(value, str):
                raise InvalidModelError(
                    f"Expected discard_empty table at {path}[{index}] to be a string, but given "
                    f"{value} of type {type(value)}."
                )
            elif item:
                raise InvalidModelError(
                    f"Expected value at {path} to be a list of strings and discards, but table at "
                    f"index {index} has unrecognized keys: {' '.join(item)}."
                )
            result.append(DiscardEmpty(value))
        else:
            raise InvalidModelError(
                f"Expected value at {path} to be a list of strings and discards, but the list item "
                f"at index {index}: {item} of type {type(item)}."
            )
    return result


def _assert_dict_str_keys(obj: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or not all(isinstance(key, str) for key in obj):
        raise InvalidModelError(
            f"Expected value at {path} to be a dict with string keys, but given: {obj} of type "
            f"{type(obj)}."
        )
    return cast(Dict[str, Any], obj)


def _assert_list_dict_str_keys(obj: Any, *, path: str) -> list[dict[str, Any]]:
    if not isinstance(obj, list) or not all(
        isinstance(item, dict) and all(isinstance(key, str) for key in item) for item in obj
    ):
        raise InvalidModelError(
            f"Expected value at {path} to be a list of dicts with string keys, but given: {obj} of "
            f"type {type(obj)}."
        )
    return cast(List[Dict[str, Any]], obj)


def _parse_when(data: dict[str, Any], table_path: str) -> Marker | None:
    raw_when = data.pop("when", None)
    if raw_when and not isinstance(raw_when, str):
        raise InvalidModelError(
            f"The {table_path} `when` value must be a string, "
            f"given: {raw_when} of type {type(raw_when)}."
        )
    try:
        return Marker(raw_when) if raw_when else None
    except InvalidMarker as e:
        raise InvalidModelError(
            f"The {table_path} `when` value is not a valid marker "
            f"expression: {e}{os.linesep}"
            f"See: https://packaging.python.org/en/latest/specifications/"
            f"dependency-specifiers/#environment-markers"
        )


@dataclass(frozen=True)
class DeactivatedCommand:
    name: str


PY_FACTOR = Factor("py")


def _parse_commands(
    commands: dict[str, Any] | None,
    required_steps: dict[str, list[tuple[Factor, ...]]],
    project_dir: Path,
    python: Python | None,
    marker_environment: dict[str, str] | None,
) -> Iterator[Command | DeactivatedCommand]:
    if not commands:
        raise InvalidModelError(
            "There must be at least one entry in the [tool.dev-cmd.commands] table to run "
            "`dev-cmd`."
        )

    seen_commands: dict[str, str] = {}
    for name, data in commands.items():
        cwd: Path | None = None
        extra_env: list[tuple[str, str]] = []
        factor_descriptions: dict[Factor, str | None] = {}
        original_name = name
        if isinstance(data, list):
            args = tuple(
                _assert_list_str_or_discard(data, path=f"[tool.dev-cmd.commands] `{name}`")
            )
            accepts_extra_args = False
            hidden = False
            description = None
            when = None
            python_spec: str | None = None
            dependency_group: str | None = None
        else:
            command = _assert_dict_str_keys(data, path=f"[tool.dev-cmd.commands.{name}]")

            raw_name = data.pop("name", name)
            if not isinstance(raw_name, str):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `name` value must be a string , given: "
                    f"{raw_name} of type {type(raw_name)}."
                )
            name = raw_name

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
                    _assert_list_str_or_discard(
                        command.pop("args"), path=f"[tool.dev-cmd.commands.{name}] `args`"
                    )
                )
            except KeyError:
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] table must define an `args` list."
                )

            raw_cwd = command.pop("cwd", None)
            if raw_cwd:
                if not isinstance(raw_cwd, str):
                    raise InvalidModelError(
                        f"The [tool.dev-cmd.commands.{name}] `cwd` value must be a string, "
                        f"given: {raw_cwd} of type {type(raw_cwd)}."
                    )
                cwd = Path(raw_cwd)
                if not cwd.is_absolute():
                    cwd = project_dir / cwd
                cwd = cwd.resolve()
                if not project_dir == Path(os.path.commonpath((project_dir, cwd))):
                    raise InvalidModelError(
                        f"The resolved path of [tool.dev-cmd.commands.{name}] `cwd` lies outside "
                        f"the project: {cwd}"
                    )

            accepts_extra_args = command.pop("accepts-extra-args", False)
            if not isinstance(accepts_extra_args, bool):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `accepts-extra-args` value must be either "
                    f"`true` or `false`, given: {accepts_extra_args} of type "
                    f"{type(accepts_extra_args)}."
                )

            hidden = command.pop("hidden", False)
            if not isinstance(hidden, bool):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `hidden` value must be a boolean, "
                    f"given: {hidden} of type {type(hidden)}."
                )

            description = command.pop("description", None)
            if description and not isinstance(description, str):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `description` value must be a string, "
                    f"given: {description} of type {type(description)}."
                )

            raw_factor_descriptions = _assert_dict_str_keys(
                command.pop("factors", {}), path=f"[tool.dev-cmd.commands.{name}] `factors`"
            )
            for factor_name, factor_desc in raw_factor_descriptions.items():
                if not isinstance(factor_desc, str):
                    raise InvalidModelError(
                        f"The [tool.dev-cmd.commands.{name}.factors] `{factor_name}` value must be "
                        f"a string, given: {factor_desc} of type {type(factor_desc)}."
                    )
                factor_descriptions[Factor(factor_name)] = factor_desc

            when = _parse_when(command, table_path=f"[tool.dev-cmd.commands.{name}]")

            raw_python = command.pop("python", None)
            if raw_python and not isinstance(raw_python, str):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `python` value must be a string, "
                    f"given: {raw_python} of type {type(raw_python)}."
                )
            python_spec = raw_python

            raw_dependency_group = command.pop("dependency-group", None)
            if raw_dependency_group and not isinstance(raw_dependency_group, str):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] `dependency-group` value must be a "
                    f"string, given: {raw_dependency_group} of type {type(raw_dependency_group)}."
                )
            dependency_group = raw_dependency_group

            if data:
                raise InvalidModelError(
                    f"Unexpected configuration keys in the [tool.dev-cmd.commands.{name}] table: "
                    f"{' '.join(data)}"
                )

        for factors in required_steps.get(name) or [()]:
            factors_suffix = f"-{'-'.join(factors)}" if factors else ""

            seen_factors: dict[Factor, FactorDescription] = {}
            used_factors: set[Factor] = set()

            def substitute(text: str) -> Substitution:
                substitution = DEFAULT_ENVIRONMENT.substitute(text, *factors)
                seen_factors.update(
                    (
                        seen_factor.factor,
                        FactorDescription(
                            factor=seen_factor.factor,
                            flag_value=seen_factor.flag_value,
                            default=seen_factor.default,
                        ),
                    )
                    for seen_factor in substitution.seen_factors
                )
                used_factors.update(substitution.used_factors)
                return substitution

            substituted_python: Python | None = None
            if python_spec:
                python_spec_prime = substitute(python_spec)
                if python_spec_prime.value:
                    from_py_factor = any(
                        PY_FACTOR == seen.factor for seen in python_spec_prime.seen_factors
                    )
                    substituted_python = Python.parse(
                        python_spec_prime.value, from_py_factor=from_py_factor
                    )

            substituted_args: list[str] = []
            for arg in args:
                value = substitute(arg).value
                if value or not isinstance(arg, DiscardEmpty):
                    substituted_args.append(value)

            substituted_extra_env = [(key, substitute(value).value) for key, value in extra_env]

            unused_factors = [factor for factor in factors if factor not in used_factors]
            if unused_factors:
                if len(unused_factors) == 1:
                    raise InvalidModelError(
                        f"The {name} command was parameterized with unused factor "
                        f"'-{unused_factors[0]}'."
                    )
                else:
                    head = ", ".join(f"'-{factor}'" for factor in unused_factors[:-1])
                    tail = f"'-{factors[-1]}'"
                    raise InvalidModelError(
                        f"The {name} command was parameterized with unused factors "
                        f"{head} and {tail}."
                    )

            mismatched_factors_descriptions: list[str] = []
            for factor, desc in factor_descriptions.items():
                factor_desc = seen_factors.get(factor)
                if not factor_desc:
                    mismatched_factors_descriptions.append(factor)
                else:
                    seen_factors[factor] = dataclasses.replace(factor_desc, description=desc)
            if mismatched_factors_descriptions:
                count = len(mismatched_factors_descriptions)
                factor_plural = "factors" if count > 1 else "factor"
                raise InvalidModelError(
                    os.linesep.join(
                        (
                            f"Descriptions were given for {count} {factor_plural} that do not "
                            f"appear in [dev-cmd.commands.{name}] `args` or `env`:",
                            *(
                                f"{index}. {name}"
                                for index, name in enumerate(
                                    mismatched_factors_descriptions, start=1
                                )
                            ),
                        )
                    )
                )

            base: Command | None = None
            if factors:
                base = Command(
                    name=name,
                    args=tuple(args),
                    extra_env=tuple(extra_env),
                    cwd=cwd,
                    accepts_extra_args=accepts_extra_args,
                    base=None,
                    hidden=hidden,
                    description=description,
                    factor_descriptions=tuple(seen_factors.values()),
                    when=when,
                    python=substituted_python or python,
                    dependency_group=dependency_group,
                )

            final_name = f"{name}{factors_suffix}"
            if when and not when.evaluate(
                venv.marker_environment(substituted_python)
                if substituted_python
                else marker_environment
            ):
                yield DeactivatedCommand(final_name)
            else:
                previous_original_name = seen_commands.get(final_name)
                if previous_original_name and previous_original_name != original_name:
                    raise InvalidModelError(
                        f"The command {original_name!r} collides with command "
                        f"{previous_original_name!r}.{os.linesep}"
                        f"You can define a command multiple times, but you must ensure the "
                        f"commands all define mutually exclusive `when` marker expressions."
                    )

                seen_commands[final_name] = original_name
                yield Command(
                    name=final_name,
                    args=tuple(substituted_args),
                    extra_env=tuple(substituted_extra_env),
                    cwd=cwd,
                    accepts_extra_args=accepts_extra_args,
                    base=base,
                    hidden=hidden,
                    description=description,
                    factor_descriptions=tuple(seen_factors.values()),
                    when=when,
                    python=substituted_python or python,
                    dependency_group=dependency_group,
                )


def _parse_group(
    task: str,
    group: list[Any],
    all_task_names: Container[str],
    tasks_defined_so_far: Mapping[str, Task],
    commands: Mapping[str, Command | DeactivatedCommand],
) -> Group:
    members: list[Command | Task | Group] = []
    for index, member in enumerate(group):
        if isinstance(member, str):
            for item in expand(member):
                command = commands.get(item)
                if isinstance(command, DeactivatedCommand):
                    continue
                try:
                    members.append(command or tasks_defined_so_far[item])
                except KeyError:
                    if item in all_task_names:
                        raise InvalidModelError(
                            f"The [tool.dev-cmd.tasks] step `{task}[{index}]` forward-references "
                            f"task {item!r}. Tasks can only reference other tasks that are defined "
                            f"earlier in the file"
                        )
                    available_tasks = (
                        " ".join(sorted(tasks_defined_so_far)) if tasks_defined_so_far else "<None>"
                    )
                    available_commands = " ".join(sorted(commands))
                    raise InvalidModelError(
                        os.linesep.join(
                            (
                                f"The [tool.dev-cmd.tasks] step `{task}[{index}]` is not the name "
                                f"of a defined command or task: {item!r}",
                                "",
                                f"Available tasks: {available_tasks}",
                                f"Available commands: {available_commands}",
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


def _parse_tasks(
    tasks: dict[str, Any] | None,
    commands: Mapping[str, Command | DeactivatedCommand],
    marker_environment: dict[str, str] | None,
) -> Iterator[Task]:
    if not tasks:
        return

    tasks_by_name: dict[str, Task] = {}
    seen_tasks: dict[str, str] = {}
    for name, data in tasks.items():
        original_name = name
        if isinstance(data, dict):
            raw_name = data.pop("name", name)
            if not isinstance(raw_name, str):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.tasks.{name}] `name` value must be a string , given: "
                    f"{raw_name} of type {type(raw_name)}."
                )
            name = raw_name

            group = data.pop("steps", [])
            if not group or not isinstance(group, list):
                raise InvalidModelError(
                    f"Expected the [tool.dev-cmd.tasks.{name}] table to define a `steps` list "
                    f"containing at least one step."
                )

            hidden = data.pop("hidden", False)
            if not isinstance(hidden, bool):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.tasks.{name}] `hidden` value must be a boolean, "
                    f"given: {hidden} of type {type(hidden)}."
                )

            description = data.pop("description", None)
            if description and not isinstance(description, str):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.tasks.{name}] `description` value must be a string, "
                    f"given: {description} of type {type(description)}."
                )

            when = _parse_when(data, table_path=f"[tool.dev-cmd.tasks.{name}]")

            if data:
                raise InvalidModelError(
                    f"Unexpected configuration keys in the [tool.dev-cmd.tasks.{name}] table: "
                    f"{' '.join(data)}"
                )
        elif isinstance(data, list):
            group = data
            hidden = False
            description = None
            when = None
        else:
            raise InvalidModelError(
                f"Expected value at [tool.dev-cmd.tasks] `{name}` to be a list containing strings "
                f"or lists of strings or else a table defining a `steps` list, but given: {data} "
                f"of type {type(data)}."
            )

        if not when or when.evaluate(marker_environment):
            if name in commands:
                raise InvalidModelError(
                    f"The task {name!r} collides with command {name!r}. Tasks and commands share "
                    f"the same namespace and the names must be unique."
                )
            previous_original_name = seen_tasks.get(name)
            if previous_original_name and previous_original_name != original_name:
                raise InvalidModelError(
                    f"The task {original_name!r} collides with task "
                    f"{previous_original_name!r}.{os.linesep}"
                    f"You can define a task multiple times, but you must ensure the "
                    f"tasks all define mutually exclusive `when` marker expressions."
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
                hidden=hidden,
                description=description,
                when=when,
            )
            tasks_by_name[name] = task
            seen_tasks[name] = original_name
            yield task


def _parse_default(
    default: Any, commands: Mapping[str, Command | DeactivatedCommand], tasks: Mapping[str, Task]
) -> Command | Task | None:
    if default is None:
        if len(commands) == 1:
            only_command = next(iter(commands.values()))
            if isinstance(only_command, Command):
                return only_command
        return None

    if not isinstance(default, str):
        raise InvalidModelError(
            f"Expected [tool.dev-cmd] `default` to be a string but given: {default} of type "
            f"{type(default)}."
        )

    if selected_task := tasks.get(default):
        return selected_task
    try:
        selected_command = commands[default]
        return selected_command if isinstance(selected_command, Command) else None
    except KeyError:
        raise InvalidModelError(
            os.linesep.join(
                (
                    f"The [tool.dev-cmd] `default` {default!r} is not the name of a defined "
                    "command or task.",
                    "",
                    f"Available tasks: {' '.join(sorted(tasks)) if tasks else '<None>'}",
                    f"Available commands: {' '.join(sorted(commands))}",
                )
            )
        )


def _parse_exit_style(exit_style: Any) -> ExitStyle | None:
    if exit_style is None:
        return None

    if not isinstance(exit_style, str):
        raise InvalidModelError(
            f"Expected [tool.dev-cmd] `exit-style` to be a string but given: {exit_style} of type "
            f"{type(exit_style)}."
        )

    try:
        return ExitStyle(exit_style)
    except ValueError:
        raise InvalidModelError(
            f"The [tool.dev-cmd] `exit-style` of {exit_style!r} is not recognized. Valid choices "
            f"are {', '.join(repr(es.value) for es in list(ExitStyle)[:-1])} and "
            f"{list(ExitStyle)[-1].value!r}."
        )


def _parse_grace_period(grace_period: Any) -> float | None:
    if grace_period is None:
        return None

    if not isinstance(grace_period, (int, float)):
        raise InvalidModelError(
            f"Expected [tool.dev-cmd] `grace-period` to be a number but given: {grace_period} of "
            f"type {type(grace_period)}."
        )

    return float(grace_period)


def _parse_python(
    index: int,
    python_config_data: dict[str, Any],
    pyproject_data: dict[str, Any],
    defaults: PythonConfig | None = None,
) -> PythonConfig:
    export_command_data = python_config_data.pop("3rdparty-export-command", None)
    if export_command_data is None and defaults is None:
        raise InvalidModelError(
            f"Configuration of [tool.dev-cmd] `python[{index}]` requires a "
            f"`3rdparty-export-command`."
        )
    thirdparty_export_command = (
        Command(
            name=f"python[{index}].3rdparty-export-command",
            args=tuple(
                _assert_list_str(
                    export_command_data,
                    path=f"[tool.dev-cmd] `python[{index}].3rdparty-export-command`",
                )
            ),
        )
        if export_command_data
        # MyPy can't follow the guard logic above.
        else cast(PythonConfig, defaults).thirdparty_export_command
    )

    when = _parse_when(python_config_data, table_path=f"[tool.dev-cmd] `python[{index}]`")

    pip_requirement = defaults.pip_requirement if defaults else "pip"
    pip_requirement_data = python_config_data.pop("pip-requirement", None)
    if pip_requirement_data:
        if not isinstance(pip_requirement_data, str):
            raise InvalidModelError(
                f"[tool.dev-cmd] `python[{index}].pip-req` value must be a string, but given: "
                f"{pip_requirement_data} of type {type(pip_requirement_data)}."
            )
        pip_requirement = pip_requirement_data

    thirdparty_pip_install_opts = defaults.thirdparty_pip_install_opts if defaults else ()
    thirdparty_pip_install_opts_data = python_config_data.pop("3rdparty-pip-install-opts", None)
    if thirdparty_pip_install_opts_data:
        thirdparty_pip_install_opts = tuple(
            _assert_list_str(
                thirdparty_pip_install_opts_data,
                path=f"[tool.dev-cmd] `python[{index}].3rdparty-pip-install-opts`",
            )
        )

    extra_requirements: tuple[str, ...] | str = (
        defaults.extra_requirements if defaults else ("-e", ".")
    )
    extra_requirements_data = python_config_data.pop("extra-requirements", None)
    if extra_requirements_data and isinstance(extra_requirements_data, str):
        extra_requirements = extra_requirements_data
    elif extra_requirements_data is not None:
        extra_requirements = tuple(
            _assert_list_str(
                extra_requirements_data, path=f"[tool.dev-cmd] `python[{index}].extra-requirements`"
            )
        )

    extra_requirements_pip_install_opts = (
        defaults.extra_requirements_pip_install_opts if defaults else ()
    )
    extra_requirements_pip_install_opts_data = python_config_data.pop(
        "extra-requirements-pip-install-opts", None
    )
    if extra_requirements_pip_install_opts_data:
        extra_requirements_pip_install_opts = tuple(
            _assert_list_str(
                extra_requirements_pip_install_opts_data,
                path=f"[tool.dev-cmd] `python[{index}].extra-requirements-pip-install-opts`",
            )
        )

    finalize_command = defaults.finalize_command if defaults else None
    finalize_command_data = python_config_data.pop("finalize-command", None)
    if finalize_command_data:
        finalize_command = Command(
            name=f"python[{index}].finalize-command",
            args=tuple(
                _assert_list_str(
                    finalize_command_data, path=f"[tool.dev-cmd] `python[{index}].finalize-command`"
                )
            ),
        )

    cache_key_inputs_pyproject_data = defaults.cache_key_inputs.pyproject_data if defaults else None
    pyproject_cache_keys_data = python_config_data.pop("pyproject-cache-keys", None)

    cache_key_inputs_paths = set(defaults.cache_key_inputs.paths) if defaults else set()
    cache_key_inputs_envs = defaults.cache_key_inputs.envs if defaults else {}
    extra_cache_keys_data = python_config_data.pop("extra-cache-keys", None)

    if python_config_data:
        raise InvalidModelError(
            f"Unexpected configuration keys in the [tool.dev-cmd] `python[{index}]` table: "
            f"{' '.join(python_config_data)}"
        )

    if extra_cache_keys_data:
        if not isinstance(extra_cache_keys_data, list):
            raise InvalidModelError(
                f"Expected value at [tool.dev-cmd] `python[{index}].extra-cache-keys` to be a "
                f"list, but given: {extra_cache_keys_data} of type {type(extra_cache_keys_data)}."
            )

        input_envs: dict[str, str | None] = {}
        input_paths: set[str] = set()
        for extra_cache_key_index, extra_cache_key in enumerate(extra_cache_keys_data):

            def validate_path(path: str) -> str:
                if os.path.isfile(path) or os.path.isdir(path):
                    return path
                if not os.path.exists(path):
                    raise InvalidModelError(
                        f"Path of {path} given at [tool.dev-cmd] "
                        f"`python[{index}].extra-cache-keys[{extra_cache_key_index}]` does not "
                        f"exist."
                    )
                raise InvalidModelError(
                    f"Path of {path} given at [tool.dev-cmd] "
                    f"`python[{index}].extra-cache-keys[{extra_cache_key_index}]` is not a file or "
                    f"directory."
                )

            if isinstance(extra_cache_key, str):
                input_paths.add(validate_path(extra_cache_key))
            else:
                extra_cache_key_data = _assert_dict_str_keys(
                    extra_cache_key,
                    path=(
                        f"[tool.dev-cmd] "
                        f"`python[{index}].extra-cache-keys[{extra_cache_key_index}]`"
                    ),
                )
                if not len(extra_cache_key_data) == 1:
                    raise InvalidModelError(
                        f"Expected value at [tool.dev-cmd] "
                        f"`python[{index}].extra-cache-keys[{extra_cache_key_index}]` to be either "
                        f"a string representing a file or directory path or else a table with a "
                        f"single `env` or `path` entry, but given: {extra_cache_keys_data} with "
                        f"{len(extra_cache_key_data)} entries."
                    )
                env_data = extra_cache_key_data.pop("env", None)
                if env_data:
                    if not isinstance(env_data, str):
                        raise InvalidModelError(
                            f"Expected value at [tool.dev-cmd] "
                            f"`python[{index}].extra-cache-keys[{extra_cache_key_index}].env` to "
                            f"be a string, but given: {env_data} of type {type(env_data)}."
                        )
                    input_envs[env_data] = os.environ.get(env_data)
                else:
                    path_data = extra_cache_key_data.pop("path", None)
                    if path_data:
                        if not isinstance(path_data, str):
                            raise InvalidModelError(
                                f"Expected value at [tool.dev-cmd] "
                                f"`python[{index}].extra-cache-keys[{extra_cache_key_index}].path` "
                                f"to be a string, but given: {path_data} of type {type(path_data)}."
                            )
                        input_paths.add(validate_path(path_data))
                if extra_cache_key_data:
                    raise InvalidModelError(
                        f"Unexpected configuration keys in the [tool.dev-cmd] "
                        f"`python[{index}].extra-cache-keys[{extra_cache_key_index}]` table: "
                        f"{' '.join(extra_cache_key_data)}"
                    )
        cache_key_inputs_envs = input_envs
        cache_key_inputs_paths = input_paths

    if (
        pyproject_cache_keys_data is None and cache_key_inputs_pyproject_data is None
    ) or pyproject_cache_keys_data is not None:
        cache_key_inputs_paths.discard("pyproject.toml")
        input_keys = (
            _assert_list_str(
                pyproject_cache_keys_data,
                path=f"[tool.dev-cmd] `python[{index}].pyproject-cache-keys]",
            )
            if pyproject_cache_keys_data is not None
            else ["build-system", "project", "project.optional-dependencies"]
        )
        input_item_data: dict[str, Any] = {}
        for key in input_keys:
            value = pyproject_data
            for component in key.split("."):
                value = value.get(component, None)
                if value is None:
                    raise InvalidModelError(
                        f"The [tool.dev-cmd] `python[{index}].pyproject-cache-keys` key of {key} "
                        f"could not be found in pyproject.toml."
                    )
            input_item_data[key] = value
        cache_key_inputs_pyproject_data = input_item_data

    cache_key_inputs = CacheKeyInputs(
        pyproject_data=cache_key_inputs_pyproject_data or {},
        envs=cache_key_inputs_envs,
        paths=tuple(sorted(cache_key_inputs_paths)),
    )

    return PythonConfig(
        when=when,
        cache_key_inputs=cache_key_inputs,
        thirdparty_export_command=thirdparty_export_command,
        thirdparty_pip_install_opts=thirdparty_pip_install_opts,
        pip_requirement=pip_requirement,
        extra_requirements=extra_requirements,
        extra_requirements_pip_install_opts=extra_requirements_pip_install_opts,
        finalize_command=finalize_command,
    )


def select_python_config(
    python: Python, pythons: Iterable[PythonConfig], quiet: bool = False
) -> PythonConfig | None:
    marker_environment = venv.marker_environment(python, quiet=quiet)
    activated_index: int | None = None
    activated_python_config: PythonConfig | None = None
    for index, python_config in enumerate(pythons):
        if python_config.when and not python_config.when.evaluate(marker_environment):
            continue
        if activated_index is not None:
            raise InvalidModelError(
                f"The [tool.dev-cmd] `python` entries at index {activated_index} and {index} are "
                f"both active.{os.linesep}"
                f"You can define multiple [tool.dev-cmd] `python` tables, but you must ensure that "
                f"they all define mutually exclusive `when` marker expressions."
            )
        activated_python_config = python_config
        activated_index = index
    return activated_python_config


def _parse_pythons(
    python: Python | None, python_config_data: Any, pyproject_data: dict[str, Any]
) -> tuple[dict[str, str] | None, tuple[PythonConfig, ...]]:
    if python and not python_config_data:
        raise InvalidArgumentError(
            f"You requested a custom Python of {python} but have not configured any "
            f"`[[tool.dev-cmd.python]]` entries.\n"
            f"See: https://github.com/jsirois/dev-cmd/blob/main/README.md#custom-pythons"
        )
    if not python_config_data:
        return None, ()

    pythons: list[PythonConfig] = []
    defaults: PythonConfig | None = None
    for index, python_data in enumerate(
        _assert_list_dict_str_keys(python_config_data, path="[tool.dev-cmd] `python`")
    ):
        if index == 0:
            defaults = _parse_python(0, python_data, pyproject_data)
        pythons.append(
            # MyPy fails to track the logic here and conclude defaults can't be None.
            cast(PythonConfig, defaults)
            if index == 0
            else _parse_python(index, python_data, pyproject_data, defaults=defaults)
        )

    marker_environment = venv.marker_environment(python) if python else None

    return marker_environment, tuple(pythons)


def _iter_all_required_step_names(
    value: Any, tasks_data: Mapping[str, Any], seen: Set[str]
) -> Iterator[str]:
    if isinstance(value, str) and value not in seen:
        for name in expand(value):
            seen.add(name)
            yield name
            if task_data := tasks_data.get(name):
                yield from _iter_all_required_step_names(task_data, tasks_data, seen)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_all_required_step_names(item, tasks_data, seen)
    elif isinstance(value, dict):
        yield from _iter_all_required_step_names(value.get("steps", []), tasks_data, seen)


def _gather_all_required_step_names(
    requested_step_names: Iterable[str], tasks_data: Mapping[str, Any]
) -> tuple[str, ...]:
    required_step_names: list[str] = []
    seen: set[str] = set()
    for requested_step_name in dict.fromkeys(itertools.chain(requested_step_names, tasks_data)):
        required_step_names.extend(
            _iter_all_required_step_names(requested_step_name, tasks_data, seen)
        )
    return tuple(dict.fromkeys(required_step_names))


def parse_dev_config(
    pyproject_toml: PyProjectToml, *requested_steps: str, requested_python: Python | None = None
) -> tuple[Configuration, tuple[str, ...]]:
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

    marker_environment, pythons = _parse_pythons(
        python=requested_python,
        python_config_data=dev_cmd_data.pop("python", None),
        pyproject_data=pyproject_data,
    )

    def pop_dict(key: str, *, path: str) -> dict[str, Any] | None:
        data = dev_cmd_data.pop(key, None)
        return _assert_dict_str_keys(data, path=path) if data else None

    commands_data = pop_dict("commands", path="[tool.dev-cmd.commands]") or {}
    tasks_data = pop_dict("tasks", path="[tool.dev-cmd.tasks]") or {}
    default_step_name = dev_cmd_data.pop("default", None)

    required_steps: defaultdict[str, list[tuple[Factor, ...]]] = defaultdict(list)
    known_names = tuple(
        data.get("name", name) if isinstance(data, dict) else name
        for name, data in itertools.chain(commands_data.items(), tasks_data.items())
    )
    required_step_names = (
        _gather_all_required_step_names(requested_steps, tasks_data) or known_names
    )
    requested_step_names: dict[str, str] = {step: step for step in requested_steps}
    for required_step_name in required_step_names:
        if required_step_name in known_names:
            required_steps[required_step_name].append(())
            continue
        for known_name in known_names:
            if not required_step_name.startswith(f"{known_name}-"):
                continue

            factors: list[Factor] = []
            factor_chars: list[str] = []
            chars = deque(required_step_name[len(known_name) + 1 :])
            while chars:
                while chars:
                    char = chars.popleft()

                    if char != "-":
                        factor_chars.append(char)
                        continue

                    # Escaped - (--)
                    if chars and chars[0] == "-":
                        factor_chars.append(char)
                        chars.popleft()
                        continue

                    if not chars:
                        factor_chars.append(char)

                    break
                factors.append(Factor("".join(factor_chars)))
                factor_chars.clear()

            required_steps[known_name].append(tuple(factors))
            requested_step_names[required_step_name] = (
                f"{known_name}-{'-'.join(factors)}" if factors else known_name
            )
            break

    commands: dict[str, Command | DeactivatedCommand] = {}
    for cmd in _parse_commands(
        commands_data,
        required_steps,
        project_dir=pyproject_toml.path.parent,
        python=requested_python,
        marker_environment=marker_environment,
    ):
        existing = commands.setdefault(cmd.name, cmd)
        if isinstance(existing, DeactivatedCommand) and isinstance(cmd, Command):
            commands[cmd.name] = cmd
    if not commands:
        raise InvalidModelError(
            "No commands are defined in the [tool.dev-cmd.commands] table. At least one must be "
            "configured to use the dev task runner."
        )

    tasks = {
        task.name: task
        for task in _parse_tasks(tasks_data, commands, marker_environment=marker_environment)
    }
    default = _parse_default(default_step_name, commands, tasks)
    exit_style = _parse_exit_style(dev_cmd_data.pop("exit-style", None))
    grace_period = _parse_grace_period(dev_cmd_data.pop("grace-period", None))

    if dev_cmd_data:
        raise InvalidModelError(
            f"Unexpected configuration keys in the [tool.dev-cmd] table: {' '.join(dev_cmd_data)}"
        )

    configuration = Configuration(
        commands=tuple(cmd for cmd in commands.values() if isinstance(cmd, Command)),
        tasks=tuple(tasks.values()),
        default=default,
        exit_style=exit_style,
        grace_period=grace_period,
        pythons=pythons,
        source=pyproject_toml.path,
    )

    return configuration, tuple(requested_step_names[step] for step in requested_steps)
