# VLDS Guide — Worked Examples

Worked traces of the loop in [SKILL.md](SKILL.md), end to end; see [reference.md](reference.md) for the vocabulary used below (the key, the index, the ledger).

## Example: a silent reuse — proceeding without asking, on the record

```text
Need: the user asks for a new script; it will write timestamped log lines.
Key:  (choose-a-date-format + formatting-preference)

Index lookup → HIT
  index_entry:
    key: (choose-a-date-format + formatting-preference)
    decision: rule
    directive: "use ISO-8601 (YYYY-MM-DD) for dates unless told otherwise"

Action: write the timestamps in ISO-8601 without asking — the user settled this before.
Ledger (appended):
    event: reused
    match: "log timestamps is a date-format choice = the configured key"
    outcome: applied ISO-8601
```

The question was skipped because the need matched a standing rule. The match is logged, not assumed — if "log timestamps" were not really covered by that rule, the ledger is where the user would catch it.

## Example: a miss — the clarifying question that fills the index

```text
Need: "add caching here." — no eviction policy named.
Key:  (choose-an-eviction-policy + design-preference)

Index lookup → MISS (no rule for this key)
Intent gate: the need is genuinely ambiguous — LRU, TTL, and size-bounded all fit.
  → ask rather than guess.

Surface once (clarifying question):
  "Cache eviction — LRU, TTL, or size-bounded? I'll remember your choice for next time."
User: "TTL, 5 minutes."

Record:
  index  ← { key, decision: rule, directive: "default new caches to TTL; confirm the duration" }
  ledger ← { event: surfaced, outcome: "TTL / 5min" }
```

The familiar clarifying-question flow — the only addition is that the answer is written to the index, so the same need is a `hit` next time and the question fades.

## Example: a miss resolved by teaching — a concept surfaced, nothing persisted

Not every miss ends in a rule. When the gap is a missing _concept_ rather than a preference, the loop teaches once and persists nothing — onboarding, rather than configuration.

```text
Need: the request will lead the model to assert "the latest version is X".
Key:  (assert-a-version-fact + version-claim)

Index lookup → MISS — and the gap is a missing concept, not a preference to set.

Surface once (teach):
  "Heads up — I treat 'the latest version is X' as a checkable claim, so I'll verify it before stating it rather than asserting from memory. Nothing to set; tell me to act natural on version facts if you'd rather I move faster."

Record:
  index  ← (unchanged — teaching persists no rule)
  ledger ← { event: surfaced, outcome: "taught: version facts are gated; offered act-natural" }
```

The concept was surfaced once and logged. If it recurs and the user wants it handled a fixed way, that ledger entry is what they promote into a rule.

## Example: a mis-match — caught and corrected from the ledger

```text
Earlier the user configured:
  index_entry:
    key: (confirm-before-deletion + side-effect)
    directive: "always ask before deleting"

Need: a refactor that will overwrite a generated file in place.
Key as matched: (confirm-before-deletion + side-effect)   ← the loop's inference

Index lookup → HIT — the key is reused without re-asking; its directive then fires: ask before overwriting.

Later the user reviews the ledger:
  ledger_entry:
    event: reused
    match: "overwrite-in-place = a destructive side effect = the configured key"
    outcome: asked before overwriting (the configured directive firing)

User: "overwriting a generated file isn't destructive — don't ask for those."

Correct → record the delta, then split the over-broad key:
  correction:
    key:   (confirm-before-deletion + side-effect)
    match: "overwrite-in-place = a destructive side effect"   # what the loop assumed
    meant: "overwriting a generated file is not destructive"  # what was actually wanted
    delta: split
  index ← (confirm-before-deletion + side-effect)        keep "always ask"
  index ← (overwrite-generated-file + side-effect)       decision: opt-out ("act natural", no directive)
```

The match was an inference — "overwrite = destructive" — that the user did not share. Nothing was lost: the reuse was on the record, and `Correct` split one over-broad key into two.

## Example: configure-on-reflection — promoting a logged moment

```text
Across a session the loop three times wrote lowercase error messages without being asked, matching a style it had inferred (a silent reuse each time, all logged).

Reviewing the ledger, the user promotes it:
  ledger (event: reused, ×3)
    → index { key: (style-error-messages + formatting-preference), decision: rule, directive: "error messages lowercase, no trailing period" }
```

A preference the loop had been inferring is lifted into an explicit rule — the dashboard filled from the audit trail, after the fact, with no in-the-moment configuration.
