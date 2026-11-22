---
name: host
description: What this host is and can do, as p4-native read it at the session's start, and the conditions it watches for a decision the platform blocked. The desktop app or a terminal, interactive or scripted, the Claude Code version, and which tools of the desktop app and of Claude Code answer in this session. Use before relying on a tool of the desktop app or on a feature one host has and another lacks, when a step differs between the desktop app, a terminal and a scripted run, when a line from p4-native says a watched condition changed, and when asked what this session can do or where the capability map is kept.
---

# host

p4-native is the host layer of ezexe/p4.
It builds no copy of anything Claude Code or the desktop app does: it asks the engine what this host is and keeps the answer where a session and the other p4 plugins read it.

## The capability map

- Call the tool `mcp__p4-native__native` with `command` set to `map` to read this session's entry, read anew at the call.
- ezexe types `/native` for the same lines, and a session cannot run that command, since Claude Code's Skill tool refuses a command a hooks module registers.
- `host` is `desktop` for a session the desktop app hosts and `terminal` for one a terminal runs, a `claude -p` run among them.
- `run` is `interactive` where a person is at a prompt and `scripted` where a program hands the session its prompts.
- `claude` is the Claude Code version of this session's engine, which in the desktop app is the app's own build and can differ from the `claude` on the PATH.
- `tools.app` lists the desktop app's tools that answer here by name, `tools.native` lists Claude Code's own, and `tools.servers` counts the tools of every other server.

## Where it is kept

- The file is `.claude/p4/native/host.json` in the project's store, and this session's entry is under `sessions.<session id>`. For a session in a git worktree that store is the main checkout's.
- The session id is the one a shell reads as `CLAUDE_CODE_SESSION_ID` and a command hook reads as `session_id`.
- The file holds the newest 24 sessions, so an older session's entry is gone and reads as not known.
- A project with no `.claude/p4` gets no file, and the tool still answers.
- A session whose hooks modules did not load has no entry, which reads as not known and never as a terminal.

## Watched conditions

- p4-native keeps one probe for each decision of p4-phi and p4-temportal that the platform blocked or a fault of the host shaped.
- Call the tool with `command` set to `probes` to list them, each with its decision, the fault as it was seen, and the answer kept for this kind of host.
- Call it with `command` set to `probe` to read the asked probes anew, which changes nothing in the session.
- An answer is `blocked` for the fault as it was seen and `open` for the fault gone.
- The probes run by themselves only when the Claude Code version of this kind of host changed, at the first turn, and never at a session's start.
- A line that begins `p4-native: the watched condition` reached this session as context because an answer changed, and it is told once.
- On such a line, tell ezexe which decision can be reopened and what was seen, and change nothing by yourself: reopening a decision is ezexe's.
- A line that begins `p4-native: Claude Code changed from` names the conditions no probe reads by itself, and `/release-notes` is where ezexe reads what changed.

## The inventory

- `hooks/weighed.json` of the plugin is the record of what the p4 plugins weighed: for each slash command, tool, hook event and event or method of the hooks module, who uses it, who declined it and why, or that nobody weighed it.
- Call the tool with `command` set to `weighed` for the record's counts and for each command and tool of this session that has no row.
- A line that begins `p4-native: Claude Code` and says `no p4 plugin has weighed` names what is new in this build, and it is told once: tell ezexe the names, and add no row by yourself.
- Before building something by hand, look the native command or tool up in the record: a row that says declined gives the reason, and one that says nobody means it was never weighed.

## A line at a miss

- A line that begins `p4-native:` beside a tool's result, or as context of a prompt, names a native feature of this host for something the session just did by hand.
- Take the tool it names for the rest of the task, and say nothing of the line to ezexe unless it matters.
- A line that names a slash command alone names what ezexe types: say so to ezexe where it helps, and type none yourself.
- Each situation is told once in a session, a line refuses no call, and `hooks/misses.ts` holds the table: a row for each command and tool a p4 plugin uses that a session can also do by hand.
- A pattern can fire on a call that is right, so a line is context and no verdict.

## Options

- `push` and `status` are options of the plugin that are off until ezexe turns them on, `hints` is on until ezexe turns it off, and a session changes none.
- Each row of the table that is checked at a call has an option of its own, `refuse_` and the row's id, off until ezexe turns it on: with it on, the by-hand call is refused before it runs, and the refusal names the native feature and the option.
- On such a refusal, take the feature it names, and where the by-hand call was the right one, tell ezexe which option refused it.
- With `push` on, the plugin itself calls `PushNotification` at the end of a turn of a session ezexe is at, and when the session waits at a permission prompt or sits idle, so send no second notification for the same turn.
- In a session with no such tool the plugin notifies on ezexe's own channel at the turn's end, by `$.ui.notify`.

## What to do with it

- Before a step that needs a tool of the desktop app, check that `tools.app` names it, and take the terminal route the step has where it does not.
- Name the tool or the command of Claude Code or of the desktop app for a thing either does, and write no script that copies it.
