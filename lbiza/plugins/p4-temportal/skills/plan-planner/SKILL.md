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
- While a plan is worked, the file keeps the name plan mode gave it, since Claude Code fixes one plan file name per session, documents no way to choose it, writes the plan again by that name when the session is resumed, and treats any other file in this folder as a protected path.
- Plan mode gives every plan of one session that same name, so a session's next plan is written under the name of the plan before it, and a plan takes a name made from its own title once it is sorted, by the rule of `Moving a plan`.
- The plan mode file is shaped by the sections below, so the plan ezexe reviews at approval already holds its intents, fences and sources.
- `Ctrl+G` opens the plan in ezexe's editor before approval, and approving it is ezexe's decision on the plan.
- After a compaction Claude Code reads the plan in again from disk, so the plan file holds what the work needs and the conversation does not.
- A plan in this folder is cleared once it is older than `cleanupPeriodDays`, as Claude Code clears its own plans, so an edit keeps a plan being worked, and a plan to keep unworked is parked.
- The folder was `temportal/plans` before p4-temportal 0.3.55, and a session whose Claude Code read that value at its start writes its plan there until it ends, which each sweep then moves into this folder.
- A session in a git worktree has the worktree's own store, and each retention sweep carries its plans into the main checkout's store, where a plan the worktree moved leaves its old place too.

## A planner another session starts

- A session started to write a plan is started in plan mode, by the start tool's `permission_mode` or by `claude --permission-mode plan`, so Claude Code names its plan file in this folder and blocks every other edit, and its turn ends with `ExitPlanMode`, whose card ezexe answers in that session.
- A plan written into this folder under a name of the session's own making is no plan file to Claude Code: `.claude` is a protected path, and Claude Code exempts from it the session's own plan file and no other file here, so each write of such a plan waits on ezexe.
- A session whose plan mode ended with no approval, as when its mode was changed from outside, edits only its plan file and asks ezexe to approve the plan before it edits any other file.
- Prep is the research one session hands to the planner that follows it: the prep session is started in plan mode too, writes the prep as its plan file, and puts `PREP COMPLETE <subject>` on line 1 once the prep is whole, which is how the planner finds it among the files directly in this folder.
- The planner reads the prep as findings to check, and reads each source the prep leans on before a fence rests on it.
- A prep is closed with the plan it fed, by `STATUS: COMPLETED <date>: prep for <plan file>` on line 2 and the move into `complete/`, where it is named by its own title as `Moving a plan` says.

## What a session reads

- A session reads only the plan files directly in `plan-planner/`, the ones not yet put into a category.
- It never opens, lists, searches or hands to a subagent anything in `complete/`, `todo/` or `unplanned/`, unless ezexe names that file or tells it to look there.
- A search across the project leaves those three folders out, by a path or glob that names only the folder's own files.

## Moving a plan

A move is a plain move of the file into its subfolder, under the name its title makes, and nothing in it is cleared by age or takes a lifetime as a whole folder.
The title is the plan file's first heading line, `# ...`.
The title's name is a slug of it: lower case, every run of characters outside `a` to `z` and `0` to `9` turned to one hyphen, the hyphens at either end taken off, cut at the last hyphen that keeps it within 60 characters or at 60 characters where no hyphen does, and then `.md`.
A plan with no heading, or whose slug is empty, keeps the name plan mode gave it.
A prep is sorted the same way, by its own first heading, and keeps the name plan mode gave it where line 1 is its `PREP COMPLETE` marker and no heading follows.
Look before a move: where a place of a plan already holds that name, the plan moves as `<stem>.<n>.md`, where `<stem>` is that name without `.md` and `<n>` the smallest number from 2 that no place of a plan holds with that stem.
A move onto a name that is taken would replace the plan sorted there.
A revive moves the plan back into `plan-planner/` under its sorted name as it stands, and takes a numbered name the same way where a plan there holds that name.
A session that revives a plan in plan mode copies the plan's content into its own plan file, since Claude Code writes only that one file in plan mode.
A plan revived in a git worktree leaves its sorted copy in the main checkout's store until the plan is sorted again, which takes that copy away.

