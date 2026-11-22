---
name: plan-planner
description: How a plan is tracked - in the store's .claude/p4/temportal/plans while it is worked, where plan mode writes it, then moved into temportal/plans/complete/ or temportal/plans/todo/ of the same store. Invoke BEFORE writing, landing, closing, parking, reviving or reading a plan or design doc. Never the repo root, the scratchpad or an ad-hoc directory.
---

# plan-planner: where plans are tracked

## The places

| Place | What sits there | Tracked by |
|---|---|---|
| `.claude/p4/temportal/plans/<plan>.md` | a plan being worked | the store's git, a repository of its own apart from the code repository |
| `.claude/p4/temportal/plans/complete/<plan>.md` | finished plans, never edited again | the store's git only, so closed plans add nothing to the code branches' history |
| `.claude/p4/temportal/plans/todo/<plan>.md` | plans parked on ezexe's word | the store's git only |

A plan is written in plan mode, where Claude Code writes it into the folder `plansDirectory` names, and p4-temportal's settings keeper names the store's `temportal/plans` there.
The file keeps the name plan mode gave it, since a resumed session writes its plan again by that name.
A plan in `plans/` is cleared once it is older than `cleanupPeriodDays`, as Claude Code clears its own plans, so an edit keeps a plan being worked, and a plan to keep unworked is parked.
Nothing in `complete/` or `todo/` is cleared by age, and neither folder takes a lifetime whole.
A session in a git worktree has the worktree's own store, and each retention sweep carries its plans into the main checkout's store, where a plan the worktree closed, parked or revived leaves its old place too.

Read a place without moving anything:

```bash
ls .claude/p4/temportal/plans/complete/ .claude/p4/temportal/plans/todo/
git -C .claude/p4 log --follow -- temportal/plans/complete/<plan>.md
```

A move is one commit of the store, where `git -C .claude/p4 rev-parse --show-toplevel` answers `.claude/p4`, and a plain move of the file where the store is no repository of its own:

```bash
git -C .claude/p4 mv temportal/plans/<plan>.md temportal/plans/<complete | todo>/<plan>.md
git -C .claude/p4 commit -m "<plan>.md moves into <complete/ | todo/ | plans/>, on ezexe's words of <date>: \"<quote>\"" -- temportal/plans
```

- **Close:** STATUS on line 2, as `STATUS: COMPLETED <date>: <sections by short sha>; <what ran where>; <what did not>`; the plan moved into `complete/` byte for byte by the move above; a bullet first under `## [Unreleased]` in `CHANGELOG.md` where the project keeps one, committed in the code repository by its explicit path.
- **Park** on ezexe's word only: `STATUS: TODO <date>: <what landed>; <what did not>`, moved into `todo/` the same way; no changelog line.
- **Revive** on ezexe's word only: moved back from `todo/` into `plans/` in one commit of the store.

The evidence links below are written from `plans/`, where `../../../../` is the project root, and keep that form when the plan moves.

## What every section of a plan holds

- **Intents:** the section opens by listing what it means to change, one line each.
- **Fences:** every edit is a fenced code block, and above it, its intent:
  - **Documented:** the source in detail: the upstream page or file and line, read live or in the checkout, quoted where a quote fits.
  - **Derivation:** in prose, how the approach follows from that source, and why this approach rather than another.
- **No choices for ezexe:** a section avoids, with all the effort it takes, putting a choice to ezexe. Wherever the plan's writer wants to present one, that is the sign the section's planning failed to find the documented approach: the writer goes back to the upstream sources, finds how upstream does it, and writes that approach with its Documented and Derivation, the alternatives named only in the Derivation's "rather than another". A choice reaches ezexe only when no upstream source settles it after that search; it then names the sources searched and what each said.
- **Evidence:** once a section is implemented, its evidence is added to that same section: links to the implemented lines (`[path:N-M](../../../../path:N-M)`) with what ran and its output. Only then does the next section start.
