# A fresh p4 marketplace, 2026-11-01

A design, not a build. Everything under `lbiza/` is deleted and replaced by what this document describes; git history keeps the old marketplace. Nothing here is a contract the model reads: the main context sees at most a few plain lines, and every piece of bookkeeping is a hook or a script.

## The purpose

The owner's statement of what the phi model is (17:30): "the phi model is what the anthropick model would be of it were trained exactly on the repository and not had to relearn it as work on something it needs to address from nill".

So: the model is what Claude would be if it had been trained on this repository, so that a session does not relearn the repo from nothing each time. "The repository" means all of it: the owner's rulings, corrections and vocabulary in `.claude/p4/`, the model's own memory, and the repository itself, its files, their symbols and headings, its history and its conventions, and which of those each kind of task has needed before. Section 0 still governs how that is delivered: as a few added lines, silent when nothing applies, never an override. The measure of success has three parts (section 8.5): short turns read right, less re-exploration before the first relevant file is opened, and nothing worse than the built-in on any category.

The owner's words that shape it, in order of weight:

- 16:53, the governing rule: "the biggest point is to not override and make claude code desktop aps and how it works already possibly worse but to only enhance it where evidence shows it will".
- 16:51, the goal: "the goal is to teach the phi model not need extensive engineered prompts to accomplish tasks that are simple back and for conversational markers".
- 16:38: "scrap it all start from a fresh p4 marketplace no skills no agents no roboto. Take the phi models optimizations we learned keep the memory and scratchpad overrides into p4 so its trackable make the phi model the vault memory quick recall for p4 subagent main agent so it becomes a model trained on the repo".
- 16:45: "everything in lbiza/* deleted the design goes into fresh lbiza/* and its based on the successful tests that found improvements and the most optimal design of the phi model acting as the ai model trained on the repository its installed on".
- 16:47, on labels: "not just fable label over stores / store labels edited to optimal fable dictionary the store is to label and learn its users vocabulary".
- 16:49, on the dictionary: "only map it if it caused confusion not if you were able to work it out already without user followup".
- 17:25, on recency: "run update on the phi model design to remember to keep up with the desipline to train on data thats more updated the the data you were trained on".
- 17:26, on the teacher: "and its trained on decisions the lates most capable model of the moment would make based on if it would have been trained at that point".
- 15:29, on where code goes: "its for when a frag turns into code the repo works/relies/depends/works better with".
- Earlier: "the entire point of the session open hook ceremony is also integral fo the phi models to work properly" — the ceremony's labels must keep coming, from somewhere as good or better.

Every part below names the measurement it rests on: `.docs/p4/findings.md` (findings 1–25, the Opus 5.5 audit of 2026-11-01), ezexe/phi `.docs/p4/nested-store.md` ("Replications on Colab", 2026-10-29), and the label-health counts from `scripts/session/store_lessons.py`. A part no measurement supports is marked **untested**, ships off or minimal, and gets a test in section 8.

## 0. The governing rule: enhance, never override

The default is Claude Code and the desktop app exactly as they ship: their memory, their closing (the wrap-up box and the question panel), their task list, their tools, their style. Nothing in the marketplace replaces, restates or competes with a built-in behavior. The audit is the reason: the four old always-on contracts took Opus 5.5 from 0.672 to 0.639 while neutral text of the same length cost nothing (findings 21–22), so what was injected hurt by its content.

Four gates, applied to every plugin and hook in this document:

1. **Earned or off.** A part ships on only where a measurement shows the built-in plus the part beats the built-in alone. Each hook's row in section 3 names its measurement. Without one it ships off, as an opt-in with its test, or not at all.
2. **Storage moves only.** The two overrides that stay (memory in `.claude/p4/memory/`, the notebook in `.claude/p4/scratchpad/`) change where files live, not how the model behaves. Section 8.1 says how that is checked: no words about them reach the model beyond what the built-in would have printed, and no reply mentions them unprompted.
3. **Additive and silent.** Recall adds lines next to the owner's message and adds nothing when the ranker is not confident. 0 lines is the common case (finding 5). Nothing is ever removed, rewritten or blocked by a hook, except the two opt-in asks of section 3.2.
4. **The first test.** Built-in plus marketplace never scores below built-in alone on any task category of `overrides_suite.py`, at a cheap judge's cost (section 8.2). A part that fails is removed, not tuned.

## 1. The goal and its measure: short turns read right, without engineered prompts

A back-and-forth with the owner is mostly short turns that carry a whole intent: "Started it", "Keep going", "how?", "Interrupted", "125$ possible?", "1 opus 1 fable 2 sonnet?", "you shouldnt need the github tokens your logged in from here correct?". Each meant something specific where it was said: a go-ahead, a cost question, a plan choice, a check. The old marketplace taught the model to read these with 45,000 characters of contract at session start (finding 2) and a judged operator launch that happened in 18–26% of sessions (finding 15). The goal is a model trained on this repo's own history that reads them right with one or two added lines, or none.

The training data already exists in every store, and the hooks keep producing it without a launch:

- every session's dispatch rows (4,239 on AudioPlugin-p4, 321 on p4-p4, 108 on ap-p4_mac): the message, its time, what was done about it (`addressed:`), and whether it was a repeat or a reversal (`state:`, `match:`);
- the corrections, retractions and missed details the owner needed when a turn was misread (113, 32 and 27 across the four repos, finding 13), and the 49 repeats the barrier caught;
- the old prompt hook's "known short command" path (`vlds_hooks.py`, `known_short`): a message of at most 5 words whose normalized token the store's owner corpus holds at least twice is a known command, and the hook prints how often and what was done the last time. That is the seed; section 4.4 is its grown form.

What the model returns for a short turn is a recall, not a prompt: one or two lines drawn from that owner's own history, in ordinary words, for example `- you have said "keep going" 6 times; last time (2026-10-29) it was taken as: continue the running CEF build as configured, nothing to change`. The vocabulary dictionary (section 5.3, misreadings only) covers the markers that caused confusion.

The measure of success is section 8.3's held-out test: the newest sessions' short turns, scored on whether the built-in plus recall reads them as `addressed:` says they were read, against the built-in alone. The success line is fewer injected words and more short turns read right, together with the two other parts of 8.5. Nothing in the design is justified by anything else.

## 1a. Newer than the model

The repo-trained model earns its place by knowing what the answering Claude model cannot: what changed after that model's training data ends. Newer versions, APIs, model ids, tool behavior, the repo's current state, and the owner's rulings since. The discipline (the owner's 17:25 direction) is to prefer and train on data newer than the answering model's training data, and to treat the model's own prior as stale whenever the repo holds something newer and verified.

Why it matters, from this project: the claude-api skill carries a drift table of API shapes that changed in 2025–2026 and that a model's prior gets wrong; the old verification-discipline plugin's whole point was that a stale prior must be re-checked before it drives an action; and today's live measurement settled a fact the docs left open, that the built-in loads `MEMORY.md` up to 25,000 bytes, cut at whole lines. None of that is in any model's training data, and all of it is the kind of line recall should print.

What it changes, each detailed where it lands:
- the store: a fact carries when it became true or was last checked, and can be marked as contradicting a likely training-era prior (3.5);
- the ranker: a per-model feature for "newer than the answering model's cutoff", from a small cutoff table, shipped only if `eval` earns it (4.3);
- training: the newer verified version of a fact is the positive; a label resting on an entry a newer entry contradicts is dropped; Fable's label edits are told the rule (5.2);
- a test: tasks whose right answer depends on a repo fact newer than the model's training, scored recall-plus-built-in against built-in alone (8.4).

