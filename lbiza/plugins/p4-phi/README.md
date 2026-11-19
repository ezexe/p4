# p4-phi

What linked Claude Code sessions hand each other, and retrieval from the project's own history, in one plugin.
The skill `skills/phi/SKILL.md` lists the commands a session runs and what p4-phi does not do.
This page holds how to install p4-phi, the docs sentences its delegation rests on, the model and effort a worker starts with, what sets a subagent's, what p4-phi does for a puppeteer, and the settings, none of which has to be set.

## Install

The marketplace `p4-marketplace` is the repository ezexe/p4, whose root holds the catalog `.claude-plugin/marketplace.json`, so add it by the repository's name, then install each plugin by its own from your shell:

```bash
claude plugin marketplace add ezexe/p4
claude plugin install p4-phi@p4-marketplace
claude plugin install p4-temportal@p4-marketplace
```

Each install is a copy in Claude Code's plugin cache, `~/.claude/plugins/cache/p4-marketplace/<plugin>/<version>/`, at user scope unless `--scope project` or `--scope local` says otherwise.
Claude Code updates installed plugins only from a marketplace whose auto-update is on, and it is off by default for a marketplace like this one: turn it on in a session with `/plugin`, the **Marketplaces** tab, `p4-marketplace`, **Enable auto-update**, or update by hand with `claude plugin update <plugin>@p4-marketplace`.
With auto-update on, a new version reaches the installed copy at the pass Claude Code runs after a session's first message, and a session that is running keeps the version it loaded until `/reload-plugins` or its next start.
Source: https://code.claude.com/docs/en/plugins/install.md, Keep plugins updated, and https://code.claude.com/docs/en/plugins/loading.md, When auto-update runs.

## Delegation

Every behaviour below rests on a sentence of the Claude Code docs at `https://code.claude.com/docs/en/<page>`.

