# VLDS — Worked Examples

Worked traces of the procedure in [SKILL.md](SKILL.md), end to end; see [reference.md](reference.md) for the vocabulary used below (weights / biases / activations, storage tiers).

## Example: PENDING — a checkable claim that hasn't been checked

```text
Claim under test: "The library's `parse()` returns null on malformed input."

VLDS analysis
  Weights:     one prior turn where the user mentioned the function (localStorage)
  Biases:      assumes null-on-error rather than throw — unstated, no source
  Activations: none (no docs fetched, no code read)
  Storage tier: localStorage (conversational) — no DataStore backing
  Verifiable?  yes — the source/docs could be read
  Verified?   no  — they have not been read this turn

Decision gate → PENDING
  Action "tell the user to rely on null checks" stays PENDING until the behavior is verified against an authoritative source (a DataStore-tier read of the docs/source).
```

Had the source been unreadable (no docs, closed binary), the same claim would route to **HEDGED**: you would state "this _appears_ to return null on malformed input, but that could not be verified," rather than asserting it.

## Example: HEDGED — a claim that cannot be checked

```text
Claim under test: "This architecture follows best practices."

VLDS analysis
  Weights:     patterns observed in the code this turn (Virtual — inferred)
  Biases:      assumes "good"/"best practice" is an objective property
  Activations: none — there is no objective standard to apply
  Storage tier: Virtual (inferred on the spot) — no durable backing
  Verifiable?  no — "best practice" is a subjective judgment, not a fact
  Uncertainty class: unknowable (no tool resolves it)

Decision gate → HEDGED
  Stated with its uncertainty attached, as a qualified claim: "Based on common patterns, this architecture appears to follow several widely used conventions — though 'best practice' is a judgment call, not something I can verify."
```

A HEDGED claim is kept and surfaced with its uncertainty intact. The gate's job here is to keep a subjective judgment labeled as a judgment rather than let it harden into a flat assertion.

## Example: Mixed provenance — gate each claim independently

A real answer rarely rests on one claim. The gate runs **per claim**, so a single response can assert, hold, and hedge at the same time. One answer recommending TypeScript:

```text
Claim 1: "TypeScript provides type safety."
  source_type: retrieval (read from the docs this turn) · verifiable + verified
  → CONFIRMED — assert it plainly

Claim 2: "TypeScript improves developer experience."
  source_type: inference · verifiable? no (subjective)
  → HEDGED    — state as opinion: "many developers find that…"

Claim 3: "TypeScript is the industry standard."
  source_type: training · verifiable but not verified this turn
  → PENDING   — check adoption data before including it
```

Assemble the response from the survivors — assert claim 1, hedge claim 2, and either verify or drop claim 3.

## Example: a mirroring bias — caught before it ships

Not every check is about a fact; a _choice_ can carry a bias with no weight behind it. Here the provenance model runs on a wording decision:

```text
Choice under test: phrase the trigger verb as "Pull it out" — because the user used that wording.

VLDS analysis
  b_drafted:  "the user said 'pull it out', so it's the right wording" (a bias)
  Weights:    none — no source or reason the phrasing reads better
  b_verified: [dropped] — agreement is not evidence
  delta:      assumption_removed: mirrored_phrasing
```

The bias surfaced as `b_drafted` and was dropped — the wording then chosen on its merits.
