---
name: discipline
description: "Envelope Discipline (futures-land-as-fields) — a 12-rule framework for HOW a seam's configurables are shaped at the moment the seam is minted. Models interface calcification as (first-of-family mistaken for the whole story) × (no envelope reserved at the only cheap moment), and gates on what is about to be MINTED, never on how small the knob looks: the first option reveals the family and gets one named options envelope at birth; defaults are the null ask (silent, deny, bare) so no default carries doctrine; futures land as new named fields, never as signature breaks or per-knob rulings; the shape propagates through every layer of the seam, wire grammar included. Use when adding a parameter, flag, query, or policy to any function, verb, API, or contract; when a behavior is about to be hardwired at a seam; or when an open design question enumerates option values and smells like a missing options container."
argument-hint: "[seam or signature to test against the discipline]"
disable-model-invocation: true
---

# Envelope Discipline — futures-land-as-fields

> An interface is cheap exactly once — at minting. This skill is the discipline of asking, in that moment, whether the parameter being added is the whole story or the first sibling of a family — and when it is a family, housing it in one named options envelope whose defaults are the null ask.
> It is the shape-side sibling of [`verification-discipline`](../../../verification-discipline/skills/discipline/SKILL.md) (what may be believed) and [`emission-discipline`](../../../emission-discipline/skills/discipline/SKILL.md) (what may be released): those two gate actions taken across contracts; this one gates how the contracts themselves are minted.

## Provenance (this framework obeys itself)

