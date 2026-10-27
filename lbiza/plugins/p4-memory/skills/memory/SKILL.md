---
name: memory
description: "p4-memory — where the built-in per-project memory lives: <project>/.claude/p4/memory/, tracked by the p4 repo, with the harness's AppData path (~/.claude/projects/<project-slug>/memory/) a junction to it. Use when a base memory is about to be written, when the session start reports a conflict or a failed link, or to explain or check where memories are stored."
---

# p4-memory

> A memory that lives only on one device is lost with the device, and never reaches the repo the work is in.

The base memory system — one fact per file plus its `MEMORY.md` index line, as the session's own `# Memory` instructions define it — is the base class the vlds override wraps.
This plugin moves its storage, never its shape: the files, the frontmatter and the index stay exactly as the base defines them; only the directory behind the path changes.

## Where

- **The store:** `<working dir>/.claude/p4/memory/` — inside the p4 repo (`.claude/p4/`, its own git repository, never the project's), so every memory rides that repo's history and reaches every device the repo does.
- **The harness's path:** `~/.claude/projects/<project-slug>/memory/` — fixed by the system prompt, in the device's local AppData on Windows. After migration it is a directory junction (a symlink off Windows) to the store, so the harness's own load of `MEMORY.md` and every Write through the AppData path land in p4.
- **Either path may be written** once the link exists; prefer the p4 path when naming a memory to the user.

## What the session start does (`hooks/p4_memory.py migrate`)

1. No `.claude/p4/` in the project → nothing (vlds creates the p4 repo; this plugin depends on it).
2. The AppData directory already links to the store → silent.
3. Otherwise each AppData file is copied into the store: absent there → copied; identical → nothing; different → the AppData copy is kept at `.claude/p4/memory/.conflicts/<name>` and the link waits. Merging a conflict is the owner's edit — the p4 file is never overwritten.
4. Every file in p4 byte for byte → the AppData directory is renamed `memory.pre-p4-<time>`, kept whole for the owner to dispose, and replaced by the link. A failed link restores the original name.
5. The harness can hold the AppData directory open while a session starts, so the rename is retried; still busy, the link waits. Until it exists, a PostToolUse mirror copies every memory written into AppData into p4 at once (the harness's own write is never refused), the Stop hook tries the link again at every turn's close, and the start prints the p4 `MEMORY.md` when the one the harness loaded is stale.

## Never

- Never deletes a memory, the renamed AppData directory, or a conflict copy — disposal of what the user authored is the owner's.
- Never commits: the p4 repo's commit is the owner's word, per act.
