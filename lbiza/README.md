# p4-marketplace

The marketplace `p4-marketplace` holds two Claude Code plugins, each with hooks, scripts and a skill.

- **p4-temportal**, whose skill `plugins/p4-temportal/skills/temportal/SKILL.md` says what it does.
- **p4-phi**, whose README `plugins/p4-phi/README.md` says what it does and how it is set.

## Where each plugin keeps its files

A project's store is the folder `<project>/.claude/p4/`, a git repository of its own.
p4-temportal keeps its files in the store's `temportal/` and p4-phi in its `phi/`, and only `p4.json`, `.git`, `.github`, `.gitignore` and `.gitattributes` stay at the store's top.
Outside the store, the plugins keep the Claude Code settings they rely on in the project's `.claude/settings.local.json`, merged with what is there: `autoMemoryDirectory`, naming the store's `temportal/memory`, so Claude Code writes and loads the auto memory there itself, and `attribution.commit` only when the store's `p4.json` gives a text in its `claude` section.
They also keep two allow rules ezexe approved under `permissions.allow`, for `phi.py` and `p4.py sync`, as entries of their own beside the user's rules; no other permission or security key is written, and a key changed by hand is left as it is.
What they own is recorded in the store's `claude-settings.json`, which the store's git ignores, and the check runs again at a store's first start, after a layout move, when Claude Code or a p4 plugin changes version, and when a settings file changes; `dox/claude-settings.html` says how.
When p4 creates the local file, it adds `.claude/settings.local.json` to the project's `.git/info/exclude` unless git already ignores it.
Outside the store, p4-phi adds one line to the project's `.git/info/exclude` that keeps `.claude/p4/` out of the project's repository, keeps the list of stores `p4-stores.json` in Claude Code's configuration directory once a store's `p4.json` sets `phi.home`, and keeps in its plugin data folder the python its runners proved on Windows.
A store in an older layout, flat in `.claude/p4/` or with `store/` and `models/` under `recall/`, is moved at the next session start by whichever plugin runs first, and when the store is a git repository the move is committed on its own.
A file that differs between the two places keeps the newer copy, and the older one goes to `<plugin>/.layout-conflicts/`, or is deleted when git ignores the file.
A session scratchpad link that pointed at the older place is pointed at the moved folder.

## An ask before code goes to a temp folder or the notebook

p4-temportal asks nothing before a write, since Claude Code's own ask rules do it, and p4 never writes a permission key, which is ezexe's.
A project that wants that ask lists ask rules on `Edit` paths under `permissions.ask` in its own settings file, one rule per extension, such as `Edit(//tmp/**/*.py)`, `Edit(~/AppData/Local/Temp/**/*.py)` and `Edit(/.claude/p4/temportal/notebook/**/*.py)`.
An `Edit` rule covers Write and NotebookEdit too, by https://code.claude.com/docs/en/permissions.md: "`Edit` rules apply to all built-in tools that edit files."
In those rules `//` starts at the filesystem root, `~/` at the home folder and a single `/` at the project in project settings, as the same page's table of path patterns says.
No permission mode approves a call an ask rule matches, bypassPermissions included, by https://code.claude.com/docs/en/permission-modes.md.
A path a shell command writes, by a redirect or `cp`, is not an `Edit` path, so these rules do not see it.

## Settings

Both plugins read their settings from `<project>/.claude/p4/p4.json`, one section each for `memory`, `scratchpad`, `temportal`, `recall` and `phi`.
The first plugin to run in a project writes it with the defaults of `p4conf.py`, and a newer plugin adds the keys it brings, keeping every value already set.
A value a plugin wrote, recorded under `_written` with the generation of the defaults that wrote it, follows a later change of its default made by a newer generation, and a value set by hand stays. Two limits: a value set by hand that equals the value recorded as written moves at the next generation, and in a store from before the record, a value set by hand that equals a past default moves.
p4-phi also reads `phi/phi.json`, and some environment variables set a value for one run.
The `claude` section of `p4.json` names the Claude Code settings a store wants beyond the defaults, and is never written by a plugin.
The copies of `p4conf.py` in the two plugins are identical.

## p4-temportal's hooks module

p4-temportal's `hooks/register.ts` is a hooks module, whose functions run inside Claude Code, named in `hooks/hooks.json` beside the command hooks.
It runs the retention sweep, `lifetime.py tick`, at a session's start, again when the next cookie is due, a minute at least and an hour at most after the sweep before, and once more at the session's end.
The sweep at the end runs in a process that `lifetime.py tick --let-go` starts and lets go of, since the `session.end` hooks of every module share the SessionEnd budget, 1.5 seconds by default, by https://code.claude.com/docs/en/plugins/mods/reference.md, "Limits".
What a sweep moved or cleared is a dim line of the transcript, which the model does not read.
The module registers the slash command `/lifetime`, whose `list`, `set <path> <lifetime>`, `clear <path>` and `now` each run the command of `lifetime.py` by that name.
The command is ezexe's: Claude Code's Skill tool refuses a command a module registers, so a session cannot run it, and the skill page tells a session to give ezexe the line to type.
The module registers no tool for the model, since an answer at `tool.call`, where https://code.claude.com/docs/en/plugins/mods/api.md serves a registered tool, skips the permission check, and `tool.run`, which fires once a call is allowed, is no event on Claude Code 2.1.322, where a module that hooks it does not load.
No command hook runs the sweep, so where the module does not load nothing is cleared until `lifetime.py now` is run by hand.
The module needs Claude Code v2.1.287 or later, and it does not load in a session started with `--safe-mode` or `--bare`, where `disableAllHooks` is set, or where managed settings block mods, by https://code.claude.com/docs/en/plugins/mods/create.md.

## Windows

Every command hook of both plugins is a shell command that starts `sh`, which on Windows is Git Bash's.
Without Git Bash, Claude Code runs the command in PowerShell, where `sh` is missing and the hook does not run.
Installing Git for Windows, or setting `CLAUDE_CODE_GIT_BASH_PATH` to a Git Bash Claude Code does not find, lets the hooks run.
Each hook of both plugins on which `onFailure` acts sets it to `continue`, so a hook that cannot start never blocks a call.
Each plugin's hooks module starts python itself, with no `sh`, so p4-temportal's retention sweep runs without Git Bash.

## Tests

Each test file runs on its own from its folder with `python -I -X utf8 <file>`: p4-temportal's in `plugins/p4-temportal/hooks/` and p4-phi's in `plugins/p4-phi/scripts/`.
The tests of a plugin's hooks module are in `hooks/register.test.ts`, and `claude plugin test <plugin folder>` runs them.
