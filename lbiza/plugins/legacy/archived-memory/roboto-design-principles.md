---
name: roboto-design-principles
description: Design decisions that shape the Roboto instance — apply when rebuilding or extending it
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 4d1a7c60-8b2e-4f19-9a3d-7e5c02f81b64
---

> _**legacy** - verbatim archive of `.temp/archived-memory/roboto-design-principles.md`, now running from/as the `legacy` plugin (`lbiza/plugins/legacy/`). Body copied word-for-word; the originSessionId in the frontmatter is a synthetic placeholder (see README), otherwise unchanged. Overview: [legacy/README.md](../README.md)._

Design stance for the P4 / Roboto instance (visible in git history + docs). Part of
[[roboto-reconstruction-recipe]].

- **Single-file-per-concern; derive, don't store** — no fragments.md/configurations.md (retired 2026-06-24); closures + the gate graph derive at runtime from each skill's metadata.p4 (tiers=closure membership, phases/depends_on=gate graph) + the rubric resolver. One skill per directory; don't store computed catalogs, don't split or version-fork.
- **Strip fake precision** — never invent step counts, sizes, or confidence numbers. Claudius marks
  unsupported deltas `unexplained`; the `total_size` tier field was dropped as fake precision — never reintroduce it.
- **Bounded reconstruction** — reconstruct context from a budget; if not reasonably supported, stop
  and label it, don't fabricate. (This is exactly why the memory is a seed, not a copy.)
- **Dependency closure** — every fragment/skill declares depends_on (+ optional_depends_on); configs
  bundle the full transitive closure.
- **Decision gate as epistemic boundary** — no unverified claim drives an action; unverifiable claims
  are qualified, not asserted.
- **Semantic line breaks** — Markdown is authored one sentence per line and one line per list item
  (bullets kept whole); prose is never hard-wrapped at a fixed column, and code/YAML/tables are never
  reflowed. Keeps every prose edit a one-line diff. Convention is documented in CONTRIBUTING.md and
  applied across `skills/`, `docs/`, and `templates/`.

**Why:** the framework is meant to be reconstructable and auditable, not a frozen artifact — its
value is the regeneration rules, not the rendered text.

**How to apply:** when rebuilding or extending Roboto, regenerate from lbiz/templations + docs + these
seeds; resist copying prose verbatim, and prefer adding a fragment/skill/tier over editing in place.
