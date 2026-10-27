---
name: roboto-repo-pointer
description: Where the Roboto instance and the P4 build kit live in the repo
metadata: 
  node_type: memory
  type: reference
  originSessionId: 4d1a7c60-8b2e-4f19-9a3d-7e5c02f81b64
---

> _**legacy** - verbatim archive of `.temp/archived-memory/roboto-repo-pointer.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word; the originSessionId in the frontmatter is a synthetic placeholder (see README), otherwise unchanged. Overview: [legacy/README.md](../README.md)._

Repo: E:\projects\ai\prompty-prompter-pioneer-puppeteer (Apache-2.0). Source for
[[roboto-reconstruction-recipe]] and the seeds.

As of 2026-06-24 the repo is a **meta-prompting P4 framework**. `lbiza/` is the framework + marketplace
(the build target); a soon-to-start `src/` builder generates plugins into `lbiza/plugins/<name>/`.
Roboto is the first worked plugin at `lbiza/plugins/roboto/`. (Restructured in place from the old
`.ai/roboto/` + `lbiz/templations/` layout — everything now lives under `lbiza/`.)
Naming is deliberate and quirky — do NOT "correct" it: the dir is `lbiza` with a CAPITAL `I` (reads
"lbiza" the island; looks like lowercase-l `lbiza` in many fonts — that resemblance is the user's
stylistic quirk, not a typo). `templations` (not `templates`, to avoid clashing with the `templates`
skill). Plugins nest under `lbiza/plugins/`.
Repo root: src/ (future builder) ; lbiza/ ; README.md + CONTRIBUTING.md + LICENSE (describe the repo).
lbiza/ (framework + marketplace):
- .claude-plugin/marketplace.json (name "p4-marketplace"); lists the plugin "mister" -> ./plugins/roboto
- (no templations/ — DELETED; there is no shared blank template kit in the repo anymore. Model any new plugin's files on roboto's equivalents.)
- plugins/roboto/ (dir "roboto"; plugin + marketplace name is "mister", NOT "roboto" — the dir name and the plugin name deliberately differ):
  - .claude-plugin/plugin.json
  - skills/{identity,rubric,templates,bias-patterns,isomorphic-operations,sjc-indexer}/SKILL.md
    (name+description frontmatter; old `extension:` manifest now under `metadata.p4`)
  - agents/roboto.md (JIT driver: always-on identity contract + rubric gate; pulls other skills on demand)
  - commands/p4-{prompty,prompter,pioneer,puppeteer}.md (P4 runtime pipeline stages)
  - scripts/p4.py (added 2026-06-29) — the closure resolver/validator: `validate` / `resolve <closure>` / `check <closure>`, derives closures from each skill's metadata.p4.tiers, checks dependency-closure + dangling refs + the always-on convention. KEY FACT (verified vs Claude Code docs): the harness does NOT parse metadata.p4 — only name/description/when_to_use drive skill triggering — so depends_on/tiers/phases/closures are INERT to the harness; p4.py is the only real enforcement of the closure model. /p4-prompter and /p4-pioneer now invoke it. (Agent `skills:` preload IS real/honored; so are command `arguments:`.)
  - (no docs/ — deleted 2026-06-24) closures + the gate graph derive at runtime from each skill's metadata.p4 (tiers=closure membership, phases/depends_on=gate graph) + the rubric skill (the resolver)
  - .mcp.json.example (ships no live MCP server)
Install (marketplace root = lbiza/): /plugin marketplace add ./lbiza ; then /plugin install mister@p4-marketplace (the roboto instance).
Note: skill names hyphenated (was bias_patterns/isomorphic_operations/sjc_indexer); internal ids
(hooks, ops, fields) stay snake_case.
