---
name: orchestration
description: The runtime puppeteer reasoning lifecycle — the sequencer that wires the other skills into one pass (RECEIVE → SCAN → BREAK → PLAY → COMPILE → TEST → SYNTHESIZE → POST), forks an under-determined request at BREAK into parallel puppeteered branches (each a fresh prompter-prompt reading), plays each branch through the four lenses, then re-merges them at SYNTHESIZE so only a genuinely unresolvable fork ever surfaces to the user. Use whenever a request is under-determined, multi-interpretation, or consequential enough that more than one reading must be carried in parallel rather than guessed between. Sequences identity, vlds, bias-patterns, templates, and the exploration skills; owns the timing and the fork/merge, not their mechanisms.
when_to_use: "Trigger when one reading would have to guess past a real ambiguity, when bias-patterns hands control to BREAK with an uncorrectable pattern, on 'consider both / weigh the options / what are the ways', or any deep-exploration ask that warrants carrying parallel branches to a merge instead of committing to one."
metadata:
  p4:
    type: skill
    phases: [prompter, pioneer, puppeteer]
    depends_on: []
    optional_depends_on: [vlds, bias-patterns, templates, isomorphic-operations, sjc-indexer, activation, persistence, vlds:inspector, flight-ops:flight-ops]
    interface:
      domains: [lifecycle_orchestration, branch_forking, branch_synthesis, run_sequencing]
      capabilities: [puppeteer_lifecycle, break_fork, parallel_branch_play, branch_compile, branch_test, cross_branch_merge, unresolvable_fork_surfacing, physical_virtual_reconciliation]
    hooks:
      on_prompty: []
      on_prompter: [stage_branches]
      on_pioneer: [fork_at_break, dispatch_branches]
      on_puppeteer: [play_branches, compile_branches, test_branches, merge_at_synthesize, emit_at_post]
    tiers: [full]
---

# Orchestration Skill

> The sequencer the puppeteer lifecycle runs: it owns the _order_ of the steps and the BREAK fork / SYNTHESIZE merge, not the mechanism each step delegates to.
> Where `rubric` _selects_ a closure and the `roboto` agent _drives_ it, `orchestration` _runs_ it — and forks it into parallel branches when a single reading would have to guess.

## What This Skill Is

The instance already has a skill for almost every step of how it answers: `bias-patterns` owns the bias scan, `identity` owns the four lenses, `vlds` owns verification, `templates` owns formatting.
What it has lacked is the skill that _wires those steps into one ordered pass_ and that does the two things no other skill does: **fork** an under-determined request into parallel readings, and **merge** those readings back into a single answer.
`orchestration` is that connective tissue.

It is deliberately a **sequencer**, not a re-implementation.
Every step below names the skill it hands off to; orchestration owns the timing and the fork/merge, never the mechanism.
`rubric` row 4 already lists "orchestration" as the marginal capability of the `full` closure — this skill is what that reference points at.

## The Lifecycle (run in this fixed order)

```text
RECEIVE    → take the request in under the resolved closure and the active mode
SCAN       → run the pre-response bias scan                       (delegates: bias-patterns)
BREAK      → fork into parallel branches when one reading would have to guess
PLAY       → run each branch through the four lenses              (delegates: identity, rubric per branch)
COMPILE    → assemble each branch's Claude / Claudio / Claudius takes + a decision-gate hand-off
TEST       → route each branch's load-bearing claims through the gate  (delegates: vlds)
SYNTHESIZE → merge the branches, then run ALIGN → DIVERGE → VERIFY → SYNTHESIZE across them (delegates: identity, vlds)
POST       → emit through the response contract; surface any unresolvable fork as Clarification (delegates: templates); signal persistence; return to mode (defer: activation)
```

The order is fixed because each step feeds the next: the scan localizes ambiguity, the fork carries it, the branches resolve it, and the merge settles it.

## BREAK: the fork (not a human pause)

A fork fires when carrying a single reading forward would mean guessing past something real:

- `bias-patterns` hands control to BREAK with a fired-but-uncorrectable pattern.
- A load-bearing detail is missing (the `context_starvation` case) and a confident default would silently become the foundation.
- The request admits two or more genuinely viable readings.

Each option becomes a **fresh prompter-prompt**, dispatched as a parallel puppeteered branch — P4 parallel mode.
BREAK is a fork, not a blocking pause: the run does not stop and wait for the user; it plays the branches out and surfaces only a fork that survives the merge.

**Boundary with `activation`.** BREAK has two faces.
`orchestration` owns the _interpretation_ fork (which reading of the request to pursue).
`activation` owns the _action_ INTERRUPT (whether a side effect may fire).
This skill never gates actions itself — when a branch wants to act, it defers to `activation`.

## PLAY: running the branches

Each branch runs the four lenses (`identity`) under its own resolved closure — `rubric` is re-entered per branch, because each branch is a fresh prompter-prompt.
The set of branches is bounded by what is actually distinct, not by a fixed number: per the instance's strip-fake-precision rule there is no baked-in branch count, and new branches stop being spawned when new readings stop being distinct.

