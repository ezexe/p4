---
name: roboto-reconstruction-recipe
description: How to regenerate the .ai/roboto P4 instance from lbiz/templations + the build docs
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d1a7c60-8b2e-4f19-9a3d-7e5c02f81b64
---

> _**legacy** - verbatim archive of `.temp/archived-memory/roboto-reconstruction-recipe.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word; the originSessionId in the frontmatter is a synthetic placeholder (see README), otherwise unchanged. Overview: [legacy/README.md](../README.md)._

Roboto is a worked-example **instance** of the P4 framework in this repo (internal name
`roboto`). As of 2026-06-24 it ships as an installable Claude Code plugin under `lbiza/plugins/roboto/`
(skills under `lbiza/plugins/roboto/skills/`), one of potentially many plugins under `lbiza/plugins/<name>/`
listed by the `lbiza/` marketplace. Rebuild it from `lbiza/templations/` (blank kit, name deliberate — not `templates/`) +
`CONTRIBUTING.md` (build rules), supplying only the instance deltas below. See
[[roboto-identity-lenses]], [[roboto-skill-seeds]], [[roboto-design-principles]],
[[roboto-repo-pointer]].

**P4 gates (the fixed gate chain lives in the rubric skill; per-skill hooks in metadata.p4.phases), dependency-chained:**
- prompty   depends_on [identity]
- prompter  depends_on [identity, prompty]
- pioneer   depends_on [identity, prompty, prompter]
- puppeteer depends_on [identity, prompty, prompter, pioneer]
A configuration must include the transitive closure of its members' depends_on.

**Closures (NO configurations.md — derive from each skill's metadata.p4.tiers; the rubric skill is the resolver and holds the fires_when signal→closure rows). identity + rubric are always-on (not listed as members). Verification and Detection are PARALLEL branches off the base (Detection drops templates); Full unions them:**
- minimal:      {identity}
- standard:     {identity, templates}
- verification: {identity, templates}
- detection:    {identity, bias-patterns}
- full:         {identity, templates, bias-patterns, isomorphic-operations, sjc-indexer}

**Puppeteer lifecycle (8 steps):**
RECEIVE -> SCAN -> BREAK -> PLAY -> COMPILE -> TEST -> SYNTHESIZE -> POST
(SCAN runs the bias scan; BREAK is a FORK, not a human-blocking pause — each option becomes a
new prompter prompt dispatched as a puppeteered parallel branch [P4 parallel mode]; PLAY plays
out the forked branches through the lenses; COMPILE assembles Claude/Claudio/Claudius +
decision_gate; TEST validates; SYNTHESIZE merges branches then runs Roboto's
ALIGN->DIVERGE->VERIFY->SYNTHESIZE; only an unresolvable fork surfaces to the user.)

**Build process (P4 builds its own configs, per CONTRIBUTING.md) — one slash command per phase:**
/p4-prompty (identify need) -> /p4-prompter (select skills) -> /p4-pioneer (validate closure) ->
/p4-puppeteer (register a new closure: a rubric row + the members' tiers — the puppet↔puppeteer sync point).

**Skill manifest is now standard `SKILL.md` frontmatter** (`name` + `description`); the old P4
`extension{...}` fields (type, phases, depends_on, optional_depends_on, interface, hooks, +tiers)
are preserved under a `metadata.p4` object. Scaffold: `lbiza/templations/SKILL.md.template`. Connectors are
MCP servers (`.mcp.json`); "tools" fold into skills+`scripts/` or MCP. Do NOT re-store the schema —
copy it from the template at rebuild time.
