> _**legacy** - verbatim archive of `.temp/archived-memory/memory-archive.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word; the two originSessionId values are synthetic placeholders (see README), otherwise unchanged. Overview: [legacy/README.md](../README.md)._

# VLDS — Memory Archive

_Created 2026-06-30. Full-fidelity archive of every VLDS-bearing line scrubbed from the user's
global memory (`~/.claude/projects/E--…/memory/`) at the user's request ("full scrub of every vlds
mention… let it only live in the projects .vlds/ directory"). This is the canonical home now._

**To restore:** copy each block below back into the named memory file (and re-add the two MEMORY.md
index lines), then delete this notice. Nothing here was lost — only relocated.

---

## DELETED WHOLE — `memory/vlds-test-agenda.md`

```markdown
---
name: vlds-test-agenda
description: "Pinned next phase for the vlds plugin — build or find an intricate, in-depth test covering all aspects (static, behavioral, install, robustness)"
metadata:
  node_type: memory
  type: project
  originSessionId: 9c3f5e12-2a74-4d8b-8f16-b0417de9265a
---

The `vlds` plugin (`lbiza/plugins/vlds`) is feature-complete: three decoupled, progressive-disclosure skills — **gate** (epistemic status `CONFIRMED / PENDING / HEDGED`), **guide** (config `hit`/`miss`; index + ledger; promote/correct), **inspector** (independent eye; `CORROBORATED / REJECTED / CONTESTED`; Blackboard). Each was verified via a 5-lens adversarial workflow. See [[roboto-repo-pointer]] for location.

**Pinned next agenda (set 2026-06-30):** build *or* find an intricate, in-depth test covering **all aspects** of the plugin. Scope to cover:

- **A — Static / structural** (scriptable, deterministic): YAML frontmatter validity + `name`==dir + combined `description`+`when_to_use` ≤ 1536; JSON validity (plugin.json, marketplace.json) + marketplace wiring (source/name); internal markdown link integrity; schema consistency across SKILL/reference/examples (state tokens, enums, field names); command derivation (`/vlds:gate|guide|inspector`); the decoupling invariant (zero `roboto`/`P4`/`rubric`/`checker` terms in the plugin).
- **B — Behavioral eval** (the hard, high-value part): trigger/activation — each skill fires on its `when_to_use` cases and is skipped on trivial/conversational ones; routing correctness — gate → right status, guide → right `hit`/`miss` + record, inspector → right converge/diverge state. Needs an LLM-judged eval against golden scenarios; the three `examples.md` are good seed fixtures.
- **C — Install / integration:** `/plugin marketplace add ./lbiza` + `/plugin install vlds@p4-marketplace`; skills discovered, commands registered, loads clean.
- **D — Robustness / runtime decoupling:** behaves with roboto absent; graceful on ambiguous/edge inputs.

**Open decision when resuming:** FIND existing Claude Code skill/plugin eval tooling vs BUILD a custom harness (A is a scriptable check suite; B reuses the adversarial Agent/Workflow fan-out pattern already used for verification, as an LLM-judge eval).

**Why:** user explicitly pinned this as the next phase after the 3-instrument build.

**How to apply:** on resume, first settle build-vs-find with the user, then work A→D; reuse the adversarial-workflow pattern for the B behavioral evals.

**Lessons from a first behavioral run (2026-06-30):**

