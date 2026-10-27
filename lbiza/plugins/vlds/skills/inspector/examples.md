# VLDS Inspector — Worked Examples

Worked traces of the loop in [SKILL.md](SKILL.md), end to end; see [reference.md](reference.md) for the vocabulary used below (independence, the distribution, the state transitions).

## Example: CORROBORATED — independent eyes agree

```text
Inside verdict: gate CONFIRMED — "the library's retry() uses exponential backoff by default."
  (verified this turn by reading one doc page)

Stakes: load-bearing — it is going into a recommendation → escalate to the inspector.

Spawn 3 independent eyes, each blind to the original reasoning, each re-grounded in sources:
  eye A → reads the source code        → confirms: backoff is exponential
  eye B → reads the changelog + tests  → confirms: exponential since v2
  eye C → reads the API reference      → confirms: exponential, base 2

Distribution: peaked — all three corroborate, from independent sources.

State: CONFIRMED → CORROBORATED
  The verdict stands, now recorded as independently checked rather than merely asserted.
```

## Example: REJECTED — the inside verdict was rationalization

```text
Inside verdict: gate CONFIRMED — "this regex is safe against catastrophic backtracking."
  (the original reasoning talked itself into it: "the quantifiers look bounded")

Stakes: security-relevant → escalate.

Spawn 3 independent eyes, blind to the original reasoning, re-grounded:
  eye A → runs the pattern against a known ReDoS test string → catastrophic backtracking reproduced
  eye B → analyzes the nested quantifier from the source     → confirms the vulnerable construct
  eye C → checks the pattern against a linter's ReDoS rule    → flagged

Distribution: peaked — against. All three refute it.

State: CONFIRMED → REJECTED
  The "safe" verdict is overturned — self-rationalization the inside check could not catch.
  The claim is discarded, not parked as unchecked; the corrected understanding (the pattern is vulnerable) is what stands, and the pattern is replaced before anything ships.
```

## Example: CONTESTED — the eyes split, and the split is the product

```text
Inside verdict: guide match — reuse the configured rule
  (need-shape: choose-a-concurrency-model; matched to a prior "default to async" rule)

Stakes: a consequential architectural choice → escalate.

Spawn 3 independent eyes, blind to the original reasoning, re-grounded in the codebase:
  eye A → the surrounding code is I/O-bound  → async fits: agrees with the match
  eye B → most call sites are I/O-bound      → async fits: agrees with the match
  eye C → a hot path here is CPU-bound       → async is wrong here: refutes the match

Distribution: 2 agree, 1 refutes — a bare majority, which is a flat distribution, not a peak.

State: CONTESTED  (the Null Object — denied the standing of CONFIRMED)
  A 2-1 majority does NOT earn CORROBORATED: one re-grounded eye refuting on a real CPU-bound hot path is signal, not a vote to be out-counted.
  The split is surfaced, not averaged: "the async default may not fit a CPU-bound hot path here — independent reads disagree." The user decides, and may Correct the match's key.
```
