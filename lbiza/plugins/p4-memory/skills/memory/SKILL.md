---
name: memory
description: "p4-memory — where the built-in per-project memory lives: <project>/.claude/p4/memory/, tracked by the p4 repo, and nowhere else; the harness's AppData path (~/.claude/projects/<project-slug>/memory/) holds only a pointer MEMORY.md naming it. Use when a base memory is about to be written, when the session start reports a conflict or a busy directory, or to explain or check where memories are stored."
---

# p4-memory

> A memory that lives only on one device is lost with the device, and never reaches the repo the work is in.

The base memory system — one fact per file plus its `MEMORY.md` index line, as the session's own `# Memory` instructions define it — is the base class the vlds override wraps.
This plugin moves its storage, never its shape: the files, the frontmatter and the index stay exactly as the base defines them; only where they live changes.

## Where

- **The store:** `<working dir>/.claude/p4/memory/` — inside the p4 repo (`.claude/p4/`, its own git repository, never the project's), so every memory rides that repo's history and reaches every device the repo does. Read every memory here, and write every memory file and index line here.
- **The harness's path:** `~/.claude/projects/<project-slug>/memory/` — fixed by the system prompt, in the device's local AppData on Windows. After migration it holds only a pointer `MEMORY.md`: an instruction telling the session where the store is. It is not a store; nothing written there stays there.

## What the session start does (`hooks/p4_memory.py migrate`)

1. No `.claude/p4/` in the project → nothing (vlds creates the p4 repo; this plugin depends on it).
2. A junction or symlink to the store left by an earlier version → removed as a link, its target untouched.
3. Every AppData memory source — `memory/` and every `memory.pre-p4-<time>` directory — is merged into the store: identical in p4 → dropped; a file of the live `memory/` absent in p4 → moved in; any other → kept at `.claude/p4/memory/.conflicts/<source>/<path>`. A p4 file is never overwritten; merging a conflict is the owner's edit.
4. Each source is then deleted (the live `memory/` emptied but for the pointer), the pointer `MEMORY.md` written, and the store's `MEMORY.md` printed — the session's real index, since the harness loaded only the pointer.
5. The harness can hold a directory open while a session starts, so a deletion is retried; still busy, the Stop hook sweeps it at the turn's close.

## A write into AppData

A Write or Edit into the AppData directory is never refused: the PostToolUse hook moves the file to the same path in the store (a p4 file it replaces kept in `.conflicts/replaced/`), appends index lines added to the pointer to the store's `MEMORY.md`, restores the pointer, and tells the session where the file went. Write to the store directly instead.

## Never

- Never touches the rest of `~/.claude/projects/<project-slug>/` — the harness's transcripts and per-session directories are its own.
- Never overwrites a p4 memory during migration, and never deletes a p4 file or a conflict copy — disposal of what the user authored in the store is the owner's.
- Never commits: the p4 repo's commit is the owner's word, per act.