- **Close:** STATUS on line 2, as `STATUS: COMPLETED <date>: <sections by short sha>; <what ran where>; <what did not>`, then the plan moved into `complete/` under its title's name.
- **Park** on ezexe's word only: `STATUS: TODO <date>: <what landed>; <what did not>`, then moved into `todo/` under its title's name.
- **Drop** on ezexe's word only: `STATUS: UNPLANNED <date>: <why it stopped>`, then moved into `unplanned/` under its title's name.
- **Revive** on ezexe's word only: moved back from `todo/` or `unplanned/` into `plan-planner/` under the name it was sorted under, its STATUS line taken out, and in plan mode its content copied into the session's own plan file.

The evidence links below are written from `plan-planner/`, where `../../../../` is the project root, and keep that form when the plan moves.

## The plan loop

A plan is looped until it holds the whole development, and nothing is built before that.

- **A round takes each section in turn:** it researches the section first, in both places every time, the checkout and the upstream pages read live on the web, and then writes what it found into that section as its intents, its fences and each fence's Documented and Derivation.
- **The web research is an agent's own step:** each round sends a research agent to the upstream pages for the section's subject, read live, beside the read of the checkout, and a section whose subject has an upstream page holds a Documented from that page, never from the checkout's docs alone.
- **Where the two speak of the same thing, the upstream page wins:** it holds the latest recommended approach, so the fence follows it, and the section gains a fence that brings the checkout's doc in step with it.
- **The checkout's docs say only what is this code's own:** a fence that writes a doc restates nothing an upstream page says, writes what the code does and why, and links the upstream page as `See more: <url>` where the subject is upstream's.
- **Research only reads:** a search or a read across files goes to a subagent that only reads, and the session that holds the plan is the one writer of the plan file.
- **A round ends with one read by a reader that has not seen the writing:** it reads the plan against the sources and the checkout, and names each section that lacks a fence, a source, a file or a check, and each defect that would make a fence fail to apply, a new test fail, a test that passes now fail, the feature not work in a real session, or leave a worker a decision. The loop's reads are counted by its rounds, and the one second read the skill `sub-agentic` allows after a mend is its rule for what an agent wrote.
- **One round's reader traces the live path of each new hook,** from Claude Code's event through every wrapper script to the handler, since a test that calls a handler by name passes with a gate shut in front of it.
- **A check is a command its worker runs as written:** it names the interpreter by its full path, the folder it is run from and the test files, and the plan's writer runs that interpreter once to see that it holds the test runner.
- **A round is dry when it changes no fence, no file list and no check.** The loop ends after two dry rounds in a row, or after five rounds, and the plan says at its head how its loop ended, and what is still open where it ended at five.
- **The plan is whole when every edit the development makes is a fence in it,** every section that changes files names its files, what it depends on and its checks, and its section `Distribution` gives each of those sections to a run.
- **Nothing is built before the approval:** until ezexe approves the whole plan, no session that writes is started and no file but the plan is edited.

## Handing a plan's sections to workers

- **Each section names what its worker needs:** a line `**Files:**` with the paths it writes, a line `**Depends on:**` with the numbers of the sections that land before it or `none`, and a line `**Checks:**` with the test files and commands that prove it.
- **A section that changes no file gets no worker:** the context and the distribution are such sections, and each has no `**Files:**` line or says `**Files:** none`.
- **Sections become runs:** sections that share a file or depend on one another are one worker's run, landed in the plan's order, and every other section is a run of its own, each run in a git worktree of its own.
- **The plan's section `Distribution` is a table of the runs:** each run's sections in order, its files, and its role with the model and effort the skill `sub-agentic` gives that role. A section whose fences are whole is landed by an integrator.
- **The table's last row is the merge:** the runs' branches are merged into one branch, and the plugin's whole test folder is run once there before a push, since each run proved only its own files.
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
