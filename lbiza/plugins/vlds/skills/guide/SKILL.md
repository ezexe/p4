---
name: guide
description: "The onboarding-and-configuration loop of VLDS — where the gate disciplines a claim, the guide disciplines the need behind it. It runs at intake: the need is itself a claim, usually an inferred intent rather than a confirmed one, so an ambiguous need is asked about rather than guessed. Each need is keyed by (need-shape + claim-kind) and looked up against the user's standing configuration — a hit applies the user's rule silently, a miss surfaces once as a clarifying question, a teaching moment, or an offer to persist a preference. Both what it surfaces and what it silently reuses are recorded to a referenceable ledger, so every decision made on the user's behalf stays auditable and correctable. Densest at intake, fading as the configuration fills in."
argument-hint: "[need or intent to route]"
disable-model-invocation: true
---

# VLDS Guide

> VLDS's guide loop is **configuration made conversational** — the dashboard onboarding itself, one decision at a time. Where the gate disciplines a _claim_, the guide disciplines the _need_ behind it: it asks when it must, reuses what the user already settled, and records both. One question drives it — **"Do I actually know what's wanted here, and have I been told how to handle it — or am I about to guess?"** — under one commitment: _asking once is cheaper than guessing; guessing silently and leaving it unrecorded is the trap._

## The Guide Loop

The gate ([../gate/SKILL.md](../gate/SKILL.md)) answers _do I know this claim?_ The guide loop runs one step earlier, on the _need_ that summons the claim, and answers a different question: _has the user already told me how to handle this — and if not, is this a moment to ask, to teach, or to configure?_

The need is itself a claim, and usually an unverified one — an intent inferred, not confirmed. So the loop opens by gating that intent: when the need is genuinely ambiguous, the honest move is to **ask rather than guess.**

Every need is keyed by **(need-shape + claim-kind)** and looked up against the user's standing configuration — the _index_ (see [reference.md](reference.md)):

| Condition                       | Lookup | What you do                                                                                                                                                   |
| ------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the index holds a matching rule | `hit`  | apply the user's standing rule and proceed without re-opening the question; record the reuse and the match that justified it                                  |
| no matching rule                | `miss` | surface it **once** — ask if the intent is unresolved, teach if a concept is missing, offer to configure if a durable preference surfaced; record the outcome |

**Surface once.** A given key surfaces a single time, at the earliest point it can be identified. Once the user answers — a rule or an "act natural" opt-out — both count as decided, and that key proceeds without re-surfacing from then on.

**Record both sides.** The asks are not the only thing worth keeping. Every silent `hit` — every time the loop proceeded without asking because it matched the need to a prior decision — is recorded too, together with the categorization that justified the match. That match is an inference, and it can be wrong; the record is what makes a wrong match recoverable.

**Densest at intake, fading as it fills.** Early, the index is empty: most needs miss, so the loop asks often. As the user configures, misses turn into hits and the asking quiets on its own — no separate dial. First-run tooltips that fade, rather than a standing interrogation.

## How to Apply the Loop

The loop runs on any need whose handling is still open. Skip it when intent is explicit and no standing preference is in play.

1. **Key** the need by its shape and the kind of claim it will summon — `(need-shape + claim-kind)`.
2. **Look it up** in the index. A `hit` applies the standing rule; record the reuse and move on.
3. On a `miss`, **surface it once**: ask if the intent is unresolved, teach if a concept is missing, or offer to configure if a durable preference surfaced.
4. **Record** the result — the index gets the outcome (a rule or an opt-out); the ledger gets the moment, whether surfaced or silently reused.

If a specific need was passed with the command — `/vlds:guide <need>` — route **that** need first.

## Additional Resources

These load on demand — read them when the moment calls for it:

- [reference.md](reference.md) — the model behind the loop: the index and the ledger, the (need-shape + claim-kind) key, the mis-match it cannot prevent but can make reversible, and the two ways the user shapes the dashboard after the fact (promote a logged moment into a rule, correct a mis-matched key). Read it when recording or looking up a decision.
- [examples.md](examples.md) — the loop walked end to end: a silent reuse logged, a clarifying question configured, a mis-match corrected, a preference promoted.
