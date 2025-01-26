# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, cast

from packaging import markers

from dev_cmd import brace_substitution
from dev_cmd.brace_substitution import Substituter
from dev_cmd.model import Factor


@dataclass
class State:
    factors: tuple[Factor, ...] = ()
    text: list[str] = field(default_factory=list, init=False)
    seen_factors: list[tuple[Factor, str | None]] = field(default_factory=list, init=False)
    used_factors: list[Factor] = field(default_factory=list, init=False)


@dataclass(frozen=True)
class Substitution:
    @classmethod
    def create(
        cls,
        value: str,
        seen_factors: Iterable[tuple[Factor, str | None]] = (),
        used_factors: Iterable[Factor] = (),
    ) -> Substitution:
        return cls(
            value=value,
            seen_factors=tuple(dict.fromkeys(seen_factors)),
            used_factors=tuple(dict.fromkeys(used_factors)),
        )

    value: str
    seen_factors: tuple[tuple[Factor, str | None], ...] = ()
    used_factors: tuple[Factor, ...] = ()


@dataclass(frozen=True)
class Environment(Substituter[State, str]):
    env: Mapping[str, str] = field(default_factory=os.environ.copy)
    markers: Mapping[str, str] = field(
        default_factory=cast(Callable[[], Mapping[str, str]], markers.default_environment)
    )

    def substitute(self, text: str, *factors: Factor) -> Substitution:
        state = State(factors)
        result = brace_substitution.substitute(text, self, state=state)
        return Substitution.create(
            value=result, seen_factors=state.seen_factors, used_factors=state.used_factors
        )

    def raw_text(self, text: str, state: State) -> None:
        state.text.append(text)

    def substitution(self, text: str, section: slice, state: State) -> None:
        symbol = text[section]
        key, sep, deflt = symbol.partition(":")
        if not key:
            raise ValueError(
                f"Encountered placeholder '{{}}' at position {section.stop} in {text!r}. "
                f"Placeholders must have keys. If a literal '{{}}' is intended, escape the "
                f"opening bracket like so '{{{{}}'."
            )
        default = deflt if sep else None
        value: str | None
        if key.startswith("-"):
            factor_name = self.substitute(key[1:]).value
            state.seen_factors.append((Factor(factor_name), default))
            matching_factors = [
                factor for factor in state.factors if factor.startswith(factor_name)
            ]
            if not matching_factors and not default:
                raise ValueError(f"The factor parameter '-{factor_name}' is not set.")
            if len(matching_factors) > 1:
                factors = " ".join(f"'-{factor}'" for factor in matching_factors)
                raise ValueError(
                    f"The factor parameter '-{factor_name}' matches more than one factor argument: "
                    f"{factors}"
                )
            if matching_factors:
                value = matching_factors[0][len(factor_name) :]
                if value.startswith(":"):
                    value = value[1:]
                state.used_factors.append(matching_factors[0])
            else:
                value = default
            if value is None:
                raise ValueError(f"The factor {factor_name!r} is not set.")
        elif key.startswith("env."):
            env_var_name = self.substitute(key[4:]).value
            value = self.env.get(env_var_name, default)
            if value is None:
                raise ValueError(f"The environment variable {env_var_name!r} is not set.")
        elif key.startswith("markers."):
            marker_name = self.substitute(key[8:]).value
            try:
                value = self.markers[marker_name] or default
            except KeyError:
                raise ValueError(f"There is no Python environment marker named {marker_name!r}.")
            if value is None:
                raise ValueError(
                    f"The environment environment marker named {marker_name!r} is not set."
                )
        else:
            raise ValueError(f"Unrecognized substitution key {key!r}.")
        state.text.append(self.substitute(value).value)

    def result(self, state: State) -> str:
        return "".join(state.text)


DEFAULT_ENVIRONMENT = Environment()
