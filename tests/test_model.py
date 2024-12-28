# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from dev_cmd.errors import InvalidModelError
from dev_cmd.invoke import Invocation
from dev_cmd.model import Command


def test_invocation_create_no_extra_args():
    command = Command("foo", args=())
    invocation = Invocation.create(command)
    assert not invocation.accepts_extra_args
    assert (command,) == invocation.steps


def test_invocation_create_accepts_extra_args():
    foo = Command("foo", args=(), accepts_extra_args=True)
    bar = Command("bar", args=(), accepts_extra_args=False)
    invocation = Invocation.create(foo, bar)
    assert invocation.accepts_extra_args
    assert foo, bar == invocation.steps


def test_invocation_create_multiple_extra_args():
    foo = Command("foo", args=(), accepts_extra_args=True)
    bar = Command("bar", args=(), accepts_extra_args=True)
    with pytest.raises(
        InvalidModelError,
        match=(
            r"The command 'bar' accepts extra args, but only one command can accept extra args per "
            r"invocation and command 'foo' already does."
        ),
    ):
        Invocation.create(foo, bar)