**The teacher, under the same discipline** (the owner's 17:26 direction): the labels are the decisions the most capable model of the moment would make if it had been trained up to the task's date.

- The teacher is not a fixed model. One line in `models/config.json`, `teacher-model:`, names it; today `claude-fable-5-1`. When a more capable model ships, the owner changes the line, and the cutoff table in `ranker.py` (4.3) carries the new model's cutoff beside the others.
- The teacher decides as if trained up to that point. Its own training stops at its cutoff, so every label-edit and dictionary prompt (5.2, 5.3) carries the repo's entries newer than that cutoff that bear on the task: the facts marked in 3.5, the rulings and corrections dated after it. The prompt states the task's date, so the teacher judges what was true then, not only what is true now.
- Labels carry their teacher. `labels.tsv` and `label-edits.md` record the teacher model id and the edit's date on every row (5.2). When the teacher changes, the newest tasks are re-edited first, within the budget; the older teacher's edits stay until replaced; `eval` compares the re-edited batch against the old one on held-out data before it replaces it, as raw against edited today (5.6).
- The answering model's prior is never the reference, and neither is the teacher's. Where the teacher and a stored label disagree about a fact newer than the teacher's cutoff, the stored, verified entry wins (`facts.md` with `verified:` and `checked:`); the teacher's job there is judging relevance, not recalling facts. The prompt says so.

Section 0 still governs: the lines are additive, silent when nothing newer applies, and removed if they cost a category.

## 2. What the evidence settles

| evidence | what it settles |
|---|---|
| all four old contracts 0.639 vs built-in 0.672; neutral text of the same length 0.672 (findings 21, 22) | always-on text costs by its content; the design injects nothing always-on by default |
| memory override alone: 89% of answers use p4 words; without it 23% (finding 23); 74% under all four (finding 1) | the memory contract goes; recall lines are ordinary words and the jargon rate is a test |
| simple answers 37 → 360 tokens, 0.8 → 0.0 (finding 22) | silent on an ordinary message: 0 lines, no head line |
| lesson tasks: old contracts 0.42 vs built-in 0.35 (finding 24) | the repo's own corrections help when they reach the answer; that is the one thing recall must keep |
| operator ran in 18% / 26% / 0% / 0% of sessions (finding 15) | every label source is a hook or an offline batch: 100% of sessions |
| JSON ranker 0.379 vs word overlap 0.313; no `.pt`, pretraining or φ structure helped (Colab) | the stdlib logistic ranker of `pick_model.py`, alone; no torch, server or deltas |
| two teachers agree at F1 0.754, with the store's labels at 0.50–0.53; a model trained on Fable's labels predicts the store's labels better than one trained on the store's (0.199 vs 0.186); Opus's labels did not (Colab) | the store's labels are kept as the source and edited by Fable 5.1, not replaced (the owner's 16:47 direction, section 5.2); Opus is not a teacher |
| `phi.py standing` printed only `form:` rulings; three repos use `scope:` (finding 11); every live rule is 26,799 chars on AudioPlugin-p4 (finding 12) | rules reach a session by recall against the message, never as a block |
| six LIVE rulings masked as FREED on ap-p4_mac (finding 17); the held branch's fix masks only entries dated before the retraction | the migration recomputes every status with that rule and must show the six as LIVE |
| mechanical row close: 76% → 93% rows completed on a copy of AudioPlugin-p4 (PR ezexe/p4#18) | the Stop hook completes message rows from `last_assistant_message` |
| mind-reader's watcher dies with its hook on macOS (finding 20) | no detached processes; hooks finish in their timeout or run `async: true` |

## 3. The marketplace layout

```
lbiza/
  .claude-plugin/marketplace.json      four plugins, in this order
  plugins/
    p4-memory/                          Claude Code's memory, stored in the repo (carried over)
      .claude-plugin/plugin.json
      hooks/hooks.json  hooks/p4_memory.py  hooks/run-hook.sh  hooks/test_p4_memory.py
    p4-scratchpad/                      the notebook, tracked; two opt-in asks
      .claude-plugin/plugin.json
      hooks/hooks.json  hooks/scratchpad.py  hooks/run-hook.sh  hooks/test_scratchpad.py
    p4-recall/                          the model trained on the repo
      .claude-plugin/plugin.json
      hooks/hooks.json  hooks/run-hook.sh
      scripts/p4.py                     one script, subcommands in 3.4
      scripts/ranker.py                 the features and the fitter, from pick_model.py
      scripts/store.py                  entries, ids, the status rule, the dictionary
      scripts/migrate.py                old layout → new, dry by default
      scripts/teacher.py                the paid batches; never run by a hook
      scripts/test_*.py
    p4-plans/                           two skills, no hooks (added 2026-11-09, below)
      .claude-plugin/plugin.json
      skills/plan-planner/SKILL.md  skills/plan-planner/flight-ops.md
      skills/plan-planner/scripts/settings.py  skills/plan-planner/scripts/check_evidence.py
      skills/sub-agentic/SKILL.md
      tests/test_p4_plans.py
```

The first three plugins have no `skills/`, no `agents/`, no `commands/`.
p4-plans is the one exception, added on 2026-11-09 on the owner's words ("adopting and migrating them it into the p4 marketplace generically and being able to remove them from the repos listed handwritten skills"): AudioPlugin's handwritten plan-planner and sub-agentic skills, made generic, their repository-specific values moved into the `plans` section of `<project>/.claude/p4/p4.json`, and `flights/` kept in place by the migration instead of archived, since the flight loop writes it and phi_store trains on its `plan.md` files.
The handwritten skills leave AudioPlugin only after the probe in the shared experiments project (`experiments/keep_or_go`) scores the generic skills with the settings within about 5 points of the handwritten ones.

`run-hook.sh` is the old plugins' wrapper: find `python3`, run with `-I`, exit 0 on any failure so a broken hook never blocks a call.

### 3.1 p4-memory (carried over; a storage move)

`p4_memory.py` as it is today (358 lines, its test): the per-project memory lives in `<project>/.claude/p4/memory/`, tracked by the p4 repo; AppData holds a pointer `MEMORY.md`.

| hook | matcher | prints at most | earned by |
|---|---|---|---|
| SessionStart | — | the p4 `MEMORY.md` index, which the built-in would have printed from AppData; one notice line when a file was moved or a conflict kept | the owner's word (storage move); gate 2's check in 8.1 |
| PostToolUse | `Write\|Edit` | one line when a write into AppData was moved into p4 | same |
| Stop | — | nothing | same |

The pointer text in AppData says only where the memory is and to write there; it carries no instruction about behavior. The old `skills/memory/SKILL.md` is dropped. Memory files are indexed by recall (4.1), so the model's own notes are part of what it trains on.

### 3.2 p4-scratchpad (src-fragger's scratchpad half)

| hook | matcher | prints at most | earned by |
|---|---|---|---|
| SessionStart | — | nothing; one line only when `.claude/p4/scratchpad/.out/.gitignore` was re-seeded or ignorable files were moved into `.out/` | the owner's word (storage move) |
| SessionStart, opt-in | — | one line per file under `.claude/p4/src/` that the project's tracked code, build, docs or CI names: "`x.py` is used by `CMakeLists.txt`; it belongs in the repo" (the held branch's `repo-uses`, finding 8) | **untested**; off by default, on with `P4_SCRATCHPAD_ASKS=1`; test in 8.1 |
| PreToolUse, opt-in | `Write\|Edit\|Bash` | an ask (never a deny) before a code file is written to `/tmp`, the harness scratchpad or `.claude/p4/scratchpad/`, naming where it belongs: the repo if the repo will use it, else `.claude/p4/src/` | **untested**; same switch; the parser and cases from `frag_gate.py` and its test |

The split by worth (15:29, finding 8): code the repo works with goes into the repo, where the repo keeps that kind of code; `.claude/p4/src/` holds only what the repo doesn't use. Dropped: the contract, the skill, the per-session `src/` trees, the register and `sindex/`.

### 3.3 p4-recall (the center)

| hook | event / matcher | timeout | prints at most | earned by |
|---|---|---|---|---|
| layout | SessionStart `startup\|resume\|clear\|compact` | 15 s | nothing. Initializes `.claude/p4/` and its git repo once, rebuilds the index if a store file changed. Only when the owner has pinned rules: a block `Standing rules from the owner:`, ≤ 1,500 chars (4.6) | silence costs nothing (finding 22); the pinned block is measured in 8.2 before it ships on |
| recall | UserPromptSubmit | 10 s | 0 lines for an ordinary message. Otherwise at most 5 lines, no head line, each `- <date> <kind>: <text ≤ 160 chars> (<file>:<line>)`; for a short turn, the history line of 4.4 | finding 24 (lessons 0.42 vs 0.35) pending 8.2; the short-turn test 8.3 |
| subagent recall | PreToolUse `Agent` | 10 s | nothing to the main context; `updatedInput` with the same `prompt` plus the lines under `Notes from this repo's memory:` (4.7) | same measurements, on the subagent's task |
| subagent recall, fallback | SubagentStart `.*` | 10 s | `additionalContext` with the same lines; built only if the PreToolUse road fails its test (4.7) | same |
| close | Stop | 30 s | nothing. Completes the message row, writes the turn's usage labels and dictionary signals, rebuilds the index if needed | PR #18: 76% → 93% rows completed mechanically |
| close (subagent) | SubagentStop `.*` | 30 s | nothing. Usage labels for the lines served to that subagent | same |
| train | Stop, `async: true` | — | nothing. `p4.py train --if-owed` (5.5); never a paid step | the ranker's 0.379 (Colab); the floor in 5.6 |

Every hook reads the harness payload on stdin, resolves `.claude/p4/` from `CLAUDE_PROJECT_DIR` or `cwd`, and exits 0 with one notice line on any failure.

### 3.4 `p4.py` subcommands

| subcommand | what it does | who runs it |
|---|---|---|
| `index` | rebuilds `models/index.json` from the store, memory and `src/` when any is newer than the index | layout and close hooks |
| `query --text … [--session …]` | the recall: short-turn history, dictionary expansion, BM25 candidates, ranker, threshold, plain lines | the recall hooks, tests, the suite |
| `row open\|close` | stamps a message row; completes it from the reply | recall and close hooks |
| `serve-log` | records what was served to which turn or subagent | the recall hooks |
| `usage` | the turn's usage labels from the served lines, the reply and the transcript | the close hooks |
| `signals` | the turn's dictionary signals: a correction, retraction, missed detail, repeat or follow-up, with the exchange that proves it | the close hook |
| `labels [--from-pools]` | lists the label set with counts per source; imports old pools | migration, tests |
| `train [--if-owed]`, `eval` | fits, evaluates held-out, promotes past the floor, appends `models/eval.tsv`; `eval` writes nothing | the async Stop hook, by hand, tests |
| `dictionary check` | every entry's two tests (5.3); turns a failing entry off | `train`, tests |
| `check` | store health: counts, statuses, orphan labels, the jargon rate of what recall would print | tests, migration |
| `migrate [--apply]` | old layout → new (section 6) | by hand, once per repo |
| `teacher edit-labels\|dictionary\|extract` | the paid batches (5.7), each with `--fake` and `--max-usd` | by hand, with a key |

### 3.5 The files under `.claude/p4/`

`.claude/p4/` stays its own git repository, nested in the project and excluded from the project's index by one line in `.git/info/exclude`, as the old layout hook did and the owner's rulings on AudioPlugin confirm ("the p4 repo is nested in the project").

```
.claude/p4/
  .gitignore                 seeded once: scratchpad/.out/, models/served/, models/*.tmp, __pycache__/, the binary types; the owner's edits win
  memory/                    p4-memory: MEMORY.md and the topic files Claude Code writes itself
  scratchpad/                the notebook, tracked; scratchpad/.out/ ignored
  src/                       code the repo does not use; flat; made on first save, not seeded
  store/
    rules.md                 the owner's rulings (ruling, owner-words, scope, form, status, time, pinned, plain)
    corrections.md           a reading that steered work and was wrong (key, time, match, meant, delta) and a detail the owner had to ask for (asked, time, omitted)
    retractions.md           what the owner freed (freed, time, cause, owner-words, swept, lesson)
    facts.md                 claims verified against a source (claim, source, verified, since, checked, time, supersedes, prior)
    vocabulary.md            the owner's terms that caused confusion, each with its proof (5.3); user-editable
    messages/<s8>.md         one file per session: every owner message (fingerprint, time, arrival, state, addressed, match, freed-by, resembles)
  models/
    index.json               derived: every entry tokenized, with its id and its dictionary expansions
    config.json              teacher-model: (claude-fable-5-1 today), and nothing else the owner has not set
    ranker.json              weights, threshold, round, the floor it passed
    labels.tsv               the training set: task id, entry id, label, source, weight, time, teacher (model id), edited (date)
    labels-raw.tsv           the store's labels before editing, kept for the comparison in 5.2
    label-edits.md           every keep / drop / add Fable made, with its reason, by task
    tasks.tsv                the tasks (id, session, time, text, kind: first | new | short)
    eval.tsv                 one row per round: counts per source, held-out numbers, dictionary check, promoted or kept old
    served/                  ignored: what each turn or subagent was shown, until its usage labels are written
  archive/                   migrated material recall does not index (section 6); made by migrate, not seeded
```

Field names inside entries are the old store's (`ruling:`, `match:`, `meant:`, `freed:`, `state:`, `addressed:`), for training continuity (finding 4). File names are plain words, and the hook translates at the boundary: `rules.md` prints as `rule`, `corrections.md` as `correction` or `missed detail`, `retractions.md` as `retracted`, `facts.md` as `fact`, `memory/` as `memory`, `messages/` as `earlier message`, `vocabulary.md` as `your word`.

A fact's recency fields (1a): `since:` is the date the fact became true where known (a release date, a commit, a ruling's time), `checked:` the date it was last verified against its `source:`, `supersedes:` the id of the older fact it replaces, and `prior:` marks a fact that contradicts what a training-era model would likely assume, with the kind: `prior: version | api-shape | model-id | limit | behavior`. Examples from this project: `claim: the built-in loads MEMORY.md up to 25,000 bytes, cut at whole lines; source: live measurement 2026-11-01; since: unknown; checked: 2026-11-01; prior: limit` and `claim: the current model ids are claude-fable-5-1, claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5; prior: model-id`. The close hook fills `checked:` when a fact is verified again; a fact without `checked:` within 90 days prints with `(last checked <date>)` so the reader knows its age. The extraction batch sets `prior:` where the claim names a version, an API field, a model id or a numeric limit; the owner edits it like any field.

An entry's id is `<file>:<time>:<sha8 of its first field's text>`, stable when lines move. The status rule, from the held branch's finding-17 fix: an entry is FREED only by a retraction whose `freed:` head matches it, or by shared owner-words with a retraction dated after the entry; `SPENT` is a field, never inferred.

## 4. The recall

### 4.1 What is indexed

Every entry of `store/*.md` except `vocabulary.md` (which expands queries instead), every section of `memory/*.md` (one entry per heading), every row of `store/messages/*.md` that has `addressed:`, and the one-line head of each file under `src/`. Not indexed: `scratchpad/`, `archive/`, FREED and EXPIRED entries (kept, never recalled; the retraction that freed them is recalled in their place). AudioPlugin-p4 holds about 4,900 indexable entries; the other three under 600.

### 4.1a The repository itself

A model trained on the repository knows the repository, not only the notes about it. Indexed mechanically, free, by `p4.py index --repo`, rebuilt incrementally from `git ls-files` and `git log <last indexed commit>..HEAD`, so a rebuild after one commit touches only that commit's files:

- **paths and headings**: every tracked file's path as one entry; for Markdown, each heading as an entry (path, heading text, the first line under it); for code, each top-level definition and class by a cheap regex per language (`def`/`class` in Python, `function`/`class`/`export` in JS and TS, `fn`/`struct`/`impl` in Rust, functions and classes by signature in C/C++/Java/C#/Swift, `func` in Go, shell functions), as `path:line symbol`; for build files (`CMakeLists.txt`, `*.cmake`, `Makefile`, `package.json` scripts, `pyproject.toml`), each target or script name;
- **history**: each commit's subject line and the files it touched, newest first, one entry per commit (`<date> <sha8> <subject>; touched: <paths>`), capped at the last 2,000 commits;
- **conventions**: `CLAUDE.md` and `CLAUDE.local.md` at every level, `AGENTS.md`, `README*`, `CONTRIBUTING*`, `.github/*.md`, indexed by section like any Markdown.

Excluded: anything `.gitignore`d (build output, caches, `scratchpad/.out/`), LFS pointers, binaries by the `.gitignore` type list, vendored and generated code (`node_modules/`, `third_party/`, `vendor/`, `*.min.*`, `*.generated.*`, files whose first line says `generated`, any directory a `.p4ignore` names), and any file over 512 KB. The index stops adding file entries at 50,000 and says so in `check`, keeping the newest-touched files first.

These entries print as `- file: <path> — <symbol or heading>` and `- commit <date>: <subject> (<paths>)`, never a file's contents. The `kind=` feature tells the ranker a file entry from a rule, and the repo labels of 5.1a teach it which files a kind of task has needed. The index is a cache, ignored by git (`models/index.json` already is).

### 4.2 The store format

Markdown files of dash-led entries, one field per line, the shape `local-storage.md` and `ledger.md` already use and `store_lessons.py` already parses. Each file starts with three lines in ordinary words (what it holds, who writes it) and no schema block with placeholders.

### 4.3 The ranker and its features

The logistic ranker of `pick_model.py`: stdlib, hashed features in a 2^18 space, AdaGrad SGD, 25 epochs, positives weighed to balance; 0.379 R-precision held-out on AudioPlugin-p4 against 0.313 for word overlap. Features kept as they are: `bm25`, `bm25-rank`, `head-bm25`, `file-rank`, `file-top6`, `top10`, `overlap`, `rare`, `length`, `file=`, `kind=`, `state=`, `age`, `recent`, `no-time`; the tokenizer kept (camelCase and snake_case split, stop words out, dotted versions kept).

Added, each **untested** until `eval` shows the set at or above the kept features:
- `dict-hit`: the query matched a vocabulary entry and this candidate is one the entry points at, or shares the entry's `means:` terms;
- `used=<n>`: how many earlier turns used this entry (log-scaled), from the usage labels;
- `edited=<n>`, `cited=<n>`: how many earlier tasks edited, or read and then cited, this file (log-scaled), from the repo labels of 5.1a;
- `corrects`: a correction whose `match:` overlaps another candidate, so it outranks what it corrected;
- `newer-than-model` (1a): set when the entry's `since:` (or its `time:` when it has none) is later than the answering model's training cutoff, read from a small table in `ranker.py` keyed by model id (`claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, with the cutoff month each; unknown model → the table's oldest cutoff), the model id taken from the hook payload where the harness gives it and from `CLAUDE_MODEL` otherwise; `prior=<kind>` set from the fact's `prior:` field. Both are features the ranker learns a weight for, never a hand-set boost, so the eval decides; a subagent's recall uses the `model` field of the Agent call when it names one.

The threshold is chosen on held-out tasks for the highest F1 with precision ≥ 0.6: a wrong line costs accuracy (finding 21), so the threshold leans toward silence.

Dropped, by the Colab replications: the `.pt` ranker, its anchor and `.phid` deltas, the node tree and effort tiers, `phi_serve`, pretraining on the store.

### 4.4 Short turns: the history line

A message of at most 5 words (the old `SHORT_WORDS`) runs the short-turn road first:

1. Its normalized token (the old `_token`: lower-cased, punctuation out) is looked up in `messages/*.md` across every session. Seen at least twice before with a completed row (the old `KNOWN_SHORT_MIN`): one line, `- you have said "<message>" <n> times; last time (<date>) it was taken as: <addressed, ≤ 120 chars>`. When the last three readings differ, the line says so: `taken as: <a> (×3), <b> (×1)`.
2. Not seen: the dictionary (5.3) expands any of its words that caused confusion before, and the ranker runs over the expanded query. A match prints as an ordinary line; the entry's `means:` prints as `- your word "<term>" has meant: <means> (vocabulary.md:<line>)` only when the dictionary entry itself is what the ranker selected.
3. Nothing: silence.

The resemblance rule of the old hook (`BARRIER_JACCARD` 0.5 over the fingerprint tokens, identical-only below 3 tokens) adds, for any message, one line when an earlier message of this session resembles it and its row is completed: `- an earlier message like this one (<time>) was answered: <head>`. This is the "repeat" benefit of finding 10 without a judged barrier.

### 4.5 How a query runs

1. The hook reads the message (UserPromptSubmit `prompt`, or the Agent call's `prompt`).
2. `p4.py query` loads `models/index.json` (about 30 ms for 4,900 entries), runs 4.4 for a short message, expands the query through the dictionary, scores BM25 over all entries, takes the top 200 as candidates, builds features, applies `ranker.json`. Without a trained ranker (a fresh repo) BM25 alone picks, showing only lines that share at least two rare terms with the message.
3. Entries above the threshold, at most 5 in all including the history and repeat lines, strongest first, at most 2 from one file. Each line: date, kind, the entry's `plain:` text when it has one and its text otherwise, cut at 160 characters, and `(<file>:<line>)` so one Read opens it whole. A repo entry prints as a starting point with its label count: `- for this, start at src/foo/bar.cc (edited for 4 similar tasks)` or `- commit 2026-10-29 a1b2c3d4: CMake 4.4 floor (CMakeLists.txt, scripts/BuildCEF.cmake)`.
4. Served ids go to `models/served/<prompt id or agent id>.json` for the usage labels.
5. Every line is checked against the suite's jargon list before printing; a line that would print an invented word and has no `plain:` is counted by `check` (target under 10%, the built-in's rate being 5%).

Latency budget: 300 ms on AudioPlugin-p4, asserted by a test. The output never approaches the 10,000-character hook cap.

### 4.6 The always-on block

None by default (gate 1). The owner can pin a rule (`pinned: yes` in `rules.md`, or saying so, which the extractor records); then the layout hook prints pinned rules verbatim under `Standing rules from the owner:`, newest first, ≤ 1,500 characters. The validation run measures `recall` against `recall+pinned` (8.2); whether the block ships on at all is open question 1.

### 4.7 How the main agent and subagents receive it

Main agent: `UserPromptSubmit` injects `additionalContext` beside the prompt; the docs say it "can't replace the prompt; it only injects additionalContext alongside it" (https://code.claude.com/docs/en/hooks, read 2026-11-01).

Subagents, two facts from the same page decide the road:

- `PreToolUse` can rewrite a tool's input: "`updatedInput` | Modifies the tool's input parameters before execution. Replaces the entire input object, so include unchanged fields alongside modified ones." The Agent tool's documented `tool_input` is `prompt`, `description`, `subagent_type`, `model`; `Agent` is listed among the tools PreToolUse matches; no tool is named as excluded from `updatedInput`. The page does not say in words that the Agent tool's `prompt` is rewritable, so the primary road is built and tested first: matcher `Agent`, return `hookSpecificOutput` with `permissionDecision: "allow"` and `updatedInput` equal to the input as received with the lines appended to `prompt`. Build step 6 settles it (a `claude -p` run whose subagent transcript must contain the appended lines).
- `SubagentStart` injects but cannot see the task: its input is `agent_id` and `agent_type` only, its output "`additionalContext` | String added to the subagent's context at the start of its conversation, before its first prompt." The fallback, if step 6 fails: read the parent transcript (`transcript_path` is a common field) backwards to the last `Agent` tool_use whose `subagent_type` equals `agent_type`, query on its `prompt`, return the lines. A fallback because that read is a guess when several agents of one type launch at once.

Also relied on: "Hooks from settings files, managed policy settings, and plugins also run inside subagents. When a subagent calls a tool, tool events such as PreToolUse and PostToolUse fire the same configured hooks as in the main conversation, and the input carries the agent_id and agent_type", so a subagent that launches an agent gets the same recall; and `SubagentStop` receives `agent_transcript_path` and `last_assistant_message`, which the usage labels read. `UserPromptSubmit` does not fire for a subagent's own prompt, so a subagent gets recall once, at launch, which fits one task and one prompt. Explore and Plan skip CLAUDE.md but not hooks.

## 5. Training: the model trained on the repo

Per repo: its own `store/`, `vocabulary.md`, `labels.tsv`, `ranker.json` and `eval.tsv`, all in that repo's `.claude/p4` git repository, so every round and every dictionary edit is a diff the owner can read and revert.

### 5.1 Label sources, and where the ceremony's labels went

| old source (finding 3) | new source | runs in | why as good or better |
|---|---|---|---|
| pool picks: one haiku child per store file in 18–26% of sessions; the operator's pass; roboto's audits | **the store's labels, edited by Fable** (5.2): the store labels every task first, mechanically; Fable reviews, keeps, drops and adds with a reason | hooks + an offline batch | the store's raw labels agree with teachers at 0.50–0.53 (Colab), so they are edited rather than trusted; they now exist for 100% of sessions instead of 18–26% |
| barrier verdicts (`state:`, `match:`) judged by the operator | the close hook writes `state: FRESH` and `resembles: <row id>`; the extraction batch labels ECHO / SUPERSEDED offline from the row pair and the reply | hook + offline | the mechanical half is what the old hook did; the judged half moves from a launch that mostly did not happen to a batch that covers every flagged row |
| completed rows (`addressed:`) | the close hook writes `addressed:` from `last_assistant_message`'s first paragraph | Stop hook | 76% → 93% on AudioPlugin-p4 (PR #18) |
| (none) | **usage labels**: a served entry is `used` when the reply or the turn's Edit/Write/Bash inputs contain two of its rare terms or a path it names that the prompt did not; else `unused`. **Untested**: weight 0.3 until the agreement test (8.1) passes | Stop, SubagentStop | free, every turn, main agent and subagents |
| (none) | **misses**: a new correction whose `match:` names a reading an existing entry would have prevented becomes a positive label for that entry on that turn's task, and a dictionary signal (5.3) | close hook | the store's own failures become labels, not only lessons |
| (none) | **short-turn labels**: every completed short row is a task whose positive is its own earlier reading (the row the history line would have shown) when the two `addressed:` agree by the resemblance rule | close hook | the data of section 1, free |
| old pools and audit files | imported once (`labels --from-pools`), source `pool`, then edited like the rest | migration | nothing already learned is lost |

### 5.1a The labels that teach it the repo

Every session's transcript already shows which files it read, searched and edited for which task, and what it found to be the answer. The close hook's `usage` step turns that into free labels, the practical meaning of "trained on the repo": for this kind of task, these files and entries were the ones that mattered.

From the turn's transcript (`transcript_path`, or `agent_transcript_path` on SubagentStop), per task (the message row): every `Read`, `Grep`/`Glob` hit path, `Edit`/`Write` path and `Bash` path argument is a candidate; its label and weight:

| what the session did with the file | label | weight |
|---|---|---|
| edited it (Edit, Write, a Bash write) | positive | 1.0 |
| read it and then cited it (its path or a symbol from it appears in the reply or in a later edit) | positive | 0.7 |
| read it and dropped it (never cited, never edited) | negative | 0.3 |
| a search hit never opened | negative | 0.2 |

The task text is the message row's fingerprint; the entries are the repo index's path, symbol and commit entries (4.1a), so a file label also lands on the symbols the turn's edits touched (by line range) and on the commits that last touched the file. Rows go to `labels.tsv` with source `repo`. Imported for history by `labels --from-transcripts`, over every transcript under `~/.claude/projects/<slug>/` that a migrated message row names (the old `backfill_dispatch.py` on ap-p4_mac already read transcripts this way), so the four repos start with labels from every session they have, free. **Untested** as a feature set: it ships through `eval` like the rest, with the repo-label subset reported separately (held-out tasks: does the ranker's top 5 contain a file the session edited), and the re-exploration measure of 8.5 is its check.

### 5.2 The store labels, edited by Fable (the owner's 16:47 direction)

The store is the source and stays the source; Fable does not compete with it. For each task in `tasks.tsv`:

1. **The store labels first, mechanically.** A task with an old pool takes the pool's picks. A task without one (most sessions never ran the ceremony) takes the history label: the entries whose rare terms the turn's `addressed:` text, its corrections and its edited paths share, by the same rule as the usage labels. Written to `labels-raw.tsv`, source `store`.
2. **The teacher edits.** `teacher edit-labels` sends the model `teacher-model:` names (Fable 5.1 today; "Fable" below means that model) the task and its date, the repo's entries newer than the teacher's cutoff that bear on it (1a), the store's picks, and the candidates (union of BM25 top 60 and ranker top 60, each distilled to 140 characters), and asks for each stored pick `keep` or `drop` with a reason, and for `add` any candidate that bears on the task with a reason. The reply is written to `label-edits.md` (by task, every decision and reason, the teacher's model id and the date) and the edited set to `labels.tsv`, source `store+edited`, with the same `teacher` and `edited` columns. A dropped pick stays in `labels-raw.tsv`.
   **On a teacher change** (`teacher-model:` edited): `teacher edit-labels --re-edit` takes the newest tasks first, as many as `--max-usd` allows; a task keeps the older teacher's edit until a newer one replaces it, and `eval` scores the re-edited batch against the old edits on held-out raw labels before it is trained on (5.6).
3. **The edit must earn its place.** `eval` trains on raw and on edited labels and scores both on held-out store labels, the Colab method: edited must be at or above raw (Colab: 0.199 vs 0.186 for Fable's labels on AudioPlugin-p4). A batch below that is held, not trained on, and listed in `eval.tsv`.

**The recency rule in training** (1a), applied by `labels` before every round and stated in Fable's edit-labels prompt: when two facts cover the same claim (one `supersedes:` the other, or the same `source:` with different `checked:` dates), the newer verified one is the positive for any task dated after it, and the older is a negative; a label that rests on an entry a newer entry contradicts is dropped and listed in `label-edits.md` with `dropped: superseded by <id>`. A stored label never beats a newer verified fact. Fable is told, in the prompt, that the task's date is the reference and that an entry newer than the answering model's cutoff is to be kept when it bears on the task even if the model's own knowledge would answer differently.

The reasons in `label-edits.md` are what the owner reads to see what Fable thinks the store got wrong; they are also where the dictionary's seeds come from when the reason names a word the owner uses.

### 5.3 The vocabulary dictionary (misreadings only, the owner's 16:47 and 16:49 directions)

The store's job is to label and learn its user's language, not to follow a fixed one. The entry rule is evidence of a miss, not frequency: a term gets an entry only when it caused a misreading the owner had to correct. A term the model understood the first time, with no follow-up, gets no entry, however unusual.

**Format**, `store/vocabulary.md`, user-editable, one entry per term:

```
- term: the mac branch thing
  means: the branch 0.0.1-apple&win&mac_mac, cut under 0.0.1-apple&win&mac
  because: 2026-11-01 11:18 — you wrote "rename it to the mac branch thing" and the session used 0.0.1-1.0.0_mac; you then wrote "yes switch under 0.0.1-apple&win&mac but branch 0.0.1-apple&win&mac_mac"
  source: correction (corrections.md: mac-branch-name)
  points-at: rules.md:2026-11-01 11:18:a1b2c3d4
  added: 2026-11-01 13:30
  status: on
```

`means:` is in the owner's own words where the follow-up supplies them, and otherwise Fable's one clause. `because:` cites the exchange that proves the confusion: the owner's words before and after, with their times. `points-at:` names the entries the term should find. `status: on | off` (off: kept, not expanded, after a failed check).

**The five signals**, each mechanical, written by the close hook's `signals` step as a pending entry (`means: (pending)`) with its `because:` already filled:

| signal | where it comes from | the term |
|---|---|---|
| correction | a new `corrections.md` entry with `match:` and `meant:` | the words of the misread message that are rare in the index (idf > 3) or unseen, and that appear in neither `match:` nor the common vocabulary |
| retraction | a new `retractions.md` entry with `owner-words:` | the same rule on the message the retraction answers |
| missed detail | a `corrections.md` entry with `asked:` / `omitted:` | the rare words of the message before the ask |
| repeat or reversal | a row the resemblance rule flagged whose `state:` the extraction batch set to ECHO or SUPERSEDED | the rare words the repeated message and the first share |
| follow-up | the owner's next message in the session that starts with a correction marker (`no`, `not`, `i meant`, `i mean`, `should have`, `incorrect`, `wrong`, `again`) or that resembles the prior message at Jaccard ≥ 0.5 within 10 minutes | the rare words of the prior message. **Untested** as a detector; its precision is a test in 8.1 |

**Growth**: mechanical, every turn, from those signals; Fable only writes `means:` for pending entries, in batches of 20 (`teacher dictionary`), from the `because:` quotes alone. A term already in the dictionary gets its new `because:` appended, never a second entry. The owner edits the file freely; an edited entry carries `added:` by the owner's date and is never overwritten.

**Seeding**: `migrate` mines the four repos' existing corrections (113), retractions (32), missed details (27) and repeats (49) with the same rule; the follow-up signal is run over the migrated message rows. Terms found: expected one to two hundred.

**How an entry is used**: at query time and in training, a message whose tokens contain an entry's `term` is expanded with the entry's `means:` tokens at weight 0.5 and the `dict-hit` feature is set on the candidates it `points-at:`. So "the mac branch thing" finds the ruling that names the branch.

**How an edit is tested**, so it cannot silently hurt recall (`dictionary check`, run on every training round and after any edit, free):
1. **It fixes its confusion**: a query on the original misread message (the first quote in `because:`) now ranks an entry in `points-at:` in the top 5. An entry that does not is set `status: off` and listed.
2. **It does no harm**: over the held-out set of messages that already worked (served lines that were used, with no follow-up), the top 5 is unchanged for at least 95% of them with the entry on; an entry that changes more is set off and listed.
3. The round's `eval.tsv` row carries the counts (entries on, off, fixed, harmed), so a regression from the dictionary shows beside one from the ranker.

### 5.4 Short-turn training (section 1)

The short rows are the largest label set the stores hold and they need no teacher: a completed short row is a task, its earlier readings are its positives (5.1). `eval` reports the short-turn subset separately: held-out newest sessions, whether the history line's reading (the last completed `addressed:` of that token) matches the held-out row's `addressed:` by the resemblance rule. This is the free half of the measure; the paid half is 8.3.

### 5.5 When and how the model trains

`train --if-owed` runs in the async Stop hook: owed when ≥ 10 labels landed since the last round and the last round is older than an hour; it never runs a paid step. Training is `ranker.fit` over every label weighted by source (`store+edited` 1.0, `pool` 0.7, `short` 1.0, `usage` 0.3 until 8.1 raises it, `miss` 1.0); evaluation is leave-one-task-out R-precision, recall@20 and precision at threshold, `pick_model.py eval`'s numbers, so the 0.379 baseline is comparable. A round takes seconds to a minute on the largest store, which `async: true` absorbs.

### 5.6 How a regression is caught

- A round is promoted only when held-out R-precision ≥ the last promoted round's − 0.02, precision at threshold ≥ 0.6, the short-turn subset not below the last round, and `dictionary check` reports no newly harmed entry left on. Otherwise `eval.tsv` says `kept old` and why.
- The first round after migration must reach ≥ 0.36 on AudioPlugin-p4 from the imported pool labels alone, proving the port before any new label enters.
- `check` reports label health as `store_lessons.labels` does: sessions, rows, completed, flagged, labels per source; a migration or upgrade that loses a row, a completion or a label is refused (the notebook's section 13 rule).
- Every teacher batch is compared with a 20-task second opinion from Opus 5.5 (the only use of Opus): Fable's edits agreeing below 0.65 with it (Colab: 0.754) hold the batch for the owner.

### 5.7 The paid steps within budget

Prices per million tokens: Fable 5.1 $10 in / $50 out; Opus 5.5 $4 / $20; Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50.

| step | model | per unit | units | cost |
|---|---|---|---|---|
| edit the store's labels (5.2): task + stored picks + ≤ 120 candidates ≈ 5,500 in, 500 out | Fable 5.1 | ≈ $0.08 | AudioPlugin-p4 100 tasks (newest first), p4-p4 40, ap-p4_mac 12, phi-p4 4 = 156 | **≈ $12** |
| second opinion on 20 tasks (5.6) | Opus 5.5 | ≈ $0.03 | 20 | **≈ $1** |
| dictionary meanings (5.3): 20 pending entries per call, ≈ 4,000 in, 1,200 out | Fable 5.1 | ≈ $0.10 | ≈ 10 calls for the seeded entries | **≈ $1** |
| extraction: rules, corrections, retractions, ECHO/SUPERSEDED verdicts and `plain:` rewrites of jargon entries from the message rows of sessions the ceremony never ran in (≈ 3,500 rows), 30 rows per call | Sonnet 5.5 | ≈ $0.03 | ≈ 120 calls | **≈ $4** |
| the short-turn test (8.3) | Opus 5.5 answers, Haiku 5.5 judge | ≈ $0.006 per answer | 150 turns × 2 pathways × 2 seeds | **≈ $4** |
| the validation run (8.2) | Opus 5.5 answers, Haiku 5.5 judge (Sonnet 5.5 if Haiku fails the grader check) | ≈ $3 per pathway-seed | 3 pathways × 2 seeds, built-in cached | **≈ $20** |
| the newer-than-the-model test (8.4) | Opus 5.5 answers, Haiku 5.5 judge | ≈ $0.006 per answer | 12 tasks × 2 pathways × 2 seeds = 48 | **≈ $0.30** |
| total | | | | **≈ $42**; reserve $28 inside the $70 cap; $60 of the $130 untouched |
| per teacher change (1a), not in the total: re-edit the newest tasks, same prompt as the edit step | the new teacher | ≈ $0.08 per task at Fable's prices; a new model's price sets it | as many as the owner approves; 50 tasks ≈ $4, all 156 ≈ $12 | **$0 until the owner approves it** |

Every paid script has `--fake` for tests and `--max-usd`, counting the input with the API's token counter before spending, as `overrides_suite.py` does. Hooks never call the API; the owner runs each batch (open question 2).

Why this loop is the best the evidence supports: the ranker is the only model that beat word overlap; the store's labels are the only ones that exist for every session, and editing them by the one teacher shown cleaner is the only correction with a measured gain; the dictionary is confined to proven misreadings and each entry is tested both ways; usage and short-turn labels scale with use, not with a launch rate, and usage is gated until measured; everything else tried (pretraining, trees, `.pt`, φ) was flat or worse.

## 6. Migration from the old layout and stores

`p4.py migrate` runs dry by default and writes `archive/migration-<date>.md`: per kind, the count found, the count written, every entry it could not place by old path and line, and the dictionary seeds found. `--apply` writes. The four clones under `.claude/p4/scratchpad/.out/p4-colab/overrides-1-work/stores/` are the fixtures; the live `~/code/AudioPlugin/.claude/p4` (the ap-p4_mac repository's checkout) is migrated last, in place, and committed by the owner.

| old | new | the check that proves nothing was lost |
|---|---|---|
| `sessions/*/vlds/local-storage.md` rulings | `store/rules.md`, fields kept, status recomputed by 3.5's rule | `store_lessons.live_rules` count on the old tree == LIVE count in the new; the six ap-p4_mac rulings of finding 17 read LIVE; every `owner-words:` string found verbatim |
| `ledger.md` corrections (113) | `store/corrections.md` | count of `meant:` equal; each `key:` once |
| `tombstones.md` (32) | `store/retractions.md` | count of `freed:` equal; each `owner-words:` present |
| `briefs.md` detail-asks (27) | `store/corrections.md` entries with `asked:` / `omitted:` | count of `omitted:` equal |
| `data-store.md` claims | `store/facts.md` | count equal; `source:`, `verified:` kept |
| `index.md` guide-loop rules | `archive/index-rules.md`, not indexed; a rule with `owner-words:` or a user ruling at its root also to `rules.md` with `source: index` | archive count equal; the owner-rooted subset listed for review (open question 3) |
| `dispatch.md` rows (4,239 + 321 + 108 + 1) | `store/messages/<s8>.md`, every field kept | `store_lessons.labels` equal before and after: rows, completed, open, judged; the 49 ECHO/SUPERSEDED rows still so |
| `recall-pool.md` per session (24 on AudioPlugin-p4) | `labels-raw.tsv` rows, source `pool`, each pick resolved to an entry id | `labelled_pool` count == tasks imported; 100% of picks resolved, the unresolved listed (a FREED pick resolves to its retraction) |
| `models/labels/*.tsv` audits (p4-p4) | `labels-raw.tsv`, source `pool` with `reader:` kept | row counts equal |
| `models/pick-model.json`, `shadow.tsv`, `train.log`, `*.phid` | `archive/models/` verbatim; a fresh round from the imported labels | the fresh round ≥ 0.36 on AudioPlugin-p4 |
| `models/dispatch-model.json`, its 244 rows | the rows live on in `messages/`; the model retrained as the resemblance scorer only if open question 5 says keep | zero repeats written FRESH, as before |
| corrections, retractions, misses, repeats (221 signals) | `store/vocabulary.md` pending entries with `because:` filled | every signal produced an entry or is listed as yielding no rare term |
| `sessions/*/src/<task>/*`, `frags.md`, `sindex/` | `src/<s8>-<task>/…`; register lines become each file's one-line head comment; repo-used frags listed for the owner, not moved | file count equal; the list names each frag's users (`compdb.py` already left for `scripts/python/`) |
| `memory/` | untouched (p4-memory owns it) | tree identical |
| `scratchpad/` | untouched; ignorables moved into `.out/` | tracked file count unchanged |
| `flights/` | untouched (p4-plans' flight loop owns it; phi_store trains on its `plan.md`) | tree identical |
| `session-storage.md`, `virtual.md`, `logger.md`, `mind-reader.md`, `sessions/*/mind-reader/`, `mrindex/` | `archive/<same path>` verbatim, not indexed | byte-identical; nothing deleted before the dry report shows zero unplaced entries |
| `vindex/`, `sindex/`, `idb/`, `phi-index.md`, `.sessions`, `.gc-heads`, `.turn-close`, `ranker.server.json`, `ranker-base.pt` | dropped: derived files the new scripts rebuild, or the retired `.pt` | the `## recall` section of `vindex/phi-index.md` copied into the report so no setting vanishes silently |
| `.git/info/exclude` line, `.claude/p4/.git` | kept | `git -C .claude/p4 status` clean after `--apply` and one commit |

Stores on the φ register with an empty keyspace (finding 14) migrate from their hot files; the keyspace is ignored. Finding 7 (a worktree hook outside p4 blocks writes under `.claude/p4/**`) is not p4's; the report says so when the project dir is a worktree.

Jargon in old entries: 74% of old answers leaked p4 words because the contracts spoke them, and many entries do too ("frag", "pour", "tombstone", "operator"). The extraction batch writes a `plain:` field beside the original of every entry matching the suite's jargon list; recall prints `plain:` when present; the original stays.

## 7. What is dropped, and why

| dropped | finding |
|---|---|
| the four always-on contracts (emission gate, src-fragger, memory override, gc contract) | 21, 22: together they lower Opus below the built-in; 1, 23: they drive the vocabulary bleed; 2: 45k characters followed in part; gate 0.1 |
| the vlds skills (gate, guide, inspector, gc, looper, recall, acts-widget), mister/roboto with its agent, commands and skills, envelope- and verification-discipline | the owner's word; 1, 2; 3 (the ceremony's cost); gate 0.1: never measured alone |
| the operator, the pool and its children, the conductor, flight-ops | 15: 18–26% launch, 0% on two repos; 3; Colab: the store's labels need editing, which a batch does for every session |
| the judged dispatch barrier, the detail-ask pickers, the pre-ask gate, the acts popup and page | 4 (a hook cannot judge; the mechanical half completes 93%); 6 (two closing protocols collided with the app's own panel); gate 0.1: the app's closing is the closing |
| mind-reader | 20; its scores were never a label |
| the keyspace (`idb.py`), the φ register, pours, compaction, `normalize.py`, `partition.py`'s per-session trees | 9; 14; the recall reads flat files and one index JSON |
| the `.pt` ranker, `phi_serve`, the node tree, `.phid` deltas, pretraining | Colab |
| `phi.py standing` and the standing block, the owner-voice digest | 11; 12; the digest is replaced by the history line, which prints only for the message at hand |
| the SessionStart one-liner and every notice that is not a storage move's | gate 0.1: silence costs nothing (finding 22) |
| the legacy plugin | git history keeps it |

Demoted, not dropped: finding 24 shows the set without the emission gate at 0.574 against 0.639 with it, so some of its rules help. The text is gone; a 10-line plain rewrite of its testable rules (complete code, no placeholders, say what was not done) is a validation pathway, and if it beats the built-in it ships as pinned rules in `rules.md`, never as a contract (open question 4).

## 8. The test plan

### 8.1 Plugin unit tests (pytest, stdlib, no network, under a minute)

The first test, gate 0.4, runs offline with `--fake`: the suite's fake client over every pathway proves the harness; the paid form is 8.2.

Gate 2's check, that the storage moves are invisible: (a) the SessionStart output of p4-memory equals, line for line, what the built-in prints from a memory directory holding the same files, plus at most one notice line; (b) the AppData pointer contains no sentence in the imperative except where to write; (c) in the smoke session and in every suite answer, no reply mentions `.claude/p4`, "p4" or "scratchpad" unless the prompt did (a grep, the suite's jargon scan extended by those words); (d) the p4-scratchpad SessionStart prints nothing on a clean tree.

