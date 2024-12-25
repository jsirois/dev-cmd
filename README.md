# dev-cmd

[![PyPI Version](https://shields.io/pypi/v/dev-cmd.svg)](https://pypi.org/project/dev-cmd/)
[![License](https://shields.io/pypi/l/dev-cmd.svg)](LICENSE)
[![Supported Pythons](https://shields.io/pypi/pyversions/dev-cmd.svg)](pyproject.toml)
[![CI](https://img.shields.io/github/actions/workflow/status/jsirois/dev-cmd/ci.yml)](https://github.com/jsirois/dev-cmd/actions/workflows/ci.yml)

The `dev-cmd` tool provides a simple way to define commands in `pyproject.toml` to develop your
project with and then execute them.

This is a very new tool that can be expected to change rapidly and in breaking ways until the 1.0
release. The current best documentation is the dogfooding this project uses for its own development
described below. You can look at the `[tool.dev-cmd]` configuration in [`pyproject.toml`](
pyproject.toml) to get a sense of how definition of commands, tasks and defaults works.

## Development

Development uses [`uv`](https://docs.astral.sh/uv/getting-started/installation/). Install as you
best see fit.

With `uv` installed, running `uv run dev-cmd` is enough to get the tools run-dev uses installed and
run against the codebase. This includes formatting code, linting code, performing type checks and
then running tests.
