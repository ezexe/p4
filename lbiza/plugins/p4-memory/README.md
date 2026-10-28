# p4-memory

Stores Claude Code's built-in per-project memory in the p4 repo, `<project>/.claude/p4/memory/`, and nowhere else.

The harness's memory path, `~/.claude/projects/<project-slug>/memory/`, is fixed by the system prompt.
At session start this plugin merges every memory found there into `.claude/p4/memory/` and deletes it from AppData, leaving one file: a pointer `MEMORY.md` telling the session that its memory lives in `.claude/p4/memory/` and must be read and written there.
The start then prints the p4 `MEMORY.md`, since the harness loaded only the pointer.
The rest of `~/.claude/projects/<project-slug>/` (the harness's transcripts and per-session directories) is never touched.

- Sources merged: the `memory/` directory, a junction or symlink to p4 an earlier version left there (removed as a link, its target untouched), and every `memory.pre-p4-<time>` directory an earlier version renamed aside.
- A file identical in p4 is dropped; a file of the live `memory/` absent in p4 is moved in; any other (a differing file, or one a renamed-aside directory holds that p4 no longer does) is kept at `.claude/p4/memory/.conflicts/<source>/<path>` for the owner's merge — a p4 file is never overwritten by the migration.
- A Write or Edit into the AppData directory is moved into p4 at once by a PostToolUse hook (a p4 file it replaces kept in `.conflicts/replaced/`), index lines added to the pointer are appended to the p4 `MEMORY.md`, the pointer is restored, and the session is told where the file went.
- A deletion the harness blocks (it can hold a directory open at a session start) is retried, then left to the Stop hook, which sweeps it at the turn's close.
- The vlds memory override names `.claude/p4/memory/` as its base class's storage.

Depends on `vlds`, which creates and initializes `.claude/p4/`.

Tests: `python hooks/test_p4_memory.py`.
