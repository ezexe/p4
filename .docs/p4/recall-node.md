# Recall by session node

The owner's words: "pr-recall should really be weaved into p4-phi precisely for this new childing and forked sessions to result in actually optimized to the environments session nodes".
This note says what a node is, how recall reads it, how the two plugins share it, and what was measured before anything ships.

## What a node is

A node is one session of the app's session tree, read at the time of one message.

- **Own task:** the session's first request. A started session's first request is the brief the session above it wrote.
- **Up:** the tasks of the sessions above it, nearest first, as far as `CHAIN_MAX` sessions, and their notes.
- **Side:** the sessions started by the same session, and the last turn each of them finished.
- **Time:** only what existed before the message counts, so a node read for training never sees its own future.

The tree comes from two places.
Live, it is phi's own files: `phi/sessions/<sessionId>/session.json`, `notes.jsonl` and `turns.jsonl`, which phi keeps for every session it runs in.
For older messages, it is the app's session records, which name each session's CLI id and the session that started it, joined to recall's `tasks.tsv` for the tasks' words.
On 2026-11-12 the app held 380 records, 97 of them with a parent.

## How recall takes the node into account

Recall today ranks the store against the message alone.
Node-aware recall adds three things, each measured on its own.

- **Query:** the content words of the own task and the up tasks join the query at a lower weight than the message's own words, the way the dictionary's expansions already do. Only the rarest of them are kept, so a long brief does not drown the message.
- **Candidates:** an entry labelled positive for a task higher up the tree is a candidate even when BM25 did not reach it, the way `near.py` adds the entries of similar earlier tasks.
- **Labels:** training rows keep their task. The node is read again at training time from the tree, never stored in `labels.tsv`, so a corrected tree corrects every row.

The gates that keep recall silent stay on the message's own words.
A node never makes a line print that the message itself gives no reason for.

## One plugin

Recall is part of p4-phi since p4-phi 0.7.0, and the p4-recall plugin is gone.

- Recall serves lines beside a message or a subagent's task, which is the moment phi hands a session its context, so the two belong in one plugin. p4-temportal stays about files and their lifetimes.
- Each hook stays its own command with its own timeout: phi's `run-hook.sh` runs `scripts/phi.py`, recall's `recall-hook.sh` runs `scripts/hook.py`. Recall's budget of about 300 ms is untouched by phi's waits for the app's record, which was the one reason to keep them apart.
- `node.py` and `p4conf.py` now exist once in the plugin. p4-temportal still carries its own copy of `p4conf.py`, and `test_p4conf.py` holds the two byte-identical.
- One plugin is one directory: recall's store and models are `phi/store/` and `phi/models/`. `p4conf.migrate_layout` moves either older layout there at the next session start: flat `store/` and `models/`, or `recall/store/` and `recall/models/`. The store's sync script merges all three, at seed 11.
- `phi_model` finds the plugin by its scripts, `scripts/p4.py` and `scripts/train.py`, and looks for a plugin named p4-phi before p4-recall.

## What phi hands over

phi hands a started session its background: the tasks of the sessions above it, their notes, the other sessions' last turns, and every rule as one line.
With a node, the background is ranked against the session's own task instead of handed over whole.

- **Rules** stay whole, a line each. A memory of this store measured that word overlap, origin messages and repeats label no rule, so there is nothing yet to rank rules by.
- **Notes and sibling turns** are ordered by how many of the own task's content words they share, and the ones sharing none are cut first when the budget is short.
- **Recall lines** for the session's first message are ranked with its node, so a child gets the lines for its brief and its place under its parent.

## The 10,000-character limit

Claude Code keeps 10,000 characters of each hook's added context and files the rest away.
phi's hooks keep to 9,500.
Recall adds at most five lines of about 160 characters each, in its own hook command, so it never shares the budget of phi's hook.
The node is never printed: it only chooses lines.

## Measurement

Both stores run recall without a trained ranker today: every round since 2026-11-11 was kept back below the precision floor, so today's lines come from the BM25 road with the `rules-facts` filter.
The comparison runs that road with and without the node, on the labelled tasks of sessions that have a parent, using only labels written before each task.

