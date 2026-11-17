# p4-marketplace

The marketplace `p4-marketplace` holds two Claude Code plugins, each with hooks, scripts and a skill.

- **p4-temportal**, whose skill `plugins/p4-temportal/skills/temportal/SKILL.md` says what it does.
- **p4-phi**, whose README `plugins/p4-phi/README.md` says what it does and how it is set.

## Where each plugin keeps its files

A project's store is the folder `<project>/.claude/p4/`, a git repository of its own.
p4-temportal keeps its files in the store's `temportal/` and p4-phi in its `phi/`, and only `p4.json`, `.git`, `.github`, `.gitignore` and `.gitattributes` stay at the store's top.
Outside the store, p4-temportal moves what Claude Code writes in its default auto memory directory into the store and leaves one pointer `MEMORY.md` there, and turns each session scratchpad folder Claude Code makes for the project into a link to `temportal/tmp/<session>/`, a junction on Windows, removing an empty one that stays quiet.
Outside the store, p4-phi adds one line to the project's `.git/info/exclude` that keeps `.claude/p4/` out of the project's repository, keeps the list of stores `p4-stores.json` in Claude Code's configuration directory once a store's `p4.json` sets `phi.home`, and keeps in its plugin data folder the python its runners proved on Windows and, in a project with no store, its once-per-step memory.
A store in an older layout, flat in `.claude/p4/` or with `store/` and `models/` under `recall/`, is moved at the next session start by whichever plugin runs first, and when the store is a git repository the move is committed on its own.
A file that differs between the two places keeps the newer copy, and the older one goes to `<plugin>/.layout-conflicts/`, or is deleted when git ignores the file.
A session scratchpad link that pointed at the older place is pointed at the moved folder.

## Settings

Both plugins read their settings from `<project>/.claude/p4/p4.json`, one section each for `memory`, `scratchpad`, `temportal`, `recall` and `phi`.
The first plugin to run in a project writes it with the defaults of `p4conf.py`, and a newer plugin adds the keys it brings, keeping every value already set.
A value a plugin wrote, recorded under `_written` with the generation of the defaults that wrote it, follows a later change of its default made by a newer generation, and a value set by hand stays. Two limits: a value set by hand that equals the value recorded as written moves at the next generation, and in a store from before the record, a value set by hand that equals a past default moves.
p4-phi also reads `phi/phi.json`, and some environment variables set a value for one run.
The copies of `p4conf.py` in the two plugins are identical.

## Tests

Each test file runs on its own from its folder with `python3 <file>`: p4-temportal's in `plugins/p4-temportal/hooks/` and p4-phi's in `plugins/p4-phi/scripts/`.
