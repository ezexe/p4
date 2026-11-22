# p4-native

The host layer of ezexe/p4, in one plugin.
It is the one place that knows what this host can do, it watches the conditions that would reopen a decision the platform blocked, and it holds the native features that fit neither p4-phi nor p4-temportal.
The rule it works by is "Native first", on https://github.com/ezexe/p4/wiki/Contributing: where Claude Code or the desktop app does a thing, a plugin configures or calls it and builds no copy.

## Install

```bash
claude plugin marketplace add ezexe/p4
claude plugin install p4-native@p4-marketplace
```

The plugin is a hooks module alone, `hooks/register.ts`, whose functions run inside Claude Code.
It runs no command hook and starts no process at a session's start, and it carries no copy of `p4conf.py`, since it writes no setting.
A hooks module needs Claude Code v2.1.287 or later, and it does not load in a session started with `--safe-mode` or `--bare`, where `disableAllHooks` is set, or where managed settings block mods, by https://code.claude.com/docs/en/plugins/mods/create.md.
The lowest Claude Code this module was seen to load on is 2.1.311, the oldest on the machine it was tried on, and it loads on 2.1.322 too: the debug log of a `claude -p` run on each holds `hooks module p4-native@inline loaded` with the events `session.start,prompt.submit,turn.start,turn.complete,session.compact,tool.call,classic.PostToolUse,command.run`.
Both builds know every event the module names and lack one method it calls, `$.session.info`, so the map's entry is written there with no `platform`.
A call of a method the build lacks throws where it is made, before there is a promise to catch, and until p4-native 0.5.9 that cost the whole map on those builds, with the debug line `the capability map was not read: $.session.info is not a function`.

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

## The command and the skill