- **Precision:** of the lines printed, the share a label marks positive for that task.
- **Silence:** the share of tasks with no line printed.
- **Characters:** what the lines add to the context.

## Results, 2026-11-12

`node_eval.py` replays recall on each store's labelled tasks, and `node_eval.py --train` runs the trainer's held-out folds.
Nothing was written to either store but the index cache the hooks refresh anyway.

### Today's road, replayed

The BM25 road, on the tasks of sessions that have a parent, at each task's own time with later entries hidden.
Precision counts every printed line, and no label can mark the repeat and history lines positive.

| store | arm | tasks | silent | lines | precision | tasks hit | chars/task |
|---|---|---|---|---|---|---|---|
| AudioPlugin | today | 229 | 0.41 | 276 | 0.029 | 5 | 230 |
| AudioPlugin | node words | 229 | 0.41 | 276 | 0.029 | 5 | 230 |
| AudioPlugin | node entries | 229 | 0.14 | 706 | 0.024 | 13 | 559 |
| p4-phi | today | 25 | 0.40 | 31 | 0.129 | 2 | 248 |
| p4-phi | node entries | 25 | 0.08 | 80 | 0.087 | 4 | 596 |

- The node's words change nothing on this road: its gates read only the message's words, and the words reorder candidates the gates then drop.
- The node's entries reach 13 tasks instead of 5, at lower precision and 2.4 to 2.7 times the characters.
- Under the stores' inject mode, `rules-facts`, no line of any arm reaches a child session on either store. Only 61 of AudioPlugin's 8,800 positive labels name a rule, correction or retraction, so that mode cannot be measured from labels at all.

### The trained ranker, held out

The trainer's own folds, with and without the `node` feature: the entries labelled positive for the tasks above a session join its candidates and are marked.

| store | tasks | arm | reached | r-precision | precision | recall@20 | top 5 |
|---|---|---|---|---|---|---|---|
| AudioPlugin | all | today | 153 | 0.042 | 0.087 | 0.258 | 0.41 |
| AudioPlugin | all | node | 160 | 0.044 | 0.104 | 0.271 | 0.41 |
| AudioPlugin | child | today | 28 | 0.084 | 0.063 | 0.508 | 0.32 |
| AudioPlugin | child | node | 35 | 0.106 | 0.071 | 0.563 | 0.31 |
| p4-phi | child | today | 3 | 0.086 | 0.078 | 0.184 | 0.33 |
| p4-phi | child | node | 3 | 0.074 | 0.159 | 0.170 | 0.67 |

- On AudioPlugin the node reaches seven more child tasks and raises every number but top 5, by small amounts on one seed.
- p4-phi has three child tasks the ranker can reach, too few to read.
- Neither arm comes near the 0.6 precision a round needs to be promoted, so turning the feature on would change no line served today.

### phi's background

Notes and the other sessions' last turns are now ordered by the content words they share with the session's own task, so the budget cuts the least related first.
No label says which note a session needed, so this cannot be measured; it moves nothing when the task is unknown or the background fits.

### Cost

The live node reads phi's session files and recall's tasks and labels: 3 ms on p4-phi's store and 19 ms on AudioPlugin's, inside recall's 300 ms.

### Decision

`recall.node.on` ships off.
The node is a small, real gain for the trained ranker and none for the road the stores run today, and the lines it adds there cost more precision than they buy.
It earns being turned on when a round with it passes the promotion floor, which the labels behind it do not support yet: the repo-file and commit labels that dominate both stores are not what `rules-facts` serves.

## The relay

Linked sessions are kept in step while they work, the way `phi/phi_rank/tree.py` keeps its node tree: each node owns a shard, a parent is formed from its children, and changes travel as deltas on a shared anchor.
The code is `lbiza/plugins/p4-phi/scripts/relay.py`, called from phi's hooks.

