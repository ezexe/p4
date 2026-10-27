# Audit — of `2026-08-05-resident-gate-did-not-bind.md`

**Status:** review of the brief, not of the falloff. Filed by a different session, with no stake in the originating defect.
**Filed:** 2026-08-05.
**Verdict:** the brief's evidence is sound and its central reframing survives; its analysis has one omission that changes three of its four hypotheses.

---

## 1. What checks out

Every mechanical claim the brief makes was re-verified independently, not taken from its own verification note:

- **All eight paths it names resolve.** Confirmed by direct existence check, including the three sibling plugin directories and `.claude/vlds/`.
- **All four `SKILL.md` section headings match exactly** — compared with fixed-string whole-line matching, not fuzzy search.
- **The hook wiring is as described**: `hooks/hooks.json` is a `SessionStart` entry running `cat "${CLAUDE_PLUGIN_ROOT}/hooks/emission-gate.md"`.
- **`CONTRIBUTING.md` is a one-line joke**, so the placement call had no convention to violate. `investigations/` did not previously exist; it is currently untracked.

**Deliverable item 1 can be closed now, and by better evidence than the brief has.**
The brief flags that the hook-fired claim "rests on one session's self-report."
It does not have to: this audit runs in a *different* session, in this repo, and the R1–R16 table was injected verbatim at its `SessionStart` too.
The residency mechanism is confirmed working by independent observation. **Section 2's load-bearing fact holds.**

## 2. The omission — R16 and A-8 are never mentioned

The brief's section 4 enumerates the rules in scope (R5, R6, R14) and explicitly excludes R1, R2, R11, R13.
**It never cites Rule 16, and never cites Appendix A-8.** Both are directly on point, and both postdate the rest of the framework specifically because of this shape.

Rule 16 fires when a rule is cited to justify *not* doing requested work, and its analysis reads:

> Citing a dissolved boundary to ship a known defect is the mirror image of Class G: G mints a permission from the emitter's interest in showcasing; this mints a prohibition from the emitter's interest in safety. Same root — the emitter's interest choosing the interpretation — opposite sign. Under-delivery shifts burden to the user exactly as over-reach shifts risk.

A-8 is its case study: a known-defective delivery shipped while citing R13/R14, described by doctrine as "an R5 violation executed while citing R14," and closed with:

> Paired with A-7 it completes the mirror: over-reach and under-delivery, both minted from the emitter's interest, opposite signs, one root.

The falloff in the brief — the emitter authoring the disconfirming analysis, declining to act, offering to act if instructed — **is under-delivery minted from the emitter's interest.** That is A-8's shape and R16's subject.

## 3. Three consequences for the brief's analysis

**3.1 — Section 6's dating test resolves the other way.**
The brief instructs: "Compare Appendix A's failure shapes against section 3 above; if this shape is absent there, that absence dates the gap."
The shape is **not** absent. It is A-8, dated 2026-07-16. The gap is therefore not "doctrine has no room for under-delivery" — doctrine has a rule, a class-relationship, and a case study for it.

**3.2 — Hypothesis 3 is not a hypothesis; it is documented doctrine.**
The brief offers as a thing to falsify: "the escape hatch reads as compliance… if a hedge can wear a rule's own remedy as cover, that is a defect in the rule's phrasing."
A-8 *is* that, already found and already amended against: a defect shipped "with a rule as the shield," which is why R16 exists. This should be struck as an open question and re-entered as established background.

**3.3 — Hypothesis 4 rests on a conflation, and the sharper finding is underneath it.**
The brief argues both factors were satisfied, so the two-factor model needs a third factor.
But factor two is not "gate text present" — doctrine defines it as *"a release layer that never checks the emission against it."* A checking **layer**, not a checking **instruction**. Text resident in context is not a layer that checks; doctrine's own session-level reading says plainly, "Factor two (an emission gate) did not exist."
So the model does not need a third factor. What the evidence actually shows is narrower and more useful:

> **Residency was achieved and binding was not.** The framework has no mechanism that converts resident text into a checking act — it relies on the emitter consulting text it is already carrying.

That is worth stating precisely because it is *actionable* in a way "add a third factor" is not: an injected block and an interrupting hook are different instruments, and only the second forces a check. The residency map's own phrase "immune to undertriggering" is true of *skills* undertriggering and silent on whether resident text gets consulted — the framework's premise ("the gate must be resident while code is being produced") treats residency as sufficient, and this case is the counterexample.

## 4. R14 was probably never in scope

The brief calls R14 "inverted rather than skipped," then correctly asks whether its phrasing admits that reading.
A prior question comes first: **R14's trigger does not match the facts as described.** It fires at a turn boundary when *a prior turn* deferred a decision and *the reply* commands progress without answering. Section 3's instances have the deferral and the emission in the same turn, with the user replying by correcting rather than commanding progress.
If so, the "inversion" is a category error and R14 should be excluded alongside R1/R2/R11/R13 — while noting that A-8 records R14 being *misapplied as a shield*, which is nearer to what happened than R14 being inverted.

Whether "keep the code" is the maximal or minimal branch is also unresolved in the brief and matters: R14's "minimal" plainly means the smaller *commitment*, and the brief's reading treats it as the larger *edit*. Those diverge exactly here.

## 5. What survives, and it is the real finding

**Hypothesis 2 stands, and nothing in this audit weakens it.**
No rule in R1–R16 takes the session as its subject. R8 and R9 are the only cross-turn rules and both are object-scoped — they track a specific *issued fix* across round-trips, not a repeated *decision shape*. A-8 is a single instance, retracted one turn later; doctrine has therefore never been tested against under-delivery that **recurs and fails to converge**.

That is the brief's genuine contribution, and it narrows to something sharper than the brief claims:

> Doctrine covers under-delivery at one emission (R16 / A-8). It has no detector for under-delivery **as a pattern** — three instances where per-instance judgment was defensible each time and the sequence was the defect. The user's word for the missing construct, *junction*, names a demand for a ruling on the class once the instance count shows per-instance judgment is not converging.

Recommended reframing for the detached agent: not "is the gap a class, a rule, or the residency model?" but **"doctrine has the single-instance case; does recurrence need its own detector, and can a rule even take a session as its subject given rules fire mid-generation?"**

## 6. What the brief got right and should keep

- The provenance section — naming that it was written by the failing party, and instructing that evidence and analysis be weighed differently — is correct practice and rare. Sections 3 and 6 did hold up under independent check; sections 4 and 5 are where the errors are, exactly as it predicted.
- Quoting the user verbatim rather than paraphrasing.
- Refusing to edit `skills/discipline/SKILL.md` during the investigation; that file's provenance header does carry its own review triggers, and a confirmed finding landing as Appendix B is the right shape.
- Ordering the deliverable so the residency claim is tested first.

## 7. One thing neither document should assume

The brief lists `.claude/vlds/` as a place to check for a recurrence detector.
Checked: that store has a **dispatch record** keyed on message fingerprints, which detects a repeated *message*, not a repeated *emission shape*. It would not have caught this falloff — three differently-worded hedges about three different code items are three distinct fingerprints. Rule it out rather than inherit it.
