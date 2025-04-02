# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import shlex
import signal
from dataclasses import dataclass
from typing import Collection

from dev_cmd.model import Command


class DevCmdError(Exception):
    """Indicates an error processing `dev-cmd` configuration."""


class InvalidProjectError(DevCmdError):
    """Indicates the `dev-cmd` runner cannot locate or parse the `pyproject.toml` file."""


class InvalidArgumentError(DevCmdError):
    """Indicates invalid arguments were passed to `dev-cmd`."""


class InvalidModelError(DevCmdError):
    """Indicates invalid `dev-cmd` configuration."""


# N.B.: This cannot be frozen because Python can attempt to assign to `__traceback__` on exception
# instances after they are constructed.
@dataclass
class ExecutionError(Exception):
    """Conveys details of 1 or more command failures in a `dev-cmd` invocation."""

    @classmethod
    def from_failed_cmd(cls, cmd: Command, exit_code: int) -> ExecutionError:
        if exit_code < 0:
            try:
                reason = f"died with {signal.Signals(-exit_code).name}"
            except ValueError:
                reason = f"died with unknown signal {-exit_code}"
        else:
            reason = f"returned non-zero exit status {exit_code}"

        return cls(
            step_name=cmd.name,
            message=f"Command `{shlex.join(cmd.args)}` {reason}",
            exit_code=exit_code,
        )

    @classmethod
    def from_errors(
        cls,
        step_name: str | None,
        total_count: int,
        errors: Collection[ExecutionError],
        parallel: bool = False,
    ) -> ExecutionError:
        name = step_name or "*"
        maybe_parallel = "parallel " if parallel else ""
        lines = [f"{len(errors)} of {total_count} {maybe_parallel}commands in {name} failed:"]
        lines.extend(f"{error.step_name}: {error.message}" for error in errors)
        return cls(step_name=name, message=os.linesep.join(lines))

    step_name: str
    message: str
    exit_code: int = 1