p4-memory: `test_p4_memory.py` as it is. p4-scratchpad: the gate's path parser and ask cases from `test_frag_gate.py`; `notebook-out`; `repo-uses` against a fixture repo whose `CMakeLists.txt` names a file in `src/`; both asks silent when the switch is off.

p4-recall, on the four fixtures migrated into a temp directory:
- `migrate`: every count in section 6, the six finding-17 rulings LIVE, zero unplaced entries, byte-identical archives, `store_lessons.labels` equal.
- `index`: rebuilt only when a store file is newer; ids stable across a line insertion.
- `query`: deterministic; 0 lines for "hi" and for a message sharing no rare term; ≤ 5 lines, ≤ 2 per file, ≤ 160 chars; under 300 ms on AudioPlugin-p4; no jargon-list word in any printed line; the history line for a token seen twice, none for once; the repeat line for a resembling completed row, none for an open one.
- hooks: each output's JSON shape against the docs; `updatedInput` carries every original Agent field; exit 0 and one notice on a corrupt store; the pinned block cut at 1,500.
- `row open|close`: the row on open; `addressed:` on close from a sample `last_assistant_message`; a notification or agent message stamped complete on arrival.
- `usage`: used when a served entry's path appears in an Edit input, unused otherwise. The agreement test, once the first Fable batch exists: usage labels against the edited labels on the 20 second-opinion tasks; F1 ≥ 0.6 raises the usage weight to 1.0.
- `signals`: on p4-p4's 19 corrections and ap-p4_mac's 5, each yields a pending entry whose `because:` quotes the owner's words before and after; the follow-up detector's precision on the message rows, judged by hand on 30 flagged pairs, must be ≥ 0.7 to stay on.
- `dictionary check`: a fixture entry that fixes its message passes; one that changes the top 5 of a working message is set off; a hand edit by the owner survives a round untouched.
- `train` / `eval`: imported pools reproduce ≥ 0.36 on AudioPlugin-p4; a round below the floor is not promoted; edited labels ≥ raw on held-out raw labels; the short-turn subset reported.
- `teacher --fake`: each batch's prompt built and parsed back; `--max-usd` stops before spending.
- the live smoke test, by hand and in the notebook: `claude -p` with the marketplace installed on a fixture repo; one prompt that must trigger a line, one that must not, one `Agent` launch whose transcript under `~/.claude/projects/…/subagents/` must contain `Notes from this repo's memory`. This settles 4.7.

