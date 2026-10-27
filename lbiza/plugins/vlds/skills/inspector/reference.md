# VLDS Inspector — Reference

The model behind the inspector defined in [SKILL.md](SKILL.md). Load this when you need to judge whether a check is genuinely independent, read the spread of its perspectives, or transition a verdict's state. The loop in `SKILL.md` is self-sufficient for routing a verdict; this file explains what makes the outside eye trustworthy.

## What the Inspector Reconstructs

The gate's limit is that a model has no introspective access to its own weights — and **calibrated confidence lives in those weights.** A model can be fluent and confidently wrong because it cannot reliably read off how sure it should be. The inspector's purpose is to rebuild that missing signal **from the outside**: the spread of independent perspectives is the confidence distribution the model cannot introspect. The independent eyes play the role of the logits — the stand-in, reconstructed from outside, for a signal the model cannot read off itself. This is the gate's epistemic limit answered the only way it can be — not from inside, where the access does not exist, but from outside, where it can be reconstructed.

## Independence: Re-grounding, Not Re-reasoning

An outside eye is only worth spawning if it is actually independent. Two things make it so:

- **Blind to the original chain.** The perspective sees the claim or verdict, never the reasoning that produced it. Shown the chain, it anchors — it rationalizes alongside the original instead of testing it.
- **Re-grounded in sources, not shared memory.** The strong lever. A perspective that merely re-reasons shares the base model's parametric priors, so its errors correlate with the original's — agreement means little. A perspective that re-derives the verdict from external sources — the way retrieval-augmented generation pins facts a model would otherwise guess — anchors to ground truth instead, and its errors decorrelate.

This is why corroboration is not a vote count: ten perspectives that re-reason from the same priors are one perspective wearing ten hats; three that re-ground in independent sources are three.

## The Distribution and the Set

The perspectives' verdicts are read by borrowing two forms the model cannot compute on itself, reconstructed from outside:

- **The distribution (a softmax read from outside).** A model's internal softmax over factual certainty is unreliable and un-introspectable; the inspector rebuilds it as the spread of independent posts. A peaked spread is high external confidence; a flat one signals the knowledge gap directly — the flatness _is_ the divergence.
- **The set, not the point (a conformal report).** The inspector does not output one false-precise verdict. It reports the set of verdicts the eyes support, and the set **widens as they disagree** — a clean peak is a narrow, confident set; a split is a wide one. The width communicates the lack of agreement honestly, the way a humble prediction interval widens on messy data.

Both are borrowed as _form_, not arithmetic: the inspector is not computing probabilities, it is reconstructing the shape of a confidence signal the model cannot produce internally. The independent eyes are the only place that shape can come from.

## The State Transition

A verdict checked from outside changes state — the gate's own State Pattern extended one layer. The inspector runs on either input lineage, a gate `CONFIRMED` claim or a guide `match`, and routes it to one of three states:

```text
gate  CONFIRMED ──inspector──▶ CORROBORATED   eyes corroborate → earned confidence
                          ──▶ REJECTED       eyes refute      → the CONFIRMED is overturned (it was wrong)
                          ──▶ CONTESTED      eyes split       → surfaced, held with its disagreement
guide match     ──inspector──▶ CORROBORATED   the match holds
                          ──▶ REJECTED       the match was wrong → Correct the key (see the guide)
                          ──▶ CONTESTED      surfaced for the user to settle
```

`CORROBORATED` is earned confidence — checked, not merely asserted. `REJECTED` does **not** send the refuted claim back to `PENDING` as if it were merely unchecked — it was checked and lost. The overturned claim is discarded; what re-enters the gate fresh, as `PENDING`, is the _corrected_ understanding, if there is one. A refuted guide match is fixed at its source — `Correct` the key. `CONTESTED` is the **Null Object** of the set: an explicit, safely-handled "no independent consensus," denied the standing of `CONFIRMED` rather than waved through — like an auth system refusing an unknown identity rather than letting it pass.

## The Limit: Independence Is Partial

The gate said certainty needs an independent eye. The inspector has to say the next true thing: **independence among instances of one model is only partial.** They share a base; their errors stay correlated even when re-grounded, because they read and interpret sources through the same priors. So a peak is evidence, not proof, and the inspector **raises confidence without manufacturing certainty.** It reconstructs the calibration the model cannot reach; it does not become the ground truth. This is why `CONTESTED` surfaces rather than resolves, and why `CORROBORATED` is recorded as _checked_, not as _true_.

## Relationship to the Gate and Guide

The four instruments are one loop, each refusing to treat an inference as fact at a different point. The gate asks _is this claim known?_ and routes it on epistemic status. The guide asks _has this need been configured?_ and routes it on hit/miss. The gc asks _is what I stored still alive?_ and routes recalled state on provenance-liveness. The inspector asks _would an outside eye agree?_ and routes the others' verdicts on independent corroboration. The gate and guide run from the inside, where the floor can be raised but the blind spot cannot be seen; the inspector is the one instrument that steps outside — which is exactly why it is the only one that can deliver corroboration, and exactly why its own independence is bounded.

## What it's an instance of

The inspector is the **Blackboard pattern**: several independent knowledge sources posting to a shared board and converging on a picture no single one holds. It composes the forms developed in the sections above — the **State Pattern** (extended from the gate), the **Null Object** (`CONTESTED`), **retrieval-augmented grounding** (RAG, the independence lever), an externally-read **softmax** (the distribution), and a **conformal** set (the widening report) — each a standardized convention.
