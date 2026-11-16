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

The cap went live in the checkout at 07:32 on 2026-11-16, and these sums are of the `user-prompt-submit` rows logged from then until 08:49 the same day.

| | Before, 510 prompts | After, 79 prompts |
| --- | --- | --- |
| Characters in all | 1,000,543 | 128,715 |
| Mean a prompt | 1,962 | 1,629 |
| Median prompt | 1,118 | 368 |
| Largest prompt | 11,654 | 9,466 |
| Prompts over 4,000 | 92 | 5 |

- The 5 prompts over 4,000 are each the first message of a started session, which carries its background once and keeps the 9,500 ceiling; they sum to 46,912 characters.
- The other 74 prompts sum to 81,803 characters, a mean of 1,105 and a median of 348, and none is over 3,965.
- 6 of those 74 reached the ceiling, and each named what it held back by count and page.
- A turn another session started carried the routing advice in full before: 106 such prompts with a mean of 2,596 and a median of 1,397.
- The same kind of turn now carries one line: 37 prompts with a mean of 1,009 and a median of 272.
- The two orchestrating sessions that were prompted in this window, the hub and the puppeteer's top, got 24 prompts with a mean of 991 and a median of 272.
- The hub itself, `local_a2a263da`, was prompted too few times in this window to stand alone, so its 321,382 characters have no like-for-like row yet.

## What the first live prompts showed

- A list of four start requests met the ceiling and was shown cut in the middle of a call.
- A held piece is no longer shown cut: it is named beside the prompt by how it begins, with its count and its page, and the session is told to read the page when a piece asks something of it.