| What the plugin does | The page | The sentence it rests on |
| :- | :- | :- |
| Sends a search or a read across files to the built-in subagent `Explore`, and ships no search agent of its own | `sub-agents.md`, "Built-in subagents" | "A fast, read-only agent optimized for searching and analyzing codebases." and "Claude delegates to Explore when it needs to search or understand a codebase without making changes." |
| Names `model` `haiku` on that Agent call | `sub-agents.md`, "Built-in subagents" and "Choose a model" | Explore's model is "the parent conversation's model", and the first source in the model order is "The per-invocation `model` parameter, which Claude can pass when it starts the subagent. On an Agent tool call, the parameter takes a model alias, not a full model ID or `inherit`." |
| Sends a review of a code change to the bundled skill `code-review`, run without `--fix` | `code-review-local.md`, "Let Claude start the review" and "What the review reads and edits" | "Claude can start `/code-review` on its own, without you typing the command" and "without `--fix`, the review's instructions ask Claude for a report only." |
| Keeps a reviewer of its own only for a result that is no code change | `code-review-local.md`, "Choose what to review" and "Change or build on the review" | "A target can be a pull request number, a branch name, a file path, or a Git revision range." and "Build your own reviewer: write a reviewer subagent or a review skill" |
| Ships that one agent in `agents/`, named `p4-phi:check` | `plugins/components.md`, "Agents" | "Each Markdown file under `agents/` defines one" and "The name form is `<plugin>:<name>`" |
| Sets `model`, `effort`, `maxTurns`, `tools` and `background` on it, and none of `hooks`, `mcpServers` or `permissionMode` | `plugins/components.md`, "Frontmatter fields in plugin agents" | "Supported fields: `name`, `description`, `model`, `effort`, `maxTurns`, ... `tools`, ... `background`" and "Ignored fields: `permissionMode`, `hooks`, `mcpServers`, and `initialPrompt`" |
| Keeps that agent in the background | `sub-agents.md`, "Supported frontmatter fields" | "Set to `true` to keep this subagent in the background even when Claude asks to wait for it." |
| Runs the readings of an under-determined message as one workflow it ships in `workflows/`, named `p4-phi:readings`, and keeps no explore or merge of its own | `workflows.md`, its opening and "Distribute a workflow in a plugin" | The page names drafting a hard plan from several independent angles as a use of a workflow, and has a script in a `workflows/` folder at the plugin root run as `/<plugin>:<name>`. |
| Has a reading return its question as data, for the session to ask once after the run | `workflows.md`, "Behavior and limits", and `sub-agents.md`, "Available tools" | A run takes no input from a person while it runs, and `AskUserQuestion` is taken from every subagent. |
| Tells a session to start a long command with `run_in_background: true` | `tools-reference.md`, "Background commands" | "Claude can set `run_in_background: true` to start the command as a background task and continue working while it runs." |
| Ships no agent that runs a command, since the session reads the command's output file itself | `interactive-mode.md`, "How backgrounding works" | "Output is written to a file and Claude can retrieve it using the Read tool" |
| Lets a long foreground command run as sent, an orchestrator's too, since the app moves it to the background at its timeout | `tools-reference.md`, "Foreground commands that move to the background" | "When a foreground command reaches its timeout without finishing, Claude Code moves it to the background instead of stopping it" |
| Drafts every start of a worker that writes with `use_worktree: true`, so it works in a git worktree and on a branch of its own, and every start of a session that only reads with `false` | `worktrees.md`, its opening, and `desktop.md`, "Run a session in its own worktree" | "Running each Claude Code session in its own worktree gives it a separate copy of the files to edit, so one session can build a feature while a second fixes a bug." and "Worktrees are stored in `<project-root>/.claude/worktrees/` by default." |
| Drafts a new orchestrator's start with `use_worktree: false`, since it lands its tree's work in the checkout that holds the default branch and syncs the store under it | `worktrees.md`, "How Claude Code enforces isolation" | "Claude Code blocks a Bash, PowerShell, or Monitor command whose working directory resolves to the main checkout" and "Claude Code blocks a Bash or Monitor command that redirects git into the main checkout." |
| Keeps the python its runners proved on Windows in the plugin's data folder | `plugins/manifest-reference.md`, "Environment variables" | "`${CLAUDE_PLUGIN_ROOT}` changes when the plugin updates, so don't write state there." and `${CLAUDE_PLUGIN_DATA}` is "kept across plugin updates" |
| Runs a hooks module, `hooks/register.ts`, inside Claude Code, named in `hooks/hooks.json` beside the command hooks | `plugins/mods/reference.md`, "Files" | "`modules`: an array with one path, relative to this file, to the hooks module" and "Can also hold settings hooks under `hooks`." |
| Reads the proved python in the module from the plugin's data folder, which it finds under the plugins root by the plugin's name | `plugins/loading.md`, "Find plugins on disk" | `data/<plugin-id>/` is "The plugin's persistent directory, exposed as `${CLAUDE_PLUGIN_DATA}`." |
| Runs an orchestrator's watcher from the module's timer, and starts no process that outlives a look | `plugins/mods/api.md`, "Run work in the background" | "`$.clock.every` and `$.clock.after` take the place of `setInterval` and `setTimeout`" and "The timer's callback runs outside any event, so it keeps running between turns and doesn't start one." |
| Runs each look of the watcher, `phi.py look`, as one command that ends | `plugins/mods/api.md`, "Reach files, processes, and the network" | "`run(['git', 'status'])` starts a command and resolves when it exits." |
| Asks for a look at a turn's end and at a message's arrival | `plugins/mods/reference.md`, "Events" | `turn.complete` fires when "A turn ended", and `session.receive` when "A message arrives from, or is about to go to, another agent or session." |
| Keeps a session's context fill and plan limits in `usage.json` in the session's folder, written by the module at the session's start and at each whole point a figure moves | `plugins/mods/reference.md`, "Mods API methods" and "Events" | "`usage()` returns `{ startedAt, context, rateLimits, cost }`: `context` has `tokens`, `window`, and `percent`, and `rateLimits` is a list of `{ kind, percentUsed, resetsAt }`.", and `session.measure` fires "After each turn, and when a plan limit's percent used changes" |

| Sends the report of each turn of a session another session started to that session, from the module, so no worker is asked for a closing line | `plugins/mods/api.md`, "Send and receive messages between sessions", and `cross-session-messaging.md`, "Message delivery" | "To send one, call `$.session.send({ to, text })`, which makes the same delivery the SendMessage tool makes." and "When the receiving session is idle, Claude Code starts a new turn with the message." |
| Starts a turn in a session whose turn ended on a step that waits on other sessions, for the work that wait leaves to move | `plugins/mods/api.md`, "Start a turn from a background job" | "The call waits until the session is idle and then starts a new turn." |

The watcher keeps one look in flight at most and `phi.watch_s` seconds between two looks.
A session that is no orchestrator pays one check, and its timer's wait then doubles to ten minutes at most.
`phi.usage_of` in `scripts/phi.py` reads `usage.json` back for the python scripts, since a command hook's input holds neither figure.

