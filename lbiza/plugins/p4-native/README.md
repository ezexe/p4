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
The lowest Claude Code this module was seen to load on is 2.1.311, the oldest on the machine it was tried on, and it loads on 2.1.322 too: the debug log of a `claude -p` run on each holds `hooks module p4-native@inline loaded` with the events `session.start,prompt.submit,turn.start,turn.complete,classic.Notification,session.attach,session.detach,session.compact,tool.call,classic.PostToolUse,command.run`, which are the events it names since 0.5.28.
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
It is read again too when a surface joins the session or leaves it, as a phone that opens the session or the desktop app that connects: the module hooks `session.attach` and `session.detach`, so the entry's surfaces are those of now.
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
For a session in a git worktree the project is the main checkout, which the module asks of `$.session.repo`, so the map and the probes' answers of every worktree session are in the main checkout's store: what a host is and can do is no fact about one checkout, and a worktree's own store goes with the worktree.
Where the main checkout has no store, a worktree's own is the project's.
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
A turn that a notice began and that a message of a person then came into is attended: the app starts a session on it, so from that prompt on the turn has no origin, and a start on it says nothing of the condition.
Seen in the desktop app on 2026-11-22, before this was so: a task's notice began a turn, ezexe wrote into it twice, the session then started another, and the probe told it as a start on a turn no person began.
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
`hooks/weighed.json` keeps what they came to as one record, 653 rows, so the plugin holds each build against it and a new native feature does not go unnoticed.
A row is a slash command, a tool, a hook event, an event of the hooks module or a method of it, and it says which plugins use it, which declined it and why, which hold it open, or that it was weighed by nobody.
448 rows are of those five kinds, and 205 are of a sixth, `doc`, one for each page of the docs index, which carry no verdict.
A key that ends in `__` stands for every tool of that server, and one that ends in `*` for every name that begins with it.

What the record comes to, by kind, as `/native weighed` prints it.

- `command`: 131 rows, 22 used, 0 open, 109 declined, 0 weighed by nobody
- `tool`: 124 rows, 55 used, 1 open, 68 declined, 0 weighed by nobody
- `hook`: 33 rows, 15 used, 0 open, 18 declined, 0 weighed by nobody
- `event`: 60 rows, 19 used, 0 open, 41 declined, 0 weighed by nobody
- `method`: 100 rows, 36 used, 0 open, 64 declined, 0 weighed by nobody
- `used`: 147 rows, 54 watched by a row of misses.ts, 93 with no by-hand call to watch, 0 with neither

When the probes run, at a change of the Claude Code version on a kind of host, the module lists the slash commands Claude Code ships, its own tools and the desktop app's tools, and names once each that has no row: new in this build and weighed by nobody.
The names told are kept in `probes.json` under the kind of host, so a name is told again only after it left the build and came back.
`/native weighed` and the tool's `weighed` print the record's counts and each command and tool of this session that has no row.
The counts answer who builds on a thing, and the section below gives what a session reads of a row.
A plugin's own command and another server's tool are no part of the host and are left out.

