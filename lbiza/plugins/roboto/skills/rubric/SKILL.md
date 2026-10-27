---
name: rubric
description: The runtime engagement gate — scores the request and resolves which dependency-closed closure to compile just-in-time, from the bare identity contract up to the full apparatus, then discloses the chosen depth. Run first, before reasoning, so the driver pulls only the skills the request actually needs.
when_to_use: "Trigger at the very start of every request to pick engagement depth — 'is this trivial or high-stakes', whether to pull vlds / bias-patterns / templates, which closure to compile just-in-time."
metadata:
  p4:
    type: skill
    phases: [prompty, prompter, pioneer, puppeteer]
    depends_on: []
    optional_depends_on: []
    interface:
      domains: [engagement_selection, dependency_gating, jit_compilation]
      capabilities: [request_scoring, closure_selection, depth_disclosure]
    hooks:
      on_prompty: [score_request]
      on_prompter: [resolve_closure]
      on_pioneer: [gatecheck_closure]
      on_puppeteer: [compile_context]
    tiers: [minimal, standard, verification, detection, full, derivation]
---

# Rubric Skill — the just-in-time engagement gate

> The gate the driver runs **first**, before reasoning.
> It reads the request, scores it, and resolves which dependency-closed closure to compile just-in-time — from the bare `identity` contract up to the full apparatus.
> `identity` and this gate are never gated off; everything above is pulled only when its signal fires.

## The gate

Engage the highest row whose signal fires, then compile that closure (it includes every lower layer it depends on).
When nothing above row 0 fires, stay at `identity`.

| # | Signal in the request                       | Marginal capability it adds                            | Builds on                    | Closure        |
| - | ------------------------------------------- | ------------------------------------------------------ | ---------------------------- | -------------- |
| 0 | Trivial / conversational                    | — (contract only)                                      | —                            | `minimal`      |
| 1 | Wants a real, shaped answer                 | `templates` (formatting)                               | `minimal`                    | `standard`     |
| 2 | Load-bearing factual / technical claims     | `vlds` (decision gate)                                 | `standard`                   | `verification` |
| 3 | Loaded / polluted / under-specified framing | `bias-patterns` (pre-response scan)                    | `standard`                   | `detection`    |
| 4 | Research, **exploration** (enumerate / map out / deep-dive), consequential, or contested | `isomorphic-operations`, `sjc-indexer`, `orchestration` | `verification`, `detection` | `full`         |
| 5 | A VLDS **store hand-off** — a session sends a moment for roboto to conduct through the vlds operator | `derivation` | `verification`, `detection` | `derivation` |

The four signals are the same questions the `prompty` stage asks — applied here as a runtime test rather than a build-time menu.

Row 5 is not a depth above `full`: it is the one row whose request is not the owner's.
A session hands roboto a store moment, and what roboto returns is a derived understanding for that session, never a response — the `derivation` skill's shape instead of the response contract.

**Builds on** is the ladder's actual shape, and it is load-bearing rather than decorative: a row's closure must contain every member of the closures it builds on, plus its own marginal capabilities. Rows 2 and 3 are **parallel branches** — both build on `standard`, neither on the other — and row 4 unions them. `p4.py validate` reads this column and fails when a closure drops something the row below it declared.

## Gate graph (fixed)

The four P4 gates and their chain — the one structure not declared on a skill:

- `prompty` depends_on `[identity]`
- `prompter` depends_on `[identity, prompty]`
- `pioneer` depends_on `[identity, prompty, prompter]`
- `puppeteer` depends_on `[identity, prompty, prompter, pioneer]`

A skill hooks gates via its `metadata.p4.phases`; resolving a gate resolves its chain, and the active gates for a request are the union of the loaded skills' `phases`.

## Resolution rules

- **Just-in-time** — pull a skill only when its row fires; never preload the whole set.
- **Closed** — pulling a skill pulls its `metadata.p4.depends_on`; a closure's member set = the skills whose `metadata.p4.tiers` lists it (`identity` + `rubric` always-on). This gate _selects_ the closure; the skills declare their own membership.
- **Branches** — the gate's **Builds on** column, not this prose, is where the ladder's shape lives; read it there.
- **Default down** — a lower closure is a declared choice, not a violation.

Row 4's **exploration** signal (enumerate / map out / deep-dive / "what do you know about") is what fires `sjc-indexer` — the runtime exploration check — so a deep-exploration ask reaches the indexer instead of getting a single-pass answer.

## Cross-cutting pulls

Two skills are **not** depth rows — they attach to any closure when their own signal fires, orthogonal to the ladder above:

- **`activation`** — pulled whenever the request will cause a side effect (a tool call, a file or memory write, a search or fetch). It is the confirm-before-acting gate and carries the SAFE / STANDARD / FULL / DEBUG **mode dial**. Mode is orthogonal to closure: a `minimal` closure can still run in SAFE mode.
- **`persistence`** — pulled when a durable preference, a repeated correction, or a reusable finding surfaces (signals like "always / never", "remember this", or a correction seen 2+ times). It proposes a save to the VLDS `localStorage` tier.

Both also auto-trigger by their own `description` / `when_to_use` like every skill; listing them here records that they **compose with** the depth ladder rather than sitting inside it.

## Plugin pulls

roboto sits on five marketplace plugins, declared as `dependencies` in its `.claude-plugin/plugin.json`: the harness installs them with roboto, and disables roboto while an installed copy sits below the version roboto is aligned to.
This skill's own directory is `${CLAUDE_SKILL_DIR}`; the plugins sit together three levels above it in a source checkout, and four in the installed cache, where each plugin sits inside a version folder.
They are not depth rows either.
A skill binds one by listing a plugin-qualified skill (`<plugin>:<skill>`) in its `depends_on` or `optional_depends_on`, so a plugin arrives with the closure whose members need it.

| Plugin                                               | Bound by                                                         | Pulled when                                                               |
| ---------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `vlds` — gate, gc, guide, inspector, looper          | `vlds`, `persistence`, `activation`, `orchestration`             | a load-bearing claim, stored state, or a high-stakes verdict is in play   |
| `verification-discipline`                            | `vlds`, `bias-patterns`, `activation`, `isomorphic-operations`   | a claim's timing is in doubt: a stale prior, or a cheap canonical oracle  |
| `emission-discipline`                                | `templates`, `bias-patterns`, `activation`, `isomorphic-operations` | a fence opens, or an ask is about to narrow                            |
| `envelope-discipline`                                | `templates`, `bias-patterns`                                     | a change mints or extends a seam                                          |
| `src-fragger`                                        | `templates`                                                      | the reply carries a script written to finish the task                    |

`p4.py validate` checks this edge, and `p4.py plugins` prints it whole.
Every plugin reference must name a declared dependency, every dependency must be found in range and bound by some skill, the bound skill must exist in the copy found, and a discipline's stage mapping must share at least one gate with the phases of the roboto skill that binds it.
The disciplines stay standalone, with no `metadata.p4`: their stage mappings remain their own prose, now checked from roboto's side.

## Disclosure

State the resolved closure in the response — which row fired and why — so engagement depth is auditable like every other influence.
