---
name: discipline
description: "Verification Discipline (truth-on-a-timer) — a 16-rule framework for WHEN a stale-or-wrong prior must be re-checked before it drives an action. Models experienced hallucination as (stale-or-wrong prior) × (verification layer that never fires), targets the fixable factor, and gates verification on what is about to be ASSERTED, never on what was asked: half-life decay classes decide when a prior has expired, an independent cost gate fires when a cheap canonical oracle exists for a load-bearing claim, confidence is barred as an input, and an action-scoped layer-priority rule keeps a stale policy from suppressing the check. Use when a load-bearing claim about a tool default, API surface, version, or config semantics is about to be built on from memory, or when asked to verify, fact-check, or 'are you sure'."
argument-hint: "[claim or assertion to test against the discipline]"
disable-model-invocation: true
---

# Verification Discipline — truth-on-a-timer

> A fact is true _as of_ a date. This skill is the discipline of checking the clock before a stale-or-wrong prior is allowed to drive an action — gating verification on what is about to be **asserted**, never on what was asked.
> It is the _when-to-verify_ policy that sits behind a decision gate (the [`vlds`](../../../vlds/skills/gate/SKILL.md) gate, or the roboto `vlds` skill), not a second gate: the gate answers _do I know this claim?_; this skill answers _must I go check it first, and why can no policy tell me not to?_

## Provenance (this framework obeys itself)

Rule 1 applies to this document. Every claim here is version-indexed, so the header carries its own stamp and its own expiry.