A module cannot list the hook events or the module's own events and methods of the build it runs on, since the engine refuses a read of `$` itself.
So those three kinds are in the record as Claude Code 2.1.330 has them, the hook events read from `hooks.md` and the module's events and methods from that build's types file, and a newer build's are walked by hand.
The record was made on Claude Code 2.1.326, and the types file of 2.1.330 holds nine events and seven methods more: the events `agent.report`, `tool.offer`, `ui.close`, `vcs.detect`, `vcs.diff`, `vcs.isolate`, `vcs.list`, `vcs.release` and `vcs.status`, and the methods `$.session.machine`, `$.vcs.detect`, `$.vcs.diff`, `$.vcs.isolate`, `$.vcs.list`, `$.vcs.release` and `$.vcs.status`.
Each has a row since 0.5.32, with the verdict of p4-temportal and of p4-native, which both declined all sixteen: neither draws a pane, answers for a version control system or makes a working copy, the calls of `$.vcs` are marked experimental, and `$.session.machine` names the kernel, the hardware and the JavaScript runtimes, which no p4 plugin asks for.
p4-phi weighed them in 0.5.38 and declined fourteen: it answers for no version control system, its upkeep reads a worktree by git itself, since that also runs as a command hook where no hooks module loads, it rewrites no agent's report, and it reads the platform from p4-native's map.
It held two open, `tool.offer` and `ui.close`.
`tool.offer` is used since p4-phi 0.11.129: where python says a session was started by another session and its plan rule is on, the module answers the offer of `EnterPlanMode` with `isOffered` false, so the session's model is not given the tool its rule keeps it from.
The event is in the types of Claude Code from 2.1.328 on, the module names it under its one glob `tool.*`, which a build with no such event hands nothing, and there the rule's sentence stands alone.
`ExitPlanMode` stays offered, so a plan made where ezexe typed `/plan` in such a session is still put to ezexe.
Seen in a scripted session on 2.1.328 and on 2.1.330, with a probe plugin that answered so for `Read`: the model replied that it has no such tool.
Not seen: `EnterPlanMode` withheld in a session, since a scripted run has no such tool and the desktop app's sessions run 2.1.326.
`ui.close` is used since p4-phi 0.11.130: its module hears its pane close there, by the person's close or a plugin's, and counts it closed from then, where it asked `$.ui.panes` after each look.
So `$.ui.panes` is declined by all three now, and no look lists a pane.
What the event does not tell is an `unload`, at which by the types a pane's own opener is not told: p4-phi's drawing answers for its own faults, so its pane goes that way only with the plugin itself.
`claude plugin test` has no call that raises the event, so a test hands the hook's own function the event's input.
Seen in a scripted session on Claude Code 2.1.328 and on 2.1.330, with a probe plugin: a `$.ui.close` raised `ui.close` at a hook of the plugin, with the pane's id and the origin `plugin`.
Not seen: a person's own close, which takes ezexe's click, and a close in the desktop app's Claude Code 2.1.326.
`ui.close` is in the types of 2.1.326, 2.1.328 and 2.1.330, and under `claude plugin test` of 2.1.328 and 2.1.330 `$.ui.close` is not a function, so no test can raise it.
So the record holds 60 module events and 100 module methods, where the paragraphs below count the 51 and the 93 of 2.1.326.
Nobody had walked them before: 20 of the 33 hook events, 36 of the 51 module events and 50 of the 80 module methods were used by no p4 plugin and weighed by nobody.
The 20 hook events are walked now, each against its section of `hooks.md`: 18 are declined, each with its reason, and the two that were open are used.
An open row names each plugin it would serve and, under `would`, what it would replace or add there.
`PostToolBatch` was open for p4-phi, which since 0.11.116 writes the lookup rows of a batch of calls in one process start.
`Notification` was open for p4-native, whose module hooks it since 0.5.28 and pushes when a session waits at a permission prompt or sits idle.
The 36 module events and the 50 module methods are walked too, each against its own comment in the types file.
The types file lists 93 methods under `$`, and 13 of them had no row at all, so the record holds 93 now: `$.agent.spawn`, `$.config.set`, `$.prompt.compose`, `$.prompt.fill`, `$.prompt.media`, `$.prompt.suggest`, `$.session.append`, `$.telemetry.log`, `$.telemetry.mark`, `$.tool.check`, `$.ui.ask`, `$.ui.focus` and `$.ui.scroll`.
The walk found one use the record had missed: p4-phi's pane reads and writes `$.state` through `read` and `update` of `claude-code`, so `$.state.get` and `$.state.set` are used, and the test reads those two helpers as the two methods.
Of the events, 34 are declined, and `session.attach` and `session.detach`, which were open for p4-native, are used since 0.5.28: its module reads the map again when a surface joins or leaves.
Of the methods, 57 are declined and none is open.
`$.ui.notify`, which was open for p4-native, is used since 0.5.28, where a session has no `PushNotification` tool.
`$.process.hookEnv` is used by p4-phi, whose module hands its python children the variables a command hook gets, and by p4-temportal since 0.3.57, for the environment of its python child and for its data folder.
p4-temportal's module names the project itself, since for a session in a git worktree that the desktop app made the variable names the main checkout, and lifetime.py clears a worktree's own store first.
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

## What a row says, and what is new in a build