- **Shard:** `phi.py shard <paths or globs>` keeps what a session alone may change in its `session.json`. A parent's shard covers its children's. When two sessions under the same parent declare overlapping shards, the one declaring is told in the command's output and the other at its next message.
- **Delta:** each turn's row in `turns.jsonl` carries its delta at Stop: the branch heads of the repositories it edited in, the files it changed, and the `deprecates:` and `replaces:` notes written since the turn before, with the paths they name.
- **Anchor:** the parent's folder keeps `anchor.json`, the latest delta of each child and the parent's own marked notes, under a version that goes up only when that content changes. It is made again at the Stop of the parent or of any child, and when a child declares a shard.
- **Rebase check:** every message a session gets, side-session events included, compares the parent's anchor with the version the session last saw. A newer anchor hands over the other nodes' deprecations and replacements first and in full, then their other deltas cut evenly to the room the hook has left. Before that comes a warning to stop and message the owner for each uncommitted file or shard path of the session that a deprecation names, and for each uncommitted file inside another node's shard. A warning is given once, and nothing is said when nothing changed.
- **Routing:** a message that names a path inside another node's shard is that node's, and the session is told to send it there by SendMessage. Only a message no shard covers gets a new forked session. A parent is never routed down to its own children.

`test_relay.py` runs it through phi's hooks on a three-session tree: one child deprecates a path its sibling holds uncommitted edits in, and the sibling's next message starts with the warning.

## Fork or fresh

Every `mcp__ccd_session__start_session` call passes a PreToolUse hook, `start-advice`, before it runs.

- **The rule:** a fork is advised only when the parent's transcript is at most 1 MB and the brief's paths cover at least half of the parent's scope, its shard or else the files its latest delta and anchor name. Otherwise a fresh session is advised.
- **Why those numbers:** on this machine's app records, 84 children with a parent transcript on disk, a fork started from a parent of median 2.9 MB and a fresh session from 2.1 MB. Above 1 MB a parent had a median of 2 to 27 of the owner's turns behind it and already held 0.76 to 0.86 of the brief's words, so a fork carries the rest of the parent's work while a brief carries most of what the child needs.
- **What the hook does:** nothing when the call already does what is advised. Otherwise it answers with a permission `ask` and the reason, so the person decides. It never blocks and never rewrites the call, since a fresh start needs a brief only the caller can write. The hooks documentation gives PreToolUse `allow`, `deny` or `ask` with a reason, and `updatedInput`. How an ask shows in a mode that asks for no permission was not measured.
- **A forked child keeps its agenda:** phi marks it as a fork from the app's record or its first message, and pins its own task and shard above the inherited conversation, at its start and beside each message. Its rebase check relays only what touches its own shard.
- **A fresh child's start comes with its first message,** since the brief only arrives then; the app's record holds no brief. With paths to cut by, its shard or those its brief names, it gets the tasks above it, its root step and the parent's plan around it, and the anchor cut to those paths, and not the parent's other notes or the siblings' last turns. With none, it gets the parent's whole background.
- **A fresh child starts with exactly what the parent has for it:** its background ends with the parent's anchor cut to the child's paths, its shard or those its task names: the parent's task, the anchor version, the deprecations, replacements and notes that touch those paths, and the heads that changed them. Nothing else of the anchor is given, and one line says so when the parent has nothing for them. That start counts as having seen the anchor, so the rebase check hands over only what changes after it.

## Plans with addresses

The user reframed the relay around plan steps: "i plan to do this in xyz steps ... step x becomes something you split into 'x' num steps ... and then for each step of x in xyz double check your parent to relay up accross or down if that step needs to be revised".
The code is `lbiza/plugins/p4-phi/scripts/plans.py`, run by a PostToolUse hook on `mcp__ccd_turn__update_plan`.