The module asks python once who started the session, with the question of where its folder is, and sends that session the turn's last message at `turn.complete`, cut to 4,000 characters.
Claude Code raises `turn.complete` once a turn, after its last Stop hook answered, so a turn the Stop hook sends back raises no report.
A turn ezexe stopped sends none, and neither does a puppeteer's standing worker or coworker, whose first line asks it for the message its turn ends with.
p4-phi still keeps each report for the starter's next message, and names one that the message already holds without repeating it.
It keeps them because a send is only queued: `plugins/mods/api.md` says the call "resolves once the message is queued", and `cross-session-messaging.md` says the receiving session may hold or refuse it and that a message reaches only a running session.

A turn that ends on a step waiting on other sessions is let end, since a Stop hook can send back only the turn that is ending.
The look that follows answers what does not depend on that wait: a child that reported done with a commit that closes an issue and is on no branch of origin, and an open step that is plain work no live child holds.
The module then submits that list as a prompt, once for a turn, and the session reads it as p4-phi's words and not ezexe's.
Each such turn counts against `phi.keep_going_max` with the Stop hook's own send-backs, until a turn begins that the module did not start.
The Stop hook's send-back to an open step stays, because `$.prompt.submit` starts a turn only after the session went idle, which the starter and the app have by then read as a turn's end.

Without a data folder, as when a test runs a hook, the proved python is kept in the plugin's own folder.

A worker starts with a model and an effort that fit its step, and `phi.child_levels` in `p4.json` sets them for each kind of step.
These are the defaults:

| Kind of step | Model | Effort |
| :- | :- | :- |
| `static`: docs pages, a rename, a version bump and other mechanical work that names no code | `claude-sonnet-5-5` | `medium` |
| `build`: every other step, such as a change to behaviour or anything that names code | the parent session's own | `high` |
| `design`: a design or review step | the parent session's own | `high` |

No start is named above the effort of the session that makes it.
p4-phi reads that session's level from the hook input's `effort.level`, or from `CLAUDE_EFFORT`, keeps the last level seen on the session's record, and holds each start's `effort` to it.
The level is Claude Code's own: `hooks.md`, "Common input fields", calls `effort` an "Object whose `level` is the effort level setting when the hook runs" and says "`$CLAUDE_EFFORT` holds the same level."
The limit is the app's and no docs page states it: a started session's effort is at most its starter's, which `scripts/claude_code_limits.json` logs.

p4-phi has no setting for a subagent's model or effort, since Claude Code sets both.
`sub-agents.md`, "Choose a model", gives the order of the sources: "The per-invocation `model` parameter, which Claude can pass when it starts the subagent", then "The `model` field in the subagent's definition, including `inherit`", then "The `CLAUDE_CODE_SUBAGENT_MODEL` environment variable", then "The main conversation's model, or the spawning subagent's model for a nested subagent".

| Subagent | What sets its model and effort | How a project or ezexe sets another |
| :- | :- | :- |
| `Explore`, Claude Code's own | The `model` `haiku` the delegation rule names on the Agent call, the first source in the order | Another `model` on the call. With no `model` on the call, a file named `Explore` under `.claude/agents/` or `~/.claude/agents/`: "A user or project subagent named `Explore` overrides the built-in and keeps its own `model` field" |
| `p4-phi:check`, the plugin's own | `model: inherit` and `effort: high` in `agents/check.md` | A `model` or an `effort` on the Agent call: "The parameter overrides the `effort` field", and for the effort "The `CLAUDE_CODE_EFFORT_LEVEL` environment variable takes precedence over both." |
| Every subagent | One model under `env` of a settings file: "set `CLAUDE_CODE_SUBAGENT_MODEL` to that model and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` to `1`" | "While `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` is on, Claude Code ignores the `model` field in subagent definitions, and Claude can't pass a model when it starts a subagent." |

### A team in a terminal session

Agent teams run in the terminal `claude` command and not in the desktop app, so a desktop session that wants one starts a terminal session to lead it, from the app's Terminal panel, and talks to that lead by message.
The skill's section "A team in a terminal session" gives the line to type and its conditions: the project's root as the folder, the starting session's own permission mode, and two screens that are ezexe's to answer once.
p4-phi writes `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` into no settings file, since every session of the project reads that file.

## The readings of an unclear message