The record answers who builds on a thing, and a session that reads `declined` there can take it for advice not to use the thing, which it is not.
So each row also says what the thing does, in Claude Code's own words, and that line is what a session reads.

- A slash command's and a tool's line is its own description, which the module reads from the session when it is asked, by `$.command.list` and `$.tool.list`, so it is the build's own at every version and the record keeps no copy.
- A hook event's line is its row of the lifecycle table of `hooks.md`, and a module event's and a module method's is the first sentence of its own comment in the types file.
- A module cannot list those three kinds, so `lbiza/scripts/native_says.py` writes their lines into the record at each change of version: 33 of 33 hook events, 55 of 60 module events and 100 of 100 module methods have a line of their own, and the other 5 events say their kind.
- A row of the kind `doc` stands for one page of the docs index, https://code.claude.com/docs/llms.txt, with the page's title and description as its line and its address under `page`: 205 rows.
- A settings key, an environment variable, a command-line flag and a feature with no command or tool have no row of their own, and are found through the page that holds them.

`/native <name>`, and the tool with that word as its `command`, look a word up: each row whose key or line holds it, eight at most, a key the word names outright first.
A row prints its name, its kind, whether a command or a tool is in this session, and its line, then what the p4 plugins made of it, worded as who builds on it: a plugin that declined a row built nothing on it.
The answer ends by saying that this is no advice against using it, and `/native weighed` says the same under its counts.

At a change of the Claude Code version on a kind of host the module keeps the names of the build's slash commands and tools in `probes.json`, and holds them against the names kept for the build before.
What the new build holds that the old one did not, and what it no longer holds, is one notice, told once, and it is kept: each later session on that build reads it as one line of context with its first prompt, unless `hints` is off.
`/native new` prints the two lists whole.

With the probes the module also fetches the docs index, by `$.http.fetch`, with the host `code.claude.com` declared under `network.hosts` in the manifest, and names once each page that has no row, so a feature that arrives as a docs page alone does not go unnoticed.
`/native docs` fetches it on request and prints the pages with no row and the rows whose page is gone.
A fetch that is refused, or that does not answer in eight seconds, costs the probes nothing.

Seen in a scripted run on Claude Code 2.1.328 and on 2.1.330: a hooks module's `$.http.fetch` of the index answered status 200 with 49,695 characters in about 70 ms, with the host declared and with none declared.
Seen in a scripted run on Claude Code 2.1.328, with the plugin loaded by `--plugin-dir`: `/native compact` printed `/compact` with the build's own description, "Free up context by summarizing the conversation so far", then `$.session.compact`, `/autocompact`, the hook events `PostCompact` and `PreCompact`, the module event `session.compact` and two docs pages, each with its line, and `/native docs` fetched the index and found a row for each of its 205 pages.
Not tested: the fetch in the desktop app.
Not seen live: the notice of a change of version, and the line at a later session's first prompt.
Held against the types file of Claude Code 2.1.330, the record had no row for nine module events and seven module methods, `agent.report` and `$.session.machine` among them, which the script printed and which have a row since 0.5.32.
The script prints such names at each run and adds none, since a row carries each plugin's verdict, which is a walk made by hand.

## One line at a miss

A session sometimes does by hand what a native feature of this host does.
`hooks/misses.ts` is the table of such situations, each with the feature to name.
Six rows have a miss seen live behind them, and each says when it was seen.
The other 37 are written from the record: one for each slash command and tool a p4 plugin uses that a session can also do by hand, with the by-hand way it is read off.
Every row of `hooks/weighed.json` that a plugin uses names under `miss` the rows that watch it, or says under `nowatch` in one line why no by-hand call exists to watch, and a test holds that.
Of the 147 used rows, 54 are watched by a row of the table and 93 say why none watches them: the 70 hook events, module events and module methods, which only a hooks module hooks or calls, and 23 commands and tools whose work no file or command a session reaches does.
The module checks the table after a tool call of the session and at the end of a turn, and hands one line of context that names the feature.

- A line refuses no call: after a tool call the hooks beneath answer first, their answer is passed on whole, and the line is added to its context.
- A situation is told once in a session.
- A line names only a tool the capability map says answers in this session, and a row whose tools are all missing here hands nothing.
- A row that stands for a slash command names the command alone, which is ezexe's to type.
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

