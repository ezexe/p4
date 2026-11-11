---
name: phi
description: Work on the session tree's memo. Use when starting a session for part of a goal, when a session you started has ended a turn, when a finding should outlive this session, when something showed the goal scored, or when asked what the tree holds, to print it, or to move a session under another one.
---

# phi: the memo on the session tree

Every session is a node.
The session that started it is its parent.
A session nobody started hangs under the store's base node.
The tree lives in `<project>/.claude/p4/phi/nodes/<node id>/`, in the store of the top session's project.

Three things happen without you:

- At your start you are told what you start from: the goals above you, the notes kept there, and the plays made beside you.
- At every turn's end your turn is kept as a play, scored or not, and handed to your parent.
- At your next message you are handed, whole, the plays of the sessions you started that ended since you last looked.

## What you do

Run these with `python -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/phi.py"`.

- **Execute the memo.** What you were told at your start was already worked out. Use it where it fits and say where it does not.
- **Keep a finding:** `note "<claim>" --source "<file and line, command, or measurement>"`. Every session you start, and every session they start, begins with it. A note without a source is refused.
- **Close a play:** `close --check "<what was run and what it showed>"` when something showed the goal scored. The turn's play is then kept closed. Without it the play is kept open, and the next session starts from where it stopped.
- **Start a session for a part of the goal** with the app's own tool. Write the brief as usual. The child gets your goal, your notes and its siblings' plays by itself, so the brief need not repeat them.
- **Read the tree:** `tree` prints every node with its state. `memo [node id]` prints a node's page. `ghost` prints what this session starts from.
- **Move a node:** `reparent <node id> <new parent id>` hangs a node, with everything under it, on another node. The app's sidebar does not follow. The memo does.

## What it does not do

- It does not find a play by the words of a request. A play is found by where its session stands in the tree.
- It does not start, stop or message sessions.
- It does not reach subagents started with the Agent tool.