A message that leaves two or more distinct readings open gets no start draft, since one draft would have to guess between them.
Routing writes the readings, and p4-phi hands the session one line that names the workflow the plugin ships in `workflows/readings.js`, which runs as `/p4-phi:readings`.
The session passes it `args`: `{"words": "<the message, whole>", "readings": ["<a reading>", {"text": "<a reading>", "writes": true}]}`.
Claude Code runs the script: one agent for each of up to four readings, a reading marked `writes` in a git worktree of its own, each with a result schema, and their results compared in the script.
p4-phi starts no session for a reading, keeps no group of readings and merges nothing itself.

| The run returns | What the session does |
| :- | :- |
| `collapsed`, with the `result` the readings came to | Carries the result on as the answer, and puts no question to ezexe |
| `forked`, with one `question`, an option for each reading and a `default` | Puts that one question to ezexe with `AskUserQuestion`, then starts the chosen reading as an ordinary child session, with the call `phi.py draft "<the chosen reading>"` prints |
| `lost` | Runs the readings again if the answer is still wanted, since no agent gave a result |

What the workflow lacks, each by the page that says so:

- A run takes no input from a person, by `workflows.md`, "Behavior and limits", and a subagent has no `AskUserQuestion`, by `sub-agents.md`, "Available tools". A reading that cannot go on without ezexe returns its question in the field `question`, and the session asks once after the run.
- A hook cannot start a run. The session makes the `Workflow` call, and outside bypass permissions the app shows its approval card until ezexe picks Always, by `workflows.md`, "Approve the plan before it runs".
- A reading is an agent and no session, so it has no row in the sidebar or the ledger and no issue. The chosen reading goes on as a session for that reason.
- A worktree a run makes is cut from the default branch on the remote unless `worktree.baseRef` is `head`, by `worktrees.md`, "Choose the base branch". A reading that writes therefore does not see the session's unpushed commits by default.
- A worktree a reading changed stays on disk with its branch until Claude Code's sweep removes it, by `worktrees.md`, "Clean up subagent and background-session worktrees".

Seen in a desktop session on Claude Code 2.1.326, in a scratch project that loaded a copy of p4-phi at 7669deb with the workflow added:

- The session listed `p4-phi:readings` among its skills and ran it by the `Workflow` tool with that `name`, and the `args` reached the script as an object.
- `SubagentStart` and `SubagentStop` fired for each agent of the run, with `agent_type` `workflow-subagent`. p4-phi bound each agent to the session's step in progress and closed it at its stop.
- No `PreToolUse` of the Agent tool comes before such an agent, so p4-phi hands it no lines at its start.
- A reading that wrote ran in `<repository>/.claude/worktrees/wf_<run id>-<n>` on the branch `worktree-wf_<run id>-<n>`, and both stayed after the run.
- The reading reads its branch from git and returns it in the field `branch`, which is how the session finds it: it passes that branch as `source_branch` when it starts the chosen reading.
- The ledger counts no level miss for a file such an agent wrote inside that worktree.

## A puppeteer and the sessions it controls

A puppeteer is the orchestrator ezexe files in the sidebar section "puppeteers", which controls the orchestrators of other trees.

| What the plugin does | How |
| :- | :- |
| Knows a puppeteer | The app's own `claude_desktop_config.json`, beside its `claude-code-sessions` folder, assigns the session to a group named as `phi.puppeteer_section` says, in `preferences.epitaxyPrefs["dframe-group-scopes"]`, each scope with `groups` and `assignments`. A missing or reshaped file makes no session a puppeteer. |
| Knows which sessions it controls | `phi.py controls <sessionId>` writes `controls` on the puppeteer's record, each entry with the store that session's tree lives in. A controlled session's own hook finds the puppeteer and keeps `puppeteer` on its own record. Each side keeps its own record. |
| Tells the controlled session | Once when it comes to have a puppeteer, and once when that ends. |
| Keeps the board | `board.md` in the puppeteer's folder. |
| Lets one session publish a tree's issues | `gh issue create` runs only in the session that publishes for a tree: the issues coworker of the puppeteer's standing worker, whose brief holds the line `Issues coworker of its standing worker`, that worker until one is marked, the puppeteer until it has a worker, and the tree's orchestrator under no puppeteer. In any other session the PreToolUse check refuses the call with one line naming the `Finding:` form and that session by full title. A permission rule cannot do this, since it holds in every session that reads its settings file: `permissions.md`, "Manage permissions", has the dialog list "all permission rules and the `settings.json` file each rule comes from", and "Extend permissions with hooks" names hooks for what is decided "at runtime". |
| Hands a puppeteer the open issues no session holds | The puppeteer's watcher lists the open issues of the repositories its controlled sessions work in at its slow looks, one `gh issue list` a repository, and keeps the ones no live session's record holds as its issue in `open-issues.json` in the puppeteer's folder. When a controlled tree closes or a controlled session reports done, the puppeteer gets one line naming each once, beside the running orchestrator whose topic covers it or as the start of a new orchestrator, to close what a landed commit covers and to route or start the rest. None is put to ezexe as a choice, and no hook reads GitHub for it. |
| Leaves a puppeteer's steps with it | No advice on where its steps go and no nudge, and at Stop a step that waits on sessions' reports ends the turn while a controlled session is not yet complete. |

