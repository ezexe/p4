---
name: temportal
description: Where this project keeps its auto memory, its notebook and its saved code, where a session's temporary files and lasting findings go, how lifetimes clear what p4 keeps, what a compaction keeps, and which of Claude Code's own commands keep the rest. Use before writing a temporary file, a probe, a log or a download, before keeping a finding past the session, before making a backup copy or pruning memory, after a compaction, and when asked what temportal holds or to clear it.
---

# temportal

p4-temportal keeps the project's lasting files in `.claude/p4/temportal/` and clears them by their lifetimes.
Each session's scratchpad directory is Claude Code's own: it is made under the system temp directory for the session, temporary files go there, and Claude Code deletes it with the session's transcript.
That is Claude Code's retention sweep, which deletes a transcript once it is older than `cleanupPeriodDays`, and keeps the transcript of a session of the desktop app at any age unless ezexe sets `desktopSessionCleanupPeriodDays`, so such a session's scratchpad stays until then or until the system clears its temp folder.
Transcripts, plans, file history and subagent memory stay where Claude Code puts them too.

- `temportal/memory/` is the project's auto memory directory once `autoMemoryDirectory` in `.claude/settings.local.json` names it: Claude Code writes memory files and their `MEMORY.md` index there and loads the index at each start itself, and nothing in it is ever cleared.
- Until that key is there, Claude Code keeps the memory in its own folder under `~/.claude/projects/`, and p4-temportal moves nothing out of it.
- A temporary file, a probe, a log or a download goes in this session's own scratchpad, the folder Claude Code names to hooks as `scratchpad_dir`, never under `.claude/`, a protected path where Claude Code prompts for a write in the default and accept-edits modes and denies it in `dontAsk` mode.
- A finding meant to outlast the session goes through p4-phi's `phi.py note "<claim>" --source "<where>"`, which p4 writes into the store.
- `temportal/notebook/` is the notebook, kept across sessions: p4's scripts write there, and a session's own write there is a write under `.claude/`, which Claude Code decides by the permission mode.
- Logs, build output and binaries in the notebook are moved into its `.out/`, which git ignores, at each start and as soon as one is added or changed, so look for such a file under `.out/` at the same relative path.
- `temportal/src/` holds code kept for reuse that the project's repository does not use.

## What Claude Code keeps by itself

Reach for Claude Code's own command or setting before building a copy by hand.

- **Memory:** Claude Code writes and loads it, and `/memory` opens it and turns it on or off. Where the session lists the skill `consolidate-memory`, that skill merges duplicates, fixes stale facts and prunes the index, so memory is pruned with it and never by a lifetime.
- **A file as it was before an edit:** Claude Code takes a checkpoint before each prompt that starts a turn, and `/rewind` restores the code, the conversation or both, so make no backup copy before an edit. A checkpoint holds what the file tools changed and not what a shell command changed.
- **The whole conversation:** the transcript stays on disk for `cleanupPeriodDays`, 30 days unless set, `/resume` opens a session again and `/export` writes one out, so the store keeps no copy of a conversation.
- **The context:** `/context` shows what fills it, `/compact` with words after it compacts at once and tells the summary those words, and `/autocompact` moves the line of the automatic compaction.
- **Plans:** a plan file is Claude Code's own, written in plan mode. Once `plansDirectory` in `.claude/settings.local.json` names the store's `temportal/plan-planner/`, the project's plans are kept there, tracked with the store, and the retention sweep clears one once it is older than `cleanupPeriodDays`, as Claude Code clears a plan in `~/.claude/plans/`, where they are until then. How a plan is shaped in plan mode, and the subfolders `complete/`, `todo/` and `unplanned/` it moves into once it is finished, parked or dropped, are the skill `plan-planner` of this plugin, so read it before writing, closing, parking, dropping, reviving or reading a plan, and read nothing in those subfolders unless ezexe names the file.
- **Worktrees:** Claude Code removes the worktree of an unnamed session by itself and sweeps the worktrees of subagents once they are older than `cleanupPeriodDays`, so no lifetime is set on one.
- **Standing instructions:** `CLAUDE.md` and the unscoped rules files load at each start and again after a compaction, so an instruction that must hold in every session goes there and not in the notebook.

