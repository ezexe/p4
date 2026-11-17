---
name: phi
description: What linked sessions hand each other. Use when a message from ezexe is about something other than this session's task, when starting a session for part of the task, when a worker or coworker you started has finished a turn, when a finding should outlast this session, when something showed the task done, or when asked what the sessions hold, to print the tree, to detach to top level or reparent a session, or when this session is a puppeteer filed in the sidebar section "puppeteers" or is controlled by one.
---

# p4-phi: what linked sessions hand each other

A session is started by another session, its parent session, or it is an orchestrator.
A session has a task, its first request, and when it finishes a turn it gives a report.
p4-phi keeps each session's files in `<project>/.claude/p4/phi/sessions/<sessionId>/`, in the store of its orchestrator's project.

## What reaches a session without a command

- At its start: the rules built into p4-phi, whole. The store's feedback and user memories reach it as their lines in the memory index the app loads, and a memory that changes later is handed once at the next message.
- Beside its first message, when the sessions linked to it left any: its start background, whose first and last lines say what it holds and how to keep a finding or say the task is done.
- Beside its next message: the reports of the workers or coworkers it started that finished a turn since.
- In a subagent it starts: the step the subagent serves and retrieval's lines, appended to the Agent call's prompt, and before a tool call of the subagent a warning of what changed beside its parent session since its launch, when anything did.
- At the moment each applies: the advice on where each work step of an orchestrator's task list goes; a writing child's issue line, which says its loop; the push line, which goes only to the tree's orchestrator, the one session that lands and pushes, a worker's `Closes #N` commit included; the refusal of a start whose brief declares no write set; and the line `done` prints, which says what follows.

A feedback memory whose rule an open issue will build into the plugin is tied to that issue by one line in the memory's own front matter, `issue: owner/name#N`.
Once a commit that closes that issue is on the remote default branch, the next Stop whose turn ran a push, pull, fetch or merge cuts the memory back to one pointer line naming the issue and the code that carries its rule, and rewrites the memory's own line in the memory index to match.

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

The built-in rule `levels`, given at a session's start, says where work runs: Claude Code's built-in subagent `Explore` for a search or a read across files, called with `model` `haiku`, a Bash or PowerShell call with `run_in_background: true` for a long command, Claude Code's bundled skill `code-review` without `--fix` for an independent review of a code change, the plugin's background subagent `p4-phi:check` for an independent read of a result that is no code change, or a worker.
`phi.child_levels` in `.claude/p4/p4.json` sets the model and effort a worker starts with for each kind of step: by default `static` runs on `claude-sonnet-5-5` at `medium`, and `build` and `design` on the parent session's model at `high`.
No start's `effort` is named above the starting session's own, since the app starts no session above its starter's effort: p4-phi reads that level from the hook input's `effort.level` or from `CLAUDE_EFFORT`, and keeps the last one seen on the session's record.
Before a batch of session starts or Agent calls, the rule and the advice that hands out the batch tell the session to read the plan limits once with the app's own `mcp__ccd_session_mgmt__get_usage`, so each `model` is picked from the work and what the limits show.
No p4 setting names a subagent's model or effort, since Claude Code sets both: by https://code.claude.com/docs/en/sub-agents.md, "Choose a model", the `model` on the Agent call comes first, then the `model` field of the agent's definition, then `CLAUDE_CODE_SUBAGENT_MODEL`, then the session's model.
So the rule's `model` `haiku` on an `Explore` call stands unless the call names another, `p4-phi:check` runs on the session's model at `high` effort as its file says unless the call names a `model` or an `effort`, and a project runs every subagent on one model with `CLAUDE_CODE_SUBAGENT_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` set to `1` under `env` of a settings file.
A Workflow script names a model for each stage: https://code.claude.com/docs/en/workflows.md says "A model the script names for a stage counts as the per-invocation model in that order." and "When nothing else assigns one, the agent runs on your session's model.", and no line of that page gives a workflow agent an effort of its own.
A worker splits at its first message: in these sessions the app has let a started session start others in its first turn and in the turns ezexe's own messages open, though no doc states it, so p4-phi tells it to plan its split then and start a session for every part that writes files or makes a decision, one per disjoint set of files, and where the app refuses that start to show the part as a suggested task card that ezexe presses.
Subagents keep reads, searches and independent checks, a single command run is a background command, and a review of a code change is the `code-review` skill's.
A writing part that comes up later is shown as a suggested task card that ezexe presses, and kept as a start request only where the card is refused too.
A subagent that wrote files is listed on the ledger under Level misses.
Before a session creates anything new, such as a module, a page, a format or a kind of test, it finds the documented terms for it and a published implementation guide for that kind of work, logs both with their sources in its decisions file, and builds by them: a writing worker's first message and every start draft carry that line.
A task list whose first creating step has no such research step before it is advised one, once.
A question that the code, the history, the issues or the current outside documentation can answer is researched and decided by the session, which logs the decision with its source in its decisions file, the one its brief names or `decisions.md` in the scratchpad directory the app names: the act-don't-wait rule every session is handed and every start draft carry that line, and a question reaches ezexe only once research cannot settle it.

