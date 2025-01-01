# dev-cmd

[![PyPI Version](https://shields.io/pypi/v/dev-cmd.svg)](https://pypi.org/project/dev-cmd/)
[![License](https://shields.io/pypi/l/dev-cmd.svg)](LICENSE)
[![Supported Pythons](https://shields.io/pypi/pyversions/dev-cmd.svg)](pyproject.toml)
[![CI](https://img.shields.io/github/actions/workflow/status/jsirois/dev-cmd/ci.yml)](https://github.com/jsirois/dev-cmd/actions/workflows/ci.yml)

The `dev-cmd` tool provides a simple way to define commands you use to develop your project with in
`pyproject.toml`.

## Configuration

You define the commands you want `dev-cmd` to run and more under the `[tool.dev-cmd]` table in
`pyproject.toml`.

### Commands

You'll need at least one command defined for `dev-cmd` to be able to do anything useful. At a
minimum a command needs a name and a list of command line arguments that form the command.
For example:

```toml
[tool.dev-cmd.commands]
greet = ["python", "-c", "import os; print(f'Hello from {os.getcwd()!r}.')"]
```

More on execution in various environments [below](#Execution), but you can run the greet command
with, for example `uv run dev-cmd greet`.

You can define as many commands as you want. They will all run from the project root directory (the
directory containing the `pyproject.toml` the commands are defined in) and accept no arguments
besides those defined in the command. You can gain further control over the command by defining it
in a table instead of as a list of command line arguments. For example:

```toml
[tool.dev-cmd.commands.test]
args = ["pytest"]
env = {"PYTHONPATH" = "../test-support"}
cwd = "tests"
accepts-extra-args = true
```

Here, the working directory is set to the `tests/` directory (which must exist) and the `PYTHONPATH`
is set to its sibling `test-support` directory. This allows for importable shared test code to be
placed under the `test-support` directory in a project laid out like so:
```
project-dir/
    pyproject.toml
    tests/
    test-support/
```

The `accepts-extra-args = true` configuration allows for passing extra args to pytest like so:
```console
uv run dev-cmd test -- -vvs
```
All arguments after the `--` are passed to `pytest` by appending them to the `test` command `args`
list. `dev-cmd` ensures at most one command `accepts-extra-args` per invocation so that they can be
unambiguously forwarded to the command that needs them. For example, lets expand the set of commands
we support:
```toml
[tool.dev-cmd.commands]
fmt = ["ruff", "format"]
lint = ["ruff", "check", "--fix"]

[tool.dev-cmd.commands.test]
args = ["pytest"]
env = {"PYTHONPATH" = "../test-support"}
cwd = "tests"
accepts-extra-args = true
```
You can now run the following and the extra args (`-vvs`) will be forwarded to `pytest` but not to
`ruff` in the `fmt` and `lint` commands:
```console
uv run dev-cmd fmt lint test -- -vvs
```
Here we ran multiple commands in sequence passing extra args to test. We could have also run this
as:
```console
uv run dev-cmd test fmt lint -- -vvs
```
The order commands are run in does not affect where extra args are passed.

### Tasks

Tasks are defined in their own table and compose two or more commands to implement some larger task.
Task names share the same namespace as command names and so must be unique from those. Continuing
with the current example:
```toml
[tool.dev-cmd.commands]
fmt = ["ruff", "format"]
lint = ["ruff", "check", "--fix"]

[tool.dev-cmd.commands.test]
args = ["pytest"]
env = {"PYTHONPATH" = "../test-support"}
cwd = "tests"
accepts-extra-args = true

[tool.dev-cmd.tasks]
tidy = ["fmt", "lint"]
```

With that configuration, executing `uv run dev-cmd tidy` will execute the `fmt` command and then
the `lint` command in sequence. Each entry in the list is referred to as a step and is the name of
any command or any task defined earlier in the file. This last restriction naturally avoids cycles.

Steps are run in sequence by default and execution halts at the 1st step to fail by default. See
[Execution](#Execution) for options to control these defaults. To cause two or more steps in a task
to run in parallel, enclose them in a sub-list. Continuing with the example above, but eliding the
command definitions:
```toml
[tool.dev-cmd.tasks]
tidy = ["fmt", "lint"]
unsafe-tidy = [["fmt", "lint"]]
checks = [[["fmt", "lint"], "test"]]
```
When `uv run dev-cmd unsafe-tidy` is run, both `fmt` and `lint` will run in parallel. This is unsafe
since both commands can modify the same files. It's up to you to control for this sort of issue when
deciding which commands to run in parallel.

When `uv run dev-cmd checks` is run, The elements in the 1st nested list are again run in parallel.
This time the 1st element is a list: `["fmt", "lint]`. Each layer of list nesting alternates between
running serially and running in parallel; so `fmt` and `list` will be run serially in that order
while they race `test` as a group in parallel.

### Global Options

You can set a default command or task to run when `dev-cmd` is passed no positional arguments like
so:
```toml
[tool.dev-cmd]
default = "checks"
```
This configuration means the following will run `fmt`, `lint` and `test`:
```console
uv run dev-cmd
```
You can also configure when `dev-cmd` exits when it encounters command failures in a run:
```toml
[tool.dev-cmd]
exit-style = "immediate"
```
This will cause `dev-cmd` to fail fast as soon as the 1st command fails in a run. By default, the
exit style is `"after-step"` which only exits after the step containing a command (if any)
completes. For the `checks` task defined above, this means a failure in `fmt` would not be
propagated until after `lint` completed, finishing the step `fmt` found itself in. The final choice
for `exit-style` is `end` which causes `dev-cmd` to run everything to completion, only listing
errors at the very end.

## Execution

The `dev-cmd` tool supports several command line options to control execution in ad-hoc ways. You
can override the configured `exit-style` with `-k` / `--keep-going` (which is equivalent to
`exit-style = "end"`) or `-X` / `--exit-style`. You can also cause all steps named on the command
line to be run in parallel instead of in order with `-p` / `--parallel`. Finally, you can skip steps
with `-s` / `--skip`. This can be useful when running a task like `checks` defined above that
includes several commands, but one or more you'd like to skip. This would run all checks except
the tests:
```console
uv run dev-cmd checks -s test
```

In order for `dev-cmd` to run most useful commands, dependencies will need to be installed that
bring in those commands, like `ruff` or `pytest`. This is done differently in different tools.
Below are some commonly used tools and the configuration they require along with the command used to
invoke `dev-cmd` using each tool.

### [PDM](https://pdm-project.org/) and [uv](https://docs.astral.sh/uv/)

Add `dev-cmd` as well as any other needed dependencies to the `dev` dependency group:
```toml
[dependency-groups]
dev = ["dev-cmd", "pytest", "ruff"]
```
You can then execute `dev-cmd` with `uv run dev-cmd [args...]`. For `pdm` you'll have to 1st run
`pdm install` to make `dev-cmd`, `pytest` and `ruff` available.

### [Poetry](https://python-poetry.org/)

Add `dev-cmd` as well as any other needed dependencies to the dev dependencies:
```toml
[tool.poetry.dev-dependencies]
dev-cmd = "*"
pytest = "*"
ruff = "*"
```

Run `poetry install` and then you can run `poetry run dev-cmd [args...]`.

### [Hatch](https://hatch.pypa.io/)

Add `dev-cmd` as well as any other needed dependencies to an environment's dependencies. Here we use
the `default` environment for convenience:
```toml
[tool.hatch.envs.default]
dependencies = ["dev-cmd", "pytest", "ruff"]
```

You can then execute `hatch run dev-cmd [args...]`.

## Pre 1.0 Warning

This is a very new tool that can be expected to change rapidly and in breaking ways until the 1.0
release. The current best documentation is the dogfooding this project uses for its own development
described below. You can look at the `[tool.dev-cmd]` configuration in [`pyproject.toml`](
pyproject.toml) to get a sense of how definition of commands, tasks and defaults works.

## Development

Development uses [`uv`](https://docs.astral.sh/uv/getting-started/installation/). Install as you
best see fit.

With `uv` installed, running `uv run dev-cmd` is enough to get the tools `dev-cmd` uses installed
and  run against the codebase. This includes formatting code, linting code, performing type checks
and then running tests.
