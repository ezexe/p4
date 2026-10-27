# verification-discipline — truth-on-a-timer

A standalone plugin holding one framework: **Verification Discipline**, the _when-to-verify_ policy that decides whether a stale-or-wrong prior gets to drive an action before it is checked.

Its single skill is [`skills/discipline`](skills/discipline/SKILL.md) — the provenance header, the core model, the 16 rules (three groups), the three mottos, a proposed mapping onto the P4 gates, and the live failure case the whole thing was derived from.

## Where it sits

It is a sibling of the [`vlds`](../vlds) plugin, not a part of it, and it is deliberately **not** a P4 skill inside [`roboto`](../roboto):

- **vlds** answers, per claim, _do I know this?_ — routing to `CONFIRMED` / `PENDING` / `HEDGED`.
- **verification-discipline** answers the meta-question behind that gate: _when must the gate fire, which conjunct sets the bar, and why can no cached policy tell it not to look?_ It is the firing policy behind the gate, not a second gate.

Because it is standalone it carries no `metadata.p4`, so its **stage mapping is a prose cross-reference** to the four P4 gates defined in `roboto` (`prompty → prompter → pioneer → puppeteer`), not a machine-checked `phases` binding.
That is the acknowledged tradeoff of shipping the framework as its own self-contained, self-obeying plugin rather than as a roboto skill: the framework stays a canonical document that "obeys itself," at the cost of each rule's placement being asserted rather than validated.
Since roboto 0.0.2, roboto's `p4.py` checks the mapping from roboto's side: roboto declares this plugin as a dependency, every gate the section opens a bullet with must be a P4 gate, and each roboto skill that binds this plugin must hook at least one of those gates.
Which rule sits at which gate stays this document's prose.

## The framework obeys itself

Per its own Rule 1, the skill opens with a provenance header carrying its stamp and expiry:

- **Derived** 2026-07-13, from the single failure case in the skill's Appendix A.
- **Version-indexed against** TypeScript 5.9 / 6.0 and an authoring model cutoff of January 2026.
- **Review triggers:** any referenced tool ships a major; six months elapse; or any rule fires incorrectly in practice.

## Install

Load it with `claude --plugin-dir ./lbiza/plugins/verification-discipline` (repeat the flag for other plugins).
As of Claude Code circa 2026-07, `--plugin-dir` loads the plugin live from disk each session, so there is no separate install or update step — but by this framework's own Rule 1 that is a Class-1 (version-indexed) claim about the loader's default behavior, stamped here rather than asserted as timeless: if a later Claude Code major changes plugin loading, verify against your version.
The skill is **direct-invoke only** (`disable-model-invocation: true`, matching the vlds instruments) — reach it with `/verification-discipline:discipline`, optionally passing a claim to test against the discipline.

## Wording deltas from the canonical payload

The 16 rule statements, the core-model prose, the three mottos, and the half-life table are reproduced **verbatim** from the source framework; markdown formatting (bold leads, one-sentence-per-line prose, the table, list grouping) is not a wording change.
Everything the plugin _added_ around that canonical text is logged here:

- **Provenance header** — added (mandated by the integration brief and by Rule 1); its three facts are transcribed from the brief.
- **Skill intro blockquote** — added framing: positions the skill as the _when-to-verify_ policy behind the vlds gate. No rule semantics touched.
- **"The only tool-behavior claims…" line** — added, to satisfy Rule 1's self-application (declares that no new unstamped tool claim was introduced).
- **Half-life table** — reproduced verbatim; one added sentence ("This is the one table in this document, because the classification is genuinely multi-axis") frames why it is the single permitted table.
- **"Bounds (this is not 'verify everything')" block** — added after the rules. It restates, without altering, the bounds already inside Rules 8, 13, and 16, to give the bidirectional (when-it-fires / when-it-doesn't) framing the brief asked for on Rules 8 and 13. No rule text was edited to do this.
- **Stage mapping** — added in full: this section is a proposal, not part of the canonical payload. P4 gate semantics are derived from the roboto plugin, not from the source framework.
- **Appendix A** — reproduced from the payload's compressed case; the only change is layout (one event per line, rule-specimen callouts bolded). Wording is unchanged.
- **Section headings and cross-reference links** — added for navigation.
- **Emission-discipline cross-reference** — one line added (2026-07-16) under "Epistemic vs consequential actions" pointing to the sibling [`emission-discipline`](../emission-discipline) plugin, which gates the consequential side of that split (what may be _released_ into a code fence). No rule semantics touched.
- **Envelope-discipline cross-reference** — one line added (2026-07-22) under "Epistemic vs consequential actions" pointing to the sibling [`envelope-discipline`](../envelope-discipline) plugin, which gates the minting side: how a seam's configurables are shaped before either twin operates across the contract. No rule semantics touched.

No rule's _wording_ was changed.
No claim's _semantics_ were altered.
Two consolidation decisions from the source (promoting the gating principles — assertion-indexed gating, half-life classes, defaults-as-Class-1, fastest-decaying-conjunct — into the Core model, and embedding the conjunct rule inside Rule 9) were carried over as the payload delivered them; net 16 rules, nothing dropped.