The hooks module registers the command `/native`, and the plugin's skill is named `host`, which a session's list shows as `p4-native:host`.
The two names differ on purpose: Claude Code gives a plugin's skill the command `/<plugin>:<skill>` and refuses a module's command of the skill's name.
Until p4-native 0.5.15 the skill was named `native`, and the debug log of every session held `/native was not registered: p4-native: $.command.register: "/native" refused: it is the plugin's /p4-native:native`, seen on Claude Code 2.1.311, 2.1.322 and 2.1.328.
So `/native` ran the skill's page and never the module's command, and `probes`, `probe` and `weighed` answered through the tool alone.
Seen on Claude Code 2.1.328 in a `claude -p` run of a copy where the skill is named `host`: the debug log held `$.command.register (p4-native): /native listed`, and the prompt `/native` printed the map.
Not seen: the command typed in the desktop app.

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
p4-temportal reads it: its hooks module's search for a python reads `platform` from this session's own entry and falls back to the shape of the plugin's folder.
p4-phi does not read the map yet.

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
- `session-compact-from-a-module`, asked: p4-temportal asks for the compaction of a quiet session by `$.session.compact` and runs `/compact` with `$.command.run` where that call is refused.
- `set-goal-tool`, asked: p4-phi sets a worker's goal by running `/goal` with `$.command.run`.
- `fullscreen-at-session-start`, asked: p4-phi opens its pane only by the typed `/phi-pane`.
- `goal-as-a-first-prompt`, by hand: p4-phi sets a worker's goal from its hooks module after the first turn.
- `agent-teams-in-the-desktop-app`, by hand: the settings keeper does not write `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, and a team is led from a terminal session.
- `message-held-across-permission-modes`, by hand: a message to a session in another permission mode is not relied on.
- `skills-copy-named-like-an-installed-plugin`, by hand: a development copy is checked live through a session's mods folder.
- `unknown-event-in-a-module`, by hand: a p4 hooks module names an event an older Claude Code lacks by a glob and tests `next.event`, as p4-temportal does for `tool.run`, and p4-phi's module names `tool.run` itself.
- `reload-plugins-and-session-start`, by hand: no p4 plugin relies on `/reload-plugins` running its SessionStart hooks again.
- `output-styles-stacking`, by hand: p4-phi ships its rule to act and not wait as no output style.
- `wake-when-done-on-a-card`, by hand: no card p4-phi's upkeep proposes carries `wake_when_done`.

The probe `start-on-an-unattended-turn` reads the origin of the prompt that began the turn, which is the last one submitted while the session was idle.
A prompt that carries a `turnId` came into a running turn, as a background task's notice does, and began none, so a start after it says nothing of the condition.
Neither does a start in the turn after it, since `turn.start` names no origin and that prompt may have begun the turn or been read inside the one before.
Until p4-native 0.5.11 the module read the origin of the latest prompt: seen in the desktop app on Claude Code 2.1.326, a start in a turn that ezexe's own message began was told as open, with the words "a start went through on a turn a prompt of the origin task-notification began", after a task's notice had arrived in the middle of that turn.

The tool `mcp__p4-native__native` and `/native` take `probes`, which lists every condition that fits this host with its decision, its fault, its check and the answer kept, and `probe`, which reads the asked probes anew and prints each answer.

Three rows of the list this began from are sorted otherwise here.
A hooks module's `$.tool.call` reached the app's tools on Claude Code 2.1.326 and not in a scripted run on 2.1.328 because the scripted run has none of those tools, not because of the version, so it is two probes, one for each kind of host.
The probe of `list_events` reads the rows under the tool's header and never the header, which says `showing n of m messages` whether or not anything is under it.
Its first rule read the header and called the condition open, which was wrong: a call on a session at work answered with that header and one row under it, the stub of a tool call.
The fault comes and goes: one call answered `(no messages)`, another a lone stub, and a third rows with the assistant's own words.
So the probe asks three times, for 3, 14 and 30 messages, and the condition is open only where every answer holds what the session's assistant said, and blocked where any one shows the fault.
An answer kept under the first rule is compared with nothing.
`FileChanged` for a new file in a watched folder was seen to fire on Claude Code 2.1.328, and p4-temportal 0.3.35 moves a notebook's log at that event, so nothing is blocked there and no probe watches it.

## The inventory

The audits of Claude Code's slash commands, tools and features against p4-phi and p4-temportal were made by hand, row by row.
`hooks/weighed.json` keeps what they came to as one record, 430 rows, so the plugin holds each build against it and a new native feature does not go unnoticed.
A row is a slash command, a tool, a hook event, an event of the hooks module or a method of it, and it says which plugins use it, which declined it and why, which hold it open, or that it was weighed by nobody.
A key that ends in `__` stands for every tool of that server, and one that ends in `*` for every name that begins with it.

What the record comes to, by kind, as `/native weighed` prints it.

- `command`: 131 rows, 20 used, 0 open, 111 declined, 0 weighed by nobody
- `tool`: 122 rows, 47 used, 1 open, 74 declined, 0 weighed by nobody
- `hook`: 33 rows, 13 used, 2 open, 18 declined, 0 weighed by nobody
- `event`: 51 rows, 15 used, 2 open, 34 declined, 0 weighed by nobody
- `method`: 93 rows, 33 used, 2 open, 58 declined, 0 weighed by nobody

When the probes run, at a change of the Claude Code version on a kind of host, the module lists the slash commands Claude Code ships, its own tools and the desktop app's tools, and names once each that has no row: new in this build and weighed by nobody.
The names told are kept in `probes.json` under the kind of host, so a name is told again only after it left the build and came back.
`/native weighed` and the tool's `weighed` print the record's counts and each command and tool of this session that has no row.
A plugin's own command and another server's tool are no part of the host and are left out.

A module cannot list the hook events or the module's own events and methods of the build it runs on, since the engine refuses a read of `$` itself.
So those three kinds are in the record as Claude Code 2.1.326 has them, the hook events read from `hooks.md` and the module's events and methods from that build's types file, and a newer build's are walked by hand.
Nobody had walked them before: 20 of the 33 hook events, 36 of the 51 module events and 50 of the 80 module methods were used by no p4 plugin and weighed by nobody.
The 20 hook events are walked now, each against its section of `hooks.md`: 18 are declined, each with its reason, and 2 are open.
An open row names each plugin it would serve and, under `would`, what it would replace or add there.
`Notification` is open for p4-native, which would add a push when a session waits at a permission prompt or sits idle, and `PostToolBatch` for p4-phi, which would write the lookup rows of a parallel batch in one process start.
The 36 module events and the 50 module methods are walked too, each against its own comment in the types file.
The types file lists 93 methods under `$`, and 13 of them had no row at all, so the record holds 93 now: `$.agent.spawn`, `$.config.set`, `$.prompt.compose`, `$.prompt.fill`, `$.prompt.media`, `$.prompt.suggest`, `$.session.append`, `$.telemetry.log`, `$.telemetry.mark`, `$.tool.check`, `$.ui.ask`, `$.ui.focus` and `$.ui.scroll`.
The walk found one use the record had missed: p4-phi's pane reads and writes `$.state` through `read` and `update` of `claude-code`, so `$.state.get` and `$.state.set` are used, and the test reads those two helpers as the two methods.
Of the events, 34 are declined, and `session.attach` and `session.detach` are open for p4-native, which would read the map's surfaces again when a surface joins or leaves.
Of the methods, 58 are declined, and two are open: `$.process.hookEnv` for p4-phi and p4-temportal, which would replace the environment each module builds by hand for a python child, and `$.ui.notify` for p4-native, which would add a notification where a session has no `PushNotification` tool.
Most rows are declined for one of three reasons: the thing is ezexe's own interface, account or choice, it belongs to a part of Claude Code no p4 plugin touches, or a plugin already does the same by a call that also works where no hooks module loads.
The nine tools the record had as weighed by nobody are walked as well, so no row of any kind says so now.
`SetGoal`, `GetGoal` and `PauseGoal` are in the build's types file and in no session's tool list here: ToolSearch found none of the three in a desktop session on Claude Code 2.1.326, with a goal in force and with none, nor in a scripted run and in a terminal session at its prompt on 2.1.328, and `$.tool.list` held none of them in either of those two.
A module's `$.tool.call` of each of the three was rejected with `no tool named "GetGoal" in this session`, and the same for the other two names, in the scripted run and in the terminal session on 2.1.328, and of `SetGoal` in the desktop app on 2.1.326.
The terminal session was started in the desktop app's Terminal panel with its first prompt on its command line and a probe mod loaded by `--plugin-dir`, which made the three calls at the end of the first turn.
Not tested: `GetGoal` and `PauseGoal` through `$.tool.call` in the desktop app, and a terminal session with a goal in force.
So `SetGoal` is open for p4-phi, which would call it in place of the `/goal` its module runs through `$.command.run` once a session has the tool, as the probe `set-goal-tool` watches, and the other two are declined.
`TaskCreate`, `TaskList`, `TaskUpdate` and `TodoWrite` are declined: by the tools reference a newer model gets the Task tools only where ezexe opts in, a session here has none, and p4-phi mirrors the app's `update_plan`.
`MultiEdit` and `KillShell` are no tools of this build, whose types file lists neither, and p4-phi names neither since its 0.11.87, so both rows are declined by all three plugins: `KillShell` is a previous name of `TaskStop`, and `MultiEdit` a legacy name.
A test holds the record to the three plugins' own files, so an event a module hooks, a method it calls and a hook event it runs each have a row that names the plugin.

Seen in the desktop app on Claude Code 2.1.326: every tool of the session had a row, and seven slash commands had none, `/motion`, `/artifact-design`, `/whiteboard`, `/keybindings-help`, `/__remote-workflow`, `/workflow-launch-exec` and `/extra-usage`.
Each of the seven has a row now, and so has `/send-to-project`, which the record had as weighed by nobody.
All eight are declined: three make or style artifacts, two run a workflow the app or a server hands a session, and keyboard shortcuts, spending and Claude Projects are ezexe's own.
No commands page lists the seven, so each verdict rests on the command's own description in the build.
Not seen live: the notice at a change of version.

## One line at a miss

A session sometimes does by hand what a tool of this host does.
`hooks/misses.ts` is a short table of such situations, each with the tool to name, and a row is in it only with a miss seen live behind it.
The module checks the table after a tool call of the session and at the end of a turn, and hands one line of context that names the tool.

- It refuses no call: after a tool call the hooks beneath answer first, their answer is passed on whole, and the line is added to its context.
- A situation is told once in a session.
- A line names only a tool the capability map says answers in this session, and a row whose tools are all missing here hands nothing.
- It starts no process and asks no model: a row is a pattern over a call's own input or a turn's own answer.
- The option `hints` turns it off, and it is on unless ezexe turns it off.

A miss a tool call shows is told beside that call's result, by the `additionalContext` of the classic event `PostToolUse`.
A miss a turn's end shows is a line of the transcript for ezexe at once and context of the session's next prompt.

- `worker-with-no-exit-notice`, at a turn's end: a `claude -p` worker was started in a Terminal tab and no notice was asked for its exit, where `SendMessage` with `notify_when_idle` gives one.
- `turn-ended-with-a-worker-out`, at a turn's end: such a worker is out and nothing is set to wake the session, where `CronCreate` schedules a prompt.
- `gh-run-polled-in-a-loop`, after a call: a shell command polls `gh run` and sleeps, where `gh run watch` run in the background ends by itself.
- `gh-run-list-short-commit`, after a call: `gh run list --commit` is given a short hash, which matches no run.
- `transcript-read-from-disk`, after a call: another session's transcript file is read from disk, where `mcp__ccd_session_mgmt__list_events`, `search_session_transcripts` and `export_transcript` exist.
- `host-limit-from-memory`, at a turn's end: the answer states a limit of the host in a session that never asked the plugin, where the map and the probes hold what was measured.

A worker in a Terminal tab is known by `claude -p` in the line typed or in the one script file that line runs, which the module reads.
The last row reads the answer for a sentence that says the desktop app, Claude Code, this host or a scripted run cannot do a thing, so it can fire on a sentence that is right.

Seen in the desktop app on Claude Code 2.1.326, with a development copy: a Bash call of `gh run list --commit` with a hash of seven characters came back with its result and the line of `gh-run-list-short-commit` as `PostToolUse:Bash hook additional context`.
Not seen live: the other five rows, and a line carried by a next prompt.

## ezexe's own choices

These were declined by choice and not by a block, so each stays a setting of Claude Code or of the desktop app, and p4-native writes none of them and probes none.

- The pull request flow: `mcp__ccd_pr__`, `/autofix-pr` and auto-merge, where ezexe lands by a local gate and a push to `main`.
- Scheduled runs: `/schedule` and the desktop app's scheduled tasks, where each run is a new session that spends usage.
- Models, effort, fast mode and the advisor: `/model`, `/effort`, `/fast` and `/advisor`.
- Permission modes, plan mode, auto mode and the sandbox: `/permissions`, `/plan`, `/auto-mode-setup` and `/sandbox`.
- `autoCompactWindow`, `idleCompaction`, the memory toggle `/memory`, and `cleanupPeriodDays` for how long transcripts stay.

## Native features behind an option

Two features of Claude Code that fit neither p4-phi nor p4-temportal are here.
Each is an option of the plugin's `userConfig`, off until ezexe turns it on, and each is one call of Claude Code's own that the module makes and does not wrap.
The third option, `hints`, is on by default and belongs to the lines at a miss above.
The options are rows of `/config` in a terminal session, and they are kept under `pluginConfigs` in `~/.claude/settings.json`, by https://code.claude.com/docs/en/plugins/manifest-reference.md, "User configuration".

```json
{"pluginConfigs": {"p4-native@p4-marketplace": {"options": {"push": true, "status": true, "hints": false}}}}
```

- `push`: ezexe hears on the desktop, and on the phone where Remote Control is connected, that a session ezexe is at ended its turn, so it waits or is done.
- `status`: ezexe sees under the prompt which host a session runs on and which Claude Code version, which differ between the desktop app and a terminal on one machine.

`push` calls the tool `PushNotification` by `$.tool.call` at the end of a turn of the main conversation, with the session's title or the project folder's name and the first line of the turn's answer, 180 characters at most.
It sends nothing in a scripted run, nothing after a turn that was stopped, and nothing in a session another session started, whose turn's end is told to that session.
The tool keeps its own rule and sends nothing while ezexe is at the keyboard, by https://code.claude.com/docs/en/env-vars.md, `CLAUDE_CODE_DISABLE_NOTIFICATION_PRESENCE_CHECK`.
`status` calls `$.ui.status` after each reading of the map, which https://code.claude.com/docs/en/plugins/mods/api.md describes as one line under the prompt that stays until it is changed.

Seen in a terminal session at its prompt on Claude Code 2.1.328, with the plugin loaded by `--plugin-dir` and both options on in a `--settings` file: the line `p4-native: terminal, interactive, Claude Code 2.1.328` stood under the prompt, and at the turn's end the module's call of `PushNotification` was answered in 9 ms with `Not sent`, since the terminal was active.
Not seen: a notification that was sent, either option in the desktop app, and the rows in `/config`.

Left out, each with its reason.

- The agent teams switch for a terminal session: the module set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` to `1` by `$.env.set` at the start of a terminal session on Claude Code 2.1.328, and a teammate asked for by name ran as a background subagent with no folder under `~/.claude/teams/`, so the check failed and the option is not shipped.
- A team is still led from a terminal session by setting that variable in the shell or in a settings file's `env` before the session starts, by https://code.claude.com/docs/en/agent-teams.md.
- Scheduled runs: ezexe's own choice, under the heading above.
- Which copy of each p4 plugin a session runs, and whether the session's window is on screen: a module is told its own folder and no other plugin's, and neither was checked.

