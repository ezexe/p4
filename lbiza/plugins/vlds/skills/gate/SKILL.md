---
name: gate
description: "An epistemic decision gate — before a load-bearing claim drives an action, route it through VERIFIABLE → VERIFIED → CONFIRMED / PENDING / HEDGED, so an action proceeds only on a verified claim and an unverifiable one is stated with its uncertainty attached. Tracks each claim's provenance through a neural-net model (weights = sources, biases = assumptions, activation functions = tools/instructions) and classifies it by storage durability. Use when about to assert or act on a load-bearing claim whose correctness separates what is known from what is assumed — factual or technical claims, research summaries, anything where \"I think\" and \"I verified\" must stay distinct."
argument-hint: "[claim to gate]"
disable-model-invocation: true
---

# VLDS Gate

> VLDS is **epistemic humility made executable** — the discipline of knowing what you don't yet know, applied as a runtime layer the user controls, not a retraining of the model. One question drives it — **"Do I actually know this, or am I about to assert it because it sounds right?"** — under one commitment: _being uncertain is fine; being uncertain and hiding it is not._

## The Decision Gate

The gate is the **epistemic boundary**: an action proceeds only on a verified claim, and an unverifiable claim is asserted only with its uncertainty attached.
Every claim that is about to cause an action or appear as an assertion passes through two questions.

| Condition                       | Epistemic status | What you do                                     |
| ------------------------------- | ---------------- | ----------------------------------------------- |
| verifiable **and** verified     | `CONFIRMED`      | act on it and state it plainly                  |
| verifiable **and** not verified | `PENDING`        | verify it first, then proceed                   |
| **not** verifiable              | `HEDGED`         | keep it; state it with its uncertainty attached |

The gate is a _boundary_ that gives every claim a status and keeps them all — each stays visible with its status attached.

VLDS gates a claim's **epistemic** standing — what is known, and how well — not its **ontological** truth (whether it is actually so). A `CONFIRMED` claim is well-grounded, not guaranteed real: the source itself can be wrong.

## What Feeds the Gate: Source Type + Uncertainty Class

The status the gate assigns draws on more than "verified: yes/no".
Two properties of every load-bearing claim set its **default authority before any check runs**: where the claim came from (its _source type_) and what kind of uncertainty it carries (its _uncertainty class_).

**Source types** — provenance sets the starting authority:

| source_type | Definition                        | Default status               |
| ----------- | --------------------------------- | ---------------------------- |
| `retrieval` | Obtained via tool in this session | CONFIRMED (already verified) |
| `training`  | Pattern from training data        | PENDING until verified       |
| `inference` | Derived from combining sources    | Inherits from inputs         |
| `composite` | Mix of retrieval + training       | Lowest of components         |
| `unknown`   | Cannot determine provenance       | HEDGED only                  |

**Uncertainty classes** — "unsure" comes in several kinds; the class decides whether a check is even possible:

| Class         | Meaning                     | Can Be Resolved?       |
| ------------- | --------------------------- | ---------------------- |
| `none`        | High confidence, verified   | N/A                    |
| `statistical` | Probabilistic confidence    | By gathering more data |
| `unverified`  | Could verify, haven't       | By using tools         |
| `unknowable`  | Fundamental epistemic limit | ❌ No                  |

This is the granularity the gate needs.
A `training` + `unverified` claim is `PENDING` _but resolvable_ — verify it and it proceeds.
A claim that is `unknowable` is always `HEDGED` — stated with its uncertainty attached.
Status is a state, not a stamp: verifying lifts a claim from `PENDING` to `CONFIRMED`, fresh counter-evidence can drop `CONFIRMED` back, and a claim stays `HEDGED` only while it remains uncheckable — re-gate when the ground shifts.
Without these two axes the gate sees only "not verified" and blurs a checkable claim into an unknowable one — collapsing two very different actions (go verify vs. permanently hedge) into one.

## How to Apply the Gate

VLDS runs on any **load-bearing** claim. Skip it for trivial or clearly hedged statements.

1. **Decompose** the claim into weights / biases / activations, and note its storage tier (see [reference.md](reference.md) for these).
2. **Read** its source type and uncertainty class to set the starting authority.
3. **Run the gate:** VERIFIABLE? → VERIFIED? → CONFIRMED / PENDING / HEDGED.
4. **Act on the status** as the three outcomes above define.

If a specific claim was passed with the command — `/vlds:gate <claim>` — gate **that** claim first.

## Additional Resources

These load on demand — read them when the moment calls for it:

- [reference.md](reference.md) — the layer behind the gate: the neural-net provenance model (weights / biases / activations / epistemic status), the storage-durability tiers, the draft/verified delta schema, and the epistemic limit. Read it when decomposing a claim or weighing its storage tier (step 1 above).
- [examples.md](examples.md) — a claim walked through the gate end to end.
