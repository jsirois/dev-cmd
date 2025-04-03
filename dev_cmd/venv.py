# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Iterator, MutableMapping

from dev_cmd import color
from dev_cmd.model import PythonConfig

AVAILABLE = False

if shutil.which("pex3") and importlib.util.find_spec("filelock"):
    from filelock import FileLock

    AVAILABLE = True


@dataclass(frozen=True)
class Venv:
    dir: str
    python: str
    bin_path: str

    def update_path(self, env: MutableMapping[str, str]) -> None:
        path = env.pop("PATH", None)
        env["PATH"] = (self.bin_path + os.pathsep + path) if path else self.bin_path


def _fingerprint(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode()


@contextmanager
def named_temporary_file(prefix: str | None = None) -> Iterator[IO[bytes]]:
    # Work around Windows issue with auto-delete: https://bugs.python.org/issue14243
    fp = NamedTemporaryFile(prefix=prefix, delete=False)
    try:
        with fp:
            yield fp
    finally:
        os.remove(fp.name)


def ensure(config: PythonConfig, python: str) -> Venv:
    fingerprint = _fingerprint(
        json.dumps(
            {
                "python": python,
                "input-files": {
                    input_file: _fingerprint(Path(input_file).read_bytes())
                    for input_file in config.input_files
                },
            }
        ).encode()
    )
    venv_dir = (
        Path(os.path.abspath(os.environ.get("DEV_CMD_WORKSPACE_CACHE_DIR", ".dev-cmd")))
        / "venvs"
        / fingerprint
    )
    layout_file = venv_dir / ".dev-cmd-venv-layout.json"
    if not os.path.exists(venv_dir):
        with FileLock(f"{venv_dir}.lck"):
            if not os.path.exists(venv_dir):
                print(
                    f"{color.yellow(f'Setting up venv for --python {python}')}...", file=sys.stderr
                )
                work_dir = Path(f"{venv_dir}.work")
                with named_temporary_file(prefix="dev-cmd-venv.") as reqs_fp:
                    reqs_fp.close()
                    requirements_export_command = [
                        (reqs_fp.name if arg == "{requirements.txt}" else arg)
                        for arg in config.requirements_export_command
                    ]
                    subprocess.run(
                        args=requirements_export_command,
                        check=True,
                    )
                    subprocess.run(
                        args=[
                            "pex3",
                            "venv",
                            "create",
                            "--force",
                            "--python",
                            python,
                            "--pip",
                            "--dest-dir",
                            work_dir,
                        ],
                        check=True,
                    )

                    result = subprocess.run(
                        args=["pex3", "venv", "inspect", work_dir],
                        text=True,
                        stdout=subprocess.PIPE,
                        check=True,
                    )
                    venv_data = json.loads(result.stdout)
                    python_exe = venv_data["interpreter"]["binary"]
                    script_dir = venv_data["script_dir"]

                    subprocess.run(
                        args=[python_exe, "-m", "pip", "install", "-U", "pip"],
                        stdout=sys.stderr.fileno(),
                        check=True,
                    )
                    subprocess.run(
                        args=[python_exe, "-m", "pip", "install", "-r", reqs_fp.name],
                        stdout=sys.stderr.fileno(),
                        check=True,
                    )
                    subprocess.run(
                        args=[python_exe, "-m", "pip", "install"] + list(config.extra_requirements),
                        stdout=sys.stderr.fileno(),
                        check=True,
                    )

                with (work_dir / layout_file.name).open("w") as out_fp:
                    json.dump(
                        {
                            "python": python_exe.replace(str(work_dir), str(venv_dir)),
                            "bin-path": script_dir.replace(str(work_dir), str(venv_dir)),
                        },
                        out_fp,
                    )
                work_dir.rename(venv_dir)

    with layout_file.open() as in_fp:
        data = json.load(in_fp)

    return Venv(dir=venv_dir.as_posix(), python=data["python"], bin_path=data["bin-path"])
