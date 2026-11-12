---
name: temportal
description: Where this project keeps the files Claude Code would otherwise write under AppData or the system temp directory, and how to give a file a lifetime so it is cleared when it is no longer relevant. Use before writing a temporary file, a probe, a log, a download or a note meant to last only a while, and when asked what temportal holds or to clear it.
---

# temportal

Every file this session would otherwise leave in AppData or the system temp directory lives in `<project>/.claude/p4/temportal/`, tracked by the store's own git repository.
Each p4 plugin writes only in its own directory under `.claude/p4/`: `temportal/`, `recall/`, `phi/`.

- `temportal/memory/` holds the project's memory. The AppData memory directory keeps only a pointer to it. Nothing here is ever cleared.
- `temportal/tmp/<session>/` is this session's scratchpad. The harness's scratchpad path is a link to it, so write there by either path. It is committed and removed after the session ends.
- `temportal/scratchpad/` is the notebook that lasts across sessions. Logs, build output and binaries in it are swept into `scratchpad/.out/`.
- `temportal/src/` holds code kept for reuse that the project repository does not use.

## Lifetimes

Two kinds of lifetime clear what is no longer relevant, the way a browser handles its cache and its cookies.

- **Cache:** a rule per directory in `.claude/p4/p4.json` under `temportal.cache`, with `max_age_days` and `max_mb`. By default `scratchpad/.out` keeps 14 days and at most 500 MB, and `.layout-conflicts` keeps 30 days. A file past its rule is cleared at the next session start.
- **Cookie:** one file or directory with its own expiry, set when you write it. Use it for anything that should outlive the session but not stay for good, such as a downloaded page, a probe's output or a note about a short-lived state.

Set a cookie:

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/hooks/lifetime.py" --p4 "<project>/.claude/p4" set "<path under temportal/>" 7d
```

The lifetime is `30m`, `12h`, `7d`, `2w`, an ISO date, or `session` with `--session <session id>` to clear it when this session ends.
`list` shows every cookie and cache rule, `clear <path>` removes an expiry and keeps the file, and `now` sweeps at once.
A path under `memory/` is refused.
A tracked file that is cleared keeps its last version in the store's git history.
