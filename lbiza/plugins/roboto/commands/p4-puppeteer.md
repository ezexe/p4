---
description: P4 puppeteer stage — register a new closure (a rubric row + the members' tiers)
argument-hint: "<closure> <fires-when>"
arguments: [closure, fires_when]
---

# /p4-puppeteer

The **puppeteer** stage of the P4 runtime pipeline — compile and emit a new closure.

This is the **sync point**: where the **puppet↔puppeteer bridges** meet over the shared-mem `memory` (the physical store) and reconcile it against VLDS (the virtual space) — SYNTHESIZE commits the coherent, synced result as the closure.

Closure + fires-when: $closure / $fires_when

Register the closure — there is no separate file; a closure _is_ its members' `tiers` plus a `rubric` row:

1. Add a row to the `rubric` gate (`skills/rubric/SKILL.md`): the firing signal → the closure name + `fires_when`, plus the **Marginal capability it adds** and the **Builds on** column naming the closure(s) this one sits above.
2. Add the closure name to each member skill's `metadata.p4.tiers`.

These two writes are the whole registration, and they are what makes the loop recurse: step 1 is the surface `prompty` scores a request against, step 2 is the graph `prompter` resolves. Neither half is the closure on its own — a row with no members is a closure `prompty` selects and `prompter` cannot fill; members with no row are a closure that exists and can never be reached.

Keep the closure dependency-closed — each member's `depends_on` resolves within it — and keep it a superset of everything in its **Builds on** column, or the new rung offers less than the rung beneath it.
A member that binds another plugin's skill (`<plugin>:<skill>`) resolves it through a dependency instead: declare that plugin in `.claude-plugin/plugin.json`, with the version range it is aligned to, before the reference lands.
Confirm it with the validator (from the roboto plugin root): `python scripts/p4.py validate` (or `check <closure>`) — it fails if the closure is not dependency-closed, has a dangling ref, re-lists the always-on base, hooks a gate it never declared, binds a plugin skill no declared dependency provides, or if the two halves of the registration disagree.
The output of this stage feeds the `prompty` gate — the loop recurses, and the validator is what closes it.
