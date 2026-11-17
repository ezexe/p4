# p4-phi

What linked Claude Code sessions hand each other, and retrieval from the project's own history, in one plugin.
The skill `skills/phi/SKILL.md` lists the commands a session runs and what p4-phi does not do.
This page holds how to install p4-phi, the docs sentences its delegation rests on, the model and effort a worker starts with, what p4-phi does for a puppeteer, and the settings, none of which has to be set.

## Install

The marketplace `p4-marketplace` is the folder `lbiza/` of a checkout of ezexe/p4, so add it by that folder's path, then install each plugin by name from your shell:

```bash
claude plugin marketplace add ./p4/lbiza
claude plugin install p4-phi@p4-marketplace
claude plugin install p4-temportal@p4-marketplace
```

`./p4` is the checkout, and each install is at user scope unless `--scope project` or `--scope local` says otherwise.
Claude Code updates installed plugins only from a marketplace whose auto-update is on, and it is off by default for a marketplace like this one: ezexe turns it on in a session with `/plugin`, the **Marketplaces** tab, `p4-marketplace`, **Enable auto-update**, or updates by hand with `claude plugin update <plugin>@p4-marketplace`.
Source: https://code.claude.com/docs/en/plugins/install.md, Keep plugins updated.

## Delegation

Every behaviour below rests on a sentence of the Claude Code docs at `https://code.claude.com/docs/en/<page>`.

| What the plugin does | The page | The sentence it rests on |
| :- | :- | :- |
| Ships three agents in `agents/`, named `p4-phi:sweep`, `p4-phi:runner` and `p4-phi:check` | `plugins/components.md`, "Agents" | "Each Markdown file under `agents/` defines one" and "The name form is `<plugin>:<name>`" |
| Sets `model`, `effort`, `maxTurns`, `tools` and `background` on each, and none of `hooks`, `mcpServers` or `permissionMode` | `plugins/components.md`, "Frontmatter fields in plugin agents" | "Supported fields: `name`, `description`, `model`, `effort`, `maxTurns`, ... `tools`, ... `background`" and "Ignored fields: `permissionMode`, `hooks`, `mcpServers`, and `initialPrompt`" |
| Keeps each agent in the background | `sub-agents.md`, "Supported frontmatter fields" | "Set to `true` to keep this subagent in the background even when Claude asks to wait for it." |
| Tells a session to go on or end its turn, and never to wait, sleep or poll | `sub-agents.md` | "Background subagents run concurrently while you continue working." and "A background subagent's report arrives inside a completion notification" |
| Tells a session to start a long command with `run_in_background: true` | `tools-reference.md`, "Background commands" | "Claude can set `run_in_background: true` to start the command as a background task and continue working while it runs." |
| Lets a long foreground command run as sent, an orchestrator's too, since the app moves it to the background at its timeout | `tools-reference.md`, "Foreground commands that move to the background" | "When a foreground command reaches its timeout without finishing, Claude Code moves it to the background instead of stopping it" |
| Says so in one line beside the result | `hooks.md`, "PreToolUse decision control" | "`additionalContext`: String added to Claude's context alongside the tool result." |
| Keeps the python its runners proved on Windows, and in a project with no store its once-per-step memory, in the plugin's data folder | `plugins/manifest-reference.md`, "Environment variables" | "`${CLAUDE_PLUGIN_ROOT}` changes when the plugin updates, so don't write state there." and `${CLAUDE_PLUGIN_DATA}` is "kept across plugin updates" |

Without a data folder, as when a test runs a hook, the proved python is kept in the plugin's own folder and the step memory in the system temp folder.

A worker starts with a model and an effort that fit its step, and `phi.child_levels` in `p4.json` sets them for each kind of step.
These are the defaults:

| Kind of step | Model | Effort |
| :- | :- | :- |
| `static`: docs pages, a rename, a version bump and other mechanical work that names no code | `claude-sonnet-5-5` | `medium` |
| `build`: every other step, such as a change to behaviour or anything that names code | the parent session's own | `high` |
| `design`: a design or review step | the parent session's own | `high` |

## A puppeteer and the sessions it controls

A puppeteer is the orchestrator ezexe files in the sidebar section "puppeteers", which controls the orchestrators of other trees.

| What the plugin does | How |
| :- | :- |
| Knows a puppeteer | The app's own `claude_desktop_config.json`, beside its `claude-code-sessions` folder, assigns the session to a group named as `phi.puppeteer_section` says, in `preferences.epitaxyPrefs["dframe-group-scopes"]`, each scope with `groups` and `assignments`. A missing or reshaped file makes no session a puppeteer. |
| Knows which sessions it controls | `phi.py controls <sessionId>` writes `controls` on the puppeteer's record, each entry with the store that session's tree lives in. A controlled session's own hook finds the puppeteer and keeps `puppeteer` on its own record. Each side keeps its own record, and a puppeteer that starts a controlled session's start request writes a `claimed` row into that session's store. |
| Tells the controlled session | Once when it comes to have a puppeteer, and once when that ends. |
| Keeps the board | `board.md` in the puppeteer's folder. |
| Leaves a puppeteer's steps with it | No advice on where its steps go and no nudge, and at Stop a step that waits on sessions' reports ends the turn while a controlled session is not yet complete. |
| Warns of an early go | A puppeteer's message to a session it controls gets one line while another controlled session, or one in its tree, still holds a file in that session's write set. The line names the holder by its full title and the command that frees the files. |

