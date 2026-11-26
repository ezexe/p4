---
name: lib-first
description: How code is developed here - documentation first, then lib first, then generic first. Invoke BEFORE planning or writing any code, and whenever you assist as a developer - a feature, a fix, a script, a hook, a test, a config, a build or a change to a plugin - and before you use an API, a library, a framework, a platform feature or a native Claude Code feature. Learn the current documentation the work rests on and cite it, search the stdlib, the libraries and the project's own modules before you write new code, and shape what you write as a reusable piece with a clear interface and a seam to extend. A plan or a report says for each piece the docs read, the lib reused or built, and the seam.
---

# lib-first: docs learned then applied, a lib reused before code is written, a generic piece built

Apply the rules as written, in this order, for every piece of code the work writes or changes.
Nothing here asks for more than the task needs: a one-line fix reads the one page it rests on and says so in one line.
The code-style rule is whatever the repository's own style skill or CLAUDE.md states.

Claude Code's own documentation is at https://code.claude.com/docs, and the skill `native` says which of its features the p4 plugins already decided on.
A live page wins over anything recalled.

## The rules

1. **Docs learned, then applied.** Before code uses an API, a library, a framework, a platform feature or a native Claude Code feature, read its current documentation, the library's page or source, the platform's reference or the page of https://code.claude.com/docs that names the feature, and cite what the code rests on as a URL or as `file:line`. No implementation from memory where documentation exists. Where the page and the checkout disagree, the page wins and the checkout is brought in step.
2. **Lib first.** Before new code is written, search in this order: the standard library, the project's own modules, a library the project already depends on, then a library it does not yet depend on. Say what was found and why it was used or was not. A library that is not yet a dependency is added only where the task justifies it and the project's own rule for dependencies allows it.
3. **Generic first.** Shape new code as a reusable module: a clear interface, parameters where a case would be hard-coded, and one named extension point, so the next change extends the module and does not rewrite it. Put it where the project keeps its shared code, with the tests of what it does. Do not abstract beyond what the documentation and the task justify: one real caller and one declared seam are enough, and a second case that nobody asked for is not built.
4. **Plans and reports state the three for each piece.** Every piece of a plan, and every piece a report says was done, carries one line as `Docs read: <url or file:line>; Lib: <reused name or built module and why>; Seam: <where it is extended>`. A piece with no documentation to read says `Docs read: none exists` and names what was searched.

## Where it is enforced

- The agents `p4-phi:writer` and `p4-phi:integrator` list this skill in their `skills` field, so its full text is in their context at start, and each returns its pieces by rule 4.
- The skill `plan-planner` of p4-temportal has every section that changes code carry the line of rule 4.
- A skill's description is how Claude decides to load it, so the description above names the moments, planning and writing code, that load it. See more: https://code.claude.com/docs/en/skills.md and https://code.claude.com/docs/en/sub-agents.md
