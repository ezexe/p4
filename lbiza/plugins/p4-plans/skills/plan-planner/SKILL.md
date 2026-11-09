---
name: plan-planner
description: Where every plan, design doc, RFC, spec, migration or rollout plan, or persisted investigation write-up lives (the repository's plans directory while in flight, then complete/ or todo/ on its archive branch) and its write-once lifecycle - tests first, an evidence section checked against the tree, close-out onto the archive. Invoke BEFORE writing or revising one; BEFORE a section's implementer lands it; BEFORE closing, parking or reviving one; BEFORE reading a closed or parked plan; and BEFORE launching any agent that writes, lands, triages or closes a plan (flight-ops.md). Overrides the default location - never the repo root, the scratchpad or an ad-hoc directory.
---

# plan-planner: where planning documents live

## Settings first

Run this from the repository root before anything else; its values fill the names in `backticks` below:

```bash
python3 -I <this skill's directory>/scripts/settings.py
```

It reads the `plans` section of `.claude/p4/p4.json` (every p4 plugin's settings; written with every default when missing) over the defaults: `plans_dir`, `archive_branch`, `archive_worktree`, `changelog`, `flights_dir`, `store_dir`, `tests`, `exclusive`, `documented`, `code_style_rule`, `role_models`, `owner_title`, and `link_prefix` (from `plans_dir` up to the root).
`owner_title` names the person whose words clear work; below it is "the owner".

## Where a plan lives

A plan lives at `plans_dir`/`<TOPIC>_PLAN.md` (or `_DESIGN.md`); a path the owner names wins; say where you put it.
A planning document is any durable "here is the approach" markdown that is not itself a shipping artifact: implementation, migration or rollout plans, design docs, RFCs, ADRs, specs, persisted investigation write-ups.

| Place | What sits there | Who opens it |
|---|---|---|
| `plans_dir` on the code branch | plans in flight, written once | any agent, for the plan it works |
| `complete/` on `archive_branch` | finished plans; append-by-move only: no edits, banners, status churn or link fixes | read only; the one move out is into `todo/`, on the owner's ruling that the plan was never finished |
| `todo/` on `archive_branch` | plans parked until the owner sends for them | only when the owner names one or asks for the todo list |

When `archive_branch` is null, a finished plan is deleted by the close-out commit and its history is git's and the changelog's; parking is then refused.

## The archive branch

`archive_branch` is an orphan branch on `origin` holding only `complete/` and `todo/`, so closed plans add nothing to the code branches' history.
It is never kept on disk: it is attached at `archive_worktree` (excluded in `.git/info/exclude`) only to move a plan in or out, and removed in the same turn.
Reading needs no attach: `git fetch origin <archive_branch>`, then `git show origin/<archive_branch>:complete/<PLAN>.md`; `git ls-tree --name-only origin/<archive_branch> todo/` lists the todo plans.
Every attach runs in this order, `<moves>` being the step's own:

```bash
git fetch origin <archive_branch>
git worktree add <archive_worktree> <archive_branch>
git -C <archive_worktree> merge --ff-only origin/<archive_branch>
<moves>
git -C <archive_worktree> commit -m "<message>"
git -C <archive_worktree> push origin <archive_branch>
git worktree remove <archive_worktree>
```

Its commit message names the plan and the move, the owner's words that asked for it with their date, and `(flight <id>)` when a flight did it.

## Writing a plan

Name it for what it plans. Its first lines:

```markdown
# <TOPIC>_PLAN: <one sentence saying what the plan changes>

Written <YYYY-MM-DD HH:MM> on <machine>, after commit `<git rev-parse --short HEAD>`.
Nothing built, run, staged or committed; every fence is unverified until the owner asks for a build.
```

A plan written by a flight adds `Writer: <model>, flight <id>.` as the next line.

- **Sections** are cut by disjoint airspace (the paths each may change), so every section can take off at once (flight-ops.md).
- **The flights table** `| Section | Airspace | Pilot | Builds on |` gives each section its row; "Builds on" is the plan's base commit, unless the section needs another's files, which its row states with that section's home commit.
- **Rollup:** an edit several sections want in one file (a list entry, a README row) is a `### Rollup` part of each section that wants it; the tower lands it at the section's home, never in the section's airspace.
- **Fences:** every step lays out its edits as fenced code, one fence per edit, the file (and function or region) named on the line above, tagged with the file's language; the code as it will read after the edit, or a `diff` fence when the surroundings matter; complete, with no `...` standing in for code. A step with no code edit says so in one line.
- **Links:** every `file:line` link is `[path:N](<link_prefix>path:N)` or `[path:N-M](<link_prefix>path:N-M)`, read from the current file, and never rewritten when the plan moves onto the archive.
- **Decisions:** every decision a plan leaves the owner ends with a `Documented:` sentence naming the upstream page read live (from `documented`, or the standard the decision rests on) and what it settles, or `Documented: none`. Only what the documentation does not settle is the owner's call.

## Tests first, then the least code

A section that changes behaviour opens with its tests, before any implementation fence: each case states one behaviour the code must have as its caller sees it, through the unit's public face alone.
A test the change retires or rewrites is laid out first the same way, and the cases that stay are named as what stays true.
The implementation fences follow and are the least code that passes those cases: a line no case needs is not written, and a design the cases cannot tell apart from a simpler one takes the simpler one; where a ruling of the owner's, not a case, holds a line, the step says which.
A section that changes no behaviour (a rename, a split, a move) adds no test and names the existing cases that hold it.
A behaviour-changing section comes home through two flights, red then green (flight-ops.md, "Red and green").

## The evidence section

Each section's implementer writes its entry right after its implementation and returns it in its report; the tower writes it into the flight record (`flights_dir`/`<id>`/`evidence.md`) and appends it at the section's home to `# <PLAN>: every layer in source`, last in the plan, entries in the plan's order.
An entry is a `- ` bullet (or `## ` heading) naming its section or step, all its `path:N` links on that first line, a fenced snippet of those lines beneath it; a short sha where source cannot show it (a build installed, files deleted); what source cannot prove (a run, a measurement) said plainly with what it rests on; a dropped step in one line with the commit or ruling that settled it.
After each append, the checker runs from the root and must print `done: 0 finding(s)`:

```bash
python3 -I <this skill's directory>/scripts/check_evidence.py <plans_dir>/<PLAN>.md .
```

It checks that every link under the evidence heading names an existing file and a range within it, and that every fence under a bullet appears line for line (whitespace-trimmed) in one of the bullet's linked files (`diff` fences and lines holding `...` excepted); it prints `MISSING`, `RANGE`, `GREPLINE`, `NOFENCE` or `MOVED` per miss.
On the owner's words a plan closes without the section, its STATUS line quoting them.

## Completing a plan, in this order

1. **Fold-ins:** `git log --format='%h %ad %s' --date=short --grep='<PLAN>'` and `git status --porcelain`; every edit no section lays out gets a section of its own after the last section, dated, with the owner's words that asked for it and its fences.
2. **Re-read**, by an evidence finder: every link and snippet of the evidence re-anchored to the current tree; older evidence is a guide to where to look, never a source of line numbers; code that no longer exists is marked removed by the commit that removed it.
3. **The evidence section** last in the file: every section present, in order, or named as waived.
4. **The checker** until it prints `done: 0 finding(s)`; no placeholder added inside a fence; fences balanced (`grep -c '^```' <PLAN>.md` is even).
5. **STATUS** on line 2, under the H1: `STATUS: COMPLETED <YYYY-MM-DD HH:MM> (<each section's landing by short sha; what was built or run and where; what was not run>)`.
6. **Onto the archive**, by the attach above, copying the plan byte for byte (links untouched): `cp <plans_dir>/<PLAN>.md <archive_worktree>/complete/<PLAN>.md`, `git -C <archive_worktree> add complete/<PLAN>.md`; message `<PLAN>.md completes into complete/, on the owner's words of <date> ("<quote>")`.
7. **The changelog bullet**, first under `## [Unreleased]` in `changelog`: `- **The <subject> plan closed on <date>: <what is now true>.** <What landed, section by section, with short shas>. The plan moved to <archive_branch>:complete/<PLAN>.md (commit <sha>). Run on <machine> on <date>: <what ran and its result>. Not run: <the checks not made and where>.`
8. **Remove it from the code branch:** `git rm <plans_dir>/<PLAN>.md`; `git status --porcelain` names only the plan and `changelog`; one commit by explicit paths, `git commit -- <plans_dir>/<PLAN>.md <changelog>`, naming what ran where and `Not run: ...`. The plan is never touched again.

## Parking in todo/

On the owner's word only, and adding nothing to the changelog: the plan gets `STATUS: TODO <date> (<one line: what landed, what did not>)` under its title and one footer, then is copied byte for byte into `todo/` by the attach and `git rm`'d from the code branch in one commit.

- `# <PLAN>: left to complete`: one entry per section in order; landed → its `path:N` or commit; not done → what is left, what it waits on, what it would touch now.
- `# <PLAN>: unplanned`: the reading line (`Read from the working tree on <date> after <sha>.`), why it is unplanned (the owner's words), what of it landed, what it would take to revive, its open items.

Out of `todo/`, on the owner's word only: resumed (written back to `plans_dir`, removed from `todo/` in one attach, finished in new sections), completed as it stands or ruled dropped (brought back and closed as above), or rewritten afresh.

## Launching agents for a plan

Before launching any agent that writes, lands, triages or closes a plan, read [flight-ops.md](flight-ops.md) and the sub-agentic skill. Each agent flies on its role's model from `role_models`, chosen by what it decides:

| Role | What it decides |
|---|---|
| writer | content the tree does not hold yet: a plan, a section, a fence, a decision with its sources; its brief carries the scope, never quietly narrowed, widened or swapped |
| integrator | lands fences as written and its section's evidence entry, as a red or a green flight when the section changes behaviour |
| cross_check | the landing's one re-read, from the plan, the staged diff and the files it names, nothing of the pilot's report |
| evidence_finder | line numbers, snippets, inventories, re-anchoring evidence: no decision, even when it edits the plan |

## What does not go here

- The README and other living reference docs are maintained in place; write-once is for plans only.
- Skills go in `.claude/skills/<name>/SKILL.md`; throwaway notes in the session scratchpad; code, tests and scripts in the repository's own trees.