- **Reinstall before any behavioral test.** A run validated nothing because the session had a *stale install* — the registry showed the fossil `vlds:vlds` with the old `PROCEED/VERIFY_FIRST/QUALIFY` vocabulary, predating the `gate` rename and `guide`/`inspector`. The new `/vlds:gate|guide|inspector` weren't even registered. Refresh from current files first.
- **A behavioral test is observe-and-judge, not a scripted transcript.** The README originally shipped an idealized guide→gate→inspector trace as "run this and see this" — an unverified claim asserted as fact (the gate's own failure mode). Judge by criteria (verified before asserting? surfaced a false premise? routed right?), not a verbatim match.
- **Activation and content are two separate tests.** Direct invocation (`/vlds:gate "<claim>"`) checks skill *content*; a natural prompt checks whether `when_to_use` actually *fires*. The "failed" run showed the model reasoning well from having *read the README*, not the skill triggering.
- **A false-premise surfacing is correct behavior, not a failure** — e.g. "add rate limiting to the API" in a repo with no API should yield "there is no API," the gate catching a bad premise. The README's `## Try it` section now reflects all of this.
- **Auto-activation is unreliable even for the looper (verified live, 2026-06-30).** With the current plugin loaded via `--plugin-dir` (no stale install), a clearly-qualifying load-bearing request (a build-version pin) did NOT auto-surface `vlds:looper`. The model handled it *well by reflex* — refused to confirm, web-searched, caught that "iOS 7.8" doesn't exist — but without invoking the skill. Diagnosis: skill auto-activation is a model *choice* (soft tendency), not a deterministic trigger; and a capable model that already applies the discipline tends not to reach for a skill that encodes what it already does. The deterministic lever for "always apply on a load-bearing turn" is a **hook** (settings.json, harness-injected), not a skill's `when_to_use`. (The "looper activates the other skills" half is impossible by design — skills can't call skills; the looper inlines their procedures.)
```

---

## DELETED WHOLE — `memory/roboto-memory-duality.md`

```markdown
---
name: roboto-memory-duality
description: roboto's physical(memory)/virtual(VLDS) duality — the two memory faces and the MMU-style verification check, woven through the instance
metadata:
  node_type: memory
  type: project
  originSessionId: 1e08b4a3-5f61-4c27-a9d0-3b8271ec4f95
---

roboto is modeled as a computer; its memory has two faces, now woven through the instance (one commit on top of the JIT/gates/closures reframe).

- **VLDS = the virtual space** — `skills/vlds` is the virtual address space of _claims_ (what is claimed/known): provenance-tagged, durability-tiered. The `Virtual` storage tier = an unbacked page; `localStorage` (userMemories) + `DataStore` = the physical-backed tiers.
- **`memory` = the physical space** — the `roboto` agent's `memory: project` field: the shared-memory ring the **puppet↔puppeteer bridges** sync through (per-OS map API, `mmap`/`MapViewOfFile`). KEPT, disclosed, highlighted — never dropped.
- **Verification = the physical↔virtual (MMU) check** — the VLDS decision gate: PROCEED = the virtual claim maps to a resident physical page; VERIFY_FIRST = a page fault (fault it in / verify); QUALIFY = an unbackable page (stays virtual, qualified). SYNTHESIZE reconciles physical (what synced) vs virtual (VLDS).
- **Disclosure pairs the faces** — `identity`'s Influence Disclosure `Memory:` line = the physical-memory channel, surfaced opposite VLDS's virtual provenance.
- **Puppeteer = the sync point** — `/p4-puppeteer` is where the bridges reconcile physical `memory` against virtual VLDS and commit the synced closure.

Canonical home of the duality = the `## Virtual space and physical memory` section in `skills/vlds/SKILL.md`. Builds on [[roboto-design-principles]], [[roboto-identity-lenses]], [[roboto-reconstruction-recipe]], [[roboto-repo-pointer]].
```

---

## MEMORY.md — two index lines removed

```markdown
- [Roboto memory duality](roboto-memory-duality.md) — physical(memory)/virtual(VLDS) duality + MMU-style verification, woven through the instance
- [VLDS test agenda](vlds-test-agenda.md) — PINNED next phase: build/find an intricate in-depth test of all aspects of the vlds plugin (static / behavioral / install / robustness)
```

---

## `memory/roboto-skill-seeds.md` — original VLDS-bearing fragments

**The whole `vlds` skill bullet (removed):**
```markdown
- **vlds** (depends_on [identity]) — epistemic transparency via a neural-net metaphor:
  weights = sources/context, biases = assumptions, activation functions = tools/instructions,
  epistemic state = provenance. VLDS = the acronym of its four storage tiers:
  **V**irtual / **l**ocalStorage / **D**ataStore / **s**essionStorage (do NOT gloss it as
  anything else, e.g. "Verifiable Ledger" — a blind rebuild made that mistake).
  Decision gate: verifiable&verified -> PROCEED(FULL); verifiable&!verified -> VERIFY_FIRST(BLOCKED);
  !verifiable -> QUALIFY(QUALIFIED). Gate INPUTS (granularity a blind rebuild dropped — keep these):
  source_type {retrieval=FULL, training=BLOCKED-until-verified, inference=inherits,
  composite=lowest-of-parts, unknown=QUALIFIED-only} and uncertainty_class
  {none, statistical, unverified, unknowable}.
```
**Original dependency references that named vlds (now stripped of the vlds token):**
- `- **templates** (depends_on [identity], optional vlds) — …`
- `- **isomorphic-operations** (depends_on [identity, vlds]) — 3 ops sharing one structure …`
- `- **sjc-indexer** (depends_on [identity, vlds, isomorphic-operations]) — SJC = …`
- orchestration line: `… the sequencer that wires the other skills (SCAN→bias-patterns, TEST/VERIFY→vlds, render→templates, per-branch lenses+synthesis→identity), …`
- count line: `… the live set is now 10 (identity, rubric, vlds, templates, bias-patterns, isomorphic-operations, sjc-indexer, activation, persistence, orchestration).`
- live-values line: `… live values: vlds []; templates []; activation []; persistence []; rubric []; identity []; orchestration []; isomorphic-operations [vlds]; sjc-indexer [vlds, isomorphic-operations]; bias-patterns [prompter] …`

---

## `memory/roboto-reconstruction-recipe.md` — original VLDS-bearing fragments

**Closures block (original):**
```markdown
**Closures (NO configurations.md — derive from each skill's metadata.p4.tiers; the rubric skill is the resolver and holds the fires_when signal→closure rows). identity + rubric are always-on (not listed as members). Verification and Detection are PARALLEL branches off the base (Detection drops vlds+templates); Full unions them:**
- minimal:      {identity}
- standard:     {identity, templates}
- verification: {identity, vlds, templates}
- detection:    {identity, bias-patterns}
- full:         {identity, vlds, templates, bias-patterns, isomorphic-operations, sjc-indexer}
```
**Duality paragraph (removed):**
```markdown
**Physical/virtual memory duality (see [[roboto-memory-duality]]):** VLDS = the virtual space
(claims); the agent's `memory: project` = the physical space (the shared-mem ring the
puppet↔puppeteer bridges sync through, mmap/MapViewOfFile); verification = the MMU-style
physical↔virtual check (PROCEED=mapped, VERIFY_FIRST=page fault, QUALIFY=unbackable); SYNTHESIZE
reconciles the two. Canonical home: the `## Virtual space and physical memory` section in
skills/vlds/SKILL.md; disclosed via identity's `Memory:` line and the /p4-puppeteer sync point.
```

---

## `memory/roboto-repo-pointer.md` — original VLDS-bearing fragments

- marketplace line: `- .claude-plugin/marketplace.json (name "p4-marketplace"); now lists TWO plugins: "mister" -> ./plugins/roboto, and "vlds" -> ./plugins/vlds (added 2026-06-29)`
- skills list: `  - skills/{identity,rubric,vlds,templates,bias-patterns,isomorphic-operations,sjc-indexer}/SKILL.md`
- **The whole vlds-plugin paragraph (removed):**
```markdown
- plugins/vlds/ (dir + plugin + marketplace name all "vlds"; added 2026-06-29) — a standalone single-skill plugin: VLDS distilled into a portable epistemic decision gate (VERIFIABLE->VERIFIED->PROCEED/VERIFY_FIRST/QUALIFY + neural-net provenance metaphor + storage-durability tiers + source-type/uncertainty-class axes), decoupled from the roboto instance (no four-lens/MMU/`memory`/w_claude coupling). Files: `.claude-plugin/plugin.json` + a **progressive-disclosure** skill at `skills/gate/` (dir renamed vlds->gate so the command reads `/vlds:gate`, not the doubled `/vlds:vlds`; plugin skills are always namespaced `<plugin>:<skill-dir>`) = lean `SKILL.md` (framing + Decision Gate + source-type/uncertainty axes + How-to-Apply + resource links) plus on-demand `reference.md` (neural-net metaphor, storage tiers, draft/verified delta schema, epistemological limit) and `examples.md` (worked example). Frontmatter name/description/when_to_use only — NO metadata.p4 block, NO invocation-control keys (gate still auto-fires; depth loads on demand). First multi-file/progressive-disclosure skill in the repo (restructured 2026-06-29: SKILL.md 178->99 lines as ~57% reference depth moved out). roboto keeps its own instance-coupled vlds; this is an extraction, not a move. Built per user ask "highlight skill-creator's value / keep it simple".
```
- install line: `Install (marketplace root = lbiza/): /plugin marketplace add ./lbiza ; then /plugin install mister@p4-marketplace (the roboto instance) and/or /plugin install vlds@p4-marketplace (the standalone gate).`

---

## `memory/roboto-identity-lenses.md` — original line

```markdown
- **Roboto**   — scope: all three + VLDS verification; synthesizes the final verified answer.
```
