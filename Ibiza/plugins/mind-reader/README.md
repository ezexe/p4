# mind-reader

A starting point: at every prompt, predict the owner's next message and the session's direction from every session's p4 vlds dispatch record, and hand both to the model while it works on the current turn.

- **Corpus:** `.claude/p4/sessions/*/vlds/dispatch.md`, the owner's own messages in time order per session.
- **Next message:** the followers of messages resembling the current one, merged and weighted; adoption tokens fill in.
- **Direction:** the earlier session whose run most resembles this one, and what it asked next.
- **Self-scoring:** each prediction is logged to `.claude/p4/sessions/<name>/mind-reader/predictions.md` and scored by the next prompt.

Resemblance is lexical token overlap; see `skills/predict/SKILL.md` for the next steps.
Depends on `vlds`, whose prompt hook writes the dispatch records.

Tests: `python hooks/test_mind_reader.py`.
