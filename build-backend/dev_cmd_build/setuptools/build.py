# Copyright 2025 John Sirois.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import base64
import csv
import hashlib
import os.path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import setuptools.build_meta

# We re-export all the setuptools PEP-517 build backend hooks here for the build frontend to call.
from setuptools.build_meta import *  # NOQA

from dev_cmd import __version__


def _add_lock(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    pylock_toml = dest_dir / "pylock.toml"
    subprocess.run(
        args=[
            "uv",
            "export",
            "--format",
            "pylock.toml",
            "--no-header",
            "--no-emit-project",
            "--all-extras",
            "--no-dev",
            "-q",
            "-o",
            pylock_toml,
        ],
        check=True,
    )
    return pylock_toml


@contextmanager
def _build_dir(name: str) -> Iterator[Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="dev-cmd.", suffix=f".{name}-build-dir"))
    try:
        yield tmpdir
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def build_sdist(sdist_directory: str, config_settings: dict[str, Any] | None = None) -> str:
    sdist_name = setuptools.build_meta.build_sdist(sdist_directory, config_settings)

    sdist_path = Path(sdist_directory) / sdist_name
    tarball_root_dir_name = f"dev_cmd-{__version__}"

    with _build_dir("sdist") as tmpdir:
        tarball_root_dir = tmpdir / tarball_root_dir_name
        with tarfile.open(sdist_path) as tf:
            tf.extractall(tmpdir)
        _add_lock(tarball_root_dir)
        with tarfile.open(sdist_path, "w:gz") as tf:
            tf.add(tarball_root_dir, tarball_root_dir_name)
        return sdist_name


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    wheel_name = setuptools.build_meta.build_wheel(
        wheel_directory, config_settings, metadata_directory
    )

    wheel_path = Path(wheel_directory) / wheel_name
    dist_info_dir_name = f"dev_cmd-{__version__}.dist-info"

    with _build_dir("wheel") as tmpdir:
        with zipfile.ZipFile(wheel_path) as zf:
            original_contents = zf.namelist()
            zf.extractall(tmpdir)

        pylock_toml = _add_lock(tmpdir / dist_info_dir_name / "pylock")
        pylock_toml_data = pylock_toml.read_bytes()
        fingerprint = base64.urlsafe_b64encode(hashlib.sha256(pylock_toml_data).digest()).rstrip(
            b"="
        )
        pylock_toml_dest: str | None = str(pylock_toml.relative_to(tmpdir).as_posix())
        with (tmpdir / dist_info_dir_name / "RECORD").open(mode="a") as fp:
            csv.writer(fp).writerow(
                (pylock_toml_dest, f"sha256={fingerprint.decode('ascii')}", len(pylock_toml_data))
            )

        with zipfile.ZipFile(wheel_path, "w") as zf:
            for path in original_contents:
                if (
                    pylock_toml_dest
                    and dist_info_dir_name == os.path.commonpath((path, dist_info_dir_name))
                    and pylock_toml_dest < path
                ):
                    zf.write(pylock_toml, pylock_toml_dest)
                    pylock_toml_dest = None
                zf.write(tmpdir / path, path)
        return wheel_name
