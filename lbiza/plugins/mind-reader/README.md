# mind-reader

A side agent, detached from the session, that predicts what the owner will say next and learns from how it scored.

- **Detached:** the prompt hook spawns a background watcher and prints nothing; the session answers uninterrupted.
- **Rotating draft:** the watcher re-predicts while the turn runs, in `.claude/p4/sessions/<name>/mind-reader/draft.md`.
- **Frozen at the turn's end:** the Stop hook freezes the prediction; the owner's next message scores it.
- **Evolving:** each source (`follow`, `progress`, `direction`, `adopt`) carries a weight in `.claude/p4/mrindex/model.json`, moved after every score; `history.tsv` keeps every score.
- **gc partition:** the scored predictions land in the session's vlds `mind-reader.md`, an object store of the keyspace poured past its budget.
- **gc safeguard:** `.claude/p4/vindex/holds.tsv` holds the entries the owner's predicted direction leans on; the vlds light pass and judged sweep skip them until they expire.

Owner, never the AI: the AI's actions are read only as what the owner will react to. No model, no network, nothing written into the conversation.

Depends on `vlds` ≥ 0.0.61, which knows the partition and the holds.
Tests: `python hooks/test_mind_reader.py`; status: `python hooks/mind_reader.py status`.
