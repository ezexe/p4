---
description: P4 pioneer stage — gate-check that a closure is dependency-closed and coherent
argument-hint: "<closure>"
arguments: [closure]
---

# /p4-pioneer

The **pioneer** stage of the P4 runtime pipeline — gate-check the closure.

Closure to validate: $closure

Run the validator — it checks the closure against the actual `metadata.p4` graph.
From the roboto plugin root (`${CLAUDE_PLUGIN_ROOT}` when installed, or `lbiza/plugins/roboto/` in the source repo), run:

```sh
python scripts/p4.py check $closure       # this closure: valid? + issues
python scripts/p4.py validate             # every closure + the whole graph (exit 1 on failure)
python scripts/p4.py plugins              # the plugin edge in full: dependencies, versions, bindings
```

The script verifies, mechanically:

1. **Closure** — every member's skill-level `depends_on` is present in the set. `depends_on` is three id-spaces: skill names resolve to `skills/<name>/`; P4 **gate** ids (`prompty | prompter | pioneer | puppeteer`) resolve to the fixed gate graph, not a skill; plugin-qualified skills (`<plugin>:<skill>`) resolve through the plugin edge (item 6).
2. **No dangling refs** — every `depends_on` / `optional_depends_on` skill name resolves to a real skill, and every `phases` entry is a valid gate id.
3. **Convention** — no skill re-lists the always-on base (`identity` / `rubric`) in `depends_on`, and both base skills exist.
4. **Hooks match phases** — a non-empty `hooks.on_<gate>` whose gate is absent from that skill's `phases` is an undeclared hook: the skill claims work at a stage it never registers for.
5. **Rubric reconciliation** — the closure is registered in _two_ places and both must agree. Every row of the `rubric` gate table names a closure some skill's `tiers` lists (no phantom row), every closure has a row (nothing unreachable by `prompty`), each row's **marginal capability** really is a member and really is new, and each row's closure contains everything the closures in its **Builds on** column contain.
6. **Plugin edge** — every `<plugin>:<skill>` reference names a dependency declared in `.claude-plugin/plugin.json`; each declared dependency is found (its marketplace entry in a source checkout, the installed cache otherwise) at a version inside its declared range and is bound by some skill; the bound skill exists in the copy found; and a discipline's stage mapping shares at least one gate with the phases of the roboto skill that binds it.

`check <closure>` also prints the rubric row that selects it, so an unreachable closure is visible at a glance.
An unreadable or unparseable gate table is itself a failure — the check fails closed rather than passing on nothing.

Then judge the one thing the script cannot: whether the closure is **appropriate** for the `fires_when` it claims (a semantic call left to you).

**Output:** `valid` (true/false), `issues`, and any recommendations.