The rows written from the record, each with the by-hand way it is read off and the rows of the record it stands for.

- `file-read-by-a-shell`, after a call: a shell command prints one file with `cat`, `head`, `tail`, `less`, `more`, `type` or `Get-Content`. It stands for `Read`.
- `files-found-by-a-shell`, after a call: a shell command lists files by name with `find`, `ls -R`, `dir /s` or `Get-ChildItem -Recurse`. It stands for `Glob`.
- `text-searched-by-a-shell`, after a call: a shell command searches file contents with `grep`, `rg`, `findstr` or `Select-String` at the head of a pipeline. It stands for `Grep`.
- `file-edited-by-a-shell`, after a call: a shell command changes a file in place with `sed -i`, `perl -pi`, `awk -i inplace` or `-replace` piped to `Set-Content`. It stands for `Edit`.
- `file-written-by-a-shell`, after a call: a shell command writes text into a file with `echo` or `printf` and a redirect, a heredoc, `Set-Content` or `Add-Content`. It stands for `Write`.
- `notebook-edited-as-a-file`, after a call: an `Edit` or `Write` call changes a Jupyter notebook as a text file. It stands for `NotebookEdit`.
- `powershell-run-from-bash`, after a call: a `Bash` call runs `powershell` or `pwsh` with a command of its own. It stands for `PowerShell`.
- `bash-run-from-powershell`, after a call: a `PowerShell` call runs `bash`, `sh` or `wsl` with a command of its own. It stands for `Bash`.
- `page-fetched-by-a-shell`, after a call: a shell command gets a public web page with `curl`, `wget`, `Invoke-WebRequest` or `Invoke-RestMethod`. It stands for `WebFetch`.
- `search-engine-fetched`, after a call: a shell command or a `WebFetch` call gets a search engine's results page. It stands for `WebSearch`.
- `claude-run-in-a-shell`, after a call: a `Bash` or `PowerShell` call starts a scripted Claude Code run with `claude -p`. It stands for `Agent`, `mcp__ccd_session__start_session`.
- `claude-runs-fanned-out-in-a-shell`, after a call: a shell command starts several scripted Claude Code runs, in a loop or side by side. It stands for `Workflow`.
- `session-messaged-in-a-shell`, after a call: a shell command sends a prompt into a session that exists, with `claude --resume` or `--continue` and `-p`. It stands for `mcp__ccd_session_mgmt__send_message`.
- `session-resumed-in-a-shell`, after a call: a shell command resumes or forks a session with `claude --resume`, `--continue` or `--fork-session`. It stands for `/resume`, `/fork`.
- `page-opened-from-a-shell`, after a call: a shell command opens an HTML file in a browser with `start`, `open`, `xdg-open` or `Invoke-Item`. It stands for `Artifact`.
- `sessions-found-by-their-processes`, after a call: a shell command lists the machine's processes and picks out Claude Code's. It stands for `ListAgents`, `mcp__ccd_session_mgmt__list_sessions`, `/list-agents`.
- `notification-raised-from-a-shell`, after a call: a shell command raises a notification of the system or rings its bell. It stands for `PushNotification`.
- `long-sleep-in-a-shell`, after a call: a shell command sleeps for a minute or longer. It stands for `ScheduleWakeup`.
- `loop-with-a-sleep-in-a-shell`, after a call: a shell loop runs a step again and again with a sleep between. It stands for `/loop`.
- `skill-read-as-a-file`, after a call: a `Read` call or a shell command prints a skill's `SKILL.md`. It stands for `Skill`.
- `process-killed-in-a-shell`, after a call: a shell command stops a process with `kill`, `pkill`, `taskkill` or `Stop-Process`. It stands for `TaskStop`, `mcp__terminal__stop_terminal_tab`, `mcp__ccd_session_mgmt__stop_session`.
- `backup-copy-made-by-hand`, after a call: a shell command copies a file to a `.bak`, `.orig`, `.old` or `.backup` beside it. It stands for `/rewind`, `Checkpoints`.
- `worktree-removed-in-a-shell`, after a call: a shell command removes a git worktree, or a folder under `.claude/worktrees`. It stands for `mcp__ccd_host__discard_kept_worktree`, `mcp__ccd_host__clean_up_worktrees`.
- `store-measured-in-a-shell`, after a call: a shell command adds up the size of a `.claude` folder with `du` or `Measure-Object`. It stands for `mcp__ccd_host__get_storage_usage`.
- `transcript-copied-by-hand`, after a call: a shell command copies this session's own transcript file. It stands for `/export`.
- `transcript-measured-by-hand`, after a call: a shell command measures this session's own transcript file to tell how full the conversation is. It stands for `/context`.
- `model-set-by-hand`, after a call: an edit of a settings file sets `model` or `effortLevel`, or a shell command sets `ANTHROPIC_MODEL`. It stands for `/model`.
- `store-file-removed-by-hand`, after a call: a shell command deletes a file of the project's `.claude/p4` store, or an edit changes its `expires.json`. It stands for `/lifetime`.
- `plugin-files-changed-by-hand`, after a call: a shell command or an edit changes the installed plugins' files under `.claude/plugins`. It stands for `/plugin`, `/reload-plugins`.
- `release-notes-fetched-by-hand`, after a call: a shell command or a `WebFetch` call gets Claude Code's changelog or its package page. It stands for `/release-notes`.
- `review-handed-to-an-agent`, after a call: an `Agent` call asks a subagent to review a code change. It stands for `/code-review`, `/review`.
- `task-list-kept-by-another-tool`, after a call: a `TaskCreate` or `TodoWrite` call keeps a task list in a session of the desktop app. It stands for `mcp__ccd_turn__update_plan`.
- `question-asked-in-prose`, at a turn's end: a turn's answer ends with a question and its choices written out as a list. It stands for `AskUserQuestion`, `mcp__ccd_turn__wrap_up`.
- `tool-said-missing-with-no-search`, at a turn's end: a turn's answer says the session has no tool for a thing, in a session that never searched its deferred tools. It stands for `ToolSearch`.
- `context-said-full`, at a turn's end: a turn's answer says the conversation is long or tells ezexe to start a new one. It stands for `/compact`.
- `terminal-output-asked-of-ezexe`, at a turn's end: a turn's answer asks ezexe to paste what a terminal printed. It stands for `mcp__terminal__read_terminal`.
- `command-handed-to-ezexe`, at a turn's end: a turn's answer tells ezexe to run a command in a terminal. It stands for `mcp__terminal__run_in_terminal`.

