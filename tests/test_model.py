# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath

import pytest

from dev_cmd.errors import InvalidModelError
from dev_cmd.model import Command, Invocation


def test_invocation_create_no_extra_args():
    command = Command("foo", env={}, args=(), cwd=PurePath(), accepts_extra_args=False)
    invocation = Invocation.create(("foo", [command]))
    assert not invocation.accepts_extra_args
    assert {"foo": (command,)} == invocation.tasks


def test_invocation_create_accepts_extra_args():
    foo = Command("foo", env={}, args=(), cwd=PurePath(), accepts_extra_args=True)
    bar = Command("bar", env={}, args=(), cwd=PurePath(), accepts_extra_args=False)
    invocation = Invocation.create(("foo", [foo]), ("bar", [bar]))
    assert invocation.accepts_extra_args
    assert {"foo": (foo,), "bar": (bar,)} == invocation.tasks


def test_invocation_create_multiple_extra_args():
    foo = Command("foo", env={}, args=(), cwd=PurePath(), accepts_extra_args=True)
    bar = Command("bar", env={}, args=(), cwd=PurePath(), accepts_extra_args=True)
    with pytest.raises(
        InvalidModelError,
        match=(
            r"The command 'bar' accepts extra args, but only one command can accept extra args per "
            r"invocation and command 'foo' already does."
        ),
    ):
        Invocation.create(("task", [foo, bar]))
