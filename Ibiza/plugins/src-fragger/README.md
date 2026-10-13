# src-fragger — code the agent writes to finish a task lives in the tracked store, not the ignored scratchpad

A small plugin with one rule, one split, one floor, and one gate: every piece of code the agent authors to complete a task — a sweep, a migration, a probe, a generator, a harness page, a workflow script, anything that replaces manual, user-involved labor with a program the agent builds and runs, and whose job no single tool call does — is a **frag**, and a frag is written to the VLDS `p4/src/` directory, registered in `src/frags.md`, and never to a scratchpad or a temp directory.

## The split

Two homes under the project's `.claude/`, one axis — worth, not file type:

- **`.claude/p4/scratchpad/` is the notebook, tracked by the p4 repo, never the project's.** What nothing will read again: notes, plans, commit drafts, a run's logs and transcripts, build trees, caches. The SessionStart hook creates it and seeds no `.gitignore`: the p4 repo tracks it, the project's repo excludes `.claude/p4/` whole, so a note costs the project nothing; an older `.claude/scratchpad/` is left for the user.
- **`.claude/p4/sessions/<s8>/src/` is git-tracked in the p4 repo, separate from the project's.** Every reusable and worthwhile output of the work — code or not, whatever someone will run, read, or edit again — lives there and rides in the p4 repo's history. The frags sit in the task's directory, registered; what they read and what they produced that is worth keeping — a fetched spec, a captured page, a downloaded source or doc, a design spec a workflow returned, a run's report — sits in the task's `out/` (`src/<task>/out/`), tracked and unregistered; a sheet or README lives beside the frags.

What the work produced on the way stays in the notebook; what it produced that is worth keeping — what a later task runs, reads or edits, what a commit is about to carry — graduates to `src/`: code into the task's directory and the register, anything else into its `out/`, a one-line pointer left behind, and a frag whose path it was follows it. A log a claim cites stays a note; the claim's own entry carries what was read, and the instrument that produced it is the output. Nothing in the notebook is force-added to git: a note that seems to need committing is an output that needs moving. A truly throwaway probe — run once to answer a question and never again — may stay in the notebook after the gate's ask; the ask exists because "throwaway" is what every kept script called itself first.

## Why

There are three places agent-written code can land, with three lifetimes:

- **The harness's per-session scratchpad dies with the session.** Code there is invisible to the user, rewritten from scratch by the next task that needs it, and unreachable when it matters most — when the harness refuses the agent's own execution and the user has to run it, a file in a temp directory named after a session id is not something a user can be asked to find.
- **The project's notebook outlives the session but lives on one disk only.** Ignored, never in the project's history — the right lifetime for a build log, the wrong one for the harness that read it.
- **A frag under `<working dir>/.claude/p4/sessions/<s8>/src/<task>/` outlives the session, is the user's to open and edit (an edit is a ruling), rides in the p4 repo's history, and when execution is refused the hand-off is one registered command.**

## The floor

A frag is measured by its job, not by its length.
An exact-match replacement is an Edit call; an append, a store row, or a whole-file write is a Write call; one shell command is a Bash call — and none of these is a frag, however long the text.
The script that does one of those jobs anyway is the tool call in costume, written nearly always because a heredoc failed on the text's backslashes, quotes, or `$`; the fallback from a failing heredoc is the dedicated tool, never a script that does the tool's job.
Such a script is worse than the call it replaces — it keys on text that moves, lands twice when its new text contains its old, and carries a header, a register entry, a state, and a retirement the call never needed — and a per-turn record is a Write call for a second reason: a frag is kept to be run again, and a record written once never is.

## What ships

- [`hooks/src-fragger.md`](hooks/src-fragger.md) — the contract, injected at every SessionStart by [`hooks/session-open.sh`](hooks/session-open.sh), which also creates `p4/src/` and the notebook, seeds the register from [`hooks/frags-seed.md`](hooks/frags-seed.md) when absent (never overwriting it — a user's edit is a ruling), and prints one notice line when the project's root rules git-ignore `src/` itself (the hook never edits the root `.gitignore` and never touches the index).
- [`hooks/frag_gate.py`](hooks/frag_gate.py) — the `PreToolUse` gate, run through [`hooks/run-hook.sh`](hooks/run-hook.sh): asks before a Write, Edit, Bash, or PowerShell call writes ANY file into the harness's per-session scratchpad, a code file (by extension, a page included, or by a name such as `CMakeLists.txt`) to any other temp location (`/tmp`, the user's temp directory), or a code file to any project's `.claude/p4/scratchpad/` (that ask carries the split and the floor; a page or source captured from elsewhere belongs in the task's `out/`). Asks, never denies. The same script's `register-lint`, the third SessionStart command, prints one line when `src/` holds code the register does not name or the register names a path that is gone and not retired — anything under a task's `out/` is never read as a frag. Acceptance tests for the gate, the lint and the SessionStart hook in [`hooks/test_frag_gate.py`](hooks/test_frag_gate.py).
- [`skills/frag`](skills/frag/SKILL.md) — the procedure: the split, the floor, reuse before rewrite, the header comment, the register shape, the double-check before any hand-off, the user's edits as rulings, graduation from the notebook, retirement without deletion. Direct-invoke (`/src-fragger:frag`); the hook carries the residency.

## Before interrupting the user

A hand-off costs the user exactly the labor the frag exists to remove, so it is the last resort, and the contract makes the agent verify four things first: the frag is registered under `src/` (one click, not a search); the refusal is durable — the same call is retried once, unchanged, in a fresh tool call, because a refusal announced "for the rest of this conversation" is bound to the conversation's content rather than the process: a fresh tool call has passed where the first was refused, a fresh conversation opened with a hand-off summary clears it, and a resume of the same conversation does not; the user's word already given still covers the act; and the interruption is a decision only the user can make rather than labor the agent could still do. The retry is recorded in the register's `retry:` field, and `state: handed-off` is not written without it. When the hand-off does happen it is one `bash`-tagged fence per command, written for the user's own shell, so the chat can run it on click — the click runs in the user's terminal, not the agent's.

## The register

`.claude/p4/sessions/<s8>/src/frags.md`, one entry per frag:

```yaml
- frag: [path relative to src/]
  time: [YYYY-MM-DD HH:MM — copied from the hook stream's now:]
  task: [the task it completes, and the manual labor it replaces]
  run: [the exact command, from the project root]
  state: live | handed-off | superseded | retired
```

## Relation to vlds

src-fragger shares the VLDS store (`<working dir>/.claude/p4/sessions/<s8>/vlds/`) and nothing else. The vlds plugin's `pre-write` gate ignores `src/` (no store file name lives there) and its `phi.py check` does not scan it; a frag's provenance — which ruling asked for it, which session wrote it — belongs in the store's own files, never in the frag, so the frag stays portable.

## Install

Add the marketplace and install at user level — `/plugin marketplace add <path-or-url-of>/Ibiza` then `/plugin install src-fragger@p4-marketplace` — which activates both hooks in every repo. For a single session, `claude --plugin-dir ./Ibiza/plugins/src-fragger`.