## What a `Files:` line holds

A path on a brief's `Files:` line that is an ancestor of another listed path, or a repository's root, is read as context and not held, unless every listed path is such context, when the first is held, so name a checkout for context in another sentence or on another line.

## The address book

Beside its first message, after a clear, and beside each later message where an entry changed, a session is handed its address book: the live sessions of its project's trees and of the trees its puppeteer controls, each by full title and id with its role, its parent, the files its `Files:` line holds, its owned paths, its open issue and its workers or coworkers.
After a compaction the summary keeps the conversation, the book among it, so the start hands only the entries that changed since the session last looked, with the path of `book.md`, and hands the session's own turns again only after a clear, which keeps nothing.
It names the puppeteer as the one address for a decision of ezexe's authority, a press the app requires or an outcome ezexe should hear, and the session's parent as the address for work off its task.
The book is whole on `book.md` in the session's folder, and a later line names only the entries that changed since the session last looked.
A message about a file, an issue or a piece of work goes straight to the session that holds that file, owns that issue or started that work.
Before a `SendMessage` or `send_message` goes, p4-phi reads the paths and issue numbers it names against the book: one sent to neither the holder nor the session that started the holder is held with the holder named, and so is one to the puppeteer that names no matter of ezexe's.
Each hold is said once for one message and recipient, so sending it again as it is goes through.
A `Finding:` on a held file or an owned issue goes straight to its holder, named under the reports that carry it; only one no live session covers goes up for an issue.

## A puppeteer

