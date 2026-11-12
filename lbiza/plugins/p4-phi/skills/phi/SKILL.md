---
name: phi
description: What linked sessions hand each other. Use when a message from ezexe is about something other than this session's task, when starting a session for part of the task, when a session you started has finished a turn, when a finding should outlast this session, when something showed the task done, or when asked what the sessions hold, to print the tree, or to detach or reparent a session.
---

# phi: what linked sessions hand each other

The words here are the app's own.
A session is started by another session, or it is a top session.
A session has a task.
When it finishes a turn it gives a report.
The files are in `<project>/.claude/p4/phi/sessions/<sessionId>/`, in the store of the top session's project.

Four things happen without you:

- At your start you are given the project's standing rules: every feedback and user memory of the store, a line each, without its Why. Do not open the memory files or CLAUDE.md to learn the rules before the work. A line cut with ... is whole on `<project>/.claude/p4/phi/rules.md`; read that one page when a rule's reason matters.
- Beside your first message you are given background: the tasks of the sessions above this one, their notes, and the last turn of the other sessions started beside it.
- When you finish a turn, the turn and its report are kept, done or not, and reach the session that started this one.
- Beside your next message you are given, in full, the reports of the sessions you started that finished a turn since you last looked.

## Stay with the task

This session's task is its first request.
When a message from ezexe is about something else, do not turn this session to it.

- **Start a session for it** with context `fork`, so it has this whole conversation and shares this checkout. Start it; do not offer a card.
- **Tell ezexe in one line** which session has it.
- **Stay with the task.** That session's report comes back here in full beside your next message.
- **A quick thing stays here:** a question, or what a few tool calls settle.
- **When ezexe says the task itself has changed:** `task "<the new task>"`. The task before it is kept.

## Commands

Run these with `python -I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/phi.py"`.

- **Use the background.** What you were given was already worked out. Use it where it fits and say where it does not.
- **Keep a finding:** `note "<claim>" --source "<file and line, command, or measurement>"`. Every session you start, and every session they start, is given it. A note without a source is refused.
- **Say the task is done:** `done "<what was run and what it showed>"`. This turn is then kept as done. Without it the turn is kept as not shown done.
- **Start a session for part of the task** with the app's own tool, and write the brief as usual. The session is given your task, your notes and the last turns of the sessions beside it, so the brief need not repeat them. It also starts with the project's rules, CLAUDE.md and the memory index, so the brief never tells it to read CLAUDE.md, MEMORY.md or a memory file; it names only what the task needs, such as a skill, a plan or source files.
- **Archive when done:** a brief or first message saying "archive when done", or `disposable` run in the session, marks it disposable. When its plan is all completed or it ran `done`, its turn's end leaves its outcome on the session that started it as one `replaces:` note, and that session is told at its next message to archive it.
- **A writing child runs one issue loop:** a child whose brief or plan names files in a repository with a GitHub `origin` is given an issue for its purpose at its first message or plan, or takes the open issue its brief names. A check, an audit, a question or a relay gets none. Each of its commits says `Closes #N`, and a commit without it is named at the next step boundary. A plan step names the test that proves the issue fixed, as a backticked command or a test file, or `proof "<command>"` names it. At Stop phi re-runs that test on the final head and comments the result on the issue. A failing test keeps the child open. A passing one sends it to push at once and sync its p4 stores with `p4.py sync --push`. Only with the issue closed is it archived, its `replaces:` note carrying the issue link, the commit and the test.
- **A top session orchestrates:** a session nobody started keeps itself for planning, relaying, decisions with ezexe and landing the work. Its work steps are advised to fresh children, a run of serial ones to one child, and its first Edit, Write or working command in a work step gets one line saying so.
- **Read the tree:** `tree` prints every session with its state. `show [sessionId]` prints a session's page. `background` prints what this session was given.
- **Detach a session:** `detach <sessionId>` makes it a top session.
- **Reparent a session:** `reparent <sessionId> <under sessionId>` puts it, with every session it started, under another. The app's sidebar does not follow either command.

## What it does not do

- It does not find an earlier turn by the words of a request. A session is given what the sessions linked to it kept.
- It does not start, stop or message sessions itself.
- It does not reach subagents started with the Agent tool.
