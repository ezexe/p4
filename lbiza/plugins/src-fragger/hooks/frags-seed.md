# src-fragger — Frags

One entry per frag: code the agent wrote to complete a task, kept under `src/` — the git-tracked home of the work's reusable and worthwhile outputs, beside the notebook `.claude/p4/scratchpad/` notebook — so the next task that needs the same labor updates it instead of rewriting it, the user can read and edit it, and a refused execution still has a file to hand over.
A frag is code whose job no single tool call does; an edit, an append, a whole-file write, or one shell command is the tool's own call and is never registered here. A notebook file that turns out to be worth keeping graduates here — code into the task's directory and this register, anything else into the task's `out/` (what its frags read and what they produced that is worth keeping, tracked and unregistered), a pointer left behind.
Consulted before any new frag is written — _does a frag already cover this labor?_ — and updated whenever a frag changes state.

Append one entry per frag, in this shape, one field to a line — never folded or wrapped (this header is the shape's authority):

```yaml
- frag: [path relative to src/, e.g. sweep-20260903/sweep.py]
  time: [YYYY-MM-DD HH:MM — copied from the hook stream's now:]
  task: [the task it completes, and the manual labor it replaces]
  run: [the exact command, from the project root]
  state: live | handed-off | superseded | retired
  retry: [optional — when a refused execution was retried unchanged, after what (fresh call, fresh conversation, compact, resume), and its outcome; required before state: handed-off]
```

---