A puppeteer is a session nobody started that ezexe filed in the sidebar section "puppeteers", and it controls the orchestrators of other trees.
Its rule is handed once, beside its first message after p4-phi sees the filing; its board, `board.md` in its session folder, says on its head how it is kept; and the line p4-phi hands at a boundary, a controlled tree that closed or every controlled session idle with no request waiting, says to keep what the board lacks with `note`.
Claude Code compacts a session by itself, so a boundary carries no compact question and no line for ezexe to type, and after a compaction, typed or automatic, the SessionStart entry hands a puppeteer its board's path first.
A controlled session is told once when it comes to have a puppeteer, and once when that ends.
Each request of ezexe's to a puppeteer is a row of its ledger, `asks.md` beside its board: a short topic, the session that holds it by full title and id, its state, and what waits on ezexe.
Every message of ezexe's opens a row, whatever its words and also while another row waits on ezexe, unless it is a status question about existing work such as "where does it stand" or "did it land", or a reply with nothing after it.
The same words again join their row while it is live, and open a new row once it is finished.
A message to a puppeteer that the app marks as another session's opens no row and is drafted no start: the body, past its leading reminders, opens with another session's message, a side-sessions event, a task notification, a system notification, a hook's feedback or a slash command's wrapper.
An orchestrator's routing still reads the work another session's message hands it.
A request takes as its holder the session the puppeteer messages, or the orchestrator it starts, whose own words share the request's topic, else, for a send to a controlled session or a start, the request its turn works on.
Its state is read from that holder's turns in the holder's own store since it took the request, also for a holder the address book leaves out: routed or started, working, reported, and done for good once one of them was shown done; closed for good once the holder is archived or no longer live with no such turn.
A held request whose holder ended no turn on it for a day ends as it stands: reported once it reported, else carried, since a long-lived orchestrator may never show it done and an interrupted turn runs no Stop hook.
A send never ends a wait, and a finished request never takes a holder.
A finished state shows only with its end kept, and a finished row leaves the page a day after it ended.
At the request's next message, one with no holder is answered when the turn on it ended without a question, and waits on ezexe when the turn ended on a question or asked one with `mcp__ccd_turn__wrap_up`, whatever its buttons, whose labels are kept whole with the wait.
It is carried when ezexe's next message comes before any turn ended; another session's message, which can come inside the turn, carries nothing.
A turn's question goes to the request whose id it starts with, as "ask-1: ...", which the line beside each message asks for, else to the request the turn worked on only while no other request waits, else to none.
A waiting request is answered only by ezexe's recognized reply to it: a button label it offered, which the app sends back as ezexe's message, its id leading the message before a reply word or a label, which answers that request or nothing, or a reply word or phrase standing alone at the message's start and followed by a stop that is no hyphen, which answers the waiting request whose topic it shares or else the latest.
An id anywhere else in a message answers nothing, and only an id that starts a turn's question gives a request a wait, never a held or finished one.
A label two waiting requests offered answers neither and opens nothing.
A message is a status question only when each of its sentences is a question or asks where things stand, and a question that asks "can you", "can we", "should we" or the like opens a request.
What follows such a reply or id opens a request of its own when it asks for more than the answer, and nothing else ezexe says ends a wait.
Beside each of the puppeteer's messages, a short line gives the counts by state and names the page.
A message of ezexe's that `route_down` sends to a controlled session's topic is drafted no start.
A puppeteer's turns hold messages only, and every other task goes to its one standing worker, which it starts under itself with the brief line `Standing worker of its puppeteer` and which splits its task groups into standing coworkers.
A second such start is refused while the first is live, and a puppeteer's shell call or edit is answered with a line that sends the task to its worker.
The worker's and each coworker's first message says what it is, that it hands up a page's path and its counts and never publishes a result as an Artifact or a file unless ezexe asks, and that it keeps a state page, `state.md` in the scratchpad directory the app names for its first turn, the folder its hooks get as `scratchpad_dir`.
At a message carrying reports, a puppeteer is handed a line naming each reporting session whose effort to raise, lower or set low with `set_session_effort`; a call to `set_session_model` is refused by the deny rule p4's settings keeper writes, since a model is passed only on the start call.

## State pages and clearing

A session whose p4-phi task names a page by `State page: <path>`, and the standing worker and each coworker, is handed that page's path first after a compaction or a clear.
No line p4-phi hands a session names a place under `.claude` to write, since every such write asks ezexe.
A standing worker's or coworker's page stays where its first scratchpad put it, kept on its record, since a clear gives the session a new scratchpad.
At every `wrap_up`, such a session is told to bring the page up to date, whatever its context reads, so a clear loses nothing, its own or one the session that started it makes.
The app counts a session's context, so p4-phi measures none: the same line tells the session to read its share with `mcp__ccd_session_mgmt__get_usage` on `"self"` and, where it reads past `phi.clear_at` percent, 60 by default in `.claude/p4/p4.json`, to make `clear_session` on `"self"` its turn's last call.
No tool clears a session together with the sessions it started, so ahead of its own clear the line names one `clear_session` call for each coworker p4-phi's records hold idle with an empty queue: a live session it started itself that keeps a state page, is not inside a turn, holds no open plan step and no background task, and whose last report it has been handed.
A queued message, a pin and a session open on ezexe's screen are in none of p4-phi's records, so the app's own refusal of the clear covers them, and a coworker whose clear is refused stays as it is.
A puppeteer, at a message carrying its worker's report, is handed the ids of the worker and its coworkers, to read each one's `get_usage`.

## What it does not do

- Apart from retrieval, which ranks the corpus against each message, p4-phi finds no earlier turn by the words of a request: a session is given what the sessions linked to it kept, and of earlier topics only a registered route, a landed topic whose records back it, is scored against a message.
- It does not start, stop or message sessions itself: the gate hands the exact call, and the session makes it.
- It does not stop a session from filing itself in the section "puppeteers", since the app asks nobody: the rule rests on ezexe's filing, and p4-phi says once, in the session and on its record, that it saw the session there, and tells every session it lists who claims it.
- It does not compact a session and hands no session a compact question: Claude Code compacts a session by itself as its context fills.
- It does not start a successor or move a session between sections: those are the app's tools, and the puppeteer makes the calls.
- It does not block a puppeteer's edits, and a start request a controlled tree filed for itself stays the tree's: only one addressed to the puppeteer is closed, when that session declines it.