A branch played out as an agent is an `orchestration-branch` flight (the flight-ops plugin's `flight-ops:flight-ops`): its brief carries the line `flight: orchestration-branch`, and its landing is material for the merge, never an action — a branch that must act defers to `activation`.

## COMPILE: assembling a branch

For each branch, assemble its Claude / Claudio / Claudius takes and stage the decision-gate hand-off for its load-bearing claims.
COMPILE does not format the final answer — that is `templates`.
It produces the per-branch material the merge will consume.

## TEST: validating a branch

Route each branch's load-bearing claims through the gate the `vlds` skill binds: `CONFIRMED` / `PENDING` / `HEDGED`.
A branch whose central claim is `PENDING` is held, not dropped — it carries that claim into the merge, where it is verified or surfaced with its hedge intact.

## SYNTHESIZE: the cross-branch merge

Merge the surviving branches, then run Roboto's `ALIGN → DIVERGE → VERIFY → SYNTHESIZE` across them.
That micro-loop belongs to `identity`; orchestration calls it _across branches_ rather than within a single one — it does not restate it.
SYNTHESIZE also reconciles the physical half of memory against the virtual claims (`vlds`): what the pooled store entries and the sources read actually back, versus what is still only claimed.
Converging branches collapse to one answer.
A divergence the gate cannot settle, on a verdict the stakes warrant, goes to the vlds plugin's inspector (`vlds:inspector`): `CORROBORATED` collapses it, `REJECTED` drops the branch that rested on it, and `CONTESTED` is the only thing that survives to be surfaced.

## POST: emit

Emit through the `identity` response contract at the audit level `templates` selected.
If the branches did not converge and the fork is genuinely unresolvable, surface it as a `templates` **Clarification** (reason + options + default) — the one case in which the user sees the fork at all.
Running as a subagent, roboto puts that Clarification in the report's hand-back, and the caller serves it to the owner.
Hand `persistence` a reusable branch outcome as a store proposal, and return to the `activation` mode.

## Worked Example

```text
Request: "make the pipeline faster."  (no metric named → under-determined)

SCAN (bias-patterns)  context_starvation fires: "faster" has no metric; a single
                      default (latency) would silently become the foundation.
BREAK                 fork two readings, each a fresh prompter-prompt:
                        branch A — "faster" = lower p99 latency
                        branch B — "faster" = higher throughput
PLAY (identity×2)     run the four lenses on each branch under its own closure.
COMPILE               branch A → batch-flush is latency-bound; branch B → writer is
                      throughput-bound. Each stages its decision-gate hand-off.
TEST (vlds)           branch A's "flush dominates p99" → verifiable, verified → CONFIRMED.
                      branch B's "writer caps throughput" → verifiable, not yet → PENDING.
SYNTHESIZE (identity) the two readings do NOT converge on one fix and VLDS cannot settle
                      which metric the user means.
POST (templates)      surface the fork as Clarification:
                        Reason:  "faster" could mean latency or throughput — the fix differs.
                        Options: (a) cut p99 latency  (b) raise throughput ceiling
                        Default: optimize p99, since the last report cited slow responses.

Had both branches converged on the same change, SYNTHESIZE would have collapsed them
to one answer and the user would never have seen the fork.
```

## Relationship to the Lifecycle and Other Skills

- **identity** (always-on base). orchestration runs the macro-lifecycle and the _cross-branch_ merge; identity owns the four lenses, the response contract, and the _per-branch_ synthesis micro-loop. orchestration calls identity at PLAY and SYNTHESIZE; it never redefines them.
- **rubric** (always-on base). rubric selects a closure once, up front; orchestration runs that closure over time and re-enters rubric for each forked branch. Selection is rubric's; sequencing is orchestration's.
- **vlds** (optional). orchestration decides _when_ the gate fires (TEST, and VERIFY inside the merge) and reconciles physical vs virtual; the gate, provenance, and tiers stay in the vlds plugin, which the `vlds` skill binds, and a contested merge escalates to the plugin's inspector (`vlds:inspector`).
- **bias-patterns** (optional). The cleanest seam: bias-patterns _is_ SCAN and explicitly "hands control to BREAK"; orchestration is the recipient of that hand-off.
- **templates** (optional). orchestration decides which outcome surfaces (one answer vs. an unresolvable fork); templates renders it, and its Clarification format is exactly the BREAK that orchestration produces.
- **isomorphic-operations / sjc-indexer** (optional). orchestration schedules _when_ and _in which branch_ the bounded loop or a deep index pass runs; the loops themselves stay in those skills.
- **activation** (optional). orchestration owns the interpretation fork; activation owns the action INTERRUPT and the mode dial. Two faces of BREAK; this skill defers every side effect to activation.
- **persistence** (optional). orchestration never writes memory; at POST it routes a reusable branch outcome to persistence as a candidate.

> **Name note.** The `/p4-puppeteer` _command_ is runtime closure _registration_ (it adds a `rubric` row + the members' `tiers`).
> This _skill_ is the runtime reasoning _lifecycle_.
> They share the "puppeteer" concept but are different things — do not conflate them, and do not add a third sense of the word.

This skill formalizes the always-on "## Orchestration" prose in `agents/roboto.md` into a JIT-pulled skill, so the heavy fork machinery loads only on `full`-closure requests instead of sitting in the always-on base.

## Dependencies & Downstream

- **`depends_on`: `[]`.** orchestration's only hard prerequisites are the always-on base — `identity` (the lenses + contract it sequences) and `rubric` (re-entered per branch) — which are implicit and declared once in the `roboto` agent, so neither is listed here.
- **`optional_depends_on`** degrade gracefully: with fewer skills loaded the lifecycle runs as a single-branch pass — RECEIVE → (scan if present) → PLAY one reading → emit — rather than failing.
- **Configuration tiers:** ships in **`full`** only. Forking is the heaviest reasoning mode, and `rubric` row 4 already scopes "orchestration" to the `full` closure; adding this skill resolves that previously dangling reference. It is deliberately absent from lower tiers — a trivial request that forked would violate the JIT, strip-ceremony posture.
