# p4-phi

What linked Claude Code sessions hand each other, and recall from the repository's own history, in one plugin.
The skill `skills/phi/SKILL.md` says what a session does with it.
This page covers two things: the levels work runs at, and the fact that nothing has to be set up.

## Levels

Work runs at the level Claude Code gives it, so a session's own turn is never held by it, and a top session never seizes.
Every behaviour below rests on a sentence of the Claude Code docs, read on 2026-11-16 at `https://code.claude.com/docs/en/<page>`.

| What the plugin does | The page | The sentence it rests on |
| :- | :- | :- |
| Ships three agents in `agents/`, named `p4-phi:sweep`, `p4-phi:runner` and `p4-phi:check` | `plugins/components.md`, "Agents" | "Each Markdown file under `agents/` defines one" and "The name form is `<plugin>:<name>`" |
| Sets `model`, `effort`, `maxTurns`, `tools` and `background` on each, and none of `hooks`, `mcpServers` or `permissionMode` | `plugins/components.md`, "Frontmatter fields in plugin agents" | "Supported fields: `name`, `description`, `model`, `effort`, `maxTurns`, ... `tools`, ... `background`" and "Ignored fields: `permissionMode`, `hooks`, `mcpServers`, and `initialPrompt`" |
| Keeps each agent in the background | `sub-agents.md`, "Supported frontmatter fields" | "Set to `true` to keep this subagent in the background even when Claude asks to wait for it." |
| Tells a session to go on or end its turn, and never to wait, sleep or poll | `sub-agents.md` | "Background subagents run concurrently while you continue working." and "A background subagent's report arrives inside a completion notification" |
| Tells a session to start a long command with `run_in_background: true` | `tools-reference.md`, "Background commands" | "Claude can set `run_in_background: true` to start the command as a background task and continue working while it runs." |
| In a top session, returns a long foreground command with `updatedInput`: the same input plus `run_in_background: true` | `hooks.md`, "PreToolUse decision control" | "Modifies the tool's input parameters before execution. Replaces the entire input object, so include unchanged fields alongside modified ones." |
| Says so in one line beside the result | `hooks.md`, "PreToolUse decision control" | "`additionalContext`: String added to Claude's context alongside the tool result." |
| Keeps its once-per-step memory, and the interpreter it proved, in the plugin's data folder when a project has no store | `plugins-reference.md`, "Environment variables" | "`${CLAUDE_PLUGIN_ROOT}` changes when the plugin updates, so don't write state there." and `${CLAUDE_PLUGIN_DATA}` is "kept across plugin updates" |

Two things the pages do not say in words were measured on 2026-11-16 with CLI 2.1.322.
A plugin hook's `updatedInput` that adds `run_in_background: true` reached the Bash tool: the command ran as a background task and its result read "Command running in background with ID".
The agent `p4-phi:sweep` loaded under that name, ran on Haiku, and stayed in the background though the call asked for the foreground.

A long command is a `test_*.py` run, `pytest`, `unittest`, or an `npm`, `pnpm`, `cargo`, `go` or `make` `test` or `build`.
It counts only where it is the program being run: a test file named to another program, or a call that only asks for `--version`, `--help` or `--collect-only`, is not one.
A top session's call is moved only when it is that command and nothing else: parts before it may go to a folder or set a variable, and its output may pass through filters such as `tail` or `grep`.
A call with a later part, such as `python test_x.py && git commit`, runs as sent, since the later part needs the command finished.
So does a call that carries a `timeout` of its own, since the caller chose to wait.
Those calls get the line once per step, and nothing about how they run is changed.
In a session another one started, the call runs as sent and the line is given once per step.
A subagent's own call is left alone, since a runner's whole work is to wait on its command.
A plan step that only reads or searches is named for `p4-phi:sweep`, one that only runs a command for `p4-phi:runner`, and the rest for a child session.

To turn the levels off in one project, set `phi.levels` to `false` in `.claude/p4/p4.json`.

