---
name: predict
description: "mind-reader — the side agent that predicts what the OWNER will say next, detached from the session: a background process that re-predicts while the turn runs (a rotating draft), freezes at the turn's end, is scored against the owner's actual next message, and learns its source weights from that history; its scored predictions are a gc-collectable vlds partition and its holds keep memories the owner's direction still leans on from being poured. Use when the owner asks how the predictions are doing, to read the draft or the history, or to extend the predictor."
---

# mind-reader

> Predict the owner, never the AI — and never let the prediction steer the conversation.

## What runs, and when

- **UserPromptSubmit (`start`)** — the owner's message has arrived. The previous turn's frozen prediction is scored against it, appended to the session's vlds partition `mind-reader.md`, logged to `.claude/p4/mrindex/history.tsv`, and each source's learned weight in `.claude/p4/mrindex/model.json` moves by how well its own best candidate matched. Then a watcher is spawned detached, and the hook prints **nothing** — the session answers uninterrupted.
- **The watcher (`watch`)** — the side agent. Every few seconds while the session's transcript grows, it re-predicts and rewrites `.claude/p4/sessions/<name>/mind-reader/draft.md` (revision n): the owner's three likeliest next messages, the direction, what the owner will be reacting to, the learned weights. It exits at the next `start` or after twenty idle minutes.
- **Stop (`finalize`)** — the turn ended: the prediction freezes (`frozen.json`, the draft marked FROZEN). A later Stop in the same turn refreezes it, so the version standing when the owner's next message arrives is the one scored. The holds are written.

## The sources it learns between

- `follow` — what the owner said after messages resembling this one, in any session.
- `progress` — what the owner tends to say in the state the turn is reaching: edits and no commit → the owner's own word for commit; a picker served → its recommended option; a version bumped and no reconcile → restart. The AI's actions are read only as what the owner will react to.
- `direction` — what the owner asked next in the earlier session whose run most resembles this one.
- `adopt` — the owner's most frequent short messages.

## The gc safeguard

At each freeze, the hot entries of every session's store that the owner's predicted direction leans on (three or more shared terms) are written to `.claude/p4/vindex/holds.tsv`, at most twelve per session, each expiring after seven days. The vlds light pass and the judged sweep skip a held entry until its hold expires; the owner's `/vlds:gc archive` ignores holds. A hold only retains — it never deletes, rewrites or steers anything.

## Safeguards

- A plain process: no model, no network, no tool calls, nothing written into the conversation.
- It reads the dispatch records, the hot files and this session's transcript; it writes only its own files, its partition and the holds.
- Agent messages and task notifications are never the owner's and never start or score a turn.
- Its prediction is never an ask. The owner's actual words always win.

## Tracking it

```bash
python Ibiza/plugins/mind-reader/hooks/mind_reader.py status
```

With `MIND_READER_SESSION=<short id>` set, or a `{"session_id": …}` payload on stdin, it prints the session's draft and the scored history (count, hits ≥ 0.3, mean, the last five). The side agent's log is under the notebook's ignored `.claude/p4/scratchpad/.out/mind-reader/`.

## Next steps

- A judged predictor (a cheap agent over the pool) scored in the same history beside the lexical one.
- Recency weighting of the corpus; reading the cold tier through `scripts/idb.py`.

Tests: `python hooks/test_mind_reader.py`.
