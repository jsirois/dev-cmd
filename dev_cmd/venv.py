# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from os import fspath
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from textwrap import dedent
from typing import IO, Any, Dict, Iterator, cast

from dev_cmd import color
from dev_cmd.errors import DevCmdError
from dev_cmd.model import Command, Python, PythonConfig, Venv, VenvConfig

AVAILABLE = False

if shutil.which("pex3") and importlib.util.find_spec("filelock"):
    from filelock import FileLock

    AVAILABLE = True


def _fingerprint(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


@contextmanager
def _named_temporary_file(
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
        with _named_temporary_file(tmp_dir=fspath(cache_dir), prefix=".gitignore.") as gitignore_fp:
            gitignore_fp.write(b"*\n")
            gitignore_fp.close()
            os.rename(gitignore_fp.name, gitignore)
    return cache_dir


@dataclass(frozen=True)
class _VenvLayout:
    python: str
    site_packages_dir: str


def _create_venv(python: str, venv_dir: str) -> _VenvLayout:
    result = subprocess.run(
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
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DevCmdError(result.stderr)

    result = subprocess.run(
        args=["pex3", "venv", "inspect", venv_dir],
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    venv_data = json.loads(result.stdout)
    python_exe = venv_data["interpreter"]["binary"]
    site_packages_dir = venv_data["site_packages"]

    return _VenvLayout(python=python_exe, site_packages_dir=site_packages_dir)


def marker_environment(python: Python, quiet: bool = False) -> dict[str, str]:
    resolved_python = python.resolve()
    fingerprint = _fingerprint(resolved_python.encode())
    markers_file = _ensure_cache_dir() / "interpreters" / f"markers.{fingerprint}.json"
    if not os.path.exists(markers_file):
        with FileLock(f"{markers_file}.lck"), TemporaryDirectory(
            dir=markers_file.parent, prefix="packaging-venv."
        ) as td:
            print(
                f"{color.yellow(f'Calculating environment markers for --python {python}')}...",
                file=sys.stderr,
            )
            venv_layout = _create_venv(resolved_python, fspath(td))
            subprocess.run(
                args=[venv_layout.python, "-m", "pip", "install", "packaging"],
                stdout=subprocess.DEVNULL if quiet else sys.stderr.fileno(),
                stderr=subprocess.DEVNULL if quiet else None,
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


def _fingerprint_python_config(venv_config: VenvConfig, python_config: PythonConfig) -> str:
    input_files = {}
    input_paths: dict[str, str] = {}
    for path in python_config.cache_key_inputs.paths:
        input_path = Path(path)
        if input_path.is_file():
            input_files[input_path] = ""
        else:
            assert input_path.is_dir(), (
                f"Expected parsing code to verify {input_path} was an existing file or directory."
            )
            for root, dirs, files in os.walk(input_path):
                root_dir = Path(root)
                input_paths.update(((root_dir / d).as_posix(), "") for d in dirs)
                input_files.update((root_dir / f, "") for f in files)

    if input_files:
        input_paths.update(
            zip(
                map(lambda f: f.as_posix(), input_files),
                # TODO(John Sirois): Investigate ThreadPool().map(..., chunk_size=?) ~# of files
                #  threshold where performance improves A quick experiment on SSD showed a thread
                #  pool to be slower for <100 files.
                map(lambda f: _fingerprint(f.read_bytes()), input_files),
            )
        )

    def extract_command_fingerprint_data(command: Command | None) -> dict[str, Any] | None:
        if command is None:
            return None
        return {
            "extra-env": dict(command.extra_env),
            "args": command.args,
            "cwd": str(command.cwd) if command.cwd else None,
        }

    return _fingerprint(
        json.dumps(
            {
                "python": venv_config.python.resolve(),
                "dependency-group": venv_config.dependency_group,
                "cache-keys": {
                    "pyproject-data": python_config.cache_key_inputs.pyproject_data,
                    "paths": input_paths,
                    "env": python_config.cache_key_inputs.envs,
                },
                "pip-requirement": python_config.pip_requirement,
                "3rdparty-export-command": extract_command_fingerprint_data(
                    python_config.thirdparty_export_command
                ),
                "3rdparty-pip-install-opts": python_config.thirdparty_pip_install_opts,
                "extra-requirements": (
                    _fingerprint(python_config.extra_requirements.encode())
                    if isinstance(python_config.extra_requirements, str)
                    else python_config.extra_requirements
                ),
                "extra-requirements-pip-install-opts": python_config.extra_requirements_pip_install_opts,
                "finalize-command": extract_command_fingerprint_data(
                    python_config.finalize_command
                ),
            },
            sort_keys=True,
        ).encode()
    )


def _chmod_plus_x(path: Path) -> None:
    path_mode = path.stat().st_mode
    path_mode &= 0o777
    if path_mode & stat.S_IRUSR:
        path_mode |= stat.S_IXUSR
    if path_mode & stat.S_IRGRP:
        path_mode |= stat.S_IXGRP
    if path_mode & stat.S_IROTH:
        path_mode |= stat.S_IXOTH
    path.chmod(path_mode)


def ensure(
    venv_config: VenvConfig,
    python_config: PythonConfig,
    rebuild_if_needed: bool = True,
    quiet: bool = False,
) -> Venv:
    python = venv_config.python

    env_description = f"--python {python}"
    if venv_config.dependency_group:
        env_description = f"{env_description} dependency-group={venv_config.dependency_group}"

    fingerprint = _fingerprint_python_config(venv_config=venv_config, python_config=python_config)
    venv_dir = _ensure_cache_dir() / "venvs" / fingerprint
    layout_file = venv_dir / ".dev-cmd-venv-layout.json"
    if not os.path.exists(venv_dir):
        with FileLock(f"{venv_dir}.lck"):
            if not os.path.exists(venv_dir):
                print(
                    f"{color.yellow(f'Setting up venv for {env_description}')}...", file=sys.stderr
                )
                work_dir = Path(f"{venv_dir}.work")
                venv_layout = _create_venv(python.resolve(), venv_dir=fspath(work_dir))

                thirdparty_export_command_args: list[str] = []
                for arg in python_config.thirdparty_export_command.args:
                    match = re.match(r"^\{dependency-group(?::(?P<default>.*))?}$", arg)
                    if not match:
                        thirdparty_export_command_args.append(arg)
                    elif venv_config.dependency_group:
                        thirdparty_export_command_args.append(venv_config.dependency_group)
                    else:
                        default_dependency_group = match.group("default")
                        if not default_dependency_group:
                            raise DevCmdError(
                                f"A [[tool.dev-cmd.python]] configuration uses {arg} and no "
                                f"default dependency-group was set."
                            )
                        thirdparty_export_command_args.append(default_dependency_group)

                with _named_temporary_file(
                    tmp_dir=fspath(work_dir), prefix="3rdparty-reqs."
                ) as reqs_fp:
                    reqs_fp.close()

                    requirements_export_command_args = [
                        (reqs_fp.name if arg == "{requirements.txt}" else arg)
                        for arg in thirdparty_export_command_args
                    ]
                    env = os.environ.copy()
                    env.update(python_config.thirdparty_export_command.extra_env)
                    subprocess.run(
                        args=requirements_export_command_args,
                        cwd=python_config.thirdparty_export_command.cwd,
                        env=env,
                        check=True,
                    )

                    pip_stdout = subprocess.DEVNULL if quiet else sys.stderr.fileno()
                    pip_stderr = subprocess.DEVNULL if quiet else None
                    subprocess.run(
                        args=[
                            venv_layout.python,
                            "-m",
                            "pip",
                            "install",
                            "-U",
                            python_config.pip_requirement,
                        ],
                        stdout=pip_stdout,
                        stderr=pip_stderr,
                        check=True,
                    )
                    subprocess.run(
                        args=[venv_layout.python, "-m", "pip", "install"]
                        + list(python_config.thirdparty_pip_install_opts)
                        + ["-r", reqs_fp.name],
                        stdout=pip_stdout,
                        stderr=pip_stderr,
                        check=True,
                    )

                if python_config.extra_requirements:

                    @contextmanager
                    def _extra_requirements_args() -> Iterator[list[str]]:
                        if isinstance(python_config.extra_requirements, str):
                            with _named_temporary_file(
                                tmp_dir=fspath(work_dir), prefix="extra-reqs."
                            ) as fp:
                                fp.write(python_config.extra_requirements.encode())
                                fp.close()
                                yield ["-r", fp.name]
                        else:
                            yield list(python_config.extra_requirements)

                    with _extra_requirements_args() as extra_requirements_args:
                        subprocess.run(
                            args=[venv_layout.python, "-m", "pip", "install"]
                            + list(python_config.extra_requirements_pip_install_opts)
                            + extra_requirements_args,
                            stdout=pip_stdout,
                            stderr=pip_stderr,
                            check=True,
                        )

                if python_config.finalize_command:
                    finalize_command_args: list[str] = []
                    for arg in python_config.finalize_command.args:
                        if arg == "{venv-python}":
                            finalize_command_args.append(venv_layout.python)
                        elif arg == "{venv-site-packages}":
                            finalize_command_args.append(venv_layout.site_packages_dir)
                        else:
                            finalize_command_args.append(arg)
                    env = os.environ.copy()
                    env.update(python_config.finalize_command.extra_env)
                    subprocess.run(
                        args=finalize_command_args,
                        cwd=python_config.finalize_command.cwd,
                        env=env,
                        check=True,
                    )

                venv_bin_dir = Path(os.path.dirname(venv_layout.python))
                work_dir_path = str(work_dir)
                work_dir_path_bytes = work_dir_path.encode()
                venv_dir_path = str(venv_dir)
                venv_dir_path_bytes = venv_dir_path.encode()
                for candidate_console_script in venv_bin_dir.iterdir():
                    if (
                        not candidate_console_script.is_file()
                        or candidate_console_script.is_symlink()
                    ):
                        continue
                    with candidate_console_script.open("rb") as candidate_fp:
                        if candidate_fp.read(2) != b"#!":
                            continue
                        shebang = candidate_fp.readline()
                        if not shebang.startswith(work_dir_path_bytes):
                            continue
                        rewrite_target = candidate_console_script.with_suffix(".rewrite")
                        with rewrite_target.open("wb") as rewrite_fp:
                            rewrite_fp.write(b"#!")
                            rewrite_fp.write(
                                shebang.replace(work_dir_path_bytes, venv_dir_path_bytes)
                            )
                            shutil.copyfileobj(candidate_fp, rewrite_fp)
                    rewrite_target.rename(candidate_console_script)
                    _chmod_plus_x(candidate_console_script)

                with (work_dir / layout_file.name).open("w") as out_fp:
                    json.dump(
                        {
                            "python": venv_layout.python.replace(work_dir_path, venv_dir_path),
                            "marker-environment": marker_environment(python, quiet=quiet),
                        },
                        out_fp,
                    )
                work_dir.rename(venv_dir)

    with layout_file.open() as in_fp:
        data = json.load(in_fp)

    print(
        color.color(f"Using venv at {venv_dir} for {env_description}.", fg="gray"), file=sys.stderr
    )
    try:
        return Venv(
            dir=venv_dir.as_posix(),
            python=data["python"],
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
        return ensure(venv_config=venv_config, python_config=python_config, rebuild_if_needed=False)
