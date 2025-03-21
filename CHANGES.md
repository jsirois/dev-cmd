# Release Notes

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