- **Derived:** 2026-07-22, from a single live failure arc — a control-plane verb minted with a flat url scalar, reconstructed in [Appendix A](#appendix-a--the-derivation-case).
- **Claims version-indexed against:** nothing — every claim here is structural (Class 0 in verification-discipline's half-life table), not tool-behavioral; the only dated fact is the derivation arc itself.
- **Review triggers (any one fires a re-read):** any rule fires incorrectly in practice; six months elapse from the derived date; or a sibling discipline revises the shared action-class framing (believed / released / minted).

Self-application: this framework ships as a new sibling plugin in the marketplace — a new field in the discipline family's own envelope — rather than as a reshape of `vlds` or `roboto`; and its skill takes one free-form argument rather than a bespoke flag per question.

## Core model

### Two-factor calcification

Experienced interface calcification = (first-of-family mistaken for the whole story) × (no envelope reserved at the only cheap moment).
Factor one is judgment-origin and inevitable: at minting, the first configurable always looks like the whole story, because its siblings do not exist yet.
Factor two is shape-origin and fixable: whether the seam reserved a named, growable container.
Neither factor alone produces the harm; the observed failure is a calcified flat scalar — a seam whose callers, wire forms, and harnesses have all frozen around one member of a family.
Target factor two — it is the only factor the design layer controls, and the design layer is the only layer present at the cheap moment.

### The temporal identity

"Correct for its moment" and "incorrect for its future" are the same judgment read at two clocks — not separable verdicts, because the future arrives as a NOW at a seam that can no longer move cheaply.
The minting moment is therefore the only moment where future-shape costs one line; every later moment prices it as a migration.
Contemplating FUTURE during NOW is not speculation — it is reading the trajectory the first sibling already announces.

### The family-reveal test

At minting, one question: is this parameter the whole story, or the first sibling?
Identity parameters — who or what the call is about: ids, tokens, the subject — tend to be the whole story.
Configurables — behaviors, policies, flags, queries, levels, anything a caller could plausibly want differently — are presumed first siblings; the burden of proof is on lone-scalar, never on family.

### Null-ask defaults

The envelope's defaults are the null ask: silent, deny, bare, empty.
A default that does something is a hidden caller — an ask nobody wrote down — and the seam's behavior hardens into doctrine that other implementations then derive desired functionality from.
Explicit fields are the only asks.

### Shape, not speculation

The future-proofing lives entirely in the shape — a named envelope that can grow — while the implementation stays NOW-sized.
No field ships without a live caller; the envelope with one field is barely more code than the bare scalar it replaces.
This is what keeps the discipline compatible with justified-existence auditing instead of becoming a license for gold-plating.

### Beyond software

Any minted contract — wire verb, protocol, process, agreement — has the same one-cheap-moment property: extension points are reserved at minting or paid for later as renegotiation.
The discipline spans layers and disciplines because calcification does.

## The 12 rules

### Group A — Minting (the one cheap moment)

1. **The first option reveals the family.** A configurable arriving at a seam is presumed the first sibling of a family, not the whole story. Treating it as a lone scalar is the claim that needs defending.
2. **Envelope at birth, not at second sibling.** For seam signatures the classic wait-for-duplication heuristic inverts: by the time the second sibling arrives, the wire, the callers, and the harnesses have calcified around the flat shape. The envelope is earned the moment the first configurable arrives, while it costs one call site.
3. **Name the envelope for the contract it configures.** Never for its first field — the first field is a member, not the family's identity. A well-named envelope survives every field it will ever gain.
4. **Identity rides the signature; configuration rides the envelope.** Who or what the call is about may stay positional. How the call should behave may not.

### Group B — Defaults & doctrine

5. **Defaults are the null ask.** Silent, deny, bare, empty. Behavior enters a seam only by a named field a caller set; a default that does something is a hidden caller nobody can audit.
6. **No presence-derived doctrine.** Nothing may infer desired functionality from an artifact's existence, a default's behavior, or a helper's baked-in choice. An ask that is not a field is not an ask.
7. **A hardwired behavior is a field in hiding.** Any baked-in choice at a seam — an appended query, a compiled-in policy, a magic constant — is an option that has not been given its name yet. Unhide it into the envelope.
8. **Per-knob rulings collapse into the shape rule.** Once the envelope exists, a knob's value is caller configuration, not architecture. An open design question that enumerates option values ("X, or Y, or an allowlist?") is a symptom of a missing envelope, not a question to answer — fix the shape and the question dissolves.

### Group C — Growth & bounds

9. **Futures land as fields.** Extension arrives as new named fields with null-ask defaults — never as signature breaks, never as accreted positional scalars, never as re-interpretation of an existing field.
10. **No speculative fields.** The envelope carries only fields with live callers; the reservation is the shape, not pre-built behavior. An envelope full of unused fields is the same disease as the flat scalar, inverted.
11. **The envelope spans every layer of the seam.** API signature, wire grammar, harness, docs — the family shape propagates through all of them, or the flat scalar has just moved down a layer and waits there.
12. **Accretion is the tell.** The moment a seam is about to take configurable parameter N+1 positionally — or a helper is about to bake in choice N+1 — the envelope was missed at N=1. Stop and wrap before adding: this addition is the cheapest moment left.

**Bounds (this is not "wrap everything"):** identity and subject parameters stay positional (Rule 4); a private helper with one caller inside one file is not a seam — a seam is a contract with callers across a boundary (process, wire, plugin, module, team); and Rule 10 bars the inverse failure, so the discipline can never justify fields without callers. The envelope is the one structure earned at birth precisely because it is the only one whose late arrival costs a migration.

## Mottos

> "Correct for its moment and wrong for its future are the same judgment read at two clocks."

> "The first option is the family announcing itself."

> "Defaults are the null ask; everything else is a caller's named request."

## Stage mapping — the rules against the P4 gates

The four P4 lifecycle gates are defined in the roboto plugin, not here; this mapping is a _proposal_ derived from their in-repo semantics ([commands/p4-\*.md](../../../roboto/commands/), gate graph in [rubric/SKILL.md](../../../roboto/skills/rubric/SKILL.md)).
Because this is a standalone plugin (no `metadata.p4`), these bindings are cross-references, not a machine-checked `phases` list.

- **prompty (recognize):** the family-reveal test binds at intake — **Rule 1** (presume first sibling), **Rule 4** (split identity from configuration before shaping anything), and **Rule 8**'s diagnostic half (a value-enumerating open question arriving in the request is a shape symptom, not a menu to pick from).
- **prompter (wire the shape):** the minting rules — **Rule 2** (envelope at birth), **Rule 3** (name it for the contract), **Rule 5** (null-ask defaults), and **Rule 7** (unhide hardwired choices into fields while the closure is still being resolved).
- **pioneer (catch the failure):** the adversarial tells — **Rule 6** (hunt presence-derived doctrine: what is deriving functionality from an artifact's existence?), **Rule 10** (hunt speculative fields: which field has no live caller?), and **Rule 12** (accretion check: is anything about to take configurable N+1 positionally?).
- **puppeteer (gate the commit):** the calcification boundary — **Rule 9** (the emitted change lands as fields with null-ask defaults, not as a signature break) and **Rule 11** (the shape crossed every layer it touches; committing a wire form flatter than its API re-mints the defect one layer down). The commit is where cheap ends: this is the last gate before the migration price applies.

**Rules that do not map cleanly to a single gate (flagged, not forced):**

- **Rule 8** is double-faced: its diagnostic half reads at prompty, but its collapse ("the ruling burden drops from per-knob to per-shape") is a standing consequence that holds at every gate.
- **Rule 12** fires at every later touch of an already-minted seam, not at one stage; it is listed at pioneer because that is where the tell is hunted deliberately.
- **The temporal identity** (core model) is gate-global: every gate is somebody's NOW.

## Appendix A — the derivation case

_Compressed reconstruction of the arc this framework was derived from (2026-07-21/22, an out-of-process CEF audio-plugin engine's control plane)._

An agent session mints the control-plane verb `CreateTab(client_pid, token, url)` — url as a flat scalar.
Correct for its moment; the family-reveal question (**Rule 1**) is never asked.
A "default page" ships beside it: the verb's empty-url case resolves to it, its URL helper bakes in an auto-play query (**Rule 7 specimen** — a hardwired ask no caller wrote), and functionality accretes around an artifact whose definition the owner never actually ruled.
A later session adds a microphone permission grant and scopes it to the default page's origin — policy derived from an artifact's presence (**Rule 6 specimen**).
The owner catches the leak, strips the scoping, unbundles the query — and TWO open points surface: "should create pass the auto-play query?" and "grant everything, only the default page, or an allowlist?"
Both are value-enumerating questions — the **Rule 8 specimen** — and the owner's ruling names the root instead of answering either:

> "where it went wrong is the url parameter in favor of an options parameter that contains url — for its moment it was correct; for its FUTURE it was incorrect to begin with; for its NOW it needs to be changed — showing a need for contemplating FUTURE during its NOW moments... this spans across multiple disciplines not just software development."
> _(the source directive, lightly normalized for spelling)_

With an options envelope on the verb, the auto-play query and the grant policy are named fields with null-ask defaults; neither open point exists; the next knob is a field.
The wire cost of the envelope at minting was one call site.
The cost at catch-time is a migration across the verb, the wire grammar, the driver client, the harnesses — and the conversation that had to relitigate two knobs that were never architecture at all.
That ratio is the entire argument for the discipline.