A worker in a Terminal tab is known by `claude -p` in the line typed or in the one script file that line runs, which the module reads.
The row `host-limit-from-memory` reads the answer for a sentence that says the desktop app, Claude Code, this host or a scripted run cannot do a thing, so it can fire on a sentence that is right.
A row written from the record is read off how the by-hand call is spelled, so it too can fire on a call that is right: a shell command is read stage by stage, a command that only takes another's output through a pipe sets off no row, and neither does a request to a local address, a download to a file or a post.
A line is context for the model and no verdict, and each is handed once in a session.

Seen in the desktop app on Claude Code 2.1.326, with a development copy: a Bash call of `gh run list --commit` with a hash of seven characters came back with its result and the line of `gh-run-list-short-commit` as `PostToolUse:Bash hook additional context`.
Not seen live: the other five of the six rows, any row written from the record, and a line carried by a next prompt.

## A row's option refuses the by-hand call

Each row checked at a call has an option of its own in the plugin's `userConfig`, `refuse_` and the row's id spelled with underscores, 35 in all.
Each is off unless ezexe turns it on, and each is a row of `/config` in a terminal session, kept under `pluginConfigs` like the three options below.
The manifest reference gives no grouped form for this.
By https://code.claude.com/docs/en/plugins/manifest-reference.md, "User configuration", `options` "applies to a `string` field that isn't `multiple`", and a `multiple` list is no row of `/config`, so one boolean for each row is the declared way.

```json
{"pluginConfigs": {"p4-native@p4-marketplace": {"options": {"refuse_text_searched_by_a_shell": true}}}}
```

