---
name: inspector
description: "The independent-eye instrument of VLDS — the outside check the gate and guide structurally cannot be, because a perspective cannot audit its own blind spot. It takes a verdict reached from the inside (a gate CONFIRMED, a guide match) and re-examines it through independent perspectives, each blind to the original reasoning and re-grounded in sources rather than shared memory so their errors decorrelate. Their spread is read as a distribution, not a vote: peaked agreement leaves the verdict CORROBORATED, peaked refutation REJECTED, a flat split CONTESTED — surfaced, not passed as fact. It reconstructs from outside the calibrated confidence a model cannot read off its own weights: it raises confidence, it never manufactures certainty."
argument-hint: "[verdict or claim to check independently]"
disable-model-invocation: true
---

# VLDS Inspector

> VLDS's inspector is **the outside eye made procedural** — the second perspective the gate and guide cannot be, because neither can audit its own blind spot from the inside. One question drives it — **"Would a perspective that never saw my reasoning, working from the sources, reach the same verdict?"** — under one commitment: _confidence is earned by independent corroboration, not by re-reading my own conclusion until it sounds right._

## The Inspector

The gate ([../gate/SKILL.md](../gate/SKILL.md)) asks _do I know this claim?_ The guide ([../guide/SKILL.md](../guide/SKILL.md)) asks _how should I handle this need?_ Both answer from the inside — they raise the floor, but neither catches self-rationalization, because the reasoning that produced a verdict cannot be the one to refute it. The inspector is the outside eye: it takes a verdict already reached and re-examines it through perspectives that never saw how it was reached.

Each perspective is made independent two ways: it is **blind to the original chain** (it sees the claim, not the reasoning behind it, so it cannot anchor), and it **re-grounds in external sources rather than shared memory** — re-deriving the verdict from external ground truth is what makes its errors decorrelate from the original's.

The perspectives' verdicts are read as a **distribution, not a vote** — the shape decides the state:

| The independent eyes…                | State          | What you do                                                                                                    |
| ------------------------------------ | -------------- | -------------------------------------------------------------------------------------------------------------- |
| corroborate it (agreement is peaked) | `CORROBORATED` | let the verdict stand; record that it was independently checked                                                |
| refute it (refutation is peaked)     | `REJECTED`     | overturn it — the verdict was rationalization; discard the claim (re-gate any correction) or correct the match |
| split (the distribution is flat)     | `CONTESTED`    | surface the disagreement; hold it as contested rather than letting it pass as confirmed                                                      |

**Read the shape over the count.** A bare majority is a flat distribution — low confidence — and routes to `CONTESTED`, never `CORROBORATED`. Only a genuine peak earns a verdict, and a peak is only as trustworthy as the eyes were independent: corroboration among perspectives that quietly share a bias is not corroboration.

**`CONTESTED` is a safe default, not a failure.** A contested verdict is held with its disagreement attached — it does not silently pass as confirmed, the way an unknown identity is denied rather than waved through. The split itself is the product: surfaced, not averaged away.

**It runs on the verdicts that earn it.** The inspector is a fan-out of independent perspectives — too costly for everything. Spend it where a verdict is load-bearing and either high-stakes or borderline; let the inside floor carry the rest.

## How to Apply the Inspector

The inspector runs on a verdict already reached from the inside, when the stakes or the closeness of the call warrant an outside eye.

1. **Take** the inside verdict — a gate `CONFIRMED` or a guide `match` — as the thing to re-examine, not to defend.
2. **Spawn** independent perspectives: each blind to the original reasoning, each re-grounded in sources, each framed to attack from its own angle (refute it, re-derive it, stress a distinct failure mode). With the flight-ops plugin installed, each perspective is a `vlds-inspector-perspective` flight: its brief carries the line `flight: vlds-inspector-perspective`, and a perspective that changed anything is void.
3. **Read the distribution** of what they post back — peaked or flat, for or against.
4. **Transition the verdict** to `CORROBORATED`, `REJECTED`, or `CONTESTED`, carrying how peaked the agreement was as its confidence.
5. **Write back:** a `REJECTED` verdict overturns the claim — it is discarded, and any corrected version re-enters the gate fresh as `PENDING` — or corrects the guide's match; a `CONTESTED` one is surfaced with its split intact.

If a specific verdict was passed with the command — `/vlds:inspector <verdict>` — check **that** one first.

## Additional Resources

These load on demand — read them when the moment calls for it:

- [reference.md](reference.md) — the model behind the inspector: what it reconstructs (the calibration the model cannot introspect), independence as re-grounding rather than re-reasoning, the distribution-and-set read, the state transitions, and the limit that independence among instances of one model is only partial. Read it when judging whether a check is genuinely independent or reading its spread.
- [examples.md](examples.md) — a verdict walked through end to end: corroborated, rejected-and-re-gated, contested-and-surfaced.
