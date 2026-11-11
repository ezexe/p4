

## p4-phi 0.2.0: a session holds its goal

The owner named the problem the tree is for.
A session gets spun around its target when the next message is about something else.
Starting a fresh session for the new thing is too tedious to do right, because the fresh session lacks the exact state this one built, and a separate worktree makes it worse.
So a session that sees its own off-topic steer should crate the new thing, ship it to a child session, and stay, while the owner goes on orchestrating from the parent.

### The decisions

- **A node has one goal.** It is the session's first request, kept in `node.json`.
- **The session judges the steer, not the hook.** Finding an off-topic message by its words is the matching that was measured and ruled out. The session has the whole conversation, so it is told the goal and the rule and left to judge.
- **The rule is given once in full.** It comes beside the first message that sets the goal, and again after a compaction or a clear. It is about 1,250 characters.
- **A line follows each of the owner's messages.** It restates the goal in at most 160 characters and says to ship a steer to a forked child and stay. A message of the harness gets no line.
- **The child is a fork.** A fork has the parent's whole conversation and shares its checkout, which is the exact state the owner asked for without a new worktree.
- **The child is started, not offered.** The rule tells the session that starting is the owner's standing instruction for the repository. The app allows a start on a turn that began with the owner's words, and a steer is such a turn.
- **The goal can be re-aimed.** `phi.py goal "<the new goal>"` replaces it when the owner says the goal itself has changed, and the goal before it is kept in `node.json`.
- **It can be turned off.** `steer` in `phi.json` or `P4_PHI_STEER=0`.

### What a live fork showed

One forked child was started from the building session.

- Its SessionStart came with the source `resume`, and its record already named its starter, so it was told the memo above it at its start: 2,993 characters.
- Its first message came under the line `Task (from the session that started this one):`, with no `Background` wrapper and no notes folder. `request_of` now takes that line off.
- The steer rule reached it beside that first message: 1,266 characters.
- Its exit was kept as a play and handed to the building session.

### What is unmeasured

- Whether a session obeys the rule is not measured at all. No live session has yet met a steering message from the owner with the rule in its context, because only the owner can send one.
- Whether a session can tell a steer from a refinement of its goal is unmeasured. A wrong call either turns the session anyway or ships something that belonged here.
- Whether the app starts the child without a card when the rule says so is untried. The app's own instructions to a session prefer offering a card for unrelated work.
- The line costs up to about 330 characters beside every message of the owner's. Whether it keeps its hold deep into a long session is unmeasured.
- The log marks every rule and line shown, and a play lists every session started, so the rate of shipped steers can be counted once sessions run with it.

## p4-phi 0.3.0: the app's own words

The owner asked that the tree carry the Claude Code desktop app's nested session semantics and wording exactly as the app reads them, with nothing coined.
Versions 0.1 and 0.2 had their own vocabulary, and the two sections above still use it because they record what was built then.
From 0.3 the plugin's files, fields, commands and every line it gives a session use the app's words.

### The words

| 0.1 and 0.2 | 0.3, as the app says it | Where the app says it |
|---|---|---|
| node | session | everywhere |
| parent | the session that started this one, `spawnedFrom.sessionId` | the handed-over message, the app's record |
| child | a session this session started | the note the app sends when one finishes a turn |
| base node, root | a top session has no `spawnedFrom` | `top` in the linked sessions reminder |
| line | `startChain`, the sessions above | the app's record |
| goal | task | `Task:` in the handed-over message |
| play | turn | "finished a turn" |
| closing | report | "It reported" |
| closed with a check | done | "Done looks like" in a brief |
| open | not shown done | |
| avoid | failed | |
| ghost, memo | background | `Background (from the session that started this one)` |
| rollup | reports of the sessions this session started | the same note |
| steer | a message about something else, `new_task` | the app's own instructions to a session |
| owner | the user | the app's own instructions to a session |
| reparent to the base node | detach | the app's detach |

`note` and `reparent` were kept: the app calls its shared folder a notes folder, and it has no word for putting a session under another one.

### The files

- `phi/sessions/<sessionId>/session.json` holds `sessionId`, `cliSessionIds`, `title`, `cwd`, `spawnedFrom`, `startChain`, `task`.
- `phi/sessions/<sessionId>/turns.jsonl` holds a row a finished turn: `prompt`, `steps`, `failed`, `report`, `done`, `sessions`.
- `phi/sessions/<sessionId>/reports.jsonl` holds the reports of the sessions it started.
- `phi/sessions/<sessionId>/notes.jsonl` and `log.jsonl` are as before.
- `phi/sessions/<sessionId>/session.md` is the session as one page.
- `phi/reports.jsonl` and `phi/sessions.md` hold the top sessions, which nobody started.
- A top session has no `spawnedFrom` at all, as in the app's record. There is no base node.

### The commands and hooks

- The commands are `note`, `done`, `task`, `show`, `tree`, `background`, `detach` and `reparent`.
- The hooks are named for their events: `session-start`, `user-prompt-submit` and `stop`.
- The names `arrive`, `prompt` and `exit` still run, because sessions that began under 0.1 or 0.2 keep calling them.
- The settings are `background`, `reports`, `turns`, `new_task`, `background_chars`, `reports_chars` and `wait_s`.

### What was done with the tree of 0.1 and 0.2

- The seven sessions kept under `phi/nodes` in the p4-phi project's store were copied into `phi/sessions` with the new field names.
- Nothing under `phi/nodes` was changed or removed, and nothing reads it any more.
- A test reads the plugin's own source and fails if a line given to a session holds one of the old words.

### What is unmeasured

- The live checks ran under 0.1 and 0.2. No session has yet been started under 0.3, so its wording has only been seen in the suite and in the session that built it.