What p4-phi does not do here is on the skill's last section.

## The files a brief covers

A brief names the files its session covers on a line `Files: <paths>`, and `Files: none` for a session that writes none.
p4-phi keeps the line on the session's record and page and in the address book, where a message about one of those files is routed by it.
The line holds no start and no edit: a session that writes works in a git worktree of its own, so p4-phi keeps no lock on a file.
No start is refused for the files its brief names, held while a live session covers one of them or queued behind a busy writer, no command narrows or releases the line, and a puppeteer's message is warned about for no file.

## No setup

The plugin works in any project it is enabled in.
It needs no key in `p4.json`, no entry in a project's `settings.json` or `settings.local.json`, no environment variable and no existing `.claude/p4` store, and it writes to no settings file.

- The plugin's own SessionStart hook makes the store `.claude/p4/` at the first session of a project and writes `p4.json` with the defaults `p4conf.py` holds, which leave out `child_levels`, `puppeteer_section` and `clear_at`: those three are read when a project sets them. A value it wrote follows a later change of its default, and a value set by hand stays. A value set by hand moves only when it equals the value recorded as written, at the next generation, or, in a store from before the record, a past default.
- Before the store exists, a session is given the built-in rules.
- The plugin ships no `settings.json`, a file no plugin page of the docs describes.

### `p4.json`, section `phi`

Every key is optional.

| Key | Default | What `false` or a value does |
| :- | :- | :- |
| `levels` | `true` | `false`: no delegation rule |
| `child_levels` | the table under Delegation | an object: a kind, `static`, `build` or `design`, with its `model`, an id or `inherit`, and its `effort` |
| `act_dont_wait` | `true` | `false`: the built-in act-don't-wait rule is left out |
| `top_orchestrates` | `true` | `false`: an orchestrator does its own task list's work |
| `issues` | `true` | `false`: no issue loop: a worker takes no open issue its brief names, gets no line on a commit that closes no issue, runs no regression test at Stop and is given no push line |
| `puppeteer_section` | `puppeteers` | another name for the sidebar section; an empty string makes no session a puppeteer |
| `clear_at` | 60 | the percent of its context, above 0 and at most 100, past which a session that keeps a state page clears itself at a turn's end; the session reads the share with the app's `get_usage` tool |
| `track` | `false` | `true`: the session tree is committed to the store |
| `home` | none | a git remote: related repositories share one session tree |
| `max_depth` | 3 | the depth, 1 to 20, at which a session starts no session of its own |
| `max_children` | 8 | the live children, 1 to 50, past which a session starts none |
| `sibling_turns` | 5 | the siblings' last turns, 0 to 50, a start background holds |
| `own_turns` | 3 | a session's own turns, 0 to 50, its background holds after a clear |
| `chain_max` | 8 | the sessions, 1 to 50, followed upward from a session |
| `turn_steps` | 12 | the steps and workers, 1 to 100, kept with a turn |
| `tree_checks` | 6 | the read-only checks of its trees, 0 to 100, an orchestrator runs in one work step |
| `keep_going_max` | 2 | the times, 0 to 7, one turn is sent back while it has open steps, counted together with the turns in a row the hooks module starts for work a wait left unmoved |
| `watch_s` | 5.0 | the watcher's tick in seconds, 1 to 600 |
| `stale_s` | 86400.0 | the seconds, 60 to 2,592,000, after which an orchestrator with open work and no turn is stale |

A cap's value of another type or out of its range keeps the default.

The `recall` section's keys and defaults are listed in `scripts/p4conf.py`, each beside its meaning.

### `phi/phi.json`

Every key is optional, and the file need not exist.

