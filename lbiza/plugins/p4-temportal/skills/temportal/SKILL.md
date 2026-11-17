---
name: temportal
description: Where this project keeps its auto memory, its notebook and its saved code, and how to give a file a lifetime so it is cleared when it is no longer relevant. Use before writing a note, a probe, a log, a download or any file meant to outlast the session, and when asked what temportal holds or to clear it.
---

# temportal

p4-temportal keeps the project's lasting files in `.claude/p4/temportal/` and clears them by their lifetimes.
Each session's scratchpad directory is Claude Code's own: it is made under the system temp directory for the session, temporary files go there, and Claude Code deletes it with the session's transcript.
Transcripts, plans, file history and subagent memory stay where Claude Code puts them too.

- `temportal/memory/` is the project's auto memory directory once `autoMemoryDirectory` in `.claude/settings.local.json` names it: Claude Code writes memory files and their `MEMORY.md` index there and loads the index at each start itself, and nothing in it is ever cleared.
- Until that key is there, Claude Code keeps the memory in its own folder under `~/.claude/projects/`, and p4-temportal moves nothing out of it.
- `temportal/notebook/` is the notebook, kept across sessions: a file meant to outlast the session, such as a state page, is written there on purpose, with a lifetime when it should not stay for good.
- Logs, build output and binaries in the notebook are moved into its `.out/`, which git ignores.
- `temportal/src/` holds code kept for reuse that the project's repository does not use.

## Lifetimes

Two kinds of lifetime clear what is no longer relevant, the way a browser handles its cache and its cookies.

- **Cache:** a rule per folder in `.claude/p4/p4.json` under `temportal.cache`, with `max_age_days` and `max_mb`, and by default `notebook/.out` keeps 14 days and at most 500 MB and `.layout-conflicts` keeps 30 days.
- **Cookie:** one file or folder with its own expiry, set when you write it, for anything that should outlive the session but not stay for good, such as a downloaded page, a probe's output or a note about a short-lived state.

The retention sweep clears what is past its lifetime at each session start and session end.

Set a cookie:

```bash
CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}" sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh" lifetime set ".claude/p4/temportal/notebook/<file>" 7d
```

The lifetime is `30m`, `12h`, `7d`, `2w`, an ISO date, or `session` with `--session ${CLAUDE_SESSION_ID}` to clear it when this session ends.
`list` shows every cookie and cache rule, `clear <path>` removes an expiry and keeps the file, and `now` runs the retention sweep at once.
A path under `memory/` is refused.
A tracked file that is cleared keeps its last version in the store's git history.