## Compaction

Claude Code compacts a conversation by itself when its context fills, and p4-temportal's hooks module keeps a compaction from losing what the session needs afterwards.

- Every summary is told to keep, word for word, every session id, file path, branch, commit hash, decision with its source and open item, and the path of every state page and hand-over note.
- Behind the summary comes a list that opens with "p4-temportal kept this list across a compaction", handed as additional context of the SessionStart hook that Claude Code runs after a compaction: the files this session wrote or edited, the latest last, built from the session's tool calls and carried from one compaction to the next.
- After a compaction, read the state page or hand-over note that list names before going on, and trust the list over the summary for where a file is.
- A minute after a turn ended with none begun since, the module compacts the session itself once its context is at or past `temportal.compact_at` in `.claude/p4/p4.json`, which is 70 percent unless set, and 0 starts none.
- What must outlast any summary belongs in a file: a state page in this session's scratchpad, or a finding kept with `phi.py note`.

## Lifetimes

Two kinds of lifetime clear what is no longer relevant, the way a browser handles its cache and its cookies.

- **Cache:** a rule per folder in `.claude/p4/p4.json` under `temportal.cache`, with `max_age_days` and `max_mb`, and by default `notebook/.out` keeps 14 days and at most 500 MB and `.layout-conflicts` keeps 30 days.
- **Cookie:** one file or folder under `temportal/` with its own expiry, for something p4 keeps that should outlive the session but not stay for good, such as a downloaded page or a probe's output.
- **Plans:** a plan file in `temportal/plan-planner/` is cleared once it is older than Claude Code's own `cleanupPeriodDays`, 30 days unless a settings file sets it, since Claude Code's cleanup does not reach a folder `plansDirectory` names. Only the plan files directly in that folder are cleared by that age, and a plan `plan-planner` moved into its `complete/`, `todo/` or `unplanned/` stays until ezexe's word moves it. A cache rule on `plan-planner` stands in place of that age, an empty one keeps every plan, and no plan is cleared by age where the setting cannot be read.

The retention sweep clears what is past its lifetime at a session's start, while the session runs, and at its end.
In a git worktree the store is the worktree's own `.claude/p4`, whose plans, notebook and saved code each sweep copies into the main checkout's store, a file's cookie with it. The settings are the main checkout's `p4.json` there, and the sweep clears the main checkout's store too.

ezexe lists, sets and clears lifetimes with the slash command `/lifetime`, which p4-temportal's hooks module registers:

- `/lifetime list` shows every cookie and cache rule, and the age at which a plan is cleared.
- `/lifetime set notebook/<file> 7d` gives a file or folder a cookie, with a lifetime of `30m`, `12h`, `7d`, `2w` or an ISO date.
- `/lifetime clear notebook/<file>` removes an expiry and keeps the file.
- `/lifetime now` runs the retention sweep at once.

A session cannot run `/lifetime` itself, since Claude Code's Skill tool refuses a command a hooks module registers.
A session calls the tool `mcp__p4-temportal__lifetime` for the same four: `command` is `list`, `set`, `clear` or `now`, a set takes `path` and `lifetime`, a clear takes `path`, Claude Code asks ezexe about the call where its permission mode asks, and ToolSearch loads the tool where the session's list does not hold it yet.
Where no such tool exists, as in a session whose Claude Code loads no hooks module, give ezexe the line to type.
What is set can be read without the command: the cookies are in `.claude/p4/temportal/expires.json` and the cache rules in `.claude/p4/p4.json`.
A path is read from the working folder, or from `temportal/` as `/lifetime list` prints it, and one with a space goes in quotes.
No lifetime ends with a session: a file that goes when its session goes belongs in that session's scratchpad, which Claude Code deletes with the session's transcript.
Nothing the store keeps waits on that sweep: the plugin's own sweep clears the store, plan files among them.
A path under `memory/` is refused.
A tracked file that is cleared keeps its last version in the store's git history.
