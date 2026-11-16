---
name: temportal
description: Where this project keeps its auto memory, each session's scratchpad directory and other temporary files, and how to give a file a lifetime so it is cleared when it is no longer relevant. Use before writing a temporary file, a probe, a log, a download or a note meant to last only a while, and when asked what temportal holds or to clear it.
---

# temportal

p4-temportal keeps in `<project>/.claude/p4/temportal/` the files Claude Code would write to the auto memory directory under `~/.claude/projects/` and to a session's scratchpad directory under the system temp directory.
Transcripts, plans, file history and subagent memory stay where Claude Code puts them.
Until `.claude/p4` is a git repository of its own, which p4-phi makes it, no scratchpad directory is committed or removed.

- `temportal/memory/` holds the project's auto memory, and nothing in it is ever cleared.
- `temportal/tmp/<session>/` is this session's scratchpad directory: write temporary files by this path, and the scratchpad path Claude Code gives is a link to it.
- A scratchpad directory is staged at each turn end, and its files are committed and removed after its session ends, so a file meant to outlast the session goes in the notebook, with a lifetime when it should not stay for good.
- `temportal/scratchpad/` is the notebook, kept across sessions, and logs, build output and binaries in it are moved into `scratchpad/.out/`, which git ignores.
- `temportal/src/` holds code kept for reuse that the project's repository does not use.
- At a start and at each turn end another session's scratchpad folder under the temp directory is linked to its scratchpad directory, or removed when it is empty and quiet, and at a start the scratchpad directory of an ended session is committed and removed.
- `CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}" sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh" scratchpad ended-sweep --dry-run` lists every ended session's scratchpad directory with what it would commit and remove, and the same command without `--dry-run` commits and removes them.

## Lifetimes

Two kinds of lifetime clear what is no longer relevant, the way a browser handles its cache and its cookies.

- **Cache:** a rule per folder in `.claude/p4/p4.json` under `temportal.cache`, with `max_age_days` and `max_mb`, and by default `scratchpad/.out` keeps 14 days and at most 500 MB and `.layout-conflicts` keeps 30 days.
- **Cookie:** one file or folder with its own expiry, set when you write it, for anything that should outlive the session but not stay for good, such as a downloaded page, a probe's output or a note about a short-lived state.

The retention sweep clears what is past its lifetime at each session start and session end.

Set a cookie:

```bash
CLAUDE_PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT}" sh "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh" lifetime --p4 "<project>/.claude/p4" set "<path under temportal/>" 7d
```

The lifetime is `30m`, `12h`, `7d`, `2w`, an ISO date, or `session` with `--session <session id>` to clear it when this session ends.
`list` shows every cookie and cache rule, `clear <path>` removes an expiry and keeps the file, and `now` runs the retention sweep at once.
A path under `memory/` is refused.
A tracked file that is cleared keeps its last version in the store's git history.
