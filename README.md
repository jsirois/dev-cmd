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

There are two special argv0's you can use in your commands:
1. "python": This will be mapped to the Python interpreter that is executing `dev-cmd`.
2. A file name ending in ".py": This will be assumed to be a python script, and it will be run using
   the Python interpreter that is executing `dev-cmd`.

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

#### Pass Through Args

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

#### Parameterization

Both command arguments and env values can be parameterized with values from the execution
environment. Parameters are introduced in between brackets with an optional default value:
`{<key>(:<default>)?}`. Parameters can draw from three sources:
1. Environment variables via `{env.<name>}`; e.g.: `{env.HOME}`
2. The current Python interpreter's marker environment via `{markers.<name>}`; e.g.:
   `{markers.python_version}`
3. Factors via `{-<name>}`; e.g.: `{-py:{markers.python_version}}`

In all three cases, the parameter name can itself come from a nested parameterization; e.g.:
`{markers.{-marker:{env.MARKER:python_version}}}` selects the environment marker value for the
environment marker named by the `marker` factor if defined; otherwise the `MARKER` environment
variable if defined and finally falling back to `python_version` if none of these are defined.

The available Python marker environment variables are detailed in [PEP-508](
https://peps.python.org/pep-0508/#environment-markers).

Factors are introduced as suffixes to command names and are inspired by and similar to those found
in [tox](https://tox.wiki/) configuration. If a command is named `test` but the command is invoked
as `test-py3.12`, the `-py3.12` factor will be defined. The value of `3.12` could then be read via
the `{-py}` factor parameter placeholder in the command arguments or env values. The factor name
prefix will be stripped from the factor argument to produce the substituted value. As a consequence,
you want to ensure the factor names you use are non-overlapping or else an error will be raised due
to ambiguity in which factor argument should be applied. An optional leading `:` can proceed the
factor argument value, and it will be stripped. So both `test-py:3.12` and `test-py3.12` pass `3.12`
as the value for the `-py` factor parameter. The colon-prefix helps distinguish factor name from
factor value, paralleling the default value syntax that can be used at factor parameter declaration
sites.

#### Documentation

You can document a command by providing a `description`. If the command has factors, you can
document these using a `factors` sub-table whose keys are the factor names and whose values are
strings that describe the factor.

For example:
```toml
[tool.dev-cmd.commands.type-check.factors]
py = "The Python version to type check in <major>.<minor> form; i.e.: 3.13."

[tool.dev-cmd.commands.type-check]
args = [
   "mypy",
   "--python-version", "{-py:{markers.python_version}}",
   "--cache-dir", ".mypy_cache_{markers.python_version}",
   "setup.py",
   "dev_cmd",
   "tests",
]
```

You can view this documentation by passing `dev-cmd` either `-l` or `--list`. For example:
```console
uv run dev-cmd --list
Commands:
type-check:
    -py: The Python version to type check in <major>.<minor> form; i.e.: 3.13.
         [default: {markers.python_version} (currently 3.12)]
```

If you'd like to hide a command from being listed, define it as a table and include a
`hidden = true` entry.

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

#### Parallelization

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

#### Expansion

The `dev-cmd` runner supports expansion of steps via enumerated placeholders like `{a,b,c}` and
range placeholders like `{0..3}`. Whether supplied as step names via the command line or in task
lists, these placeholders will result in the surrounding step name being expanded into two or more
steps. For example, the following configuration results in a type-checks task that runs `mypy` in
parallel checking against Python 3.8 through 3.13:
```toml
[tool.dev-cmd.commands]
type-check = ["mypy", "--python", "{-py:{markers.python_version}}"]

[tool.dev-cmd.tasks]
type-checks = [["type-check-py3.{8..13}"]]
```

You could also ad-hoc check against just Python 3.8 and 3.9 in parallel via the following, even if
your shell does not do parameter expansion of this sort:
```console
uv run dev-cmd -p 'type-check-py3.{8,9}'
```

#### Documentation

You can document a task by defining it in a table instead of as a list of steps. To do so, supply
the list of steps with the `steps` key and the documentation with the `description` key:
```toml
[tool.dev-cmd.commands]
fmt = ["ruff", "format"]
lint = ["ruff", "check", "--fix"]
type-check = ["mypy", "--python", "{-py:{markers.python_version}}"]

[tool.dev-cmd.commands.test]
args = ["pytest"]
cwd = "tests"
accepts-extra-args = true

[tool.dev-cmd.tasks.checks]
description = "Runs all development checks, including auto-formatting code."
steps = [
    "fmt",
    "lint",
    # Parallelizing the type checks and test is safe (they don't modify files), and it nets a ~3x
    # speedup over running them all serially.
    ["type-check-py3.{8..13}", "test"],
]
```

You can view this documentation by passing `dev-cmd` either `-l` or `--list`. For example:
```console
uv run dev-cmd --list
Commands:
fmt
lint
type-check:
    -py: [default: {markers.python_version} (currently 3.12)]
test (-- extra pytest args ...)

Tasks:
checks (-- extra pytest args ...):
    Runs all development checks, including auto-formatting code.
```

If you'd like to hide a task from being listed, define it as a table and include a `hidden = true`
entry.

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