- With a row's option on, the module refuses the by-hand call at `tool.call`, before the call runs and before its permission check, and the refusal is the row's line, which names the native feature, and the option that refused it.
- A call is refused only where a tool the line names answers in this session, so no session is refused the by-hand way on a host that has no other.
- A call a hooks module made itself is never refused.
- With no such option on, the module hooks no call of another tool.
- `hints` stays the one switch for the lines, and a refusal is no line: with `hints` off and a row's option on, the call is still refused.
- The eight rows checked at a turn's end have no option, since an answer already written is no call to refuse.

A pattern can fire on a call that is right, and a refused call has no way through but the option, so each is ezexe's to turn on where the by-hand way is never wanted.

Seen in a scripted run on Claude Code 2.1.328 and again on 2.1.330, with the plugin loaded by `--plugin-dir` and `refuse_text_searched_by_a_shell` on under `pluginConfigs`, `p4-native@inline`, in a `--settings` file: the session's Bash call of `grep -rn TODO src` came back as a tool error that held the row's line and the option's name, and no permission was asked for it.
Not seen live: a refusal in the desktop app, any other row's refusal, and the 35 rows in `/config`.

## What ezexe chose, and what sessions decided

Two things here are ezexe's own word.

- No pull requests: work lands by its checks passing on the commit and a push to `main`, so the pull request flow, `mcp__ccd_pr__`, `/autofix-pr` and auto-merge, is not taken up.
- Planning and delegation follow two skills, `plan-planner` and `sub-agentic`: a plan is shaped and tracked as the first says, and every subagent, fork, workflow and started session gets its model and its effort by its role, as the second says. No p4 plugin sets a session's own model, so `/model` and `/effort` stay ezexe's to change.

The rest were verdicts of the sessions that weighed the rows, and ezexe gave none of them.
Each stays a setting of Claude Code or of the desktop app that p4-native neither writes nor probes, and each is ezexe's to reopen.

- Fast mode and the advisor: `/fast` and `/advisor`.
- Permission modes, auto mode and the sandbox: `/permissions`, `/auto-mode-setup` and `/sandbox`.
- `autoCompactWindow`, `idleCompaction` and the memory toggle `/memory`.
- The desktop app's scheduled tasks.

Three that sessions had called declined are reopened on ezexe's word, as open rows of `weighed.json` for p4-phi to take up the way it took up `/goal` and `/loop`: plan mode, with `/plan`, `EnterPlanMode` and `ExitPlanMode`, the prompts on a schedule inside a session, with `CronCreate`, `CronDelete` and `CronList`, and the scheduled runs of `/schedule`.
The prompts on a schedule are taken up since p4-phi 0.11.119: while a worker in the Terminal panel is live, whose end the app sends no note of, its upkeep hands `/loop` with an interval, which Claude Code runs by `CronCreate`, after a read of `CronList`, and once the last such worker is gone it hands the end, `CronList` and `CronDelete`.
The scheduled runs are taken up since p4-phi 0.11.122: for a step a session says falls due when no session may be open, `phi.py upkeep wait "<the step>" --at "<when>"` prints `/schedule` with the time and the prompt written, for ezexe to type, since making a run that starts sessions later is ezexe's, and with `--local`, for a step that needs the project's local store, it prints a Desktop scheduled task's instructions in its place, to be made on ezexe's yes.
The desktop app's tool that makes such a task, `mcp__scheduled-tasks__create_scheduled_task`, has its row since 0.5.39, with p4-phi under used: p4-phi names it in the line of a step that needs the local store and calls it nowhere itself.
The server's other tools, which list, change, run and delete a task, have the server's own row since 0.5.42, `mcp__scheduled-tasks__`, declined by all three plugins: to keep a task once it is made is ezexe's in the app.
Plan mode is taken up since p4-phi 0.11.127, by a rule built into p4-phi: a session ezexe is at calls `EnterPlanMode`, the mode `/plan` enters, where a message asks for a change whose approach is open, and puts the plan to ezexe with `ExitPlanMode`, and a session another session started is kept out of plan mode, plans with the built-in `Plan` subagent and takes its starter's message as the approval.
What would settle a plan's approval with no person in such a session is not built: it would be a part of the set of what p4-phi settles with no approval card, which is ezexe's to say yes to.

