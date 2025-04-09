# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev_cmd.errors import InvalidProjectError

try:
    import tomllib as toml  # type: ignore[import-not-found]
    from tomllib import TOMLDecodeError as TOMLError  # type: ignore[import-not-found]
except ImportError:
    import tomli as toml  # type: ignore[import-not-found,no-redef]
    from tomli import (  # type: ignore[import-not-found,no-redef,assignment]
        TOMLDecodeError as TOMLError,
    )


@dataclass(frozen=True)
class PyProjectToml:
    path: Path

    def parse(self) -> dict[str, Any]:
        try:
            with self.path.open("rb") as fp:
                return toml.load(fp)
        except (OSError, TOMLError) as e:
            raise InvalidProjectError(f"Failed to parse {self.path}: {e}")


def find_pyproject_toml() -> PyProjectToml:
    start = Path()
    candidate = start.resolve()
    while True:
        pyproject_toml = candidate / "pyproject.toml"
        if pyproject_toml.is_file():
            return PyProjectToml(pyproject_toml)
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    raise InvalidProjectError(
        os.linesep.join(
            (
                f"Failed to find the project root searching from directory '{start.resolve()}'.",
                "No `pyproject.toml` file found at its level or above.",
            )
        )
    )
