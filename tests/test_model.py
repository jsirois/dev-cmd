# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from dev_cmd.errors import InvalidArgumentError, InvalidModelError
from dev_cmd.invoke import Invocation
from dev_cmd.model import Command


def test_invocation_create_no_extra_args():
    command = Command("foo", args=())

    invocation = Invocation.create(command, skips=(), grace_period=1.0)
    assert (command,) == invocation.steps

    with pytest.raises(
        InvalidArgumentError,
        match=(
            r"The following extra args were passed but none of the selected commands accept extra "
            r"arguments: unused"
        ),
    ):
        Invocation.create(command, skips=(), grace_period=1.0, extra_args=("unused",))


def test_invocation_create_accepts_extra_args():
    foo = Command("foo", args=(), accepts_extra_args=True)
    bar = Command("bar", args=(), accepts_extra_args=False)

    invocation = Invocation.create(foo, bar, skips=(), grace_period=1.0)
    assert foo, bar == invocation.steps

    invocation = Invocation.create(foo, bar, skips=(), grace_period=1.0, extra_args=("a", "b"))
    assert foo, bar == invocation.steps


def test_invocation_create_multiple_extra_args():
    foo = Command("foo", args=(), accepts_extra_args=True)
    bar = Command("bar", args=(), accepts_extra_args=True)

    invocation = Invocation.create(foo, bar, skips=(), grace_period=1.0)
    assert tuple([foo, bar]) == invocation.steps, (
        "Expected conflicting accepts_extra_args to be OK when extra args are not actually passed."
    )

    with pytest.raises(
        InvalidModelError,
        match=(
            r"The command 'bar' accepts extra args, but only one command can accept extra args per "
            r"invocation and command 'foo' already does."
        ),
    ):
        Invocation.create(foo, bar, skips=(), grace_period=1.0, extra_args=("a", "b"))

    invocation = Invocation.create(foo, bar, skips=["foo"], grace_period=1.0)
    assert tuple([bar]) == invocation.steps
