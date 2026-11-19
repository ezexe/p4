---
name: native
description: What this host is and can do, as p4-native read it at the session's start. The desktop app or a terminal, interactive or scripted, the Claude Code version, and which tools of the desktop app and of Claude Code answer in this session. Use before relying on a tool of the desktop app or on a feature one host has and another lacks, when a step differs between the desktop app, a terminal and a scripted run, and when asked what this session can do or where the capability map is kept.
---

# native

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

- The file is `.claude/p4/native/host.json` in the project's store, and this session's entry is under `sessions.<session id>`.
- The session id is the one a shell reads as `CLAUDE_CODE_SESSION_ID` and a command hook reads as `session_id`.
- The file holds the newest 24 sessions, so an older session's entry is gone and reads as not known.
- A project with no `.claude/p4` gets no file, and the tool still answers.
- A session whose hooks modules did not load has no entry, which reads as not known and never as a terminal.

## What to do with it

- Before a step that needs a tool of the desktop app, check that `tools.app` names it, and take the terminal route the step has where it does not.
- Name the tool or the command of Claude Code or of the desktop app for a thing either does, and write no script that copies it.
