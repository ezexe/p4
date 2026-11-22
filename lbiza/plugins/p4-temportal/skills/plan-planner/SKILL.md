---
name: plan-planner
description: How a plan is written and tracked - written in plan mode into the store's .claude/p4/temportal/plan-planner, the folder plansDirectory names, and moved once it is finished, parked or dropped into its complete/, todo/ or unplanned/ subfolder, which no session reads unless ezexe names the file. Invoke BEFORE writing, landing, closing, parking, dropping, reviving or reading a plan or design doc. Never the repo root, the scratchpad or an ad-hoc directory.
---

# plan-planner: where plans are tracked

## The places

| Place | What sits there | Who reads it |
|---|---|---|
| `.claude/p4/temportal/plan-planner/<plan>.md` | a plan being worked, written in plan mode | every session working on it |
| `.claude/p4/temportal/plan-planner/complete/<plan>.md` | finished plans, never edited again | only the session ezexe directs to that file |
| `.claude/p4/temportal/plan-planner/todo/<plan>.md` | plans parked on ezexe's word | only the session ezexe directs to that file |
| `.claude/p4/temportal/plan-planner/unplanned/<plan>.md` | plans ezexe dropped before they were planned through | only the session ezexe directs to that file |

The folder is p4-temportal's own, the plugin that creates it, and the store's git tracks it apart from the code repository.

## Plan mode writes the plan

- A plan is written in plan mode, where Claude Code writes it into the folder `plansDirectory` names, and p4-temportal's settings keeper names this folder there.
- The file keeps the name plan mode gave it, since a resumed session writes its plan again by that name.
- The plan mode file is shaped by the sections below, so the plan ezexe reviews at approval already holds its intents, fences and sources.
- `Ctrl+G` opens the plan in ezexe's editor before approval, and approving it is ezexe's decision on the plan.
- After a compaction Claude Code reads the plan in again from disk, so the plan file holds what the work needs and the conversation does not.
- A plan in this folder is cleared once it is older than `cleanupPeriodDays`, as Claude Code clears its own plans, so an edit keeps a plan being worked, and a plan to keep unworked is parked.
- A session in a git worktree has the worktree's own store, and each retention sweep carries its plans into the main checkout's store, where a plan the worktree moved leaves its old place too.

## What a session reads

- A session reads only the plan files directly in `plan-planner/`, the ones not yet put into a category.
- It never opens, lists, searches or hands to a subagent anything in `complete/`, `todo/` or `unplanned/`, unless ezexe names that file or tells it to look there.
- A search across the project leaves those three folders out, by a path or glob that names only the folder's own files.

## Moving a plan

A move is a plain move of the file into its subfolder, and nothing in it is cleared by age or takes a lifetime as a whole folder.

- **Close:** STATUS on line 2, as `STATUS: COMPLETED <date>: <sections by short sha>; <what ran where>; <what did not>`, then the plan moved into `complete/`.
- **Park** on ezexe's word only: `STATUS: TODO <date>: <what landed>; <what did not>`, then moved into `todo/`.
- **Drop** on ezexe's word only: `STATUS: UNPLANNED <date>: <why it stopped>`, then moved into `unplanned/`.
- **Revive** on ezexe's word only: moved back from `todo/` or `unplanned/` into `plan-planner/`, its STATUS line taken out.

The evidence links below are written from `plan-planner/`, where `../../../../` is the project root, and keep that form when the plan moves.

## What every section of a plan holds

- **Intents:** the section opens by listing what it means to change, one line each.
- **Fences:** every edit is a fenced code block, and above it, its intent:
  - **Documented:** the source in detail: the upstream page or file and line, read live or in the checkout, quoted where a quote fits.
  - **Derivation:** in prose, how the approach follows from that source, and why this approach rather than another.
- **No choices for ezexe:** a section avoids, with all the effort it takes, putting a choice to ezexe. Wherever the plan's writer wants to present one, that is the sign the section's planning failed to find the documented approach: the writer goes back to the upstream sources, finds how upstream does it, and writes that approach with its Documented and Derivation, the alternatives named only in the Derivation's "rather than another". A choice reaches ezexe only when no upstream source settles it after that search; it then names the sources searched and what each said.
- **Evidence:** once a section is implemented, its evidence is added to that same section: links to the implemented lines (`[path:N-M](../../../../path:N-M)`) with what ran and its output. Only then does the next section start.
