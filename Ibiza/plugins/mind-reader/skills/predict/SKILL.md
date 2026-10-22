---
name: predict
description: "mind-reader — how to read and use the prediction its prompt hook prints: the owner's likely next message and the session's likely direction, derived from every session's p4 vlds dispatch record. Use when the `## mind-reader` block appears and the turn could prepare for what comes next, when asked how well the predictions score, or to extend the predictor."
---

# mind-reader

> The repository already holds every road the owner has taken; the next message is usually one of them.

## What the hook prints

At every prompt, `hooks/mind_reader.py predict` reads `.claude/p4/sessions/*/vlds/dispatch.md` — the owner's own messages only (arrival `turn`; agent messages, task notifications and hook injections are left out) — and prints a `## mind-reader` block:

- **predicted next message** — up to three, each with a weight and where it came from: the messages that followed ones resembling the current message, in any session, merged when they resemble each other; the owner's adoption tokens (the most frequent short messages, such as `commit`) fill in when nothing resembles.
- **direction** — the earlier session whose run of messages most resembles this session's so far, and what it went on to ask after the matching point.
- **scored** — the previous prediction, scored against the message that just arrived (best token-overlap resemblance), and the session's running hit rate (a hit is ≥ 0.3).

## How to use it

- It is context for the turn, never an ask: the owner's actual words always win, and nothing is done because it was predicted.
- When the predicted next message is a step the current work leads to anyway (a commit, a restart, a test run), the closing may offer it as an option; it is never taken unasked.
- A direction that matches an earlier session is a pointer to read that session's store through the vlds operator, not a license to repeat what it did.

## Where it writes

`.claude/p4/sessions/<name>/mind-reader/predictions.md` — one entry per prompt (`after`, `time`, `next`, `direction`, and `scored` once the next prompt arrives), in the p4 repo beside the session's vlds store. Derived, never a ruling. The vlds store is read, never written.

## Next steps (the starting point stops here)

- A judged predictor: hand the pool and the dispatch runs to a cheap agent at the prompt, in the background, and compare its score against the lexical one in the same log.
- Weight recent sessions and the owner's adoption tokens by recency; read `addressed:` to predict the follow-up a kind of work tends to draw.
- Read the cold tier through `scripts/idb.py` for stores the keyspace indexes, which raw files miss.

Tests: `python hooks/test_mind_reader.py`.
