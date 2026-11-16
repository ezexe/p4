---
name: phi
description: What linked sessions hand each other. Use when a message from ezexe is about something other than this session's task, when starting a session for part of the task, when a worker or soldier you started has finished a turn, when a finding should outlast this session, when something showed the task done, or when asked what the sessions hold, to print the tree, to detach to top level or reparent a session, or when this session is a puppeteer filed in the sidebar section "puppeteers" or is controlled by one.
---

# p4-phi: what linked sessions hand each other

A session is started by another session, its parent session, or it is an orchestrator.
A session has a task, its first request, and when it finishes a turn it gives a report.
p4-phi keeps each session's files in `<project>/.claude/p4/phi/sessions/<sessionId>/`, in the store of its orchestrator's project.

## What reaches a session without a command

- At its start: the store's feedback and user memories, a line each. A line cut with ... is whole on `<project>/.claude/p4/phi/rules.md`.
- Beside its first message, when the sessions linked to it left any: its start background, whose first and last lines say what it holds and how to keep a finding or say the task is done.
- Beside its next message: the reports of the workers or soldiers it started that finished a turn since.
- In a subagent it starts: the step the subagent serves and retrieval's lines, appended to the Agent call's prompt, and before a tool call of the subagent a warning of what changed beside its parent session since its launch, when anything did.
- At the moment each applies: ezexe's standing instruction for a message about something else, in full at the first message and kept on the session's `standing.md`; the advice on where each work step of an orchestrator's task list goes; a writing child's issue line, which says its loop; the push line, which says who pushes; the refusal of a start whose brief declares no write set; and the line `done` prints, which says what follows.

A store moves only by `python -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/p4.py" sync --push --p4 "<store>"`.

## Commands

Run each with `python -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/phi.py"`, and pass `--session <sessionId>` or `--p4 <store>` to act for another session or store.

- `note "<claim>" --source "<where it was checked>"` keeps a finding for every session below this one, and `--kind` labels it with a free word, such as `decision`, `waiting` or `parked`.
- `done "<what was run and what it showed>"` keeps this turn as done.
- `task "<the new task>"` replaces this session's task and keeps the one before.
- `proof "<command>"` names the regression test of this session's issue.
- `files <path> ...` replaces this session's write set with the paths it still writes, `files --release` empties it, and `files` alone prints it.
- `shard <path> ...` sets this session's owned paths, the paths or globs it alone may change, and `shard` alone prints them.
- `disposable` marks this session as one p4-phi counts as archived once it is done.
- `request "<title>" --brief "<the whole brief>"` files a start request, `--to-puppeteer` addresses it to this session's puppeteer, and `request --withdraw <request id>` withdraws a pending one.
- `tree` prints every session that is not archived, with its state, `show [sessionId]` a session's page, and `background` what this session was given.
- `detach [sessionId]` moves a session to top level in p4-phi's records, and `reparent <sessionId> <under sessionId>` puts it, with every session below it, under another; the app's sidebar follows neither.
- `controls <sessionId> ...` records the sessions a puppeteer controls, `controls` alone prints each by its full title, `--drop <sessionId>` ends one, `--hand <new sessionId>` hands over to a successor, `--from <old sessionId>` takes over from one, and `--decline <request id> "<why>"` declines a request.
- `ledger` prints `ledger.md`, which an orchestrator's watcher writes in its session folder from p4-phi's files and the app's records, and `watch` is that watcher, which p4-phi starts itself.
- `draft "<words>"` drafts the next session for any words, and `pioneer <draft id> --request` keeps a clean draft as a start request.
- `readings "<one>" "<two>" --words "<the message>"` drafts one child for each reading of a message, and `merge <group> --result "<text>"` settles a fork between them.
- `routes` lists the registered routes, `routes --register` registers every landed topic the records back, and `routes --why <sessionId>` says what a topic's route still lacks.
- `meta` runs the meta pass over every orchestrator's ledger and prints `meta-ledger.md`.
- `settle <session> "<what took it up>"` clears a row of unfinished work a session left at its archive.

## Delegation

The built-in rule `levels`, given at a session's start, says where work runs: the background subagents `p4-phi:sweep`, `p4-phi:runner` and `p4-phi:check`, a background command, or a worker.
`phi.child_levels` in `.claude/p4/p4.json` sets the model and effort a worker starts with for each kind of step: by default `static` runs on `claude-sonnet-5-5` at `medium`, and `build` and `design` on the parent session's model at `high`.
A worker splits at its first message: the app lets a session start sessions only in its first turn and in the turns ezexe's own messages open, so p4-phi tells it to plan its split then and start a session for every part that writes files or makes a decision, one per disjoint set of files.
Subagents keep reads, searches, single command runs and independent checks.
A writing part that comes up later is kept as a start request, which ezexe starts by a click.
A subagent that wrote files is listed on the ledger under Level misses.

## What a `Files:` line holds

A path on a brief's `Files:` line that is an ancestor of another listed path, or a repository's root, is read as context and not held, unless every listed path is such context, when the first is held, so name a checkout for context in another sentence or on another line.

## A puppeteer

A puppeteer is a session nobody started that ezexe filed in the sidebar section "puppeteers", and it controls the orchestrators of other trees.
Its rule is handed once, beside its first message after p4-phi sees the filing; its board, `board.md` in its session folder, says on its head how it is kept; and the line p4-phi hands at a boundary says what to do then.
A controlled session is told once when it comes to have a puppeteer, and once when that ends.

## What it does not do

- Apart from retrieval, which ranks the corpus against each message, p4-phi finds no earlier turn by the words of a request: a session is given what the sessions linked to it kept, and of earlier topics only a registered route, a landed topic whose records back it, is scored against a message.
- It does not start, stop or message sessions itself: the gate hands the exact call, and the session makes it.
- It does not stop a session from filing itself in the section "puppeteers", since the app asks nobody: the rule rests on ezexe's filing, and p4-phi says once, in the session and on its record, that it saw the session there, and tells every session it lists who claims it.
- It does not compact a session, start a successor or move a session between sections: those are the app's tools, and the puppeteer makes the calls p4-phi names.
- It does not block a puppeteer's edits, and a start request a controlled tree filed for itself stays the tree's: only one addressed to the puppeteer is closed, when that session declines it.
