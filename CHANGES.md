# Release Notes

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