## No setup

The plugin works in any project it is enabled in.
It needs no key in `p4.json`, no entry in a project's `settings.json` or `settings.local.json`, no environment variable and no existing `.claude/p4` store, and it writes to no settings file.

- The store `.claude/p4/` is made by the plugin's own SessionStart hook at the first session of a project, with `p4.json` written at the defaults below.
- Before the store exists, a session is still given the built-in rules, and a top session's long command is still moved to the background.
- A plugin's own `settings.json` is not used: the plugin pages read name none.
- `scripts/test_hooks.py` `ZeroConfiguration` runs the session-start, message, PreToolUse and stop handlers in an empty folder and proves this.

### `p4.json`, section `phi`

Every key is optional.

| Key | Default | What `false` or a value does |
| :- | :- | :- |
| `levels` | `true` | `false`: no levels rule and no long command moved to the background |
| `act_dont_wait` | `true` | `false`: the built-in act-don't-wait rule is left out |
| `top_orchestrates` | `true` | `false`: a top session does its plan's work itself |
| `file_sets` | `true` | `false`: a session may be started by a brief that declares no file set |
| `issues` | `true` | `false`: no GitHub issue is filed for a writing child's purpose |
| `session_archives` | `false` | `true`: sessions may archive sessions |
| `track` | `false` | `true`: the session tree is committed in the store's own repository |
| `home` | none | a git remote: related repositories share one session tree |

The `recall` section's keys and defaults are listed in `scripts/p4conf.py`, each beside its meaning.

### `phi/phi.json`

Every key is optional, and the file need not exist.

| Key | Default |
| :- | :- |
| `background`, `reports`, `turns`, `new_task`, `rules`, `puppeteer` | `true` |
| `background_chars` | 3000 |
| `reports_chars` | 6000 |
| `prompt_chars` | 4000 |
| `wait_s` | 2.0 |

### Environment variables

None has to be set.
Each is for one run, a test or one machine's unusual layout.

| Variable | Unset means | Set |
| :- | :- | :- |
| `P4_PHI` | the plugin runs | `0` turns it off |
| `P4_PHI_RULES`, `P4_PHI_NEW_TASK` | as `phi.json` says | `0` or `1` for one run |
| `P4_PHI_PUPPETEER`, `P4_PHI_WATCH` | the puppeteer and its watcher run | `0` turns one off |
| `P4_PHI_WATCH_S`, `P4_PHI_WATCH_NET` | a look every 5 seconds, GitHub read | a tick in seconds, `0` for no network |
| `P4_PHI_ISSUES` | as `phi.issues` says | `0` files no issue |
| `P4_PHI_GH` | the `gh` on PATH, and no issue loop without one | another `gh` |
| `P4_PHI_PROOF_S` | a proving test has 15 seconds inside the Stop hook, then finishes behind it | another limit |
| `P4_PHI_WAIT` | 2 seconds for the app's record of a new session | another wait |
| `P4_PHI_APP_SESSIONS` | the app's own session folder for this system | another folder |
| `P4_PHI_STORES` | `p4-stores.json` beside Claude Code's settings | another file |
| `P4_PHI_PLUGIN_ROOT` | `CLAUDE_PLUGIN_ROOT` | another plugin root |
| `P4_PHI_CATCHUP` | the catch-up notice runs | `0` turns it off |
| `P4_RECALL_INJECT` | as `recall.inject` says | `0`, `1` or `rules-facts` |
| `P4_RECALL_SYNC` | a clean call's record is written behind the call | `1` waits for it |
| `P4_AGENT_ALLOW` | no permission decision on a subagent's rewritten prompt | `1` adds `allow` |

## What still depends on the machine

- `python` 3 and `sh` must be on PATH. On Windows, `sh` comes with Git.
- The issue loop needs `gh`, signed in, and a repository whose `origin` is on GitHub. Without them it does nothing.
- The session tree is read from the Claude desktop app's records. In a plain terminal session every session is a top session.
