# p4-marketplace

The marketplace `p4-marketplace` holds three Claude Code plugins, each with hooks and a skill.

- **p4-temportal**, whose skill `plugins/p4-temportal/skills/temportal/SKILL.md` says what it does.
- **p4-phi**, whose README `plugins/p4-phi/README.md` says what it does and how it is set.
- **p4-native**, the host layer, whose README `plugins/p4-native/README.md` says what it does.

## Install

The marketplace's catalog is `.claude-plugin/marketplace.json` at the root of ezexe/p4, the folder above this one, so add the marketplace by the repository's name, then install each plugin by its own from your shell:

```bash
claude plugin marketplace add ezexe/p4
claude plugin install p4-phi@p4-marketplace
claude plugin install p4-temportal@p4-marketplace
claude plugin install p4-native@p4-marketplace
```

Each install is a copy in Claude Code's plugin cache, `~/.claude/plugins/cache/p4-marketplace/<plugin>/<version>/`, at user scope unless `--scope project` or `--scope local` says otherwise.
This folder holds no catalog of its own.

## Where each plugin keeps its files

A project's store is the folder `<project>/.claude/p4/`, a git repository of its own.
p4-temportal keeps its files in the store's `temportal/`, p4-phi in its `phi/` and p4-native in its `native/`, and only `p4.json`, `.git`, `.github`, `.gitignore` and `.gitattributes` stay at the store's top.
Outside the store, the plugins keep the Claude Code settings they rely on in the project's `.claude/settings.local.json`, merged with what is there: `autoMemoryDirectory`, naming the store's `temportal/memory`, so Claude Code writes and loads the auto memory there itself, `plansDirectory`, naming the store's `temportal/plans` from the project's root, so Claude Code writes its plan files there, and `attribution.commit` only when the store's `p4.json` gives a text in its `claude` section.
`plansDirectory` is written only where the store lies inside the project and no user, project or managed settings file names a folder for plans, and `"plansDirectory": false` in the `claude` section of `p4.json` leaves it unwritten.
They also keep two allow rules ezexe approved under `permissions.allow`, for `phi.py` and `p4.py sync`, as entries of their own beside the user's rules; no other permission or security key is written, and a key changed by hand is left as it is.
What they own is recorded in the store's `claude-settings.json`, which the store's git ignores, and the check runs again at a store's first start, after a layout move, when Claude Code or a p4 plugin changes version, and when a settings file changes; `docs/claude-settings.html` says how.
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

p4-phi and p4-temportal read their settings from `<project>/.claude/p4/p4.json`, one section each for `memory`, `scratchpad`, `temportal`, `recall` and `phi`.
The first plugin to run in a project writes it with the defaults of `p4conf.py`, and a newer plugin adds the keys it brings, keeping every value already set.
A value a plugin wrote, recorded under `_written` with the generation of the defaults that wrote it, follows a later change of its default made by a newer generation, and a value set by hand stays. Two limits: a value set by hand that equals the value recorded as written moves at the next generation, and in a store from before the record, a value set by hand that equals a past default moves.
p4-phi also reads `phi/phi.json`, and some environment variables set a value for one run.
The `claude` section of `p4.json` names the Claude Code settings a store wants beyond the defaults, and is never written by a plugin.
The copies of `p4conf.py` in those two plugins are identical, and p4-native carries none, since it writes no setting.

## p4-temportal's hooks module

