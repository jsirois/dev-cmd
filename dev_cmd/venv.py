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
from os import fspath
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from textwrap import dedent
from typing import IO, Dict, Iterator, cast

from dev_cmd import color
from dev_cmd.model import PythonConfig, Venv

AVAILABLE = False

if shutil.which("pex3") and importlib.util.find_spec("filelock"):
    from filelock import FileLock

    AVAILABLE = True


def _fingerprint(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode()


@contextmanager
def named_temporary_file(
    tmp_dir: str | None = None, prefix: str | None = None
) -> Iterator[IO[bytes]]:
    # Work around Windows issue with auto-delete: https://bugs.python.org/issue14243
    fp = NamedTemporaryFile(dir=tmp_dir, prefix=prefix, delete=False)
    try:
        with fp:
            yield fp
    finally:
        try:
            os.remove(fp.name)
        except FileNotFoundError:
            pass


def _ensure_cache_dir() -> Path:
    cache_dir = Path(os.path.abspath(os.environ.get("DEV_CMD_WORKSPACE_CACHE_DIR", ".dev-cmd")))
    gitignore = cache_dir / ".gitignore"
    if not gitignore.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        with named_temporary_file(tmp_dir=fspath(cache_dir), prefix=".gitignore.") as gitignore_fp:
            gitignore_fp.write(b"*\n")
            gitignore_fp.close()
            os.rename(gitignore_fp.name, gitignore)
    return cache_dir


@dataclass(frozen=True)
class VenvLayout:
    python: str
    bin_path: str


def _create_venv(python: str, venv_dir: str) -> VenvLayout:
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
            venv_dir,
        ],
        check=True,
    )

    result = subprocess.run(
        args=["pex3", "venv", "inspect", venv_dir],
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    venv_data = json.loads(result.stdout)
    python_exe = venv_data["interpreter"]["binary"]
    script_dir = venv_data["script_dir"]

    return VenvLayout(python=python_exe, bin_path=script_dir)


def marker_environment(python: str) -> dict[str, str]:
    fingerprint = _fingerprint(python.encode())
    markers_file = _ensure_cache_dir() / "interpreters" / f"markers.{fingerprint}.json"
    if not os.path.exists(markers_file):
        with FileLock(f"{markers_file}.lck"), TemporaryDirectory(
            dir=markers_file.parent, prefix="packaging-venv."
        ) as td:
            print(
                f"{color.yellow(f'Calculating environment markers for --python {python}')}...",
                file=sys.stderr,
            )
            venv_layout = _create_venv(python, fspath(td))
            subprocess.run(
                args=[venv_layout.python, "-m", "pip", "install", "packaging"],
                stdout=sys.stderr.fileno(),
                check=True,
            )
            temp_markers_file = Path(td) / markers_file.name
            temp_markers_file.write_bytes(
                subprocess.run(
                    args=[
                        venv_layout.python,
                        "-c",
                        dedent(
                            """\
                            import json
                            import sys

                            from packaging import markers

                            json.dump(markers.default_environment(), sys.stdout)
                            """
                        ),
                    ],
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout
            )
            temp_markers_file.rename(markers_file)
    return cast(Dict[str, str], json.loads(markers_file.read_bytes()))


def ensure(config: PythonConfig, python: str, rebuild_if_needed: bool = True) -> Venv:
    fingerprint = _fingerprint(
        json.dumps(
            {
                "python": python,
                "input-data": _fingerprint(config.input_data),
                "input-files": {
                    input_file: _fingerprint(Path(input_file).read_bytes())
                    for input_file in config.input_files
                },
            },
            sort_keys=True,
        ).encode()
    )
    venv_dir = _ensure_cache_dir() / "venvs" / fingerprint
    layout_file = venv_dir / ".dev-cmd-venv-layout.json"
    if not os.path.exists(venv_dir):
        with FileLock(f"{venv_dir}.lck"):
            if not os.path.exists(venv_dir):
                print(
                    f"{color.yellow(f'Setting up venv for --python {python}')}...", file=sys.stderr
                )
                work_dir = Path(f"{venv_dir}.work")
                venv_layout = _create_venv(python, venv_dir=fspath(work_dir))
                with named_temporary_file(prefix="dev-cmd-venv.") as reqs_fp:
                    reqs_fp.close()
                    requirements_export_command = [
                        (reqs_fp.name if arg == "{requirements.txt}" else arg)
                        for arg in config.requirements_export_command
                    ]
                    subprocess.run(args=requirements_export_command, check=True)
                    subprocess.run(
                        args=[
                            venv_layout.python,
                            "-m",
                            "pip",
                            "install",
                            "-U",
                            config.extra_requirements.pip_req,
                        ],
                        stdout=sys.stderr.fileno(),
                        check=True,
                    )
                    subprocess.run(
                        args=[venv_layout.python, "-m", "pip", "install", "-r", reqs_fp.name],
                        stdout=sys.stderr.fileno(),
                        check=True,
                    )

                subprocess.run(
                    args=[venv_layout.python, "-m", "pip", "install"]
                    + list(config.extra_requirements.install_opts)
                    + list(config.extra_requirements.reqs),
                    stdout=sys.stderr.fileno(),
                    check=True,
                )

                with (work_dir / layout_file.name).open("w") as out_fp:
                    json.dump(
                        {
                            "python": venv_layout.python.replace(str(work_dir), str(venv_dir)),
                            "bin-path": venv_layout.bin_path.replace(str(work_dir), str(venv_dir)),
                            "marker-environment": marker_environment(python),
                        },
                        out_fp,
                    )
                work_dir.rename(venv_dir)

    with layout_file.open() as in_fp:
        data = json.load(in_fp)

    try:
        return Venv(
            dir=venv_dir.as_posix(),
            python=data["python"],
            bin_path=data["bin-path"],
            marker_environment=data["marker-environment"],
        )
    except KeyError:
        if not rebuild_if_needed:
            raise
        print(
            color.yellow(f"Venv for --python {python} at {venv_dir} is out of date, rebuilding."),
            file=sys.stderr,
        )
        shutil.rmtree(venv_dir)
        return ensure(config, python, rebuild_if_needed=False)
