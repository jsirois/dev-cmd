# Release Notes

## 0.26.0

The `--py` / `--python` and command "python" now all accet version number abbreviations without the
dot. For example, to specify Python 3.8 you can now say any of `--py python3.8`, `--py 3.8` or
`--py 38`.

## 0.25.0

This release adds support for `--python` and command "python" abbreviations. In addition to
specifying `--python /usr/bin/python3.12` and `--python python3.12` you can now just say
`--python 3.12` and this will be expanded to `--python python3.12`. For maximum brevity, you can
say `--py 3.12`.

Also, creating `--python` venvs previously would error out in some scenarios previously when
re-writing venv script shebangs. This is now fixed.

Finally, using factors now mixes cleanly with commands that have aliases. Specifying a factor for
the alias now plumbs through to the underlying command correctly.

## 0.24.0

This release adds support for setting a custom `python` per-command. This `python` works just like
the global `--python` option, but scoped to an individual command and trumping all other
configuration. If a command says it needs `python = "python3.9"` then it will always run under
`python3.9`.

Also, the error output is improved when the requested `--python` can't be found and console script
shebangs in `--python` venvs are fixed to point to the correct interpreter allowing direct use.

## 0.23.3

Fix `[[tool.dev-cmd.python]] extra-requirements` handling of string values (requirements.txt style
value).

## 0.23.2

Fix `[[tool.dev-cmd.python]] pyproject-cache-keys` inheritance handling.

## 0.23.1

Fix regression in `when` handling for 1st defined `[[tool.dev-cmd.python]]`.

## 0.23.0

This release re-works `--python` venv setup customization with breaking TOML schema changes. Please
review https://github.com/jsirois/dev-cmd/blob/main/README.md#custom-pythons to learn about the new
features and TOML structure changes under the `[toolAlso provid.dev-cmd] python` key.

## 0.22.0

Add support for per-`--python` venv setup customization. This allows for vagaries in older Pythons
and the Pips that support them.

Also provide finer-grained venv caching control with the new
`[tool.dev-cmd.python.requirements] input-keys` for selecting just a subset of pyproject.toml's
values to form the cache key.

## 0.21.1

Fix `when` environment marker evaluation to take place in the requested Python's environment when a
custom `--python` is specified.

## 0.21.0

Add support for `--python PYTHON` to have `dev-cmd` establish a custom python venv to run commands
in. This option is only present if you install `dev-cmd` with the `old-pythons` extra; e.g. a
requirement string like `"dev-cmd[old-pythons]"`. As the extra name suggests, this will allow you to
run development commands against Pythons older than those supported by the underlying development
tool you use to run `dev-cmd`.

This release also fixes a regression in `--color` output handling.

## 0.20.3

Fix command timing regression that reported ~0s for serially executed commands.

## 0.20.2

Fix redundant step prefixes for bare commands.

## 0.20.1

Fix up parallel step indication and timing rollups.

## 0.20.0

Add support for task timing rollups and fix a bug in `accepts-extra-args` handling when there are
multiple `accepts-extra-args` commands in a run, but they all resolve to the same command.

## 0.19.1

Fix times reported via `-t` / `--timings` to have a consistent format with the overall run time.

## 0.19.0

Add support for emitting detailed timings with `-t` / `--timings`.

## 0.18.2

Fix rendering of command output to be resilient to bytes that can't be decoded into the console
character encoding.

## 0.18.1

Fix late detection of configuration errors in the run phase from bubbling up uncaught.

## 0.18.0

Add support for `when` marker expressions to commands and tasks to allow defining
platform-specific commands and tasks. Also add support for an explicit `name` for commands and
tasks to allow defining one version of a command or task for one platform and others for other
platforms.

## 0.17.1

Fix extra args support to pass all args after the 1st occurrence of `--` in the arg list.
Previously, only args after the last occurrence were captured.

## 0.17.0

Denote the default command or task in `-l` / `--list` output with a leading asterisk.

## 0.16.1

