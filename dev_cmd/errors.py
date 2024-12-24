# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class DevError(Exception):
    """Indicates an error processing dev commands."""


class InvalidProjectError(DevError):
    """Indicates the dev runner cannot locate or parse the `pyproject.toml` file."""


class InvalidArgumentError(DevError):
    """Indicates invalid argument were passed to the dev command."""


class InvalidModelError(DevError):
    """Indicates invalid dev command configuration."""


class ParallelExecutionError(Exception):
    """Conveys details of 2 or more failed parallel commands."""
