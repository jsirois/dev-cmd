# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import math
import re
from collections import deque
from typing import Iterable, Iterator, List, Tuple, TypeVar, Union

from dev_cmd import brace_substitution
from dev_cmd.brace_substitution import Substituter

T = TypeVar("T")


def sliding_window(items: Iterable[T], size: int) -> Iterator[Tuple[T, ...]]:
    iterator = iter(items)
    window = deque(itertools.islice(iterator, size - 1), maxlen=size)
    for x in iterator:
        window.append(x)
        yield tuple(window)


class ExpandBraces(Substituter[List[Union[str, List[str]]], Tuple[str, ...]]):
    def raw_text(self, text: str, *, state: list[str | list[str]]) -> None:
        state.append(text)

    def substitution(self, text: str, section: slice, *, state: list[str | list[str]]) -> None:
        symbol = text[section]
        if match := re.match(
            r"(?P<start>-?\d+)\.\.(?P<stop>-?\d+)(?:\.\.(?P<step>-?\d+))?", symbol
        ):
            start = int(match["start"])
            stop = int(match["stop"])
            if raw_step := match.group("step"):
                step = int(raw_step)
            else:
                step = 1 if start <= stop else -1
            stop += int(math.copysign(1, step))
            state.append(list(map(str, range(start, stop, step))))
        elif "," in symbol:
            expansion: list[str | list[str]] = []
            brace_substitution.substitute_partial(symbol, self, state=expansion)

            work: list[str | list[str]] = []
            for item in expansion:
                if isinstance(item, str):
                    work.extend(item.split(","))
                else:
                    work.append(item)

            expanded: list[str] = []
            for prefix, item in sliding_window(["", *work], 2):
                if isinstance(prefix, str):
                    if isinstance(item, str):
                        expanded.append(item)
                    else:
                        if not expanded:
                            expanded.extend(item)
                        else:
                            expanded[-1:] = [f"{expanded[-1]}{atom}" for atom in item]
                elif isinstance(prefix, list):
                    if isinstance(item, str):
                        expanded[-len(prefix) :] = [f"{p}{item}" for p in expanded[-len(prefix) :]]
                    else:
                        expanded[-len(prefix) :] = [
                            f"{p}{atom}" for p in expanded[-len(prefix) :] for atom in item
                        ]

            state.append(expanded)
        else:
            raise ValueError(
                f"Encountered expansion '{{{symbol}}}' at position {section.start} in {text!r}. "
                f"Expansions must either contain multiple comma-separated atoms to expand or else "
                f"a range descriptor of form `<N>..<M>(..<S>)?`."
            )

    def result(self, *, state: list[str | list[str]]) -> tuple[str, ...]:
        results: list[str] = []
        for item in state:
            if isinstance(item, str):
                if not results:
                    results = [item]
                else:
                    results[:] = [f"{result}{item}" for result in results]
            else:
                results[:] = [f"{result}{atom}" for result in results for atom in item]
        return tuple(results)


def expand(text: str) -> tuple[str, ...]:
    state: list[str | list[str]] = [""]
    return brace_substitution.substitute(text, ExpandBraces(), state=state)
