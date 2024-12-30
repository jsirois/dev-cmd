# Copyright 2024 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from dataclasses import dataclass
from typing import Any, TextIO

import aioconsole


@dataclass(frozen=True)
class Console:
    quiet: bool = False

    def print(
        self,
        *values: Any,
        sep: str = " ",
        end: str = os.linesep,
        flush: bool = True,
        file: TextIO = sys.stdout,
        force: bool = False,
    ) -> None:
        if self.quiet and not force:
            return
        print(*values, sep=sep, end=end, flush=flush, file=file)

    async def aprint(
        self,
        *values: Any,
        sep: str = " ",
        end: str = os.linesep,
        flush: bool = True,
        use_stderr: bool = False,
        force: bool = False,
    ) -> None:
        if self.quiet and not force:
            return
        await aioconsole.aprint(*values, sep=sep, end=end, flush=flush, use_stderr=use_stderr)