| Key | Default |
| :- | :- |
| `background`, `reports`, `turns`, `book`, `rules`, `puppeteer` | `true` |
| `background_chars` | 3000 |
| `reports_chars` | 6000 |
| `wait_s` | 2.0 |

`puppeteer` set to `false` gives an orchestrator no watcher and no start draft on ezexe's message.

### Environment variables

None has to be set.
Each is for one run, a test or one machine's unusual layout.

| Variable | Unset means | Set |
| :- | :- | :- |
| `P4_PHI` | phi.py's hooks run | `0` turns off phi.py's three hook commands, the checks hook.py hands it, the watcher, the usage record, the report sent to a starter and the turn started for a wait, while retrieval goes on |
| `P4_PHI_RULES`, `P4_PHI_BOOK` | as `phi.json` says | `0` or `1` for one run |
| `P4_PHI_PUPPETEER` | as `puppeteer` in `phi.json` says | `0` or `1` for one run |
| `P4_PHI_WATCH` | an orchestrator's watcher runs | `0` keeps it from starting, and with it the turn the module starts for a wait, while a worker's report still goes to its starter |
| `P4_PHI_WATCH_S`, `P4_PHI_WATCH_NET` | a look every 5 seconds, or every 30 once nothing has changed for 10 minutes, with GitHub read | a tick in seconds, `0` for no network |
| `P4_PHI_ISSUES` | as `phi.issues` says | `0` turns the issue loop off for one run, as `phi.issues` false does |
| `P4_PHI_GH` | the `gh` on PATH, and no issue loop without one | another `gh` |
| `P4_PHI_PROOF_S` | a regression test has 15 seconds inside the Stop hook, then finishes behind it | another limit |
| `P4_PHI_WAIT` | 2 seconds for the app's record of a new session | another wait |
| `P4_PHI_APP_SESSIONS` | the app's own session folder for this system | another folder |
| `P4_PHI_STORES` | `p4-stores.json` in Claude Code's configuration directory | another file |
| `P4_PHI_PLUGIN_ROOT` | `CLAUDE_PLUGIN_ROOT` | another plugin root |
| `P4_PHI_CATCHUP` | the catch-up notice runs | `0` turns it off |
| `P4_RECALL_INJECT` | as `recall.inject` says | `0`, `1` or `rules-facts` |
| `P4_RECALL_SYNC` | a clean call's record is written behind the call | `1` waits for it |
| `P4_AGENT_ALLOW` | no permission decision on a subagent's rewritten prompt | `1` adds `allow` |

## Developing p4-phi while it is installed

A session that edits p4-phi runs with Claude Code's own features, and p4-phi builds nothing in their place.
The page `dox/plugin-development.html` in ezexe/p4 says how: a clone loaded with `claude --plugin-dir <clone>/lbiza/plugins/p4-phi --debug`, edits picked up by `/reload-plugins`, the installed copies off for the development project in a `.claude/settings.local.json` ezexe writes, each copy's `CLAUDE_PLUGIN_DATA` folder checked on disk, and the installed copy moved by Claude Code's own auto-update after a landing bumps a version, with `claude plugin update` as the move by hand.
What the plugin makes a model do is checked by the cases in `evals/`, run by hand from this folder with `claude plugin eval . --scaffold --trust-plugin --model claude-sonnet-5-5 --judge-model claude-haiku-5-5 --no-publish --max-cost-usd 5`, which gates no landing.

## What depends on the machine

- `python` 3, `sh` and `git` must be on PATH. On Windows, `sh` comes with Git.
- The issue loop needs `gh`, signed in, and a repository whose `origin` is on GitHub. Without them it does nothing.
- The session tree is read from the Claude desktop app's records. In a plain terminal session every session is an orchestrator.
- The readings workflow needs dynamic workflows on. They are on for every paid plan, on Pro from the Dynamic workflows row in `/config`, and `disableWorkflows` or `CLAUDE_CODE_DISABLE_WORKFLOWS` turns them off. Source: https://code.claude.com/docs/en/workflows.md.
- The hooks module needs Claude Code v2.1.287 or later, and it does not load in a session started with `--safe-mode` or `--bare`, or where `disableAllHooks` is set. Source: https://code.claude.com/docs/en/plugins/mods/create.md. Where it does not load no watcher runs, and a ledger is rewritten at ezexe's message to its orchestrator and by `phi.py ledger`. No report is sent to a starter there and no turn is started for a wait, so a starter reads its workers' reports beside its next message.