### 8.2 The first gate, measured: `overrides_suite.py`

The suite measures a context against the built-in stand-in on 64 general tasks (code, fences, honesty, simple, format, judgment, memory) plus the lesson tasks mined from each repo's store. One small change (in the build order): `--context-dir` accepts `<pathway>.<task id>.md` beside `<pathway>.md`, so the recall pathway carries the lines `p4.py query` prints for each task over the migrated store the task came from (usually none for the general tasks, which is the point).

Pathways: `builtin` (cached, free); `=recall`; `=recall+pinned` (a 1,500-character block of each repo's `form:` rulings); `=emission-plain` (the 10-line rewrite). Two seeds, Opus 5.5 answers; the judge is Haiku 5.5 after `--check-graders` passes on it (every reference answer passes, every bad one fails), Sonnet 5.5 otherwise. About $3 per pathway-seed in answers at the audit's rates (finding 25), the judge under $0.20: **≈ $20**.

Pass, per gate 0.4: on every category, `=recall` within noise of `builtin` on both seeds (never below by more than 0.02 on a category of 8 or more tasks), simple tasks at the built-in's 0.8 with output tokens within 1.5× of 37, jargon rate ≤ 10%, and lessons ≥ 0.42, the old contracts' score (finding 24). A pathway that fails a category is removed from the default, not tuned. `=recall+pinned` and `=emission-plain` ship on only if they beat `=recall` where it matters without losing a category.

### 8.3 The measure of success: short turns held out

From each repo's `messages/`, the newest sessions' short rows (≤ 5 words, completed): about 150 across the four repos, held out of training. For each, the context is the built-in stand-in plus the two preceding rows of that session (their fingerprints and `addressed:`, as the conversation the turn arrived in); the pathways are that context alone and that context plus the recall lines for the turn. The model answers in one short paragraph what it would do; Haiku 5.5 judges whether it matches the held-out `addressed:`. Two seeds, Opus 5.5 answering: 150 × 2 × 2 = 600 answers at ≈ $0.006, **≈ $4**.

Pass: recall reads more short turns right than the built-in alone on both seeds, and never fewer, with at most 2 lines injected on average. The free half (5.4) runs on every training round so the number is watched between paid runs.

### 8.4 Newer than the model, measured

About 12 tasks whose right answer depends on a repo fact newer than the answering model's training, taken from what this project already holds: the current model ids and their prices (the suite's `PRICES` table), the 25,000-byte whole-line `MEMORY.md` cut, the hooks' 10,000-character output cap and its file-and-preview behavior, the `SubagentStart` input fields, the `.phid`/`.pt` retirement (vlds 0.0.77), the CMake 4.4 floor and the `_mac` branch rulings from ap-p4_mac. Each task is a question a 2025-trained prior answers wrong, with the right answer and a `bad` answer for `--check-graders`, in the suite's task format with category `newer`. The facts are entered in each fixture's `facts.md` with `since:`, `checked:` and `prior:`.

