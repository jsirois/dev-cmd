# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from importlib.metadata import PackageNotFoundError
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
    module = Path(__file__)
    start = module.parent
    try:
        dist_files = metadata.files("dev-cmd")
        if dist_files and any(module == dist_file.locate() for dist_file in dist_files):
            # N.B.: We're running from an installed package; so use the PWD as the search start.
            start = Path()
    except PackageNotFoundError:
        # N.B.: We're being run directly from sources that are not installed or are installed in
        # editable mode.
        pass

    candidate = start.resolve()
    while True:
        pyproject_toml = candidate / "pyproject.toml"
        if pyproject_toml.is_file():
            return PyProjectToml(pyproject_toml)
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    raise InvalidProjectError(
        f"Failed to find the project root searching from {start}. No `pyproject.toml` file found "
        f"at its level or above."
    )