p4-temportal's `hooks/register.ts` is a hooks module, whose functions run inside Claude Code, named in `hooks/hooks.json` beside the command hooks.
It runs the retention sweep, `lifetime.py tick`, at a session's start, again when the next cookie is due, a minute at least and an hour at most after the sweep before, and once more at the session's end.
The sweep at the end runs in a process that `lifetime.py tick --let-go` starts and lets go of, since the `session.end` hooks of every module share the SessionEnd budget, 1.5 seconds by default, by https://code.claude.com/docs/en/plugins/mods/reference.md, "Limits".
What a sweep moved or cleared is a dim line of the transcript, which the model does not read.
The module registers the slash command `/lifetime`, whose `list`, `set <path> <lifetime>`, `clear <path>` and `now` each run the command of `lifetime.py` by that name.
The command is ezexe's: Claude Code's Skill tool refuses a command a module registers, so a session cannot run it.
A session has the same four as the tool `mcp__p4-temportal__lifetime`, which the module registers by `$.tool.register`: `command` is `list`, `set`, `clear` or `now`, with `path` and `lifetime` for a set and `path` for a clear.
The module serves the tool at `tool.run`, the event that fires once Claude Code allowed the call, so the permission check stands before a set, a clear and a sweep, which end in deleted files, and p4 writes no allow rule for the tool.
It hooks no `tool.call`, where https://code.claude.com/docs/en/plugins/mods/api.md serves a registered tool and an answer skips that check.
What `lifetime.py` printed is the tool's result, what it refused with is the call's error, and the words of a call go after `--`, so a path that opens with a dash is no option.
Seen on Claude Code 2.1.328, in a `claude -p` run of the plugin from a scratch project, told to use no shell command: `mcp__p4-temportal__lifetime` was in the session's tool list, the session loaded it with ToolSearch, a `list` printed the two cache rules, a `set` of `notebook/probe.md` to `7d` printed its expiry and `expires.json` held the cookie, and a `set` of a path outside `temportal/` came back as the call's error with the line of `lifetime.py`.
That run allowed the tool by `--allowedTools`, so the ask before a call was not seen.
At `session.compact`, the event of every compaction in the API types of Claude Code 2.1.326, the module adds a keep list to what the summary is told: every session id, file path, branch, commit hash, decision with its source and open item, and the path of every state page and hand-over note.
The list goes after what was typed behind `/compact`, and once.
A session where the module does not load is told the same list by the `PreCompact` command hook `compact.py keep`, whose stdout Claude Code uses as instructions for the summary, by https://code.claude.com/docs/en/hooks.md, "PreCompact output".
That hook prints nothing where the `custom_instructions` it is handed already hold the list, which they do beneath the module: seen on Claude Code 2.1.328 in a `claude -p` run from a scratch project, a `/compact` with no words after it handed a `PreCompact` hook the module's list.
Behind the summary the module adds one message, the ledger: the paths of the files the session wrote or edited, read from the transcript's calls of Write, Edit and NotebookEdit with no model, the last 60 with a count of the older ones.
A compaction runs over the messages since the one before, so a ledger takes the paths of the ledger before it, which is among those messages.
A minute after a turn of the main conversation ended, with no turn begun since, the module reads the context by `$.session.usage`, and where it is at or past `temportal.compact_at` it compacts the session by running `/compact` with the keep list.
`temportal.compact_at` is a percent of the model's context window in the store's `p4.json`: 70 where it is unset, and 0 or `false` starts no compaction.
The module starts none where auto-compaction is off, none at the token count where Claude Code compacts by itself, and none where the first reading after a compaction is already at or past the line, until Claude Code compacted again.
Claude Code's own compaction is untouched: its threshold, `idleCompaction`, `/compact` and a project's "Compact instructions" stay ezexe's, by https://code.claude.com/docs/en/context-window.md and https://code.claude.com/docs/en/model-config.md.
Seen in the desktop app on Claude Code 2.1.326, in a session another session started: a plugin's own call of `$.session.compact` was refused five times over a minute with "not available in a headless (-p / SDK) session yet: compaction here runs inside a turn (a /compact prompt)", and `/compact` run by `$.command.run` compacted the session, from 194,336 tokens to 30,108 by the result's own counts.
The module's own `session.compact` hook heard that compaction with the trigger `manual`, the message it added was in the context afterwards, and the message added at one compaction was among the messages of the next.
The event lacks a call that starts a compaction outside a turn in such a session, a trigger that tells the plugin's compaction from one ezexe typed, and any summary string to check, so the SessionStart command hook for the source `compact` stays.
Not seen live: a compaction Claude Code starts by itself, and the compaction of a subagent's transcript.
`tool.run` is in the API types of Claude Code 2.1.326 and is no event on 2.1.322, where a module that hooks it does not load.
No command hook runs the sweep, so where the module does not load nothing is cleared until `lifetime.py now` is run by hand.
The module was seen to load on Claude Code 2.1.326 and 2.1.328.
A hooks module needs Claude Code v2.1.287 or later, and it does not load in a session started with `--safe-mode` or `--bare`, where `disableAllHooks` is set, or where managed settings block mods, by https://code.claude.com/docs/en/plugins/mods/create.md.

## Windows

Every command hook of p4-phi and p4-temportal is a shell command that starts `sh`, which on Windows is Git Bash's.
Without Git Bash, Claude Code runs the command in PowerShell, where `sh` is missing and the hook does not run.
Installing Git for Windows, or setting `CLAUDE_CODE_GIT_BASH_PATH` to a Git Bash Claude Code does not find, lets the hooks run.
Each hook of those two plugins on which `onFailure` acts sets it to `continue`, so a hook that cannot start never blocks a call.
Each of their hooks modules starts python itself, with no `sh`, so p4-temportal's retention sweep runs without Git Bash.
p4-native runs no command hook and no python, so it needs neither.

## Tests

The python tests are under `tests/`, beside this file, each in the folder named after the plugin whose code it runs.
`python -m pytest`, run in this folder, runs every one of them.
The tests of a plugin's hooks module are in `hooks/register.test.ts`, and `claude plugin test <plugin folder>` runs them.
