# p4-native

The host layer of ezexe/p4, in one plugin.
It is the one place that knows what this host can do, and it watches the conditions that would reopen a decision the platform blocked.
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

## Watched conditions

Some decisions in p4-phi and p4-temportal were made because the platform blocked the native way, or because the host had a fault.
`hooks/probes.ts` holds one probe for each, and each probe names the decision it belongs to, the fault as it was seen, and the answer the decision was made on.
An answer is `blocked` for the fault as it was seen and `open` for the fault gone.

The probes run when the Claude Code version kept for this kind of host is not this session's, and on request, and never at a session's start.
A kind of host is the map's `host` and `run`, such as `desktop/interactive` and `terminal/scripted`, since the desktop app runs a Claude Code of its own beside the one on the PATH.
A session's start reads the probes' file once and runs no probe.
Where the probes are due, the first turn of the main conversation waits for them, which happens once for a version on a kind of host.
The answers are kept in `<project>/.claude/p4/native/probes.json` under `hosts.<kind>`, each with what was seen and the version it was read on.

When an answer differs from the one kept, or from the one its decision was made on where none is kept, the session is told once that the decision can be reopened, with what changed.
The notice is a line of the transcript for ezexe, and the next prompt of any session of the project carries it to the model as context and takes it out of the file.
A change of version also names the conditions no probe reads by itself, beside `/release-notes`.
A project with no `.claude/p4` keeps no answer, so there the probes run on request alone.

A probe is one of three kinds.

- `asked`: the module reads the answer itself, from the capability map or from one call that changes nothing.
- `seen`: the answer is read off a call the session makes anyway, since asking would start a session.
- `by hand`: no reading is free of a side effect or a second session, so the probe names the check a session or ezexe runs.

The probe of a plugin's own compaction asks for a compaction that this module's own `session.compact` hook vetoes, at the end of a turn, so no probe ever compacts a session.

- `start-on-an-unattended-turn`, seen: p4-phi's upkeep hands a step to a live session, a terminal worker or the app's card where the app refuses a start.
- `list-events-of-a-session-at-work`, asked: p4-phi keeps a worker's reports itself in place of the app's `list_events`.
- `app-tools-in-a-terminal-session`, asked: p4-phi keeps its reads of the desktop app's record files as the fallback.
- `module-call-of-an-app-tool`, asked: p4-phi's hooks module asks the app's own tools by `$.tool.call` unless a store turns `app_tools` off.
- `session-compact-from-a-module`, asked: p4-temportal compacts a quiet session by running `/compact` with `$.command.run`.
- `set-goal-tool`, asked: p4-phi sets a worker's goal by running `/goal` with `$.command.run`.
- `fullscreen-at-session-start`, asked: p4-phi opens its pane only by the typed `/phi-pane`.
- `goal-as-a-first-prompt`, by hand: p4-phi sets a worker's goal from its hooks module after the first turn.
- `agent-teams-in-the-desktop-app`, by hand: the settings keeper does not write `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, and a team is led from a terminal session.
- `message-held-across-permission-modes`, by hand: a message to a session in another permission mode is not relied on.
- `skills-copy-named-like-an-installed-plugin`, by hand: a development copy is checked live through a session's mods folder.
- `unknown-event-in-a-module`, by hand: each p4 hooks module hooks only events of Claude Code 2.1.326.
- `file-changed-for-a-new-file`, by hand: p4-temportal moves no notebook file at a `FileChanged` hook.
- `reload-plugins-and-session-start`, by hand: no p4 plugin relies on `/reload-plugins` running its SessionStart hooks again.
- `output-styles-stacking`, by hand: p4-phi ships its rule to act and not wait as no output style.
- `wake-when-done-on-a-card`, by hand: no card p4-phi's upkeep proposes carries `wake_when_done`.

The tool `mcp__p4-native__native` and `/native` take `probes`, which lists every condition that fits this host with its decision, its fault, its check and the answer kept, and `probe`, which reads the asked probes anew and prints each answer.

Two rows of the list this began from are sorted otherwise here.
A hooks module's `$.tool.call` reached the app's tools on Claude Code 2.1.326 and not in a scripted run on 2.1.328 because the scripted run has none of those tools, not because of the version, so it is two probes, one for each kind of host.
The desktop app's `list_events` answered a session at work with its messages when the probe first read it, on Claude Code 2.1.326, so that condition reads `open` and its decision can be reopened.

## ezexe's own choices

These were declined by choice and not by a block, so each stays a setting of Claude Code or of the desktop app, and p4-native writes none of them and probes none.

- The pull request flow: `mcp__ccd_pr__`, `/autofix-pr` and auto-merge, where ezexe lands by a local gate and a push to `main`.
- Scheduled runs: `/schedule`, the desktop app's scheduled tasks, `CronCreate` and `/loop`, where each run is a new session that spends usage.
- Models, effort, fast mode and the advisor: `/model`, `/effort`, `/fast` and `/advisor`.
- Permission modes, plan mode, auto mode and the sandbox: `/permissions`, `/plan`, `/auto-mode-setup` and `/sandbox`.
- `autoCompactWindow`, `idleCompaction`, the memory toggle `/memory`, and `cleanupPeriodDays` for how long transcripts stay.

## Seen live

Seen on Claude Code 2.1.328, in a `claude -p` run with the plugin loaded by `--plugin-dir`, started from a desktop session's shell with that session's variables in its environment: the entry read `terminal`, `scripted`, no surface and no tool of the desktop app, and it listed 31 tools of Claude Code, `PushNotification`, `CronCreate` and `SendMessage` among them.
The run took four seconds end to end.
Seen in the desktop app on Claude Code 2.1.326, with a development copy loaded from the session's mods folder into a session another session started: the entry read `desktop`, `interactive`, the one surface `desktop`, 67 tools of the desktop app and 43 of Claude Code, and the tool `mcp__p4-native__native` printed the same entry and named its file.
In that desktop session `probe` read four conditions: `list_events` answered a session at work with `showing 1 of 6779 messages`, the module's call of `get_session` answered, `SetGoal` was not in the tool list, and `session.start` carried `cwd`, `surface` and `isInteractive`.
In a `claude -p` run on Claude Code 2.1.328 the first turn kept three answers and the turn's end a fourth: the plugin's `$.session.compact` was rejected with `not available in a headless (-p / SDK) session yet`, before any hook heard it, so the veto was not reached.
Seen in the desktop app on Claude Code 2.1.326: `$.session.compact` called while a `tool.call` hook is held is rejected with `called from a tool.call hook`, which is why that probe waits for the turn's end.
Not seen live: a session at a terminal's prompt, a session whose id a `/clear` changed, a change of version between two runs, a notice carried by a prompt, and a call of `start_session` passing through the hook that watches it.

## Tests

`python -m pytest`, run in `lbiza/`, runs the tests under `tests/p4-native/`, and `claude plugin test lbiza/plugins/p4-native` runs the module's own in `hooks/register.test.ts`.