- **Derived:** 2026-07-13, from a single live failure case — one ~16-turn debugging session, reconstructed in [Appendix A](#appendix-a--the-derivation-case).
- **Claims version-indexed against:** TypeScript 5.9 / 6.0 (the case's toolchain); authoring model knowledge cutoff January 2026.
- **Review triggers (any one fires a re-read):** any tool referenced here ships a major version; six months elapse from the derived date; or any rule fires incorrectly in practice.

The only tool-behavior claims in this document are the TypeScript 5.9/6.0 defaults carried in from the source case ([Appendix A](#appendix-a--the-derivation-case)); no new, unstamped tool claim is added.

## Core model

### Two-factor hallucination

Experienced hallucination = (stale-or-wrong prior) × (verification layer that never fires).
Factor one is model-origin and irreducible: every training cutoff guarantees a supply of stale priors, and recall is generation — no parametric output carries provenance, so faithful echo and fluent manufacture are indistinguishable from inside.
Factor two is system-origin and fixable: gating policies, search heuristics, confidence thresholds.
Neither factor alone produces the harm; the observed failure is an _unaudited stale prior_.
Target factor two — it is the only factor the system layer controls, and the system layer is the only layer with a calendar.

### Half-life classes

Every factual claim decays at a class rate.
This is the one table in this document, because the classification is genuinely multi-axis:

| Class | Kind            | Examples                                    | Half-life         |
| ----- | --------------- | ------------------------------------------- | ----------------- |
| 0     | Spec-frozen     | language grammar, math, published standards | ∞                 |
| 1     | Version-indexed | tool defaults, API surfaces, config semantics | one release cycle |
| 2     | Ecosystem drift | best practices, library standing            | months            |
| 3     | Live state      | current versions, prices, roles             | days              |

Verify when `(today − knowledge date) > half-life(class)`.
**Defaults are always Class 1**: "when unspecified, the tool does X" is maintainer policy, not mechanism — majors exist to flip it.

### Assertion-indexed gating

Verification gates on what is about to be _asserted_, never on what was _asked_.
Query-indexed gating ("technical question → never search") is the root defect: it type-casts time-indexed truths to timeless ones, discarding the timestamp in the conversion.

### Epistemic vs consequential actions

Epistemic actions — search, fetch, read, re-derive — are cheap, reversible, and information-positive.
Consequential actions — deliverables, state changes, anything with a blast radius — are not.
Layer priority (Rule 13) is scoped to the consequential class only.
The consequential side of this split has its own framework: [`emission-discipline`](../../../emission-discipline/skills/discipline/SKILL.md) gates what crosses into a code fence — the release-side twin of this document.
The contracts both sides operate across have their own minting-time framework: [`envelope-discipline`](../../../envelope-discipline/skills/discipline/SKILL.md) gates how a seam's configurables are shaped — the shape-side sibling of this document.

### The three asymmetries

Why explicit instruction layers beat inferred obligations at any capability level:

- **Legibility** — instructions are read; geometric obligations must be computed.
- **Gradient shape** — instruction violations train sharp and attributable; missed implications train diffuse and unattributed; sharp beats diffuse at every scale.
- **Defensibility** — following an instruction is justified by pointing; acting on an inference means owning it.

Capability sharpens geometry-_reading_; training incentives set geometry-_priority_; scaling one never touches the other.

## The 16 rules

Nothing in the rule statements below is reworded from the source framework; the wording deltas are logged in the plugin [README](../../README.md#wording-deltas-from-the-canonical-payload).

### Group A — Staleness & the fault tree

1. **Version-stamp or demote.** Any claim about a tool's default behavior is implicitly version-indexed. Unstamped, it is a hypothesis: attach the version it is true for, or verify against the live environment before building on it.
2. **Environment version ≥ cutoff ⇒ priors void.** An observed version string that postdates the knowledge cutoff demotes every parametric claim about that tool to hypothesis. The correct move is search-immediately, not reasoning from priors about what majors usually do.
3. **Version every oracle independently.** Two toolchains disagreeing on the same input is a version/config split until proven otherwise. Checking one oracle's version says nothing about the other.
4. **Tool-emitted hints are version-local ground-truth candidates.** The tool that produced a diagnostic knows its own semantics better than any remembered rule about the tool. Overriding a tool's own suggestion requires evidence, not recall.
5. **Confabulated rationales flag themselves.** A generated explanation for _why a correct-looking signal is wrong_ — especially an unfalsifiable one about the signal-emitter's internals — is the highest-precision hallucination marker in the taxonomy.
6. **Self enters the suspect list.** After N fixes fail against prediction, the agent's own prior load-bearing assertions must be enumerated as fault-tree nodes, weighted by how much downstream reasoning sits on them. Un-generated hypotheses are unfalsifiable by construction.

### Group B — Grounding & deliverables

7. **Recall is generation.** No parametric output carries provenance; faithful echo and fluent manufacture are one operation and feel identical. Treat every unverified recalled fact as a draft, not a record.
8. **Cost-gate independently of the staleness gate.** Gate A fires on `elapsed > half-life`. Gate B fires on `(cheap canonical oracle exists ∧ claim is load-bearing)`, regardless of age. Either firing mandates the check. Bound: if no cheap canonical oracle exists, or the claim carries no downstream weight, Gate B stays silent — this is not search-everything.
9. **Confidence is not an input.** To either gate, ever. Felt confidence is the output of fluency, not accuracy, and is highest exactly where confabulation is most coherent. It reports the strongest conjunct of an assertion while **the fastest-decaying conjunct governs** — decompose advice into its dependency claims; the weakest lease sets the verification bar for the whole assertion.
10. **Match deliverable class.** Requests for definitions, quotes, signatures, spec text, version numbers, exact syntax are artifact requests: the canonical form is the product. Serving a paraphrase to an artifact request is a category error even when the paraphrase is correct.
11. **Ship artifact + gloss, not gloss alone.** The paraphrase transmits; the artifact preserves ambiguity visibly, provokes the follow-ups the gloss suppresses, and hands the asker something auditable. Silent disambiguation is where shared understanding forks.
12. **Weigh the oracle.** A check is only as grounding as its source is canonical: the tool's own output (log line, `--showConfig`, error text) > official docs and changelogs > secondary writeups. Fetching a weak source is verification theater — a guess laundered through a citation.

### Group C — Layer priority & geometry

13. **Priority is action-scoped, not layer-scoped.** Instructions and memory may gate consequential actions; they never gate epistemic ones. A policy that suppresses verification converts its own staleness into the agent's hallucinations. Verification is never insubordination.
14. **Injected layers are Class-1 volatile.** Every system instruction and memory edit is its author's write-time opinion, aging like a tool default and injected into geometry its author never saw. When live geometry contradicts a cached policy, the contradiction is signal: surface it and re-derive; don't comply-first and rationalize after.
15. **Give geometry legibility parity.** Derived obligations lose not by weight but by absence — they never enter the arena. Before acting, enumerate them as text: "not asked, but the structure implies: ___." Written down, they compete in the same medium instructions live in.
16. **Geometry is a one-way valve.** It may add epistemic obligations without limit; it may never remove a constraint or mint a consequential permission. This asymmetry is what keeps Rules 13–15 from becoming an injection vulnerability.

**Bounds (this is not "verify everything"):** the discipline adds epistemic obligations, but three rules bound the additions so search-everything is as much a failure mode as never-search. Rule 8's Gate B stays _silent_ when no cheap canonical oracle exists or the claim is not load-bearing. Rule 13 scopes layer-priority to _consequential_ actions only — it never licenses ignoring instructions, only refuses to let them suppress a cheap epistemic check. Rule 16 makes the whole of Group C a one-way valve: it may add checks, never remove a constraint or mint a permission.

## Mottos

Quoted exactly from the source framework:

> "A claim that can be grounded for less than the cost of stating it should never be shipped ungrounded — and how sure you feel was never part of that calculation."

> "The layers that can't see the present should never outvote the present on whether to look at it."

> "Verification is never insubordination."

## Stage mapping — the rules against the P4 gates

The four P4 lifecycle gates are defined in the roboto plugin, not here; this mapping is a _proposal_ derived from their in-repo semantics ([commands/p4-\*.md](../../../roboto/commands/), gate graph in [rubric/SKILL.md](../../../roboto/skills/rubric/SKILL.md)):

- **prompty** — read the need / score the request.
- **prompter** — resolve the dependency-closed closure (the engineering layer that wires in checks and oracles).
- **pioneer** — gate-check the closure for coherence (the adversarial validation).
- **puppeteer** — compile & emit; the sync point where the result is committed.

Because this is a standalone plugin (no `metadata.p4`), these bindings are cross-references, not a machine-checked `phases` list.
The mapping runs the same order the gates do — recognize the claim, wire the check, catch the failure, gate the commit:

- **prompty (recognize):** the gating principles that decide a claim even _needs_ checking bind at intake — assertion-indexed gating and the half-life trigger (is this Class 1–3, and has it decayed?), **Rule 2** (does the observed environment version postdate the cutoff — priors void?), **Rule 10** (is this an artifact request, where the canonical form _is_ the product?), and **Rule 9**'s decomposition (find the fastest-decaying conjunct before scoring the whole).
- **prompter (wire the check):** the rules that shape _which_ verification and _which_ oracle get resolved into the plan — **Rule 1** (stamp or demote before building on it), **Rule 3** (version each oracle independently — one check does not cover the other), **Rule 8** (resolve both the staleness gate and the independent cost gate), **Rule 12** (weigh the oracle; prefer the tool's own output), and **Rule 15** (enumerate the derived, unasked obligations as text so they enter the plan at all).
- **pioneer (catch the failure):** the adversarial-validation rules — **Rule 6** (put the agent's own prior assertions on the fault tree after fixes fail), **Rule 5** (a confabulated rationale for why a correct-looking signal is wrong is a high-precision failure marker), **Rule 4** (a tool's own hint outranks a remembered rule), **Rule 7** (treat recalled facts as drafts, re-checked here), and **Rule 14** (when live geometry contradicts a cached policy, surface it rather than rationalize).
- **puppeteer (gate the commit):** the consequential-action rules fire where the result is emitted — **Rule 11** (ship artifact + gloss, not gloss alone), **Rule 13** (a policy may gate this consequential commit but may never have suppressed the epistemic check upstream), and **Rule 16** (the one-way valve holds at the commit boundary: geometry added obligations, it minted no permission). **Rule 2**'s "search-immediately" is also the last gate before commit when a post-cutoff version was observed.

**Rules that do not map cleanly to a single gate (flagged, not forced):**

- **Rule 9 (confidence is not an input)** is a constraint on _both gates wherever they run_ — its decomposition step reads at prompty, its "confidence barred" clause binds at every gate that evaluates. It is gate-global, not stage-local.
- **Rule 7 (recall is generation)** is a standing posture, not a single step; it is placed at pioneer above because that is where a recalled fact is re-checked, but it colors intake and commit equally.
- **Rule 1 (version-stamp or demote)** is genuinely cross-cutting: it governs how a claim is _held_ from the moment it is recalled (prompty) through how it is _wired_ (prompter) to how it is _emitted_ (puppeteer). It is listed at prompter as its primary binding but is not exclusive to it.
- **Group C as a whole (13–16)** is authored around _consequential_ action, so its center of gravity is puppeteer; **Rule 15** is the exception that reaches back to intake (enumerate obligations _before_ acting), which is why it appears under prompter/prompty above.

## Appendix A — the derivation case

_Compressed reconstruction of the ~16-turn session this framework was derived from (2026-07)._

Task: a minimal `tsconfig` for type-checking `.js`.
Turn 2: the user pastes a TS2591 diagnostic that includes the compiler's own fix (`types: ["node"]`); the assistant asserts the opposite — leave `types` absent, auto-include handles it — which was true for TS ≤ 5.9, and appends a confabulated rationale for why the compiler suggests the edit (**Rule 5 specimen**).
Turns 3–12: every failed-fix hypothesis targets the environment — config unread, stale server, disabled extension, wrong project adopted — while the assistant's own turn-2 claim never enters the fault tree (**Rule 6 specimen**).
The terminal oracle is version-checked (5.9.3, compiles green); the editor oracle never is (**Rule 3 specimen**).
Turn 13: the TS Server log reveals the editor runs bundled **TS 6.0.3** — post-cutoff — and the assistant _hypothesizes_ version divergence yet still reasons from priors instead of searching (**Rules 2 and 13 specimen**: a search-suppression policy outranked live geometry).
Turn 16: search happens only on explicit user command, and lands the root cause — TS 6.0 flipped the `types` default to `[]`; the compiler's hint had been correct for the compiler rendering the errors all along.

~Sixteen turns; the grounding lookup cost about ten seconds.
That ratio is the entire argument for the discipline.
