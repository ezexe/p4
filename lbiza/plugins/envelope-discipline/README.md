# envelope-discipline — futures-land-as-fields

A standalone plugin holding one framework: **Envelope Discipline**, the _minting-time_ policy that decides how a seam's configurables are shaped — one named options envelope from birth, null-ask defaults, futures landing as fields.

Its single skill is [`skills/discipline`](skills/discipline/SKILL.md) — the provenance header, the core model (two-factor calcification, the temporal identity, the family-reveal test, null-ask defaults, shape-not-speculation), the 12 rules (three groups), the three mottos, a proposed mapping onto the P4 gates, and the live minting failure the whole thing was derived from.

## Where it sits

It is a sibling of [`verification-discipline`](../verification-discipline) and [`emission-discipline`](../emission-discipline), completing an action-class trio:

- **verification-discipline** gates what the model may _believe_ — when a stale prior must be re-checked before it drives an action.
- **emission-discipline** gates what the model may _release_ — what is licensed to cross into a code fence.
- **envelope-discipline** gates what the model may _mint_ — the shape of the contracts the other two operate across.

The first two govern actions taken **across** existing contracts; this one fires earlier, at the only moment a contract is cheap to shape.
Like its siblings it is deliberately standalone (no `metadata.p4`), so its **stage mapping is a prose cross-reference** to the four P4 gates defined in `roboto`, each rule's placement asserted rather than validated — the same acknowledged tradeoff the siblings carry.
Since roboto 0.0.2, roboto's `p4.py` checks the mapping from roboto's side: roboto declares this plugin as a dependency, every gate the section opens a bullet with must be a P4 gate, and each roboto skill that binds this plugin must hook at least one of those gates.

## The framework obeys itself

- **Derived** 2026-07-22, from the single live failure arc in the skill's Appendix A — a control-plane verb minted with a flat `url` scalar, whose missing envelope later surfaced as a doctrine leak (permission policy scoped to an artifact's presence) and two value-enumerating open points.
- **No tool-behavior claims:** every claim is structural (Class 0 in verification-discipline's half-life table); the only dated fact is the derivation arc.
- **Review triggers:** any rule fires incorrectly in practice; six months elapse; or a sibling discipline revises the shared believed / released / minted framing.
- **Self-application:** the plugin lands as a new sibling in the marketplace — a new field in the discipline family's own envelope — rather than as a reshape of `vlds` or `roboto`; its skill takes one free-form argument rather than a bespoke flag per question; and it ships with exactly the fields it uses (no hooks, no agents, no speculative scaffolding — Rule 10 applied to itself).

## Install

Load it with `claude --plugin-dir ./lbiza/plugins/envelope-discipline` (repeat the flag for other plugins).
As of Claude Code circa 2026-07, `--plugin-dir` loads the plugin live from disk each session, so there is no separate install or update step — per verification-discipline's Rule 1 that is a Class-1 (version-indexed) claim about the loader's behavior, stamped here rather than asserted as timeless.
The skill is **direct-invoke only** (`disable-model-invocation: true`, matching the sibling disciplines) — reach it with `/envelope-discipline:discipline`, optionally passing a seam or signature to test against the discipline.

## Derivation notes

Unlike the sibling plugins, this framework was **authored directly into the plugin** on 2026-07-22 — no canonical payload predates it, so there is no wording-delta log; this document and the skill are the canonical text.
The source directive it formalizes is quoted verbatim (lightly normalized for spelling) in the skill's Appendix A, alongside the compressed failure arc it was issued over.
The framework generalizes the directive's own closing claim: the one-cheap-moment property of minted contracts spans multiple disciplines, not just software development.
