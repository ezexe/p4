---
name: roboto-skill-seeds
description: One regeneration line per Roboto skill — enough to rebuild each from the skill template
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1a7c60-8b2e-4f19-9a3d-7e5c02f81b64
---

> _**legacy** - verbatim archive of `.temp/archived-memory/roboto-skill-seeds.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word; the originSessionId in the frontmatter is a synthetic placeholder (see README), otherwise unchanged. Overview: [legacy/README.md](../README.md)._

Six skills under lbiza/plugins/roboto/skills/<name>/SKILL.md (name+description frontmatter, P4 fields under metadata.p4).
Each rebuilds from lbiza/templations/SKILL.md.template + the seed line here. Identity is detailed in
[[roboto-identity-lenses]]; recipe in [[roboto-reconstruction-recipe]].

- **identity** (depends_on []) — four-lens reasoning + response contract. See [[roboto-identity-lenses]].
- **templates** (depends_on [identity]) — response format at 4 audit levels
  (Prose / Minimal / Regular / Full) x content formats (File Change / Code / Analysis / Clarification),
  plus a selection matrix mapping request type -> audit level + format.
- **bias-patterns** (depends_on [identity, prompter]) — 5 pre-response patterns:
  context_pollution, context_starvation, capability_limit_overstatement,
  philosophical_mode_trap, response_structure_bypass. Protocol: PAUSE -> FIRE correctable_query
  -> EVALUATE -> SEPARATE domains -> PROCEED.
- **isomorphic-operations** (depends_on [identity]) — 3 ops sharing one structure
  (QUERY -> INDEX -> RESULTS -> REFINE -> ITERATE -> ACCUMULATE): web_search, prompt_generation,
  artifact_api_calls. Reframe rule: replace "I cannot X" with "not directly, but indirectly via <op>".
- **sjc-indexer** (depends_on [identity, isomorphic-operations]) — SJC = Structured Junction
  Counterfactual; formula SPECIFIC + STRUCTURED + JUNCTION + COUNTERFACTUAL = HIGH_YIELD; 3 prompt tiers
  (anchor / junction / counterfactual); 5 components run in sequence: anchor_selector, seam_finder,
  junction_explorer, boundary_mapper, synthesizer.
- **orchestration** (depends_on [] — always-on base identity+rubric implicit, not listed, see convention below; optional bias-patterns/templates/iso-ops/sjc/activation/persistence; tiers [full]) —
  added 2026-06-29. Owns the runtime puppeteer reasoning lifecycle RECEIVE→SCAN→BREAK→PLAY→COMPILE→TEST→SYNTHESIZE→POST:
  the sequencer that wires the other skills (SCAN→bias-patterns, render→templates, per-branch lenses+synthesis→identity),
  forks an under-determined request at BREAK into parallel puppeteered branches (each a fresh prompter-prompt), and re-merges at SYNTHESIZE
  so only an unresolvable fork surfaces. Delegates every mechanism — owns timing + the fork/merge only. It is what `rubric` row 4's dangling
  "orchestration" token points at, and formalizes the agent's always-on "## Orchestration" prose into a JIT skill. Closes gap-report #10.
  Note: NOT the same as the `/p4-puppeteer` command (that is build-time closure registration; this is the runtime reasoning loop).

Skill count drift (the "Six" above is stale): the plugin ships rubric + activation + persistence too, so the live set is now 9
(identity, rubric, templates, bias-patterns, isomorphic-operations, sjc-indexer, activation, persistence, orchestration).

depends_on convention (2026-06-29): identity + rubric are the always-on base, declared ONCE in the roboto agent (agents/roboto.md —
the "This is the always-on base…" line, the file that actually preloads them via skills: [identity, rubric]) and NO LONGER listed in any skill's depends_on. Read every per-skill depends_on above with
identity (and rubric) stripped — live values: templates []; activation []; persistence []; rubric []; identity [];
orchestration []; isomorphic-operations []; sjc-indexer [isomorphic-operations]; bias-patterns [prompter] (a P4 gate id,
not a skill). depends_on now carries only non-always-on skills + gate ids; the commands (p4-prompter/p4-pioneer) state this too.