Fix missing help output for come commands and fix `--color` help.

## 0.16.0

Note when commands and tasks can accept extra args in `-l` / `--list` output.

## 0.15.0

Add support for hiding commands and tasks from `-l` / `--list` output.

## 0.14.0

Add support for documenting commands and tasks and listing them with their documentation via
`-l` / `--list`.

## 0.13.0

Support an optional leading `:` in factor argument values to parallel factor parameter default
syntax and better visually separate factor values from factor names.

## 0.12.0

This change adds support for command parametrization via environment variables, Python interpreter
marker environment values and factors similar to those found in [tox](https://tox.wiki/)
configuration.

## 0.11.1

Improve error message when the project root cannot be discovered.

## 0.11.0

Fix commands with an argv0 of "python" on Windows and add support for argv0 being a Python script.

## 0.10.4

Fix `-p` / `--parallel` handling of tasks - no longer flatten them.

## 0.10.3

Gracefully handle keyboard interrupt and kill in-flight processes with logging.

## 0.10.2

Fix missing typing-extensions dependency and update README.

## 0.10.1

Fix `-s` / `--skip` interaction with extra args support.

## 0.10.0

Add support for skipping task steps with `-s` / `--skip`.

## 0.9.3

Fix `dev-cmd` handling of execution errors. Previously an uncaught exception assigning
`__traceback__` could be observed in certain situations.

## 0.9.2

Fix `dev-cmd` for interactive commands that read from stdin.

## 0.9.1

Fix sdist release to include tests and `uv.lock`.

## 0.9.0

Add support for Python 3.8.

Also improve color support for Windows.

## 0.8.0

Add `-q` / `--quiet` to quiet `dev-cmd` output to just the output of the commands it runs.

Also fix the `dev-cmd` exit code to reflect the exit code of a failing command when there is
exactly one failing command.

Finally, fix `dev-cmd` color setting propagation to subprocesses in certain situations where
`NO_COLOR` or `FORCE_COLOR` are present in the environment.

## 0.7.0

Add knobs to control when and how `dev-cmd` exits an invocation that has command failures:
+ `[tool.dev-cmd] exit-style` and `-k` / `--keep-going` or `-X` / `--exit-style` allow configuring
  how quickly the `dev-cmd` invocation exits after a command failure. By default, it exits after the
  step containing the 1st command failure completes, but an immediate end or continuation through
  all steps can be requested.
+ `[tool.dev-cmd] grace-period` and `--grace-period` allow configuring how in-flight commands are
  terminated when exiting an invocation with command errors.

## 0.6.0

Emit a trailing message indicating overall run status and timing.

## 0.5.1

Fix inadvertent `-p` / `--parallel` output interleaving.

## 0.5.0

Add support for `--color` choice and respect ambient color setting when there is not `--color`
choice.

Add support for `-p` / `--parallel` to request all top-level commands and tasks requested on the
command line be run in parallel.

Also, re-work task parallelization to be more robust and general. Now sub-lists in a task definition
are either run in parallel or serial depending on their nesting depth, which can be arbitrarily
deep. The 1st level, the task list itself, is run in serial to seed the alternation.

## 0.4.1

Several parallelization fixes:
+ Restore color support.
+ Restore `accepts-extra-args` support.
+ Complete parallel tasks incrementally.

## 0.4.0

Breaking pre-1.0 changes:
+ `[tool.dev-cmd.aliases]` is now named `[tool.dev-cmd.tasks]`.
+ The default task or command is now specified with the `default` key in
  the `[tool.dev-cmd] table. The key is just the name for the task or
  command that should be default.

## 0.3.1

Fix regression in cwd and env support for commands.

## 0.3.0

Add support for parallelizing execution of commands in an task.

## 0.2.1

Fix project root dir detection.

## 0.2.0

Guarantee commands are run in the root project dir or else the custom
`cwd` project sub-dir defined for the command.

## 0.1.1

Update project metadata.

## 0.1.0

Initial release.
