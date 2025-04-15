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

There are two special argv0's you can use in your command arguments list:
1. "python": This will be mapped to the Python interpreter specified for the command (described
   below) or else the Python interpreter executing `dev-cmd`.
2. A file name ending in ".py": This will be assumed to be a python script, and executed with a
   Python interpreter as described in 1 above.

You can define as many commands as you want. They will all run from the project root directory (the
directory containing the `pyproject.toml` the commands are defined in) and accept no arguments
besides those defined in the command. You can gain further control over the command by defining it
in a table instead of as a list of command line arguments. For example:

```toml
[tool.dev-cmd.commands.test]
python = "python3.9"
args = ["pytest"]
env = {"PYTHONPATH" = "../test-support"}
cwd = "tests"
accepts-extra-args = true
```

Here, the test command will be run with `python3.9` regardless of the interpreter running `dev-cmd`.
This relies on configuration for custom interpreters described [below](#Custom-Pythons).

Also, the working directory is set to the `tests/` directory (which must exist) and the `PYTHONPATH`
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

#### Platform Selection

You can condition command availability based on the current platform characteristics as determined
by a `when` [environment marker][environment marker]. For example, to define a Windows-only command:
```toml
[tool.dev-cmd.commands.query-registry]
when = "sys_platform == 'win32'"
args = ["scripts/query-windows-registry.py"]
```

You can also use `when` conditions to select from amongst a mutually exclusive set of commands, each
tailored to a specific platform. For this you can specify a common `name` for the commands forming
the mutually exclusive group. For example, to define a "query" command that has a different
implementation for Windows than for other systems:
```toml
[tool.dev-cmd.commands.query-posix]
when = "sys_platform != 'win32'"
name = "query"
args = ["scripts/query-posix.py"]

[tool.dev-cmd.commands.query-windows]
when = "sys_platform == 'win32'"
name = "query"
args = ["scripts/query-windows-registry.py"]
```

[environment marker]: https://packaging.python.org/en/latest/specifications/dependency-specifiers/#environment-markers

#### Parameterization

A command's python, arguments and env values can be parameterized with values from the execution
environment. Parameters are introduced in between brackets with an optional default value:
`{<key>(:<default>)?}`. Parameters can draw from four sources:
1. Environment variables via `{env.<name>}`; e.g.: `{env.HOME}`
2. The current Python interpreter's marker environment via `{markers.<name>}`; e.g.:
   `{markers.python_version}`
3. Factors via `{-<name>}`; e.g.: `{-py:{markers.python_version}}`
4. A hash seed via `{--hashseed}`. The value comes from `dev-cmd --hashseed` if passed; otherwise a
   random hash seed suitable for use with `PYTHONHASHSEED` is generated.

In the first three cases, the parameter name can itself come from a nested parameterization; e.g.:
`{markers.{-marker:{env.MARKER:python_version}}}` selects the environment marker value for the
environment marker named by the `marker` factor if defined; otherwise the `MARKER` environment
variable if defined and finally falling back to `python_version` if none of these are defined.

The available Python marker environment variables are detailed in [PEP-508](
https://peps.python.org/pep-0508/#environment-markers).

Command arguments can be elided from the list when their value is parameterized and evaluates to
empty by wrapping the argument in a single-item `{discard_empty = "..."}` table. For example,
debug flags could be passed to pytest via the `DEBUG` env var, but only when present, with:
```toml
[tool.dev-cmd.commands]
pytest = ["python", "-m", "pytest", {discard_empty = "{env.DEBUG:"}]
```

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
sites. If your factor value contains a `-`, just escape it with a `-`; i.e.: `--` will map to a
single `-` in a factor value instead of indicating a new factor starts there.

There are two special forms of factors to be aware of: flag factors for passing one value or another
conditionally and the `py` factor when used as the value of a command python.

An example of a flag factor is `{-color?--color=always:--color=auto}`. Here the factor name is
`color` and, when present as a command suffix, it evaluates to `--color-always`. When the factor is
absent from the command name, it evaluates to `--color=auto`. Re-visiting the `discard_empty`
example above, you might more usefully parameterize pytest debugging with:
```toml
[tool.dev-cmd.commands]
pytest = ["python", "-m", "pytest", {discard_empty = "{-debug?--pdb:"}]
```

Instead of having to say `DEBUG=--pdb uv run dev-cmd pytest` you can say
`uv run dev-cmd pytest-debug`. This has the advantage of being discoverable via `--list` and sealing
in the correct debugger flag for pytest.

The other special form if the factor named `py` when used as the value for a command python. For
example:
```toml
[tool.dev-cmd.commands.query]
python = "{-py:}"
args = ["scripts/query.py"]
```

Here, executing `uv run dev-cmd query-python3.8` will run the query script with Python 3.8. This
is just standard factor substitution at work. However, you can also say: `query-py3.8` or even
`query-py38` with the same result. Namely, for a command python, the `py` factor has special value
handling that will add the `python` prefix for you if you just supply the version number or even
just the version digits. PyPy is also supported. Instead of using the awkward `query-py:pypy` or
`query-pypypy`, you can use `query-pypy`. The `py` factor value gets expanded to `pypy`. This also
works with the version number handling; so you can say `query-pypy310` to pass `pypy3.10` as the
query script Python to use.

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

#### Platform Selection

You can define platform-specific tasks using `when` and `name` entries in a task's table similar to
the facility described for platform-specific commands above.

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

### Custom Pythons

If you'd like to use a modern development tool, but you need to run commands against older Pythons
than it supports, you may be able to leverage the `--py` / `--python` option as a workaround. There
are a few preconditions your setup needs to satisfy to be able to use this approach:
1. Your development tool needs to support locking for older pythons if it uses lock files.
2. Your development tool needs to be able to export your project development requirements in Pip
   requirements.txt format.

If your development tool meets these requirements (for example, `uv` does), then in order to have
access to the `--python` option you need to install `dev-cmd` with the `old-pythons` extra;
e.g.: a requirement string like `"dev-cmd[old-pythons]"`.

With that done, a minimal configuration looks like so:
```toml
[[tool.dev-cmd.python]]
3rdparty-export-command = ["uv", "export", "-q", "--no-emit-project", "-o", "{requirements.txt}"]
```

Here your export command just needs to be able to output a Pip requirements.txt compatible
requirements file to build the venv with. The `{requirements.txt}` placeholder should be inserted in
the command line wherever its output path argument lives.

By default, `dev-cmd` also installs your project in each custom venv in editable mode as an extra
requirement. You may wish to adjust which extra requirements are installed, in which case you use
the `extra-requirements` key:
```toml
[[tool.dev-cmd.python]]
3rdparty-export-command = [
   "uv", "export", "-q",
   "--no-emit-project",
   "--no-emit-package", "subproject",
   "-o", "{requirements.txt}"
]
extra-requirements = [
   "-e", ".",
   "subproject @ ./subproject"
]
```

Here we exclude the main project and a local subproject from the requirements export since `uv`
exports hashes for these which Pip does not support for directories. To work around, we just list
these two local projects in `extra-requirements` and they get installed as-is without a hash check
after the exported requirements are installed. You can alternatively supply `extra-requirements` as
a single string, in which case the string will be written out to a file and passed to `pip install`
as a `-r` / `--requirement` file.

You can also supply a `finalize-command` as a list of command line argument strings for the venv.
This command will run last after the 3rdparty requirements and extra requirements are installed and
can use `{venv-python}` and `{venv-site-packages}` placeholders to receive these paths for
manipulating the venv.

You may find the need to vary venv setup per Python `--version`. This is supported by specifying
multiple `[[tool.dev-cmd.python]]` entries. For example:
```toml
[[tool.dev-cmd.python]]
when = "python_version >= '3.7'"
3rdparty-export-command = ["uv", "export", "-q", "--no-emit-project", "-o", "{requirements.txt}"]

[[tool.dev-cmd.python]]
when = "python_version < '3.7'"

pip-requirement = "pip<10"
extra-requirements = ["."]
extra-requirements-pip-install-opts = ["--no-use-pep517"]
```

You must ensure just one `[[tool.dev-cmd.python]]` entry is selected per `--python` via a `when`
environment marker. You can then customize the version of Pip selected for the venv via
`pip-requirement`, the extra `extra-requirements` to install and any custom `pip install` options
you need for either the 3rdparty requirements install via `3rdparty-pip-install-opts` or the extra
requirements install via `extra-requirements-pip-install-opts`.

Note that when defining multiple `[[tool.dev-cmd.python]]` entries, the 1st is special in setting
defaults all subsequent `[[tool.dev-cmd.python]]` entries inherit for keys left unspecified. In the
example above, the second entry for Python 3.6 and older could add a `3rdparty-export-command` if
it needed different export behavior for those older versions.

Venvs are created under a `.dev-cmd` directory and are cached based on the values of the
"build-system", "project" and "project.optional-dependencies" in `pyproject.toml` by default. To
change this default, you can specify a custom `pyproject-cache-keys`. You can also mix the full
contents of any other files, directories or environment variables into the venv cache key using
`extra-cache-keys`. For files or directories, add a string entry denoting their path or else an
entry like `{path = "the/path"}`. For environment variables, add an entry like
`{env = "THE_ENV_VAR"}`. Here, combining both of these options, we turn off pyproject.toml inputs to
the venv cache key and just rely on the contents of `uv.lock`, which is what the export command is
powered by:
```toml
[tool.dev-cmd.python.requirements]
3rdparty-export-command = ["uv", "export", "-q", "--no-emit-project", "-o", "{requirements.txt}"]
pyproject-cache-keys = []
extra-cache-keys = ["uv.lock"]
```

If you need to vary the venv contents based on the command being run you can specify which
dependency-group the command needs and then have your export command respect this value. For
example:
```toml
[dependency-groups]
dev = [
   "dev-cmd[old-pythons]",
   "mypy",
   "ruff",
   {include = "test"}
]
test = ["pytest"]

[tool.dev-cmd.commands]
fmt = ["ruff", "format"]
lint = ["ruff", "check", "--fix"]
type-check = ["mypy", "--python", "{-py:{markers.python_version}}"]

[tool.dev-cmd.commands.test]
args = ["pytest"]
cwd = "tests"
accepts-extra-args = true
dependency-group = "test"

[tool.dev-cmd.python.requirements]
3rdparty-export-command = [
   "uv", "export", "-q",
   "--no-emit-project",
   "--only-group", "{dependency-group:dev}",
   "-o", "{requirements.txt}"
]
pyproject-cache-keys = []
extra-cache-keys = ["uv.lock"]
```

Here, the export command uses the special `{dependency-group:default}` placeholder to ensure
`uv run dev-cmd --py 38 fmt lint type-check test` creates a Python 3.8 venv populated by the "test"
dependency group to run pytest in and a default Python 3.8 venv populated with everything in the
"dev" dependency group to run everything else in.

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