## Seen live

Seen on Claude Code 2.1.328, in a `claude -p` run with the plugin loaded by `--plugin-dir`, started from a desktop session's shell with that session's variables in its environment: the entry read `terminal`, `scripted`, no surface and no tool of the desktop app, and it listed 31 tools of Claude Code, `PushNotification`, `CronCreate` and `SendMessage` among them.
The run took four seconds end to end.
Seen in the desktop app on Claude Code 2.1.326, with a development copy loaded from the session's mods folder into a session another session started: the entry read `desktop`, `interactive`, the one surface `desktop`, 67 tools of the desktop app and 43 of Claude Code, and the tool `mcp__p4-native__native` printed the same entry and named its file.
In that desktop session `probe` read four conditions: `list_events` answered a session at work with the header `showing 1 of 6779 messages`, the module's call of `get_session` answered, `SetGoal` was not in the tool list, and `session.start` carried `cwd`, `surface` and `isInteractive`.
In a `claude -p` run on Claude Code 2.1.328 the first turn kept three answers and the turn's end a fourth: the plugin's `$.session.compact` was rejected with `not available in a headless (-p / SDK) session yet`, before any hook heard it, so the veto was not reached.
Seen in the desktop app on Claude Code 2.1.326: `$.session.compact` called while a `tool.call` hook is held is rejected with `called from a tool.call hook`, which is why that probe waits for the turn's end.
At that turn's end the same desktop session kept `session-compact-from-a-module` as `blocked`, with the same refusal as the scripted run.
The notice that first rule made reached the model once, as context of the session's next prompt, and was gone from the file, and it reached a second session of another project from the installed copy.
Seen with the installed copy, version 0.2.0, in a `claude -p` run on Claude Code 2.1.328: the session loaded the tool with ToolSearch, and `map` and `probes` answered.
Seen in a terminal session at its prompt on Claude Code 2.1.328: the entry read `terminal`, `interactive` and the one surface `terminal`, and the probes ran for `terminal/interactive`.
Not seen live: a session whose id a `/clear` changed, a change of version between two runs, a call of `start_session` passing through the hook that watches it, and the installed copy in a desktop session, where every check ran a development copy.

## Tests

`python -m pytest`, run in `lbiza/`, runs the tests under `tests/p4-native/`, and `claude plugin test lbiza/plugins/p4-native` runs the module's own in `hooks/register.test.ts`.
