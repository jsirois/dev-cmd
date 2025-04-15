# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import re
import sys

import pytest
from packaging.markers import default_environment

from dev_cmd.model import Factor
from dev_cmd.placeholder import Environment, SeenFactor, Substitution


@pytest.fixture
def env() -> Environment:
    return Environment()


def substitute(env: Environment, text: str) -> str:
    return env.substitute(text).value


def test_substitute_noop(env: Environment) -> None:
    assert "" == substitute(env, "")
    assert "foo" == substitute(env, "foo")


def test_substitute_env() -> None:
    env = Environment(env={"FOO": "bar", "BAZ": "FOO"})

    assert "bar" == substitute(env, "{env.FOO}")
    assert "FOO" == substitute(env, "{env.BAZ}")

    assert "bar" == substitute(env, "{env.{env.BAZ}}"), "Expected recursive substitution to work."

    assert "baz" == substitute(env, "{env.DNE:baz}"), "Expected defaulting to work."
    assert "env.FOO" == substitute(env, "{env.DNE:env.FOO}")

    assert "bar" == substitute(env, "{env.DNE:{env.also_DNE:{env.FOO}}}"), (
        "Expected recursive defaults would work."
    )

    with pytest.raises(ValueError, match=re.escape("The environment variable 'DNE' is not set.")):
        env.substitute("{env.DNE}")


def test_substitute_markers(env) -> None:
    current_markers = default_environment()

    assert (
        ".".join(map(str, sys.version_info[:2]))
        == current_markers["python_version"]
        == substitute(env, "{markers.python_version}")
    )
    assert (
        ".".join(map(str, sys.version_info[:3]))
        == current_markers["python_full_version"]
        == substitute(env, "{markers.python_full_version}")
    )

    with pytest.raises(
        ValueError, match=re.escape("There is no Python environment marker named 'bob'.")
    ):
        env.substitute("{markers.bob}")


def test_substitute_factors(env: Environment) -> None:
    factors = Factor("a1"), Factor("b:2")
    assert Substitution.create(
        "1", seen_factors=[SeenFactor(Factor("a"))], used_factors=[Factor("a1")]
    ) == env.substitute("{-a}", *factors)
    assert Substitution.create(
        "2", seen_factors=[SeenFactor(Factor("b"))], used_factors=[Factor("b:2")]
    ) == env.substitute("{-b}", *factors)
    assert Substitution.create(
        "12",
        seen_factors=[SeenFactor(Factor("a")), SeenFactor(Factor("b"))],
        used_factors=[Factor("a1"), Factor("b:2")],
    ) == env.substitute("{-a}{-b}", *factors)
    assert Substitution.create(
        "123",
        seen_factors=[
            SeenFactor(Factor("a")),
            SeenFactor(Factor("b")),
            SeenFactor(Factor("c"), default="3"),
        ],
        used_factors=[Factor("a1"), Factor("b:2")],
    ) == env.substitute("{-a}{-b}{-c:3}", *factors)

    with pytest.raises(ValueError, match=re.escape("The factor parameter '-c' is not set.")):
        env.substitute("{-c}", *factors)

    with pytest.raises(
        ValueError,
        match=re.escape(
            "The factor parameter '-foo' matches more than one factor argument: '-foo1' '-foobar2'"
        ),
    ):
        env.substitute("{-foo}", Factor("foo1"), Factor("foobar2"))


def test_substitute_flag_factor(env: Environment) -> None:
    assert Substitution.create(
        "true",
        seen_factors=[SeenFactor(Factor("flag"), flag_value="true", default="false")],
        used_factors=[Factor("flag")],
    ) == env.substitute("{-flag?true:false}", Factor("flag"))

    env = Environment(env={"FOO": "bar", "BAZ": "FOO"})
    assert Substitution.create(
        "bar",
        seen_factors=[
            SeenFactor(Factor("flag"), flag_value="{env.FOO:true}", default="{env.BAZ:false}")
        ],
        used_factors=[Factor("flag")],
    ) == env.substitute("{-flag?{env.FOO:true}:{env.BAZ:false}}", Factor("flag"))


def test_substitute_intra_recursive() -> None:
    expected_python_version = ".".join(map(str, sys.version_info[:2]))

    env = Environment(env={"USE_FACTOR": "py", "USE_MARKER": "python_version"})
    assert expected_python_version == substitute(env, "{markers.{env.USE_MARKER}}")
    assert Substitution.create(
        expected_python_version,
        seen_factors=[SeenFactor(Factor("py"))],
        used_factors=[Factor("py{markers.{env.USE_MARKER}}")],
    ) == env.substitute("{-{env.USE_FACTOR}}", Factor("py{markers.{env.USE_MARKER}}"))


def test_substitute_hashseed() -> None:
    env = Environment(hashseed=42)
    assert Substitution.create("42") == env.substitute("{--hashseed}")

    with pytest.raises(
        ValueError,
        match=re.escape(
            "The {--hashseed} placeholder does not accept a default. Found placeholder: "
            "{--hashseed:137}"
        ),
    ):
        env.substitute("{--hashseed:137}")