## Native features behind an option

Two features of Claude Code that fit neither p4-phi nor p4-temportal are here.
Each is an option of the plugin's `userConfig`, off until ezexe turns it on, and each is one call of Claude Code's own that the module makes and does not wrap.
The third option, `hints`, is on by default and belongs to the lines at a miss above, and the 35 `refuse_` options belong to the rows of that table.
The options are rows of `/config` in a terminal session, and they are kept under `pluginConfigs` in `~/.claude/settings.json`, by https://code.claude.com/docs/en/plugins/manifest-reference.md, "User configuration".

```json
{"pluginConfigs": {"p4-native@p4-marketplace": {"options": {"push": true, "status": true, "hints": false}}}}
```

- `push`: ezexe hears on the desktop, and on the phone where Remote Control is connected, that a session ezexe is at ended its turn, so it waits or is done.
- `status`: ezexe sees under the prompt which host a session runs on and which Claude Code version, which differ between the desktop app and a terminal on one machine.

`push` calls the tool `PushNotification` by `$.tool.call` at the end of a turn of the main conversation, with the session's title or the project folder's name and the first line of the turn's answer, 180 characters at most.
It sends nothing in a scripted run, nothing after a turn that was stopped, and nothing in a session another session started, whose turn's end is told to that session.
In a session with no such tool it calls `$.ui.notify` at the turn's end in its place, which raises the notification on ezexe's own channel, the one `preferredNotifChannel` names.
A session that waits on ezexe pushes too.
Claude Code raises its own notification of a permission prompt that has waited about six seconds and of a session idle for about a minute, by https://code.claude.com/docs/en/hooks.md, "Notification", and the module hears both at the classic event `Notification` and calls the tool with Claude Code's own words.
A session that sits idle after a turn whose push went out is not told twice, and a session with no tool is not notified again there, since Claude Code's own notification is already on that channel.
No other type starts a push: a `plugin_notification` is what `$.ui.notify` itself raises.
The tool keeps its own rule and sends nothing while ezexe is at the keyboard, by https://code.claude.com/docs/en/env-vars.md, `CLAUDE_CODE_DISABLE_NOTIFICATION_PRESENCE_CHECK`.
`status` calls `$.ui.status` after each reading of the map, which https://code.claude.com/docs/en/plugins/mods/api.md describes as one line under the prompt that stays until it is changed.

Seen in a terminal session at its prompt on Claude Code 2.1.328, with the plugin loaded by `--plugin-dir` and both options on in a `--settings` file: the line `p4-native: terminal, interactive, Claude Code 2.1.328` stood under the prompt, and at the turn's end the module's call of `PushNotification` was answered in 9 ms with `Not sent`, since the terminal was active.
Seen in a scripted run on Claude Code 2.1.328 and on 2.1.330, with a probe plugin: `$.ui.notify` answered `{"isSent":false,"reason":"no-surface"}`, and a `classic.Notification` hook of the same plugin heard that notification with the type `plugin_notification`.
Not seen: a notification that was sent, either option in the desktop app, and the rows in `/config`.
Not seen live: `$.ui.notify` in a session with a surface, the push of a session that waits, and a surface that joins or leaves, each of which ran under `claude plugin test` alone.
A terminal session started in a hidden console for this stopped at the trust dialog of its scratch folder, whose default is No, and no session answered it.

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
The module's tests pass whole under the test kits of Claude Code 2.1.311, 2.1.322, 2.1.328 and 2.1.330, 61 cases on each.

- The two older kits have no event `session.info`, and a kit refuses a hook on an event it lacks, which until 0.5.34 failed 57 of the 61 cases there.
- So the file's stub for `$.session.info` stands at the glob `session.*` and names the event by `next.event`, and the two cases that read a platform expect none where nothing asked the stub.
- The file names no other event those kits lack, and it enters each call the way a session does, through `$`.
- `claude plugin validate --strict` passes on 2.1.328 and later.
- On 2.1.311 and 2.1.322 it reports one warning, that the manifest's field `network` is unknown and is ignored at load, and fails for that alone: the field names the host of the docs index and, by the manifest reference, requires Claude Code v2.1.328 or later.
