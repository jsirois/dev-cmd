# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Protocol, TypeVar, runtime_checkable

S = TypeVar("S", contravariant=True)
R = TypeVar("R", covariant=True)


@runtime_checkable
class Substituter(Protocol[S, R]):
    def raw_text(self, text: str, *, state: S) -> None: ...
    def substitution(self, text: str, section: slice, *, state: S) -> None: ...
    def result(self, *, state: S) -> R: ...


def substitute_partial(text: str, substituter: Substituter[S, R], *, state: S) -> None:
    if "{" == text:
        raise ValueError(
            "Encountered text of '{'. If a literal '{' is intended, escape it like so: '{{'."
        )

    previous_char = ""
    inside_placeholder = 0
    start = 0
    for index, c in enumerate(text):
        if "{" == c and inside_placeholder == 0:
            if index - start > 0:
                substituter.raw_text(text[start:index], state=state)
            previous_char = "{"
            inside_placeholder = 1
            start = index + 1
        elif "{" == c and inside_placeholder > 0 and previous_char == "{":
            substituter.raw_text("{", state=state)
            inside_placeholder = 0
            start = index + 1
        elif "{" == c and inside_placeholder > 0:
            inside_placeholder += 1
        elif "}" == c and inside_placeholder > 1:
            inside_placeholder -= 1
        elif "}" == c and inside_placeholder == 1:
            substituter.substitution(text, slice(start, index), state=state)
            previous_char = "}"
            inside_placeholder = 0
            start = index + 1
        else:
            previous_char = c

    if len(text) - start > 0:
        substituter.raw_text(text[start:], state=state)


def substitute(text: str, substituter: Substituter[S, R], *, state: S) -> R:
    substitute_partial(text, substituter, state=state)
    return substituter.result(state=state)