What p4-phi does not do here is on the skill's last section.

## Write sets

A brief declares the files its session writes on a line `Files: <paths>`, and the refusal a start without one meets says why.
A session narrows its write set with `phi.py files <path> ...` and empties it with `phi.py files --release`, and a start held on the released paths goes ahead at once.

## No setup

The plugin works in any project it is enabled in.
It needs no key in `p4.json`, no entry in a project's `settings.json` or `settings.local.json`, no environment variable and no existing `.claude/p4` store, and it writes to no settings file.

- The plugin's own SessionStart hook makes the store `.claude/p4/` at the first session of a project and writes `p4.json` with the defaults `p4conf.py` holds, which leave out `child_levels`, `puppeteer_section` and `puppeteer_chars`: those three are read when a project sets them. A value it wrote follows a later change of its default, and a value set by hand stays. A value set by hand moves only when it equals the value recorded as written, at the next generation, or, in a store from before the record, a past default.
- Before the store exists, a session is given the built-in rules, and a session's long foreground command gets the line.
- The plugin ships no `settings.json`, a file no plugin page of the docs describes.

### `p4.json`, section `phi`

Every key is optional.

| Key | Default | What `false` or a value does |
| :- | :- | :- |
| `levels` | `true` | `false`: no delegation rule and no line beside a long foreground command |
| `child_levels` | the table under Delegation | an object: a kind, `static`, `build` or `design`, with its `model`, an id or `inherit`, and its `effort` |
| `act_dont_wait` | `true` | `false`: the built-in act-don't-wait rule is left out |
| `top_orchestrates` | `true` | `false`: an orchestrator does its own task list's work |
| `file_sets` | `true` | `false`: a session may be started by a brief that declares no write set |
| `issues` | `true` | `false`: no issue loop: a worker takes no open issue its brief names, gets no line on a commit that closes no issue, runs no regression test at Stop and is given no push line |
| `puppeteer_section` | `puppeteers` | another name for the sidebar section; an empty string makes no session a puppeteer |
| `puppeteer_chars` | 200000 | the characters p4-phi may hand a puppeteer between compactions before its boundary notice says so |
| `track` | `false` | `true`: the session tree is committed to the store |
| `home` | none | a git remote: related repositories share one session tree |
| `max_depth` | 3 | the depth, 1 to 20, at which a session starts no session of its own |
| `max_children` | 8 | the live children, 1 to 50, past which a session starts none |
| `sibling_turns` | 5 | the siblings' last turns, 0 to 50, a start background holds |
| `own_turns` | 3 | a session's own turns, 0 to 50, its background holds after a compaction or a clear |
| `chain_max` | 8 | the sessions, 1 to 50, followed upward from a session |
| `turn_steps` | 12 | the steps and workers, 1 to 100, kept with a turn |
| `tree_checks` | 6 | the read-only checks of its trees, 0 to 100, an orchestrator runs in one work step |
| `keep_going_max` | 2 | the times, 0 to 7, one turn is sent back while it has open steps |
| `compactions` | 3 | the compactions, 1 to 100, after which a puppeteer's notice offers a successor |
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
| `prompt_chars` | 4000 |
| `wait_s` | 2.0 |

`puppeteer` set to `false` gives an orchestrator no watcher and no start draft on ezexe's message.

### Environment variables

None has to be set.
Each is for one run, a test or one machine's unusual layout.

| Variable | Unset means | Set |
| :- | :- | :- |
| `P4_PHI` | phi.py's hooks run | `0` turns off phi.py's three hook commands and the checks hook.py hands it, while retrieval goes on |
| `P4_PHI_RULES`, `P4_PHI_BOOK` | as `phi.json` says | `0` or `1` for one run |
| `P4_PHI_PUPPETEER` | as `puppeteer` in `phi.json` says | `0` or `1` for one run |
| `P4_PHI_WATCH` | an orchestrator's watcher runs | `0` keeps it from starting |
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
The page `dox/plugin-development.html` in ezexe/p4 says how: a clone loaded with `claude --plugin-dir <clone>/lbiza/plugins/p4-phi --debug`, edits picked up by `/reload-plugins`, the installed copies off for the development project in a `.claude/settings.local.json` ezexe writes, each copy's `CLAUDE_PLUGIN_DATA` folder checked on disk, live checks run on a clone in a scratch project, and `claude plugin update` run only when a release is cut.

## What depends on the machine

- `python` 3, `sh` and `git` must be on PATH. On Windows, `sh` comes with Git.
- The issue loop needs `gh`, signed in, and a repository whose `origin` is on GitHub. Without them it does nothing.
- The session tree is read from the Claude desktop app's records. In a plain terminal session every session is an orchestrator.