Pathways: the built-in alone, and the built-in plus the recall lines for the task; Opus 5.5 answers, Haiku 5.5 judges; two seeds; **≈ $0.30**. Pass: recall-plus-built-in answers more of them right on both seeds and never fewer; the `newer-than-model` and `prior=` features ship only if `eval` on the labelled tasks (the 12 here plus every `prior:` fact's own task) is at or above the kept feature set, as 4.3 says. The free half runs in 8.1: a unit test that a fact with `supersedes:` outranks the fact it replaces for a task dated after it, and that `labels` drops a label resting on the superseded one.

### 8.5 The measure of success, in three parts

1. **Short turns read right**: 8.3.
2. **Less re-exploration**: on held-out sessions, the tool calls and input tokens spent before the first relevant file is opened, with recall against without. A relevant file is one the session later edited or cited (the 5.1a labels). The history half is free, computed from transcripts: for each held-out task, the tool calls and tokens from the message to the first Read of a relevant file, and whether that file was in recall's top 5 for the message (if so, the counterfactual cost is one Read). The live half runs on a handful of tasks (about 6, from the newest sessions of two repos) with `claude -p` on the signed-in account, with and without the marketplace, counting tool calls and tokens to the first relevant Read from the transcript; it spends subscription usage, not API credit, so the budget table is unchanged. Pass: fewer calls and tokens to the first relevant file with recall on both halves, never more.
3. **Nothing worse than the built-in**: 8.2, on every category.

A release ships only when all three hold; a part that fails one is removed, not tuned.

## 9. Build order

Each step is testable alone and leaves the tree runnable.

1. Empty `lbiza/`; `marketplace.json` and the three `plugin.json`s; p4-memory copied with its test; `claude plugin validate` passes.
2. p4-scratchpad: the storage half on, the two asks behind the switch, tests, the gate-2 checks (a)–(d) as tests.
3. `store.py`, `p4.py index|query` over the new format; the ap-p4_mac fixture converted by hand; latency, cap, jargon and short-turn tests. Then `index --repo` (4.1a): paths, headings, symbols, build targets, commits and conventions from `git ls-files` and `git log`, incremental, with the exclusions and caps; tested on the p4 repo itself and on a fixture holding a generated file, an LFS pointer and a `node_modules/` directory, none of which may appear.
4. `migrate.py` dry over the four clones; section 6's counts, finding 17, the dictionary seeds.
5. The recall and close hooks (SessionStart silent, UserPromptSubmit, Stop); the smoke test on a fixture repo, including the "must not trigger" prompt.
6. The `Agent` PreToolUse hook; the subagent transcript check. If it fails, the SubagentStart fallback with the same test.
7. `labels --from-pools`, `ranker.py`, `train|eval` with the floor; ≥ 0.36 reproduced on AudioPlugin-p4.
8. The history labels for tasks without a pool (`labels-raw.tsv`), usage labels, `signals`, SubagentStop, the async train hook, `dictionary check`. Then the repo labels (5.1a): `usage` reading the turn's transcript for read, searched, edited and cited files; `labels --from-transcripts` over the four repos' history; `eval`'s repo-label subset and the free half of the re-exploration measure (8.5) on held-out sessions.
9. `teacher.py` with `--fake`; then the paid batches: edit-labels and the second opinion (≈ $13), dictionary meanings (≈ $1); the agreement and the raw-vs-edited numbers in `eval.tsv`.
10. The extraction batch (≈ $4); `plain:` fields; `check`'s jargon rate under 10%.
11. The suite change; the validation run (≈ $20), the short-turn test (≈ $4) and the newer-than-the-model test (≈ $0.30); the pinned-block and emission decisions from the numbers; anything failing a category removed.
12. `migrate --apply` on the four repos and the live AudioPlugin store; one commit each by the owner.
13. Only when the owner changes `teacher-model:` and approves the spend: `teacher edit-labels --re-edit --max-usd <approved>`, newest tasks first; `eval` must show the re-edited batch at or above the old edits before `train` uses it.

## 10. Open questions for the owner

1. **An always-on block at all?** Recommendation: none; the pinned block ships only if `=recall+pinned` beats `=recall` on lessons without losing a category in 8.2.
2. **May a hook ever call the API?** Training is free and runs in the async Stop hook; label editing, dictionary meanings and extraction cost money. Recommendation: by hand only (`p4.py teacher …`), never from a hook, until the credit is replenished; a scheduled task later if wanted.
3. **The old `index.md` guide-loop rules**: archive only, or also index the owner-rooted ones? Recommendation: archive, and index only those with `owner-words:`; the report lists them and the owner strikes any.
4. **The emission gate's remainder**: test the 10-line rewrite as pinned rules? Keep `fence_gate.py`'s ask before a placeholder literal is persisted, as a third opt-in ask in p4-scratchpad? Recommendation: test the rewrite in 8.2; add the fence ask only if placeholder fences have landed since the contracts went.
5. **The dispatch model**: retrain it as the resemblance scorer, or keep the Jaccard rule alone? Recommendation: keep it; its rows migrate either way and its one promise (never a repeat written FRESH) is tested.
6. **The two p4-scratchpad asks**: on by default, as the old brief had them, or off until measured, as gate 0.1 says? Recommendation: off; turn on per repo with the switch and judge by whether code still lands in temp dirs.
7. **Frags the repo uses**: the migration lists them with their users; who moves them? Recommendation: the owner, one commit per repo, since the move lands in the project's history.
8. **`plain:` rewrites of jargon entries** by Sonnet, or print entries verbatim? Recommendation: rewrite; the original is kept and the rate is measured.
9. **The dictionary's `means:` writer**: Fable 5.1 (≈ $1 for the seeds; the owner's "optimal fable dictionary") or Sonnet 5.5 (cents)? Recommendation: Fable for the seeds, since every entry is a proven misreading and there are few; Sonnet for later batches if the second opinion shows no difference.
10. **The budget**: about $42 paid in steps 9–11, $28 reserve inside the $70. Recommendation: approve steps 9 and 10 first (≈ $18); run step 11 only after the free numbers (the 0.36 floor, edited ≥ raw, the unit tests) pass.
