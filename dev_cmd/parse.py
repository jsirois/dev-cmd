# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple, cast

from dev_cmd.errors import InvalidModelError
from dev_cmd.model import Command, Dev
from dev_cmd.project import PyProjectToml


def _assert_list_str(obj: Any, *, path: str) -> List[str]:
    if not isinstance(obj, list) or not all(isinstance(item, str) for item in obj):
        raise InvalidModelError(
            f"Expected value at {path} to be a list of strings, but given: {obj} of type "
            f"{type(obj)}."
        )
    return cast("List[str]", obj)


def _assert_dict_str_keys(obj: Any, *, path: str) -> Dict[str, Any]:
    if not isinstance(obj, dict) or not all(isinstance(key, str) for key in obj):
        raise InvalidModelError(
            f"Expected value at {path} to be a dict with string keys, but given: {obj} of type "
            f"{type(obj)}."
        )
    return cast("Dict[str, Any]", obj)


def _parse_commands(commands: Optional[Dict[str, Any]]) -> Iterator[Command]:
    if not commands:
        raise InvalidModelError(
            "There must be at least one entry in the [tool.dev-cmd.commands] table to run "
            "`dev-cmd`."
        )

    for name, data in commands.items():
        env = os.environ.copy()
        if isinstance(data, list):
            args = tuple(_assert_list_str(data, path=f"[tool.dev-cmd.commands.{name}]"))
            accepts_extra_args = False
        else:
            command = _assert_dict_str_keys(data, path=f"[tool.dev-cmd.commands.{name}]")

            for key, val in _assert_dict_str_keys(
                command.pop("env", {}), path=f"[tool.dev-cmd.commands.{name}.env]"
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
                        command.pop("args"), path=f"[tool.dev-cmd.commands.{name}.args]"
                    )
                )
            except KeyError:
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}] table must define an `args` list."
                )

            accepts_extra_args = command.pop("accepts-extra-args", False)
            if not isinstance(accepts_extra_args, bool):
                raise InvalidModelError(
                    f"The [tool.dev-cmd.commands.{name}.accepts-extra-args] value must be either "
                    f"`true` or `false`, given: {accepts_extra_args} of type "
                    f"{type(accepts_extra_args)}."
                )
            if data:
                raise InvalidModelError(
                    f"Unexpected configuration keys in the [tool.dev-cmd.commands.{name}] table: "
                    f"{' '.join(data)}"
                )
        yield Command(name, env, args, accepts_extra_args=accepts_extra_args)


def _parse_aliases(aliases: Optional[Dict[str, Any]]) -> Iterator[Tuple[str, Tuple[str, ...]]]:
    if aliases:
        for alias, commands in aliases.items():
            yield alias, tuple(_assert_list_str(commands, path=f"[tool.dev-cmd.aliases.{alias}]"))


def _parse_default(
    default: Optional[Dict[str, Any]],
    commands: Mapping[str, Command],
    aliases: Mapping[str, Tuple[Command, ...]],
) -> Optional[Tuple[str, Tuple[Command, ...]]]:
    if not default:
        if len(commands) == 1:
            name, command = next(iter(commands.items()))
            return name, tuple([command])
        return None

    default_commands: Optional[Tuple[str, Tuple[Command, ...]]] = None
    alias = default.pop("alias", None)
    if alias:
        if not isinstance(alias, str):
            raise InvalidModelError(
                f"Expected default alias to be a string but given: {alias} of type {type(alias)}."
            )
        try:
            default_commands = alias, aliases[alias]
        except KeyError:
            raise InvalidModelError(f"The default alias {alias!r} is not defined.")
    else:
        command = default.pop("command", None)
        if command:
            if not isinstance(command, str):
                raise InvalidModelError(
                    f"Expected default command to be a string but given: {alias} of type "
                    f"{type(alias)}."
                )
            try:
                default_commands = command, tuple([commands[command]])
            except KeyError:
                raise InvalidModelError(f"The default command {command!r} is not defined.")
    if default:
        raise InvalidModelError(
            f"Unexpected configuration keys in the default table: {' '.join(default)}"
        )
    return default_commands


def parse_dev_config(pyproject_toml: PyProjectToml) -> Dev:
    pyproject_data = pyproject_toml.parse()
    try:
        run_dev_data = _assert_dict_str_keys(
            pyproject_data["tool"]["dev-cmd"], path="[tool.dev-cmd]"
        )  # type: ignore[index]
    except KeyError as e:
        raise InvalidModelError(
            f"The commands, aliases and defaults run-dev acts upon must be defined in the "
            f"[tool.dev-cmd] table in {pyproject_toml}: {e}"
        )

    def pop_dict(key: str, *, path: str) -> Optional[Dict[str, Any]]:
        data = run_dev_data.pop(key, None)
        return _assert_dict_str_keys(data, path=path) if data else None

    commands = {
        command.name: command
        for command in _parse_commands(pop_dict("commands", path="[tool.dev-cmd.commands]"))
    }
    aliases: Dict[str, Tuple[Command, ...]] = {}
    for alias, cmds in _parse_aliases(pop_dict("aliases", path="[tool.dev-cmd.aliases-]")):
        if alias in commands:
            raise InvalidModelError(
                f"The alias name {alias!r} conflicts with a command of the same name."
            )
        alias_cmds: List[Command] = []
        for cmd in cmds:
            if cmd in commands:
                alias_cmds.append(commands[cmd])
            elif cmd in aliases:
                alias_cmds.extend(aliases[cmd])
            else:
                raise InvalidModelError(
                    f"The task {cmd!r} defined in alias {alias!r} is neither a command nor a "
                    f"previously defined alias."
                )
        aliases[alias] = tuple(alias_cmds)

    default = _parse_default(pop_dict("default", path="[tool.dev-cmd.default]"), commands, aliases)

    if run_dev_data:
        raise InvalidModelError(
            f"Unexpected configuration keys in the [tool.dev-cmd] table: {' '.join(run_dev_data)}"
        )
    if not commands:
        raise InvalidModelError(
            "No commands are defined in the [tool.dev-cmd.commands] table. At least one must be "
            "configured to use the dev task runner."
        )

    return Dev(default=default, commands=commands, aliases=aliases, source=pyproject_toml.path)
