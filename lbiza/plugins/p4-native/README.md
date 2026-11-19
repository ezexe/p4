# p4-native

The host layer of ezexe/p4, in one plugin.
It is the one place that knows what this host can do, and it holds the native features that fit neither p4-phi nor p4-temportal.
The rule it works by is "Native first", on https://github.com/ezexe/p4/wiki/Contributing: where Claude Code or the desktop app does a thing, a plugin configures or calls it and builds no copy.

## Install

```bash
claude plugin marketplace add ezexe/p4
claude plugin install p4-native@p4-marketplace
```

The plugin is a hooks module alone, `hooks/register.ts`, whose functions run inside Claude Code.
It runs no command hook and starts no process at a session's start, and it carries no copy of `p4conf.py`, since it writes no setting.
A hooks module needs Claude Code v2.1.287 or later, and it does not load in a session started with `--safe-mode` or `--bare`, where `disableAllHooks` is set, or where managed settings block mods, by https://code.claude.com/docs/en/plugins/mods/create.md.

## The capability map

At a session's start the module asks the engine what this host is and writes one entry for the session.

- `host` is `desktop` for a session the desktop app hosts, `terminal` for one a terminal runs, a `claude -p` run among them, and for any other host the name of the surface it draws on.
- `run` is `interactive` where a person is at a prompt and `scripted` where a program hands the session its prompts.
- `claude` and `base` are the engine's version and the release it is built from, as `$.session.version` answers them.
- `platform` is the operating system, as `$.session.info` answers it.
- `surfaces` is what `$.session.surfaces` answers.
- `tools.app` lists the desktop app's tools by name, each of which begins with `mcp__ccd_`, `tools.native` lists Claude Code's own tools, and `tools.servers` counts the tools of every other server by the server's name.
- `at` is the moment the entry was read.

A session is read as `desktop` when a tool of the desktop app answers in it or it draws on the `desktop` surface.
No environment variable is read: a `claude -p` run started from a desktop session's shell inherits `CLAUDE_CODE_ENTRYPOINT` and `CLAUDE_CODE_HOST_SESSION_ID` from that session.
The session does not wait for the map.
The map is read again at the first turn of the main conversation, when a tool server that was still connecting at the start has answered, and after the session's id changed, as a `/clear` changes it.
An entry is written again only where it says something new.

## One way to read it

The map is the file `<project>/.claude/p4/native/host.json`, and a session's entry is under `sessions.<session id>`.
The session id is `$.session.id()` in a hooks module, `session_id` in a command hook's input and `CLAUDE_CODE_SESSION_ID` in a shell.

```json
{
 "sessions": {
  "40fa8166-de44-42ca-9be9-475195f7986a": {
   "at": "2026-11-19T14:37:03.384Z",
   "host": "terminal",
   "run": "scripted",
   "claude": "2.1.328",
   "base": "2.1.328",
   "platform": "windows",
   "surfaces": [],
   "tools": {"app": [], "native": ["Agent", "Bash", "Read"], "servers": {}}
  }
 }
}
```

- A hooks module reads the file by `$.fs.read`, and a script opens it.
- A session calls the tool `mcp__p4-native__native` with `command` set to `map`, which reads the map anew, writes the entry and prints it.
- ezexe types `/native`, which prints the same lines.

The file holds the newest 24 sessions, so it needs no sweep.
The folder `native/` holds a `.gitignore` of `*`, which the module writes once, so nothing in it enters the store's own git repository: what a host can do is a fact of one machine.
Two sessions that start at once each read the file back after their write and write again where their entry is missing.
An entry that is not there means not known: the session is older than the newest 24, its hooks modules did not load, or the project has no store.
A project with no `.claude/p4` gets no file, and the tool and the command still answer from the session's own reading.
p4-phi and p4-temportal do not read the map yet.

## Seen live

Seen on Claude Code 2.1.328, in a `claude -p` run with the plugin loaded by `--plugin-dir`, started from a desktop session's shell with that session's variables in its environment: the entry read `terminal`, `scripted`, no surface and no tool of the desktop app, and it listed 31 tools of Claude Code, `PushNotification`, `CronCreate` and `SendMessage` among them.
The run took four seconds end to end.
Seen in the desktop app on Claude Code 2.1.326, with a development copy loaded from the session's mods folder into a session another session started: the entry read `desktop`, `interactive`, the one surface `desktop`, 67 tools of the desktop app and 43 of Claude Code, and the tool `mcp__p4-native__native` printed the same entry and named its file.
Not seen live: a session at a terminal's prompt, and a session whose id a `/clear` changed.

## Tests

`python -m pytest`, run in `lbiza/`, runs the tests under `tests/p4-native/`, and `claude plugin test lbiza/plugins/p4-native` runs the module's own in `hooks/register.test.ts`.