- **Plan:** each call to the plan tool is applied to the session's `plan.json`: its steps with their addresses, statuses and the step in progress. A whole new list, an advance, done and start are all read.
- **Addresses:** a top session's steps are 1, 2, 3. A session started for a step of its parent's plan has that step as its root, so its steps are 2.1, 2.2. The root is the step the brief names, else the parent's step in progress when the child first writes its plan.
- **Plan tree:** the parent's anchor holds every child's plan and its own, so its version moves with every step. The rebase check resends a sibling's heads and files only when those changed, not at every step.
- **Step boundary:** when a step moves to in progress, the hook answers with what bears on it, and says nothing otherwise. Up: the parent's step this session owns was revised, removed or passed. Across: a sibling's step in progress that shares two content words with it, or names a path in its shard. Down: a child's progress, when it moved since the last check. Warnings kept for the session come first.
- **Revision:** a new list that changes or removes steps is a revision. Steps are matched by their words before their address, so removing step 2 renumbers step 3 without calling it changed. Children rooted at a changed, removed or renumbered step are told on their next message, before any tool runs; siblings whose step in progress shares words with a changed step are told across; the parent is told up.
- **Child starts:** a fresh child's start carries its root step and the parent's plan around it, the step before and after, with the siblings' related steps in progress. A forked child's pinned line names its root step and its numbering.
- **What the harness allows:** PostToolUse answers with `additionalContext`, which the hooks documentation describes as context added for Claude. It was not measured live in this session, so whether the app shows it beside the plan tool's result is unconfirmed.

`test_plans.py` runs a three-session tree through phi's hooks: the parent revises step 2 while its child is on 2.2, and the child is told at its next advance; a removed root step stops the child at its next message; a sibling's revised step reaches the other sibling at its next step; the parent sees its children's progress at its own boundary.

## A turn is a delta, and so is a background task

- **A turn's report:** at every Stop, the turn's report and its step in progress are matched against the open steps of the session's children, down, and of its siblings, across. A step matches by its address, by a path in that session's shard, or by sharing two content words with a sentence of the report. The match is relayed with the report's own sentences quoted, and is told at the other session's next message or step boundary. When a match reached a child the turn sent no SendMessage, the parent's next message says which steps of which child its last turn changed and to relay it. This closes a miss of 2026-11-12: a parent's report voided a child's checks and the child was never told.
- **Background tasks:** a background Bash call, a Monitor, an Agent run in the background and a Workflow are recorded under the step in progress in `plan.json`, by a PostToolUse hook: the task id from the tool's result, its command or prompt, the heads of the repositories it names, and its paths. Open tasks travel in the anchor's plan tree.
- **Their check:** at each step boundary an open task is checked against what moved since it started: a head it ran against that moved, or a newer `deprecates:` or `replaces:` note naming its paths or sharing its words. A flagged task gets one line with its id: `TaskStop <id>` and a re-run against the new head, or, after ten minutes, finishing it and recording the result as against the old head. A step marked done over a flagged open task gets a line saying so.
- **Completions:** found 2026-11-12 in this session's transcript and phi's log: a completion notice that arrives while the session is idle starts a turn, and UserPromptSubmit fires with the notice as its message; one that arrives during a turn is queued as an attachment and no hook fires. So a completion is read from the message at UserPromptSubmit, and from the transcript's tail at Stop and at each step boundary, and attaches its status and summary to its task.

## phi/ tracked in the store

- **Tracked:** the session tree, `session.json`, `turns.jsonl`, `notes.jsonl`, `reports.jsonl`, `plan.json` and `anchor.json`, so it reaches the other machines with the rest of the store. Recall's `phi/store` stays tracked and `phi/models` keeps its ignored caches.
- **Ignored:** what is per machine or made again: each session's `log.jsonl` and `session.md`, `sessions.md`, `rules.md`, the catch-up mark `catchup.json` and every `*.tmp`. phi makes sure of those lines itself before it adds anything, since the recall hook that seeds the rest of `.gitignore` runs beside it at a start.
- **Switched on per store:** only when the store's `p4.json` sets `phi.track`, which is off by default.
- **Paths per machine:** the test session found `cwd`, delta files and heads stored absolute. The files on disk keep this machine's paths, so every reader works unchanged. The store's git runs `pathfilter.py` on `phi/` as a clean and smudge filter, which holds the project's root as `{project}` in every spelling a session writes and writes each machine's own root back at checkout. `.gitattributes` carries the filter line for every machine; each machine's git config names its own python and plugin, set by `track`. Paths outside the project, such as a session's temp folder, name that machine's own files and stay as they are.
- **Committed:** on its own the first time phi starts in a store, marked in the store's git folder; after that each Stop stages `phi/`, and the store's own sync snapshot commits it.
- **Merged across machines,** by the store's sync script at seed 12: a session's `turns.jsonl`, `notes.jsonl` and `reports.jsonl` as both sides' rows, each once, in time order; `plan.json` step by step, matched by words and else by address, the later status winning, both sides' tasks by id, a step only the lower version added kept after the others, the rest from the side with the higher version; `anchor.json` from the side with the higher version, since the next Stop makes it again.

