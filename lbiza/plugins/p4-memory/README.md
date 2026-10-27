# p4-memory

Stores Claude Code's built-in per-project memory in the p4 repo, `<project>/.claude/p4/memory/`, instead of only in the device's local AppData.

The harness's memory path, `~/.claude/projects/<project-slug>/memory/`, is fixed by the system prompt.
At session start this plugin copies that directory into `.claude/p4/memory/`, renames the original aside (`memory.pre-p4-<time>`, never deleted), and replaces it with a directory junction (a symlink off Windows) to the p4 copy.
The harness keeps reading and writing its own path; the bytes live in the p4 repo.

- A file that differs between the two is copied to `.claude/p4/memory/.conflicts/` and the link waits for the owner's merge.
- The rename is retried (the harness can hold the directory open at a session start); until the link exists, a PostToolUse mirror copies every memory written into AppData into p4 at once, and the Stop hook retries the link.
- The vlds memory override names `.claude/p4/memory/` as its base class's storage.

Depends on `vlds`, which creates and initializes `.claude/p4/`.

Tests: `python hooks/test_p4_memory.py`.
