# The text phi adds beside a prompt, measured

This page holds the measurement that ezexe/p4#43 asks for.
The numbers are sums of the `said` field of each session's `log.jsonl` in the store `E:/projects/p4-phi/.claude/p4`.
`said` is the count of characters one hook call returned.

## Before the cap, on 2026-11-13

- The hub `local_a2a263da`: 321,382 characters from all hooks, 298,758 of them from 170 `user-prompt-submit` calls.
- The hub's largest single prompt carried 11,654 characters, and its median prompt carried 1,385.
- The median was one paragraph, the routing advice for a turn another session started, repeated on every such turn.
- The whole store: 1,267,667 characters from all hooks, 907,718 of them from 471 `user-prompt-submit` calls, a mean of 1,927 a prompt.
- Eight sessions had at least one prompt at the old ceiling of 9,498 characters.

## What changed

- `PROMPT_CHARS`, 4,000 by default and `prompt_chars` in `phi/phi.json`, is the ceiling on what phi adds beside one prompt.
- The first message of a started session, which carries its background once, keeps the harness's own ceiling of 9,500.
- A piece that does not fit is kept whole on the session's `held.md` and named beside the prompt by count and by that page.
- A sibling's `replaces:` or `deprecates:` note is shown only when it touches the session's task, shard or open steps.
- The other notes are a count and the pages of the sessions that wrote them, and each note is counted once.
- The routing advice for a turn another session started is said once in full, then as one line naming `standing.md`.
- After a compaction the rules and the standing instruction come back as one line each with their page.
- Reports beyond the room are cut and named with their pages.

## After the cap

The rows below are filled from the same logs once the change has run on live prompts.