## A shared home store

- **The setting:** a project's `p4.json` may name `phi.home`, the home store's git remote, so the same value holds on every machine. It ships unset; this project and AudioPlugin get one only with the user's go-ahead.
- **Finding it on a machine:** every phi start in a store whose `p4.json` names a home, the home store naming itself, keeps this machine's folder for the starting store's remote in a per-user map, `p4-stores.json` beside Claude Code's settings and in no repository. `P4_PHI_STORES` points it elsewhere, which the tests do. Remotes are compared as host/owner/name, whatever the scheme or `.git` suffix.
- **What goes there:** a project with a home writes its session tree into the home store's `phi/`: sessions, plans, anchors, notes and reports. Its memory, rules and recall data, `phi/store` and `phi/models`, stay in its own store.
- **The root anchor:** sessions of different repositories are top sessions, which nobody started, so the home keeps `phi/anchor.json` for them: their marks and plans, never their heads or files. A top session's rebase check reads it as a child reads its parent's.
- **When the home is not found here:** the session tree stays in the project's own store, and the start says so in one line.

## Stale nodes

- **Detected** when a parent's anchor is made again: a child whose work is over, its last turn shown done or its plan with steps and none open and nothing it changed left uncommitted, is stale when a sibling's or the parent's newer `deprecates:` or `replaces:` note names a file of its last delta or its shard, or shares words with its root step. A session with no plan and no done turn is never taken as finished.
- **Its outcome kept:** before it is marked, one note on the parent, beginning `replaces:`, says what it left in place, with its files, heads and last report, and what superseded it.
- **Fenced off:** marked `stale` in its `session.json` with the anchor version and the note, it is left out of the anchor, of every fresh child's slice and of the relay up, across and down.
- **Handed to the parent:** the parent's next message names the stale children with their ids, once, and says to archive them with `mcp__ccd_session_mgmt__archive_session`; a hook cannot archive a session itself.
- **Reactivated:** a stale session messaged again is handed what superseded it, once, and is un-staled when its next turn ends having seen that anchor.

## Routing through the hooks every session already has

- **What was found,** by the marketplace test session: Claude Code reads a session's `hooks.json` once, at its start, while the scripts its entries call are read from the plugin folder at every call. So the `start-advice`, `branch-guard`, `plan` and `task` entries added after 13:30 never ran in any session open before them; neither a marketplace update nor disabling and enabling the plugin reloaded them.
- **The rule from here:** `hooks.json` stays at the entries every open session holds, the list of 13:30. A new check runs inside an entry that already fires: recall's `lookup-check`, PreToolUse on every tool, hands `start_session` to start-advice and `EnterWorktree`, Bash and PowerShell to branch-guard; recall's `lookup-record`, PostToolUse on every tool, hands `update_plan` to the plan check and background Bash, Monitor, Agent and Workflow to task registration.
- **The shell fast paths:** `recall-hook.sh` lets `start_session`, `EnterWorktree` and any command naming git reach Python, and never runs an `update_plan` record detached, since its answer goes beside the result.
- **Once per call:** a session started while the dedicated entries were in `hooks.json` holds both; each check marks the call's `tool_use_id` in its session folder's `.calls/`, which is never tracked, so it runs once whichever entry reaches it first.
- **Seen:** each routed check writes its line in the session's `log.jsonl`.
- **Sessions older than the lookup entries,** found live 2026-11-12: a session started before 13:30 that day holds a hook list naming p4-recall's folder, which the fold into p4-phi removed, so recall's lookup hooks never run in it and nothing routed reaches it. phi's own three entries still run there, so at each message and each Stop phi reads the transcript's `update_plan` calls and background launches that no hook handled, in order, each once by its `tool_use_id`: the plan is kept and a step boundary is answered at the next message instead of beside the call.
- **Tests stay out of live stores:** recall's hook tests run with `P4_PHI=0`, since they inherit the real session's host id, and a routed phi check had written their calls into a live session's folder.
