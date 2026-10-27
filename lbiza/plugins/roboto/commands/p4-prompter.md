---
description: P4 prompter stage — resolve the dependency-closed skills and gates for a closure
argument-hint: "<closure>"
arguments: [closure]
---

# /p4-prompter

The **prompter** stage of the P4 runtime pipeline — resolve the closure.

Closure to resolve: $closure

Run the resolver — it reads each skill's `metadata.p4` and computes the closure, so there is no need to resolve it by hand.
From the roboto plugin root (`${CLAUDE_PLUGIN_ROOT}` when installed, or `lbiza/plugins/roboto/` in the source repo), run:

```sh
python scripts/p4.py resolve $closure
```

It prints the closure's members (`identity` + `rubric` are always-on), the skills pulled by tier, the plugin skills its members bind with the version found, the active P4 gates, and `dependencies_satisfied` with anything missing.
How it resolves: members = the skills whose `metadata.p4.tiers` lists the closure; `depends_on` is three id-spaces — skill names, P4 gate ids, and plugin-qualified skills (`<plugin>:<skill>`) that resolve through the dependencies declared in `.claude-plugin/plugin.json`; `optional_depends_on` enhances but is not required for closure.

**Output:** the resolver's report.
