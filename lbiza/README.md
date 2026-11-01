# p4-marketplace

Three Claude Code plugins. No skills, no agents, no commands: each is a few hooks and a script. Claude Code and the desktop app keep working as they ship. These plugins change where some files are stored, and they add lines next to a message only when the repo's own history has something relevant.

- **p4-memory** stores Claude Code's built-in per-project memory in `<project>/.claude/p4/memory/` instead of `~/.claude/projects/<slug>/memory/`. The AppData directory keeps one pointer `MEMORY.md`. At session start the hook prints the p4 `MEMORY.md` the way the built-in would print its own, plus one line when it moved a file or kept a conflict. A memory written into AppData is moved into p4.
- **p4-scratchpad** keeps the notebook in `<project>/.claude/p4/scratchpad/`, tracked by the p4 repo. At session start it sweeps logs, build results and binaries into `scratchpad/.out/`, which ignores itself. It prints nothing unless it did something. Two asks about where code belongs ship off. `P4_SCRATCHPAD_ASKS=1` turns them on: a line for each file in `.claude/p4/src/` that the repo uses, and an ask before a code file is written to a temp directory or the notebook.
- **p4-recall** is a small ranker trained on the repo's own store: rulings, corrections, retractions, facts, earlier messages and memory. When it is confident, it adds a few lines from that history next to the owner's message or a subagent's task. Otherwise it adds nothing.

The design, with the measurements behind each part and the test plan, is [`.docs/p4/fresh-marketplace.md`](../.docs/p4/fresh-marketplace.md).

Tests: `python3 plugins/p4-memory/hooks/test_p4_memory.py`, `python3 plugins/p4-scratchpad/hooks/test_scratchpad.py`.
