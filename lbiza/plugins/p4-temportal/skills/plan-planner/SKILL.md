---
name: plan-planner
description: How a plan is written and tracked - written in plan mode into the store's .claude/p4/temportal/plan-planner, the folder plansDirectory names, and moved once it is finished, parked or dropped into its complete/, todo/ or unplanned/ subfolder, which no session reads unless ezexe names the file. Invoke BEFORE writing, looping on, handing to workers, landing, closing, parking, dropping, reviving or reading a plan or design doc. Never the repo root, the scratchpad or an ad-hoc directory.
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
- The folder was `temportal/plans` before p4-temportal 0.3.55, and a session whose Claude Code read that value at its start writes its plan there until it ends, which each sweep then moves into this folder.
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

## The plan loop

A plan is looped until it holds the whole development, and nothing is built before that.

- **A round takes each section in turn:** it researches the section first, in the checkout and on the upstream pages read live, and then writes what it found into that section as its intents, its fences and each fence's Documented and Derivation.
- **Research only reads:** a search or a read across files goes to a subagent that only reads, and the session that holds the plan is the one writer of the plan file.
- **A round ends with one read by a reader that has not seen the writing:** it reads the plan against the sources and the checkout, and names each section that lacks a fence, a source, a file or a check, and each fence that does not fit the tree as it is. The loop's reads are counted by its rounds, and the one second read the skill `sub-agentic` allows after a mend is its rule for what an agent wrote.
- **A round is dry when it changes no fence, no file list and no check.** The loop ends after two dry rounds in a row, or after five rounds, and a plan that ends at five names what is still open at its head.
- **The plan is whole when every edit the development makes is a fence in it,** every section that changes files names its files, what it depends on and its checks, and its section `Distribution` gives each of those sections to a run.
- **Nothing is built before the approval:** until ezexe approves the whole plan, no session that writes is started and no file but the plan is edited.

## Handing a plan's sections to workers

- **Each section names what its worker needs:** a line `**Files:**` with the paths it writes, a line `**Depends on:**` with the numbers of the sections that land before it or `none`, and a line `**Checks:**` with the test files and commands that prove it.
- **A section that changes no file gets no worker:** the context and the distribution are such sections, and each has no `**Files:**` line or says `**Files:** none`.
- **Sections become runs:** sections that share a file or depend on one another are one worker's run, landed in the plan's order, and every other section is a run of its own, each run in a git worktree of its own.
- **The plan's section `Distribution` is a table of the runs:** each run's sections in order, its files, and its role with the model and effort the skill `sub-agentic` gives that role. A section whose fences are whole is landed by an integrator.
- **A worker's brief names the plan file by its full path and its sections by number,** carries their `Files:` line and their checks as what done looks like, and tells the worker to stop and report where a fence does not fit the tree, writing no approach of its own.
- **p4-phi drafts those starts where it is installed:** `phi.py sections <plan file>` prints one start call for each run.
- **A worker never edits the plan file:** its report holds the lines each fence landed at and each check's output, and the session that holds the plan writes them into the section as its Evidence.

## What every section of a plan holds

- **Intents:** the section opens by listing what it means to change, one line each.
- **Fences:** every edit is a fenced code block, and above it, its intent:
  - **Documented:** the source in detail: the upstream page or file and line, read live or in the checkout, quoted where a quote fits.
  - **Derivation:** in prose, how the approach follows from that source, and why this approach rather than another.
- **No choices for ezexe:** a section avoids, with all the effort it takes, putting a choice to ezexe. Wherever the plan's writer wants to present one, that is the sign the section's planning failed to find the documented approach: the writer goes back to the upstream sources, finds how upstream does it, and writes that approach with its Documented and Derivation, the alternatives named only in the Derivation's "rather than another". A choice reaches ezexe only when no upstream source settles it after that search; it then names the sources searched and what each said.
- **Evidence:** once a section is implemented, its evidence is added to that same section: links to the implemented lines (`[path:N-M](../../../../path:N-M)`) with what ran and its output. Only then does a section that depends on it start.
