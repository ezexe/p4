# VLDS Partition — Dispatch

One entry per message this session has addressed: how it arrived, what was done about it, and whether a later message freed it.
Consulted by the **dispatch barrier** as the thought stream forms — _is this message new, or am I answering it twice?_ — before a response is committed to.
One file per session, in the session's own store (`.claude/p4/sessions/<s8>/vlds/`): seeded on its first prompt, never poured or dated — the session directory is the session's record; a resume keeps its own; entries are never promoted to a standing rule.
The same hook stamps every message's row — `fingerprint`, `time`, `arrival` — before the model sees it; the model completes `state:` before answering and `addressed:` by turn end. A row still lacking `state:` is a message received by a session that never finished recording it: on re-arrival, treat it as `FRESH`.

States: `FRESH` (no match — address it, then record it) · `ECHO` (already addressed, unchanged — answer the delta, never the whole message again) · `SUPERSEDED` (addressed, then freed by a later message — surface the free; acting on it is a use-after-free).
When a match is uncertain, default to `FRESH`: re-answering wastes a turn, but wrongly suppressing drops the user's request entirely, and only one of those is recoverable.

One entry per message, in this shape — one field to a line, never folded or wrapped; the prompt hook writes the first three fields, the model the rest (all of it when no hook output arrived):

```yaml
- fingerprint: [the opening clause plus the ask, enough to recognize it again]
  time: [YYYY-MM-DD HH:MM]
  arrival: turn | mid-turn interleave | hook injection | summary replay | task notification | agent message
  kind: [detail-ask | submit+detail-ask — the prompt hook's, when a question about a served picker arrives; absent otherwise]
  on: [the picker it asks about — widget «title» | panel «header»; absent otherwise]
  state: FRESH | ECHO | SUPERSEDED
  addressed: [what was actually done about it]
  match: [what justified an ECHO or SUPERSEDED call]
  freed-by: [the later message that superseded it]
```

---
