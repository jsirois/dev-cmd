# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from enum import Enum
from typing import Tuple, Union

import colors
from typing_extensions import TypeAlias

try:
    import colorama
except ImportError:
    pass
else:
    colorama.just_fix_windows_console()


def _use_color() -> bool:
    # Used in Python 3.13+
    python_colors = os.environ.get("PYTHON_COLORS")
    if python_colors in ("0", "1"):
        return python_colors == "1"

    # A common convention; see: https://no-color.org/
    if "NO_COLOR" in os.environ:
        return False

    # A less common convention; see: https://force-color.org/
    if "FORCE_COLOR" in os.environ:
        return True

    return sys.stderr.isatty() and "dumb" != os.environ.get("TERM")


USE_COLOR = _use_color()


class ColorChoice(Enum):
    ALWAYS = "always"
    AUTO = "auto"
    NEVER = "never"

    def __str__(self) -> str:
        return self.value


def set_color(choice: ColorChoice) -> None:
    if choice is ColorChoice.NEVER:
        os.environ["PYTHON_COLORS"] = "0"
        os.environ["NO_COLOR"] = "1"
        os.environ.pop("FORCE_COLOR", None)
    elif choice is ColorChoice.ALWAYS:
        os.environ["PYTHON_COLORS"] = "1"
        os.environ["FORCE_COLOR"] = "1"
        os.environ.pop("NO_COLOR", None)

    global USE_COLOR
    USE_COLOR = _use_color()


def cyan(text: str) -> str:
    return colors.cyan(text) if USE_COLOR else text


def magenta(text: str) -> str:
    return colors.magenta(text) if USE_COLOR else text


def yellow(text: str) -> str:
    return colors.yellow(text) if USE_COLOR else text


def red(text: str) -> str:
    return colors.red(text) if USE_COLOR else text


def bold(text: str) -> str:
    return colors.bold(text) if USE_COLOR else text


ColorSpec: TypeAlias = Union[str, int, Tuple[int, int, int]]


def color(
    text: str, fg: ColorSpec | None = None, bg: ColorSpec | None = None, style: str | None = None
) -> str:
    return colors.color(text, fg=fg, bg=bg, style=style) if USE_COLOR else text
