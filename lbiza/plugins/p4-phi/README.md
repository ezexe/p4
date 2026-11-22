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
claude plugin install p4-native@p4-marketplace
```

Each install is a copy in Claude Code's plugin cache, `~/.claude/plugins/cache/p4-marketplace/<plugin>/<version>/`, at user scope unless `--scope project` or `--scope local` says otherwise.
Claude Code updates installed plugins only from a marketplace whose auto-update is on, and it is off by default for a marketplace like this one: turn it on in a session with `/plugin`, the **Marketplaces** tab, `p4-marketplace`, **Enable auto-update**, or update by hand with `claude plugin update <plugin>@p4-marketplace`.
With auto-update on, a new version reaches the installed copy at the pass Claude Code runs after a session's first message, and a session that is running keeps the version it loaded until `/reload-plugins` or its next start.
Source: https://code.claude.com/docs/en/plugins/install.md, Keep plugins updated, and https://code.claude.com/docs/en/plugins/loading.md, When auto-update runs.

## Delegation

Every behaviour below rests on a sentence of the Claude Code docs at `https://code.claude.com/docs/en/<page>`.

| What the plugin does | The page | The sentence it rests on |
| :- | :- | :- |
| Decides whether to delegate, how many agents, and each one's type, model and effort by the skill `sub-agentic` it ships, whose table of roles each agent and each drafted start follows | `plugins/components.md`, "Skills", and `sub-agents.md`, "Choose a model" | A plugin's skill is "One `<name>/SKILL.md` per skill", and the model order puts "The `model` field in the subagent's definition" after the call's own `model` |
| Sends a search or a read across files to its own read-only subagent `p4-phi:finder`, the skill's evidence finder, with `model: haiku` and `effort: low` in its file | `sub-agents.md`, "Built-in subagents" and "Choose a model" | The built-in Explore's model is "the parent conversation's model", so it runs small only while each call names a model; a definition's `model` field holds with nothing on the call |
| Ships `p4-phi:writer` on `opus` at `medium` and `p4-phi:integrator` on `sonnet` at `medium`, the skill's writer and integrator | `plugins/components.md`, "Agents" | "Each Markdown file under `agents/` defines one" and "The name form is `<plugin>:<name>`" |
| Sends a review of a code change to the bundled skill `code-review`, run without `--fix` | `code-review-local.md`, "Let Claude start the review" and "What the review reads and edits" | "Claude can start `/code-review` on its own, without you typing the command" and "without `--fix`, the review's instructions ask Claude for a report only." |
| Keeps a reviewer of its own only for a result that is no code change | `code-review-local.md`, "Choose what to review" and "Change or build on the review" | "A target can be a pull request number, a branch name, a file path, or a Git revision range." and "Build your own reviewer: write a reviewer subagent or a review skill" |
| Ships its reviewer in `agents/`, named `p4-phi:check`, the skill's cross-check for a result that is no code change | `plugins/components.md`, "Agents" | "Each Markdown file under `agents/` defines one" and "The name form is `<plugin>:<name>`" |
| Sets `model` and `effort` on each of its agents, and `maxTurns`, `tools` and `background` where the agent needs them, and none of `hooks`, `mcpServers` or `permissionMode` | `plugins/components.md`, "Frontmatter fields in plugin agents" | "Supported fields: `name`, `description`, `model`, `effort`, `maxTurns`, ... `tools`, ... `background`" and "Ignored fields: `permissionMode`, `hooks`, `mcpServers`, and `initialPrompt`" |
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
| Reads the proved python in the module from the plugin's data folder, which the engine names as `CLAUDE_PLUGIN_DATA` of `$.process.hookEnv`, and which it finds under the plugins root by the plugin's name where the engine gives none | `plugins/loading.md`, "Find plugins on disk" | `data/<plugin-id>/` is "The plugin's persistent directory, exposed as `${CLAUDE_PLUGIN_DATA}`." |
| Hands each python child of the module the variables a command hook of the session gets, so a script the module runs and a command hook read one store | the types of `claude-code`, `$.process.hookEnv` | "Returns the variables that name the session and this plugin, as its command hook gets them, to pass as a child's `env`" |
| Hands the SessionStart command hooks the settings Claude Code loaded, each source's by itself, so the settings keeper takes the managed settings with every managed tier merged | the types of `claude-code`, `$.settings.read` | "Resolves with the settings merged over every source, with one source's settings as loaded (`{ source }`), or with the value of one top-level key" |
| Runs an orchestrator's watcher from the module's timer, and starts no process that outlives a look | `plugins/mods/api.md`, "Run work in the background" | "`$.clock.every` and `$.clock.after` take the place of `setInterval` and `setTimeout`" and "The timer's callback runs outside any event, so it keeps running between turns and doesn't start one." |
| Runs each look of the watcher, `phi.py look`, as one command that ends | `plugins/mods/api.md`, "Reach files, processes, and the network" | "`run(['git', 'status'])` starts a command and resolves when it exits." |
| Asks for a look at a turn's end and at a message's arrival | `plugins/mods/reference.md`, "Events" | `turn.complete` fires when "A turn ended", and `session.receive` when "A message arrives from, or is about to go to, another agent or session." |
| Keeps a session's context fill and plan limits in `usage.json` in the session's folder, written by the module at the session's start and at each whole point a figure moves | `plugins/mods/reference.md`, "Mods API methods" and "Events" | "`usage()` returns `{ startedAt, context, rateLimits, cost }`: `context` has `tokens`, `window`, and `percent`, and `rateLimits` is a list of `{ kind, percentUsed, resetsAt }`.", and `session.measure` fires "After each turn, and when a plan limit's percent used changes" |
| Keeps the origin Claude Code stamps on each prompt in `origin.json`, written by the module before that prompt's UserPromptSubmit command hooks run, which are given the prompt's text and no origin | the types of `claude-code`, `PromptOrigin`, which `prompt.submit` carries as `e.origin` | "A hooks module reads `e.origin.kind` to tell the user's own Enter from a notification, a peer session, a schedule or another plugin", and the kinds are "a closed set, never a text prefix" |
| Asks the desktop app's own tools for sessions, `mcp__ccd_session_mgmt__get_session` for the session and `mcp__ccd_session_mgmt__list_sessions` for the sessions linked to it, unless the store's `phi.json` turns `app_tools` off, and keeps what they answer in `app.json`, which `phi.py` reads ahead of the app's record files | the types of `claude-code`, `$.tool.call` | "Calls a tool: the event `tool.call`, the same call the engine makes for the model's tool calls, under a `tool_use_id` of its own." and "The check opens no dialog and asks no classifier: every ask becomes an allow" |

| Sets the rules built into p4-phi as a section of the system prompt, `p4-phi:rules`, last on the session's side, with the text `phi.py rules` prints for the session, so no hook hands them at a start, a clear or a compaction | `plugins/mods/reference.md`, "Prompts and what Claude reads" | `prompt.compose` fires when "Claude Code renders a system prompt", and a hook answers "`{ sections }`, a list of `{ id, text, scope }` in the order they're sent" |
| Hands a session ezexe is at Claude Code's own plan mode for a change whose approach is open, by the built-in rule `plan-mode`, and builds no plan of its own: the session calls `EnterPlanMode`, the mode `/plan` enters, and puts the plan to ezexe with `ExitPlanMode` | `tools-reference.md`, the tools table, and `commands.md` | `EnterPlanMode` "Switches to plan mode to design an approach before coding", `ExitPlanMode` "Presents a plan for approval and exits plan mode", and `/plan` is "Enter plan mode directly from the prompt." |
| Keeps a session another session started out of plan mode, where no person answers a plan's approval: it plans with the built-in `Plan` subagent and takes its starter's message as the approval | `sub-agents.md`, "Built-in subagents", and `docs/plugin-development.html`, "Plan mode for a worker" | Plan is "A research agent used during plan mode to gather context before presenting a plan", with read-only tools, and the page has the approval card seen in the desktop app, which ezexe alone answered. |
| Binds a subagent to the Agent call that launched it, in a file hook.py reads at the subagent's `SubagentStart`, so a start gets its own launch's lines whatever the order of launches | `plugins/mods/reference.md`, "Events", and the types of Claude Code 2.1.326 | `agent.spawn` fires when "A subagent or an agent team teammate is about to start", carries "The Agent tool call this spawn belongs to" and answers "The started subagent's id: the same string its loop's `tool.call` events carry as `agentId`" |
| Sends the report of each turn of a session another session started to that session, from the module, so no worker is asked for a closing line | `plugins/mods/api.md`, "Send and receive messages between sessions", and `cross-session-messaging.md`, "Message delivery" | "To send one, call `$.session.send({ to, text })`, which makes the same delivery the SendMessage tool makes." and "When the receiving session is idle, Claude Code starts a new turn with the message." |
| Starts a turn in a session whose turn ended on a step that waits on other sessions, for the work that wait leaves to move | `plugins/mods/api.md`, "Start a turn from a background job" | "The call waits until the session is idle and then starts a new turn." |
| Checks a tool call before it runs from the module, at `tool.check`, and starts python only for a call python has a check for, so no `PreToolUse` entry runs for every tool and no hook stands on `tool.call` | the types of `claude-code`, `tool.check` and the remarks of `tool.run` | `tool.check` is raised when the engine decides whether a tool call may run, after the PreToolUse hooks, and "As at `tool.call`, a hook that may match a tool, even one that only passes `next(e)` on, turns off for that tool what would carry its output past the hook: the move to the background, a served call's live output, Code Mode's wait for a stopped result." |
| Gives a session `phi.py note`, `phi.py done`, `phi.py tree` and `phi.py goal ask` as the tools `mcp__p4-phi__note`, `mcp__p4-phi__done`, `mcp__p4-phi__tree` and `mcp__p4-phi__goal`, which the module declares at a session's start and runs itself once a call is allowed, at `tool.run` or at `tool.call` as "The module on each Claude Code" says, so a session keeps a finding with no shell line | the types of `claude-code`, `$.tool.register` | "Declares a tool the model can call from the next prompt on: the name, description and input schema of `mcp__<plugin>__<name>`" |
| Shows a puppeteer's board, the ledger of ezexe's requests and an orchestrator's ledger of its sessions in a pane beside the chat, which the command `/phi-pane` opens and no session start does. The module reads `board.md`, `asks.md` and `ledger.md` from the session's folder into `$.state` when the command runs and after each look while the pane is open, and the pane draws them from there, each page whole as markdown, or one line a page as the desktop app's widget. The values are declared in `types/index.d.ts`, which `plugin.json` names as `types` | the types of `claude-code`, `$.ui.open`, `RenderViewport` and the `Pane` props | "one the plugin makes on its own waits undrawn below 144 terminal columns", and of the fact that says whether a surface docks a pane, which only a drawing and a command's run carry: "so a pane a plugin opens unasked is a sidebar, not a takeover; absent is unknown" |

The watcher keeps one look in flight at most and `phi.watch_s` seconds between two looks.
A session that is no orchestrator pays one check, and its timer's wait then doubles to ten minutes at most.
`phi.usage_of` in `scripts/phi.py` reads `usage.json` back for the python scripts, since a command hook's input holds neither figure.
The section of the system prompt is left out where `P4_PHI=0`, `P4_PHI_RULES=0`, `rules: false` in `phi.json`, or `phi.act_dont_wait`, `phi.plan_mode` and `phi.levels` all false in `p4.json` turn the rules off, and a rule one of those three keys turns off is left out of it.
The rule `plan-mode` has a switch of its own, `phi.plan_mode`, so a project whose sessions enter plan mode only when asked leaves it out and keeps the act-don't-wait rule, and it reads in one of two ways, by whether another session started the session, which the app's record of it says.
In a session ezexe is at it names which change is one whose approach is open in the words of the `EnterPlanMode` tool's own text, one that could be made in more than one way, that decides a structure, or that reaches past two or three files, and it names the plans folder from `p4conf.PLANS`, relative to the store, where the settings keeper points `plansDirectory`.
How a plan is shaped and where it moves once it is done is p4-temportal's skill `plan-planner`, which the rule names.
What would settle `ExitPlanMode` with no person in a started session is not built: seen in the desktop app on Claude Code 2.1.326, an allow at `classic.PermissionRequest` with the input handed back as `updatedInput` settled it, and an allow at `tool.check` or at `classic.PreToolUse` did not, but a hook that answers that card would be a part of the set of what p4-phi settles with no approval card, which is ezexe's to say yes to.
A subagent holds no such section: Claude Code raises `prompt.compose` for the main conversation's system prompt, and a live check on Claude Code 2.1.326 raised none for a subagent started in the same session.
A setting changed during a conversation reaches its system prompt at the next compaction or clear, since by `plugins/mods/reference.md` Claude "keeps reading the text saved with the conversation" until then.
A puppeteer's line at its standing worker's report and the upkeep's check of a short context read each session's share there, so no session is asked for its usage, and only a session with no measure kept is named for a `get_usage` read.

The module holds a prompt's origin while its `prompt.submit` is in flight and writes it at `classic.UserPromptSubmit`, inside which that prompt's UserPromptSubmit command hooks run, as `{"promptId": <the prompt's prompt_id>, "kind": <kind>}` with what else the kind carries.
In a project whose store has a models folder the record is `.claude/p4/phi/models/served/start-<CLI session id>/origin.json`, in the folder that holds a launch's lines and a subagent's binding, which git ignores and the `layout` hook sweeps at a session's start.
In a project with no store it is `origin.json` in the session's own folder in the tree's store, beside `usage.json`, once a look has answered where that folder is: no prompt waits for python, so a prompt submitted before that keeps no record.
`rows.origin_of` in `scripts/rows.py` returns the record whose `promptId` equals the hook input's `prompt_id`, and `rows.whose` names whose words the prompt is: `composer`, `bridge`, `slack-ping`, and `plugin` with `asUser` are ezexe's own, `peer`, `peer-send-message`, `coordinator` and `projects-relay` are another session's, `plugin` without `asUser` is a plugin's prompt, p4-phi's own wake among them, and `task-notification` is an event.
The scripts ask the origin first for the request a message holds, for who began a turn, for a puppeteer's request rows and its usage line, and for the retrieval hook's message row, so a typed message of ezexe's that opens with `<` or with a mark is ezexe's own where the origin says `composer`.
For every other kind, and for a prompt with no record, the marks at the head of the text are read: `sdk` is the SDK host's own turn, which the desktop app's unstamped deliveries share with a scripted run's prompt, so a handed-over brief, a `<side-sessions-event>`, a Stop hook's feedback and "This session is being continued" are told by their marks, `unclassified` is what the app's own `[Cross-session delivery notice]` and `[Cross-session idle notice]` are, and no mark tells `scheduled-trigger`, `auto-continuation`, `channel`, `observer` or `observer-activity` from ezexe's words.
The origin names no sender, so the sender of a cross-session message is read from the wrapper Claude Code puts around it, by `rows.sender_of`: the `from-session` attribute where the wrapper has one, as on a report a hooks module sent with `$.session.send`, whose `from` is the sender's socket, and `from` otherwise.
A hook of the module at an event whose answer can refuse what was asked, `session.receive`, `prompt.submit`, `classic.UserPromptSubmit`, `agent.spawn`, `classic.SubagentStart`, `tool.check`, `classic.PostToolUse` or `classic.PostToolUseFailure`, lets the event through where it fails.
Seen on Claude Code 2.1.328, in a `claude -p` run of the plugin from a scratch project: the module wrote `{"promptId":"0ab0519e-…","kind":"sdk"}` before the UserPromptSubmit command hooks ran, the debug log has `classic.UserPromptSubmit settled in 532.4ms` inside `prompt.submit settled in 617.4ms`, and the request's `cc_prompt_id` is the record's id.
Seen in the desktop app on 2.1.326: another session's message is `peer` at `prompt.submit`, and a background task's notice is `task-notification`.
Not seen at the event: ezexe's own typing in the desktop app, whose transcript rows carry the origin `human`, which Claude Code 2.1.328 maps to `composer`, or to `bridge` for a Remote Control client.

The module asks python once who started the session, with the question of where its folder is, and sends that session the turn's last message at `turn.complete`, cut to 4,000 characters.
Claude Code raises `turn.complete` once a turn, after its last Stop hook answered, so a turn the Stop hook sends back raises no report.
A turn ezexe stopped sends none, and neither does a puppeteer's standing worker or coworker, whose first line asks it for the message its turn ends with.
A turn that Claude Code's own `[Cross-session delivery notice]` began sends none either, since that notice says a message of this session was held, refused or dropped, and a report of it would be held in its turn.
By `cross-session-messaging.md`, "Control inbound messages", a session that bypasses permission prompts holds each message of one that does not, and the other way round, so a worker in another class of permission mode than its starter reaches it only once ezexe approves each message or `crossSessionInbound` is `accept`.
p4-phi still keeps each report for the starter's next message, and names one that the message already holds without repeating it.
It keeps them because a send is only queued: `plugins/mods/api.md` says the call "resolves once the message is queued", and `cross-session-messaging.md` says the receiving session may hold or refuse it and that a message reaches only a running session.
A session's own send is told the same where it matters.
In the desktop app a message to a session whose turn is running waits for that turn to end: the send tool's own text gives "queued" as "waiting behind that session's current work", and its answer then ends with `(delivery: queued; ...)`.
At such an answer the module hands the sender one line beside the result, with no process started: the message waits for that session's turn to end, and where that session waits only on the message and the sender started it, `mcp__ccd_session_mgmt__stop_session` ends that turn and the queued message runs next.
That is the stop tool's own text, "a message already queued in it runs next", and "Usually no prompt when the target is a session this session started".
p4-phi calls that tool nowhere, and an answer that says `delivered` is told nothing.
Seen on 2026-11-19 and on 2026-11-22: a worker waited inside its turn for an answer that sat queued behind that wait, fifteen minutes the first time, until its starter stopped the turn.

A turn that ends on a step waiting on other sessions is let end, since a Stop hook can send back only the turn that is ending.
The look that follows answers what does not depend on that wait: a child that reported done with a commit that closes an issue and is on no branch of origin, and an open step that is plain work no live child holds.
The module then submits that list as a prompt, once for a turn, and the session reads it as p4-phi's words and not ezexe's.
Each such turn counts against `phi.keep_going_max` with the Stop hook's own send-backs, until a turn begins that the module did not start.
Where a project turns `phi.upkeep` on, the look also answers upkeep that is due while every started session is idle, and the module starts one turn for it, as "Upkeep of a session tree" below says.
The Stop hook's send-back to an open step stays, because `$.prompt.submit` starts a turn only after the session went idle, which the starter and the app have by then read as a turn's end.

The module checks a tool call at `tool.check`, which Claude Code raises after the PreToolUse hooks, and runs `scripts/hook.py lookup-check` only for a call python has a check for, with a PreToolUse hook's input on stdin and 10 seconds at most, so the check starts no shell, and no python for any other call.
Python has a check for a web call, a message to another session, a session archiving itself and a session's start, for an edit in a session that owes a nudge or is a puppeteer, which `phi/.nudge/<CLI session id>` and `phi/.puppeteers/<CLI session id>` in the project's store mark, and for every call of a subagent phi.py marked open with `phi/.agents/<agent id>`.
It has one for a Bash or PowerShell call whose tool and input hold `git` as a word, `push`, `merge` or the program `gh`, whose command starts in the background, whose session one of those two markers names, or whose store has a failure model `lookups-model.json` whose first line weighs shell calls, read once a minute at most.
A `deny` of python's is the verdict `deny`, which the model reads as the call's error, `Permission to use <tool> denied by plugins <names>: <reason>`, where the names are every plugin hooked on `tool.check`, and an `ask` is the verdict `ask`, which Claude Code puts to ezexe and marks with the plugin's name.
Python's words for the model are added beside the call's result by the module's hooks at `classic.PostToolUse` and `classic.PostToolUseFailure`, after the command hooks' own context, and are appended to the reason of a `deny`.
The engine's verdict stands for a call it already refused, for a plugin's `$.tool.check` question about a call nobody made, and where the check fails, as with no python found or at its timeout.
The module hooks no `tool.call`: a subagent may call any tool, and a hook there that may match a tool turns off that tool's move to the background and its live output.
It hooks no function at `classic.PreToolUse` either, whose input holds no agent id, which phi.py's checks of a subagent's call read.
The check does not obey `P4_PHI=0`: retrieval's check runs, and phi.py's own checks read the switch themselves.
The `Agent` entry of `PreToolUse` stays a command hook, and so do the entries of `PostToolUse`, `PostToolUseFailure` and `PostToolBatch` that record a call.
After a call that worked, the call waits on a shell only for a tool whose record can answer, which the one matcher of `PostToolUse` names: `Bash`, `PowerShell`, `Write`, `Edit`, `TaskStop`, `mcp__ccd_turn__update_plan` and `mcp__ccd_turn__wrap_up`, with the entry `lookup-record`.
A call of any other tool starts no process of its own once it ran, so nothing stands between the call and its result.
The lookup row of every call that worked is written by one async entry of `PostToolBatch`, `lookup-batch`, which by `hooks.md`, "PostToolBatch", "fires exactly once with the full batch", so a batch of parallel calls starts one process for its rows.
Until p4-phi 0.11.116 each call had an async `PostToolUse` entry of its own for its row, one process a call.
Seen on Claude Code 2.1.328 and 2.1.330 in a scripted run: the event came once a batch, for a batch of one call too and for a subagent's batch with its `agent_id`, and after the `PostToolUse` and `PostToolUseFailure` entries of its calls had answered.
A call of `tool_calls` carries its tool, its input, its id and its response, and a call that failed stood there with its error's text as the response and nothing that marks it.
So the hooks module, which hears each failed call at `classic.PostToolUseFailure`, names the failed calls of a batch by their ids under `p4_failed` in the input of the `PostToolBatch` command hooks, and the batch's entry leaves those to their own entry.
Where no module loads, a row is still written once by its id, so the row the `PostToolUseFailure` entry wrote stays as it is.
A call's response in a batch is what the model reads, a string or a list of content blocks, where `PostToolUse` hands the tool's own object, so a row's text is the model's text.
A call that failed has the `lookup-record` entry of `PostToolUseFailure` whatever its tool.
These stay command hooks where the hooks module loads too: a function hook at `classic.PostToolUse` runs above the command hooks and cannot keep its own plugin's entry out, since Claude Code has a module's `plugin.register` judged by the modules admitted before it and never by itself, so a function that made the record would run beside the shell that makes it.
A call a plugin's hooks module makes itself, with `$.tool.call` or `$.session.send`, runs those entries too, under an id that begins `toolu_plugin_`: the shell ends at once for such an id, and no lookup row and no record of `phi.py` is kept of it, since no model reads its result.
Seen on Claude Code 2.1.328, in a `claude -p` run of the plugin beside a probe mod from a scratch project: no shell started before any of four Bash calls, `tool.check` settled in 44.5 ms and 28.2 ms for two plain commands with no python started and in 523.3 ms for `git status`, where `hook.py lookup-check` ran, a `tool.check` hook's `deny` reached the model as `Permission to use Bash denied by plugins p4-four-probe, p4-phi, cc-plugin-privacy: <reason>`, and context a function hook added at `classic.PostToolUse` reached the model beside the result.
Seen in the desktop app on 2.1.326: a function hook at `classic.PreToolUse` was handed the tool, the call's id and the tool's arguments and no agent id, and in a `claude -p` run a subagent's call carried `agentId` at `tool.check` and none at `classic.PreToolUse`.

Where a store's `phi.json` sets `goal` true, a worker gets Claude Code's own goal in place of that send-back.
The line `Done looks like:` of its brief is the goal's condition, and the module sets it once the worker's first turn has ended, by running `/goal <condition>` with `$.command.run`.
`$.command.run` queues the command until the session is idle, so it waits through a turn that begins at once, and a stop of that turn drops it: `plugins/mods/api.md`, "Work your mod started before the interruption", gives the call as rejected with `the command was removed from the queue before it ran`, and as refused from then until the session's next input.
So a condition that was answered and is not set is answered again, to the look after a later turn's end and to three looks in all, and never while the module's command has not answered.
The module tells `phi.py` what a command that set no goal said, and `phi.py goal` prints it with how many looks the condition was answered to.
A goal the transcript's own goal row shows as set is marked set with no word from the module, so no second command starts a second turn on it.
The condition of a session another session started ends with two sentences p4-phi adds: the id of the session that started it, and that a part of the condition counts as met once a message from that session in the conversation says that session does that part itself or takes that part or the whole work as done.
The evaluator "judges your condition against what Claude has surfaced in the conversation", by `goal.md`, so a brief's line cannot follow a later change of orders unless the condition says such a message counts.
Seen in the desktop app on 2026-11-19, on Claude Code 2.1.326, without those sentences: a worker whose line named a start and a push that its starter then made itself was sent back nine times at the end of every turn, until its starter stopped the turn.
No other route sets a goal with nobody at the prompt: `goal.md` names the typed command alone, `SetGoal` is no tool of a session, a brief that begins with `/goal` runs no command since the app writes a started session's first message itself, and a `/goal` in another session's message arrives as text.
While the goal is set the Stop hook sends no turn back for an open step, since the goal's evaluator does and the two share Claude Code's one count of eight continuations in a row.
The evaluator "does not call tools, so it can only judge what Claude has already surfaced in the conversation", by `goal.md`, so the checks a script makes stay in the Stop hook: the regression test of a worker's issue, the commits on the default branch and the open issue.
Claude Code writes a goal's verdict to the transcript after the Stop hooks have answered, so the look that follows a turn's end reads it: a goal met marks the turn done with the evaluator's reason, and a goal met, judged impossible or cleared is over, so the send-back is back.
With `goal` unset or false no worker is given a goal, and `phi.py goal` prints how a session's goal stands.
Any session may also ask for a goal of its own, one no session started too, with the condition it states: the tool `mcp__p4-phi__goal`, or `phi.py goal ask`, keeps the condition, the look at that turn's end answers it, and the module sets it by the same `/goal <condition>`.
That ask needs no `goal` in `phi.json`, since the key is for the goal a worker is given unasked, and it takes the place of a goal the session has, as `goal.md` says of a second `/goal`.
A condition under 12 characters is refused, so no word that clears a goal is ever sent as one.
The page `docs/plugin-development.html` holds what the live probes behind this showed.

The module declares four tools with `$.tool.register`, at a session's start and at each reload of the module: `mcp__p4-phi__note`, `mcp__p4-phi__done`, `mcp__p4-phi__tree` and `mcp__p4-phi__goal`.
`note` requires `claim` and `source` and takes `kind`, `done` requires `text`, `tree` takes nothing, and `goal` requires `condition`.
`note` and `done` are in a session's tool list from its start, and `tree` and `goal` wait behind ToolSearch, as an MCP server's tool does, where a session loads each before its first call.
One hook of the module serves each call once Claude Code has allowed it: it runs `phi.py note`, `phi.py done`, `phi.py tree` or `phi.py goal ask` through `$.process.run`, for this session, in the session's working folder, with the python the runners proved and 30 seconds at most.
The words of a call come after `--`, so a finding that opens with a dash is still the finding.
What the command prints is the tool's result, and what it says on a failure is the call's error: `done` with a text shorter than eight characters answers `phi: say what was run and what it showed`.
A hook that fails answers the call's error too, since nothing runs beneath it.
The four commands still run from a shell, which is how a session whose Claude Code loads no hooks module runs them, and how a call for another session or store goes, since no tool takes `--session` or `--p4`.
`P4_PHI=0` declares no tool.

The module on each Claude Code.
The lowest build the module was seen to load on is 2.1.311.
Seen in a scripted `claude -p` run of a development copy on 2.1.311 and on 2.1.322: the debug log holds `hooks module p4-phi@inline loaded` with its events, the first look, the rules and the prompt's origin ran, and the run answered.
On both, `claude plugin validate --strict` passes and `claude plugin test` passes all 107 cases, as on 2.1.326, 2.1.328 and 2.1.330.
Until p4-phi 0.11.108 both older builds refused the module whole, since it named the event `tool.run`, which is in the API types from 2.1.326 on, and it called `$.session.info`, which those builds lack.
The four tools are declared on Claude Code 2.1.326 and later, read by `$.session.version`, and on an older build none is declared, where nothing was seen to serve one once its call is allowed: a session there runs the four commands from a shell.
No source can name `tool.run` and load on the older builds, so the hook that serves the tools stands on the glob `tool.*` under the four names and reads `next.event`.
On 2.1.326 to 2.1.328 that glob is handed `tool.run`, and the command runs there.
On 2.1.330 no glob is handed `tool.run`, `tool.*` and `*` alike: the allowed call comes to its run, finds no hook, and Claude Code answers "p4-phi registered the tool note but no hook answered this call", which comes back up to `tool.call`, where the module runs the command in its place.
A call the permission check refused comes back with its refusal and goes up as it came, so the check stands on every build.
This rests on the words of that answer: a build that words it another way answers a call with its own error and runs no command, which fails closed.
Tried and refused by the builds: a hook that names `tool.run` inside a `try`, a second file under `modules` in `hooks.json`, and an event name that is no string literal.
A python child of the module is started with the variables `$.process.hookEnv` gives, on Claude Code 2.1.326 and later, which are the ones a command hook of the session gets.
So in a session whose folder is a git worktree, where a command hook's `CLAUDE_PROJECT_DIR` is the main checkout's root by `worktrees.md`, "What worktrees share with the main checkout", the module's scripts read and write the main checkout's store as the hooks do, and the files the module keeps for python land there.
Until p4-phi 0.11.113 the module named the session's own folder as the project, so in such a session its scripts kept a second store in the worktree.
The input of the check before a call still carries the session's own folder as `cwd`, which is the worktree.
On 2.1.311 and 2.1.322, which have no such method, the module names the session's id and its folder as before.
At a session's start the module reads the settings of the sources `user`, `project`, `local` and `policy` by `$.settings.read({ source })`, keeps the keys p4's python reads, and adds them to the input of the SessionStart command hooks as `p4_settings`.
`p4conf.py`'s settings keeper takes the managed settings from there, where it knows one managed file a platform by itself, and reads the user, project and local files itself, since it writes one of them for every later session.
p4-temportal's module hands the same field in the same shape, and where a module above handed it the input goes down as it came and nothing is read again.
Where the read is refused python reads the settings files, as it does where no module loads.
The module hands none at a ConfigChange: seen on Claude Code 2.1.328 and 2.1.330 in a scripted run, `$.settings.read({ source: 'local' })` at the ConfigChange of the local file answered that file as it was loaded before the change, so the changed source would be handed stale, and the keeper reads the files there as before.
The check before a tool call hands python the transcript's path from `$.session.info`, and none on a build with no such method, where a session's brief is then read from the task p4-phi kept.

The settings keeper writes no allow rule for the tools, so in a permission mode that asks, Claude Code asks about a tool's first call as it does for any MCP tool.
Seen on Claude Code 2.1.328, in a `claude -p` run of the plugin from a scratch project, told to use no shell command: `mcp__p4-phi__note` and `mcp__p4-phi__done` were in the model's tool list from the start and `mcp__p4-phi__tree` was loaded with ToolSearch, the note tool answered `kept` and `notes.jsonl` held the claim, which opened with a dash, with its source and kind, the done tool, given the text `ok`, answered the error `phi: say what was run and what it showed`, and the tree tool printed the session.
Seen in the desktop app on 2.1.326: a probe mod's registered tool was listed behind ToolSearch, and a `tool.run` hook served it.

Without a data folder, as when a test runs a hook, the proved python is kept in the plugin's own folder.

A worker starts with the model and the effort of its step's role in the skill `sub-agentic`, and `phi.child_levels` in `p4.json` sets them for each kind of step.
The start tool takes `model` as a model id, "Same family or cheaper than yours; anything higher is ignored", and `effort` "at or below yours", and inherits each it is not given.
These are the defaults:

| Kind of step | Role | Model | Effort |
| :- | :- | :- | :- |
| `static`: docs pages, a rename, a version bump and other mechanical work that names no code | integrator | `claude-sonnet-5-5` | `medium` |
| `build`: every other step, such as a change to behaviour or anything that names code | writer | `claude-opus-5-5` | `medium` |
| `design`: a design, a plan or a decision with its sources | writer | `claude-opus-5-5` | `medium` |
| `review`: a review, an audit or a check of another's work | cross-check | `claude-sonnet-5-5` | `medium` |
| `top`: a brief that makes a new top session | orchestrator | the parent session's own | the parent session's own |

No start is named above the effort of the session that makes it.
p4-phi reads that session's level from the hook input's `effort.level`, or from `CLAUDE_EFFORT`, keeps the last level seen on the session's record, and holds each start's `effort` to it.
The level is Claude Code's own: `hooks.md`, "Common input fields", calls `effort` an "Object whose `level` is the effort level setting when the hook runs" and says "`$CLAUDE_EFFORT` holds the same level."
The limit is the app's and no docs page states it: a started session's effort is at most its starter's, which `scripts/claude_code_limits.json` logs.

p4-phi has no setting for a subagent's model or effort, since Claude Code sets both.
`sub-agents.md`, "Choose a model", gives the order of the sources: "The per-invocation `model` parameter, which Claude can pass when it starts the subagent", then "The `model` field in the subagent's definition, including `inherit`", then "The `CLAUDE_CODE_SUBAGENT_MODEL` environment variable", then "The main conversation's model, or the spawning subagent's model for a nested subagent".

| Subagent | What sets its model and effort | How a project or ezexe sets another |
| :- | :- | :- |
| `p4-phi:finder`, the plugin's own | `model: haiku` and `effort: low` in `agents/finder.md` | A `model` or an `effort` on the Agent call |
| `p4-phi:writer` and `p4-phi:integrator`, the plugin's own | `model: opus` and `model: sonnet`, each with `effort: medium`, in their files | A `model` or an `effort` on the Agent call |
| `p4-phi:check`, the plugin's own | `model: sonnet` and `effort: medium` in `agents/check.md` | A `model` or an `effort` on the Agent call: "The parameter overrides the `effort` field", and for the effort "The `CLAUDE_CODE_EFFORT_LEVEL` environment variable takes precedence over both." |
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

## Upkeep of a session tree

A session that started others keeps them by itself once the project turns `phi.upkeep` on, and with it off everything stays as the other sections say.
`phi.py upkeep on` and `phi.py upkeep off` set it in the store's `p4.json` and run the settings keeper at once, and `phi.py upkeep` prints what is due.
With it on, beside every message such a session gets, p4-phi hands the acts that are due for the sessions it started, and the setting is ezexe's standing word for each, so none waits on ezexe.

- Archive: a started session that is finished, with no open step, no background task and its last report handed, and whose commits are all on its repository's default branch on the remote, is named by its whole title with the call `mcp__ccd_session_mgmt__archive_session` and its `session_id`. A session that made no commit of its own has nothing to land, so it is named only while nobody but its starter drives it: not after a turn that another live session's message began, nor after one the prompt of a plugin other than p4-phi began. One whose work is not landed gets the landing line first. That line and the push line follow the repository's own test workflow: where a workflow under `.github/workflows/` runs its tests on every push to the default branch, the checks the task named and the test files of the touched paths run before the push, and that workflow's run on the pushed commit is read after it with `gh run watch <run id> --exit-status` and kept by a note that says the workflow was green at that hash. Where the repository holds no such workflow, the full suite runs once on the commit being pushed, since a local run is then the only run.
- Follow-through: what a finished worker's report lists as found and not fixed, or as left, is kept as open items in `upkeep.json` in the orchestrator's folder. Each goes back to that worker by message while it is live and its context is short, and otherwise to a successor, and it closes only on a commit on the default branch that names it, on a note that says why it is left, or on ezexe's word. Every open item is listed at every turn.
- Steps that wait: a step kept with the session it waits on is handed as due once that session's work is on the default branch.
- Steps that fall due when no session is open: a step that waits on a time, and not on a session, is kept by `upkeep wait "<the step>" --at "<when>"`, which prints the scheduled run of Claude Code that fits it with the prompt written, and p4-phi makes none, since making one starts sessions later and is ezexe's. A step that needs only the repository gets `/schedule <when>, <prompt>` on a line of its own, for ezexe to type: a cloud scheduled task, which works in a fresh clone with this machine on or off, and whose own flow asks ezexe for the repository and confirms the time. With `--local`, a step that needs the project's local store, which no clone holds, gets a Desktop scheduled task's instructions: the session puts it to ezexe once and, on ezexe's yes alone, makes it with `mcp__scheduled-tasks__create_scheduled_task`, or ezexe makes it under Scheduled, New task. Such a wait is handed as due by no line, `upkeep` lists it until `upkeep close` closes it, and `/loop` is no answer to it, since a loop needs an open session.
- The sweep's loop: a session with a live worker and no loop of its own is handed one line, once, to start Claude Code's own `/loop` with no interval, by the Skill tool with the skill `loop` and the sweep's words, which `upkeep.SWEEP` holds so no session writes them by hand. Each sweep reads the live sessions and the workers in the Terminal panel, sends on one that stopped with work left, verifies one that reports done, and waits long, since the app's note of a started session's turn end is the main wake-up. A session whose loop runs while nothing of its tree is live is handed, once, the call that ends it, `ScheduleWakeup` with `stop` true.
- The sweep's schedule: the app sends no note when a worker in the Terminal panel ends, so no notice ends that wait, and while one is live the sweep is `/loop` with an interval in place of the self-paced loop. The session is handed one line, once: read the tasks with `CronList`, and where none holds the sweep's words, call the Skill tool with the skill `loop`, the interval `upkeep.EVERY`, ten minutes, and the words `upkeep.SWEEP_FIXED`, which Claude Code runs on a fixed schedule by `CronCreate`. The schedule sweeps the started sessions too, so a session has one of the two and never both, and the line ends a self-paced loop that runs. Once no terminal worker is live the session is handed, once, the end: `CronList`, and `CronDelete` with the id of the task that holds those words, which the line gives where the session's own `CronCreate` call answered with one.
- Leftovers on disk: after an archive, a clean worktree and its merged branch are named for removal by `git worktree remove` with no force and `git branch -d`, never `-D`, and so is the worktree of a subagent whose branch is merged. Anything dirty or unmerged is named to ezexe once and left, and so is a worktree that holds another checkout, while one a live session still works in is passed over until that session is archived.

What the app and Claude Code already do is configured or called, and p4-phi builds only the rest:

- The archive is the app's tool, and https://code.claude.com/docs/en/desktop.md, "Work across sessions", says "You get an approval card before Claude archives a session, except in Auto mode and Bypass permissions mode". So p4-phi archives nothing: it names the call, and with the setting on the keeper writes no ask rule on the tool and takes its own entry out.
- The app removes the worktree it made for a session at its archive, and Claude Code removes a subagent's worktree that holds no changes and sweeps the others once they are older than `cleanupPeriodDays`, by https://code.claude.com/docs/en/worktrees.md, "Clean up subagent and background-session worktrees". p4-phi names what neither removes: the merged branch, a worktree a session made itself with `git worktree add`, and a merged subagent worktree before that sweep.
- A message between sessions is `SendMessage`, and a new session is the app's start tool or its card, so p4-phi sends and starts nothing for an item or a step: it names the call.
- The scheduled runs are Claude Code's own: https://code.claude.com/docs/en/scheduled-tasks.md, "Compare scheduling options", gives a cloud scheduled task "No (fresh clone)" for access to local files and no need of the machine or of an open session, a Desktop scheduled task the machine's files and no need of an open session, and `/loop` the need of one, and says "Use cloud tasks for work that should run reliably without your machine. Use Desktop tasks when you need access to local files and tools." https://code.claude.com/docs/en/routines.md says "Run `/schedule` in any session to create a scheduled task conversationally. You can also pass a description directly", and https://code.claude.com/docs/en/desktop-scheduled-tasks.md says "Tasks only run while the desktop app is running and your computer is awake" and "You can also ask Claude in any Desktop session to set the schedule". The desktop tool's own text says "an approval prompt may or may not appear depending on the user's permission settings", so the line asks for ezexe's yes before the call. The case this came from: ezexe/p4's `tests` workflow ran on a push and on a pull request alone and installs the newest Claude Code each time, so a new build that turned `main` red showed only at the next push. That case needs no session at all, so it is no scheduled run of Claude Code's: the workflow runs once a day by its own `schedule` trigger, which is GitHub's, and GitHub's notice of a failed run goes to the account that last changed that schedule. A step that takes a session's reading and needs only the repository is a cloud scheduled task's, by `upkeep wait "<the step>" --at "every day at 7:17am"`, whose `/schedule` line ezexe types.
- The sweep that keeps a session tree runs by `/loop`, and p4-phi schedules nothing: https://code.claude.com/docs/en/scheduled-tasks.md, "Run a prompt repeatedly with /loop", says a prompt with no interval "runs at an interval Claude chooses each iteration", and "Stop a loop" says "Claude calls the `ScheduleWakeup` tool with `stop: true`, which cancels the pending wakeup immediately". Whether a loop runs is read off the session's own calls at each turn's end, and a self-paced loop is not restored when a session is resumed, so the line is handed anew once the kept wakeup and its fallback have passed.
- The sweep's fixed schedule is Claude Code's too: the same page, "Run on a fixed interval", says "When you supply an interval, Claude converts it to a cron expression, schedules the job, and confirms the cadence and job ID", and "Stop a loop" says "to stop a loop such as `/loop 5m`, ask Claude to cancel it". Seen in the desktop app: `/loop` with `10m` and the sweep's words had the session call `CronCreate` with `*/10 * * * *`, the words as given and `recurring` true, which answered "Scheduled recurring job f5726d66 (Every 10 minutes)", `CronList` listed the task with its id and the first eighty characters of its prompt, and `CronDelete` with that id answered "Cancelled job f5726d66." Whether the schedule runs is read off the session's own `CronCreate` and `CronDelete` calls, until the seven days after which Claude Code ends a recurring task by itself. The `/loop` skill asks the person whether to make a cloud schedule in its place where the interval is sixty minutes or more or the words read like a daily cadence, so the interval stays under the hour and the words name no day.
- The turn for upkeep that is due while every started session is idle is `$.prompt.submit` of the hooks module, the call that already starts the turn after a wait, inside the same `phi.keep_going_max`.

The session runs every command itself, so its own permission rules hold for each: p4-phi asks git only what is true and removes nothing in its own process.
Where a step or an item wants a new session on a turn no person began, which the app refuses a start on, upkeep has the session start a worker in the Terminal panel in place of the app's card: a scripted `claude -p` run in a worktree of its own, whose prompt is `/goal` with a condition that names its brief, with p4's plugins off and its messages accepted by its settings file, in a session that runs in auto or bypass permissions mode.
Such a worker has no row in the sidebar, no Changes card and no archive, and once its run has ended and its work is on the default branch upkeep names the close of its tab, the unlock of its worktree and their removal.
The skill page lists what upkeep cannot do, a start on a turn no person began among them.

## Approval cards and a session's start

A session another session started stops on no approval card for work its brief covers, once ezexe has said yes to the set of what p4-phi settles with no card.
What needs ezexe is settled by the top session before the start, and never by the started session in the middle of its work.
The page `docs/claude-settings.html`, "Approval cards and a session's start", lists every kind of card, what raises it, and how it is settled before a start or why it stays.

- The set is `p4conf.CARD_SET`, kept in `p4conf.py` and nowhere else: an allow rule for each tool a p4 hooks module declares, the leftover ask rule on the archive tool taken out where `phi.upkeep` is on, a worktree's own branch moved unasked, a push made unasked where the brief tells the session to push, a refusal with the session to ask in place of every other card a guard of p4-phi raised, and a refusal of a start that would leave its session cut off or waiting.
- It is in force for a store only while `phi.cards` in that store's `p4.json` holds the set's name, which `phi.py cards` prints with the set and every kind of card, and the store's record `claude-settings.json` holds ezexe's yes to that set.
- `phi.py cards on <id>` asks for it and `phi.py cards off` takes it out. For the first, p4-phi's guard raises one approval card in every permission mode, with the set whole as its text, and p4-phi's hook after that call keeps the yes, so the yes is ezexe's own press in the top session. A session another session started is refused the command.
- The key alone puts nothing in force. Written by an edit of `p4.json`, or by the command run where no hook of p4-phi runs, such as the app's Terminal panel, it has no yes beside it and the set stays off.
- A yes given before the record of one existed is carried over once, with no card: where the store's record holds the set's allow rules as an earlier keeper wrote them and the key still names the set, the first whole check of this keeper keeps the yes itself, marked as carried over. The record then holds that the look was made, so a key written later with no press leaves the set off.
- A copy of p4-phi whose set differs has another name, so a changed set is in force nowhere until ezexe has said yes to it.
- With the set off nothing changes: each guard raises Claude Code's approval card as before.

What Claude Code and the app already do is configured or called.
The rules are entries of `permissions.allow` in the project's local settings file, which a new session reads at its start, by `permissions.md`.
The card for the yes is a hook's `ask`, which Claude Code puts to a person in every mode.
A started session's mode is the start call's own `permission_mode`, left out so that it inherits its starter's, since `cross-session-messaging.md` holds every message between a session that bypasses permission prompts and one that does not.

## A puppeteer and the sessions it controls

A puppeteer is the orchestrator ezexe files in the sidebar section "puppeteers", which controls the orchestrators of other trees.

| What the plugin does | How |
| :- | :- |
| Knows a puppeteer | The app's own `claude_desktop_config.json`, beside its `claude-code-sessions` folder, assigns the session to a group named as `phi.puppeteer_section` says, in `preferences.epitaxyPrefs["dframe-group-scopes"]`, each scope with `groups` and `assignments`. A missing or reshaped file makes no session a puppeteer. Where `app_tools` is on in `phi.json`, the section is read first from `group` in what the app's `get_session` and `list_sessions` answered the hooks module, and the file is read for a session those answers do not hold. For a puppeteer the module also asks `mcp__ccd_sidebar__list_sections`, or `mcp__ccd_sidebar__list_groups` where that answers nothing, and the line that has it file an orchestrator it started gives the section's id from those answers, and names both tools beside `mcp__ccd_sidebar__move_sessions` either way. |
| Knows which sessions it controls | `phi.py controls <sessionId>` writes `controls` on the puppeteer's record, each entry with the store that session's tree lives in. A controlled session's own hook finds the puppeteer and keeps `puppeteer` on its own record. Each side keeps its own record. |
| Tells the controlled session | Once when it comes to have a puppeteer, and once when that ends. |
| Keeps the board | `board.md` in the puppeteer's folder. |
| Lets one session publish a tree's issues | `gh issue create` runs only in the session that publishes for a tree: the issues coworker of the puppeteer's standing worker, whose brief holds the line `Issues coworker of its standing worker`, that worker until one is marked, the puppeteer until it has a worker, and the tree's orchestrator under no puppeteer. In any other session p4-phi's check before the call refuses it with one line naming the `Finding:` form and that session by full title. A permission rule cannot do this, since it holds in every session that reads its settings file: `permissions.md`, "Manage permissions", has the dialog list "all permission rules and the `settings.json` file each rule comes from", and "Extend permissions with hooks" names hooks for what is decided "at runtime". |
| Hands a puppeteer the open issues no session holds | The puppeteer's watcher lists the open issues of the repositories its controlled sessions work in at its slow looks, one `gh issue list` a repository, and keeps the ones no live session's record holds as its issue in `open-issues.json` in the puppeteer's folder. When a controlled tree closes or a controlled session reports done, the puppeteer gets one line naming each once, beside the running orchestrator whose topic covers it or as the start of a new orchestrator, to close what a landed commit covers and to route or start the rest. None is put to ezexe as a choice, and no hook reads GitHub for it. |
| Leaves a puppeteer's steps with it | No advice on where its steps go and no nudge, and at Stop a step that waits on sessions' reports ends the turn while a controlled session is not yet complete. |

What p4-phi does not do here is on the skill's last section.

## The files a brief covers

A brief names the files its session covers on a line `Files: <paths>`, and `Files: none` for a session that writes none.
p4-phi keeps the line on the session's record and page and in the address book, where a message about one of those files is routed by it.
The line holds no start and no edit: a session that writes works in a git worktree of its own, so p4-phi keeps no lock on a file.
No start is refused for the files its brief names, held while a live session covers one of them or queued behind a busy writer, no command narrows or releases the line, and a puppeteer's message is warned about for no file.

## Kept beside a native feature

Each passage names a thing of p4-phi that stands beside a thing Claude Code or the desktop app does, and what the native thing lacks for p4-phi to stand on it alone.

### Findings in `notes.jsonl`, beside the app's shared notes folder

The desktop app names one folder to the sessions of a group of linked sessions, in the first message it writes for a started session: `Shared notes folder for this group of sessions`, a folder `side-session-notes/<the starting session's id>` in the app's own data folder.
p4-phi keeps a finding in `notes.jsonl` in its writer's folder in the store, by `phi.py note` and the tool `mcp__p4-phi__note`, and moves none into that folder.

- No page of the Claude Code docs states the folder. `desktop.md` and `cross-session-messaging.md` hold no sentence on it, as read on 2026-11-19, so where it is, how long it stays and who clears it rest on the words of the app's message alone.
- It is named in a message the app writes for a session of the desktop app. A scripted `claude -p` worker, a session in a terminal and a subagent are handed no such message.
- It is a folder on one machine, outside the repository and outside the store, so the store's sync carries nothing of it to another machine.
- A file in it is free text. A row of `notes.jsonl` holds its claim, its source, its kind, its time and its writer, a finding with no source is refused, and a claim may open with `deprecates:` or `replaces:`, the marks a tree's anchors are made from and by which a newer note supersedes a finished child's work.
- Nothing hands a file in it to a session. A row of `notes.jsonl` reaches every session below its writer in the background beside that session's first message.

p4-phi uses the folder for what it gives: the id in its path names a started session's starter before the app's record does, and a terminal worker's brief, script and report are files in its `terminal-workers` folder.

### The check before a second background copy, beside Claude Code's list of background tasks

Claude Code keeps the list of a session's running background tasks itself.
`/tasks` shows it to a person, and a Stop hook's input holds it as `background_tasks`, each task with its `id`, `type`, `status`, `description` and, for a shell task, its `command`, by `hooks.md`, "Stop input".
p4-phi makes no list of its own.
Its Stop hook keeps that input's list on `session.json`, an entry leaves it when its completion notice arrives or a `TaskStop` call stops it, and before a shell call with `run_in_background` the check `restart-check` refuses a command the kept list still holds as running, once for each copy, with the id to wait on.

- Nothing of Claude Code refuses or warns of a second start of a command that still runs in the background. `tools-reference.md`, "Background commands", and `interactive-mode.md`, "How backgrounding works", name no such check.
- The list reaches a hook at `Stop` and `SubagentStop` and at no other event. The input of `PreToolUse` and of the module's `tool.check` lists no running task, so a check before a call has only what the last Stop kept.
- `/tasks` is a view for a person, which no hook reads and no tool of a session returns, and `TaskList` is the list of to-dos.
- The hooks module's API has no method that returns the list: the 80 methods of Claude Code 2.1.326, as p4-native's `hooks/weighed.json` lists them, hold none for a background task.

So the kept list and the check stay, and they rest on the native list alone: where the Stop input held no `background_tasks`, the check refuses nothing.

## The host, from p4-native's capability map

p4-native writes what the host is into `<project>/.claude/p4/native/host.json`, a session's entry under `sessions.<session id>`, and its README gives that file as the one way to read it.
Where the file holds an entry for the session, p4-phi's hooks module reads it first in the two places where it worked the host out by itself.
Its own reading stays in both, for a machine with no p4-native, a project with no store, a map that is no JSON and an entry that is not written yet, since p4-native's start does not wait for the map.
For a session in a git worktree p4-native keeps the map in the main checkout's store, so the module reads it there first and then in the session's own folder, in that plugin's own order.
The main checkout's root is `$.session.repo`'s to give, whose `root` is by the types of `claude-code` "The repository's root, absolute: the main working tree's for a worktree".
Until p4-phi 0.11.114 the module read the map in the session's own folder alone, so a worktree session found no entry and fell back to its own reading.

- The search for a python, where no runner kept one: whether this is Windows is the entry's `platform`, and the shape of the plugin's own folder where the entry has none or says `unknown`.
- The first round of calls of the desktop app's own tools: an entry whose `host` is not `desktop` and whose `tools.app` is empty says that no such tool answers, so none is called. p4-phi's own reading is the call itself, which the engine rejects in a session the app does not host.
- An entry that reads `desktop` and lists no tool of the app was read before the app's tool server had connected, so it decides nothing and the call's own answer tells.
- Another session's entry is never read, since one folder can be open in the desktop app and in a terminal at once.

Seen on Claude Code 2.1.328, in a scripted `claude -p` run with the installed p4-native and p4-phi's development copy: the entry read `terminal`, `scripted` and `windows` with no tool of the app, and the module's debug log held `p4-native's map reads no tool of the desktop app in this session, so the app's tools are not asked` and no line of a rejected call.
The search for a python is not seen live, since this machine's plugin data folder holds a kept one.

Left as they are, each with its reason.

- `upkeep.terminal`, which routes work to a worker in the Terminal panel, asks nothing of the host today. Holding it to the entry's `tools.servers.terminal` is a new check and no swap, and an entry read before that server had connected would refuse a worker that could start.
- `relay.PUSH`, the sentence that opens "Where this session's tool list holds `PushNotification`", leaves the look to the session, whose own tool list is never out of date, and python would need the session's CLI id and the project's root at both places that hand it.
- The reads of `CLAUDE_CODE_HOST_SESSION_ID` in `phi.py` and `node.py` tell which session of the app this is, which the map does not hold, since p4-native reads no environment variable.
- The reads of the app's record files tell who started a session and whether it is archived, which the map does not hold either.
- The python scripts ask their own interpreter for the operating system by `os.name`, which costs nothing and is never out of date.

## No setup

The plugin works in any project it is enabled in.
It needs no key in `p4.json`, no entry in a project's `settings.json` or `settings.local.json`, no environment variable and no existing `.claude/p4` store, and it writes to no settings file.

- The plugin's own SessionStart hook makes the store `.claude/p4/` at the first session of a project and writes `p4.json` with the defaults `p4conf.py` holds, which leave out `child_levels`, `puppeteer_section` and `clear_at`: those three are read when a project sets them. A value it wrote follows a later change of its default, and a value set by hand stays. A value set by hand moves only when it equals the value recorded as written, at the next generation, or, in a store from before the record, a past default.
- Before the store exists, a session holds the built-in rules in its system prompt, as every session does.
- The plugin ships no `settings.json`, a file no plugin page of the docs describes.

### `p4.json`, section `phi`

Every key is optional.

| Key | Default | What `false` or a value does |
| :- | :- | :- |
| `levels` | `true` | `false`: no delegation rule |
| `child_levels` | the table under Delegation | an object: a kind, `static`, `build`, `design`, `review` or `top`, with its `model`, an id or `inherit`, and its `effort`, a level or `inherit` |
| `act_dont_wait` | `true` | `false`: the built-in act-don't-wait rule is left out |
| `plan_mode` | `true` | `false`: the built-in plan rule, which hands plan mode, is left out |
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
| `keep_going_max` | 2 | the times, 0 to 7, one turn is sent back while it has open steps, counted together with the turns in a row the hooks module starts for work a wait left unmoved, and the most turns it starts for upkeep until ezexe's own message begins one |
| `upkeep` | false | true has a session that started others handed their upkeep as acts that wait on nobody, with no ask rule on the archive tool; `phi.py upkeep on` and `off` set it |
| `cards` | none | the name of the set of what p4-phi settles with no approval card, as `phi.py cards` prints it, which asks for that set; read from the file alone, with no variable, and written by `phi.py cards on <id>` behind one approval card. The set is in force only with ezexe's yes beside it, which p4-phi's hook keeps in the store's record at the end of that call |
| `watch_s` | 5.0 | the watcher's tick in seconds, 1 to 600 |
| `stale_s` | 86400.0 | the seconds, 60 to 2,592,000, after which an orchestrator with open work and no turn is stale |

A cap's value of another type or out of its range keeps the default.

The `recall` section's keys and defaults are listed in `scripts/p4conf.py`, each beside its meaning.

### `phi/phi.json`

Every key is optional, and the file need not exist.

| Key | Default |
| :- | :- |
| `background`, `reports`, `turns`, `book`, `rules`, `puppeteer`, `app_tools` | `true` |
| `background_chars` | 3000 |
| `reports_chars` | 6000 |
| `wait_s` | 2.0 |
| `goal` | `false` |

`puppeteer` set to `false` gives an orchestrator no watcher and no start draft on ezexe's message.
`goal` set to `true` gives a worker Claude Code's own goal, with the line `Done looks like:` of its brief as the condition, and stands the Stop hook's send-back down while that goal is set.
`phi.py goal on` and `phi.py goal off` write the key and print how it stands, since a session writes nothing under `.claude` with its own tools.
Where no prompt hook saw a worker's brief, as when the plugin was loaded after the session's first message, the line is kept at the first Stop the plugin sees, where the task is.
`app_tools`, which is on unless a store sets it to `false`, has the hooks module ask the desktop app's own tools for the session and the sessions linked to it after a look, once a minute at most and never while a turn of the session runs, and write the answers to `app.json` beside the prompt's origin.
`phi.py` then reads a session's title, folders, archive state, permission mode, branch and named starter from that file while it is under five minutes old, and from the app's record file for a session the file does not hold and for everything the tools do not answer: the CLI session ids, a session with no starter named, and the worktree path.
The record files stay the fallback: a session the app did not start has no such tool, so the module's first call is refused there, it asks none again, and every read is the record's.
With it set to `false` no tool of the app is called and the record files are read alone.
`phi.py app_tools off` is the way out and `phi.py app_tools on` the way back: they write the key as `goal on` writes its own, and `phi.py app_tools` alone prints how it stands, which is on for a store that has not set it.
Seen in the desktop app on Claude Code 2.1.326: the calls reach the four tools from the module, mid-turn and idle, leave no row in the transcript and move no token count, and the page [`docs/plugin-development.html`](../../../docs/plugin-development.html) holds what each answered.
That the module's call reaches those tools in a desktop session is not yet seen, which is why the setting is off unless a project turns it on.

### Environment variables

None has to be set.
Each is for one run, a test or one machine's unusual layout.

| Variable | Unset means | Set |
| :- | :- | :- |
| `P4_PHI` | phi.py's hooks run | `0` turns off phi.py's three hook commands, the checks hook.py hands it, the watcher, the usage record, the origin kept in a session's folder, the report sent to a starter, the turn started for a wait and the four tools the module declares, while retrieval goes on with the origin kept in the store's `served` folder |
| `P4_PHI_RULES`, `P4_PHI_BOOK`, `P4_PHI_GOAL`, `P4_PHI_APP_TOOLS` | as `phi.json` says | `0` or `1` for one run |
| `P4_PHI_PUPPETEER` | as `puppeteer` in `phi.json` says | `0` or `1` for one run |
| `P4_PHI_WATCH` | an orchestrator's watcher runs | `0` keeps it from starting, and with it the turn the module starts for a wait and the goal a worker is given, while a worker's report still goes to its starter |
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
The page `docs/plugin-development.html` in ezexe/p4 says how: a clone loaded with `claude --plugin-dir <clone>/lbiza/plugins/p4-phi --debug`, edits picked up by `/reload-plugins`, the installed copies off for the development project in a `.claude/settings.local.json` ezexe writes, each copy's `CLAUDE_PLUGIN_DATA` folder checked on disk, and the installed copy moved by Claude Code's own auto-update after a landing bumps a version, with `claude plugin update` as the move by hand.
What the plugin makes a model do is checked by the cases in `evals/`, run by hand from this folder with `claude plugin eval . --scaffold --trust-plugin --model claude-sonnet-5-5 --judge-model claude-haiku-5-5 --no-publish --max-cost-usd 5`, which gates no landing.

## What depends on the machine

- `python` 3, `sh` and `git` must be on PATH. On Windows, `sh` comes with Git.
- The issue loop needs `gh`, signed in, and a repository whose `origin` is on GitHub. Without them it does nothing.
- The session tree is read from the Claude desktop app's records: its record files of sessions, which no docs page describes, and, unless `app_tools` is off in `phi.json`, what its own session tools answered the hooks module, read first. In a plain terminal session every session is an orchestrator. A scripted run, `claude -p` started from a desktop session's shell, inherits that session's `CLAUDE_CODE_HOST_SESSION_ID`, and p4-phi holds the id against the app's record of that session, so the run is recorded as the CLI session it is and never as the desktop session that started it.
- The readings workflow needs dynamic workflows on. They are on for every paid plan, on Pro from the Dynamic workflows row in `/config`, and `disableWorkflows` or `CLAUDE_CODE_DISABLE_WORKFLOWS` turns them off. Source: https://code.claude.com/docs/en/workflows.md.
- p4-phi names no `MultiEdit` and no `KillShell` in a matcher, in its hooks module or in a script. `MultiEdit` is a legacy name by `permissions.md`, `KillShell` is a previous name of `TaskStop` by the Agent SDK's reference, which Claude Code's changelog names from 2.1.30 on, and a hook's input carries the tool's own name, so neither arrives on a build the hooks module loads on.
- The hooks module needs Claude Code v2.1.287 or later, and it does not load in a session started with `--safe-mode` or `--bare`, or where `disableAllHooks` is set. Source: https://code.claude.com/docs/en/plugins/mods/create.md. It also needs a Claude Code that knows every event it hooks, `tool.check` and `tool.run` among them: Claude Code refuses whole a module that names an event it does not know, a registration inside a `try` included, as a `claude -p` run on 2.1.328 of a module naming a made-up event showed. It was seen loading in the desktop app on 2.1.326 and in `claude -p` on 2.1.328. Where it does not load no watcher runs, and a ledger is rewritten at ezexe's message to its orchestrator and by `phi.py ledger`. No report is sent to a starter there and no turn is started for a wait, so a starter reads its workers' reports beside its next message. No origin is kept there either, so the marks at the head of a prompt's text tell whose message it is. No check runs before a tool call there, so p4-phi refuses no call, asks about none and puts no earlier finding beside a web call. No tool of p4-phi's is declared there, so a session runs `phi.py note`, `phi.py done` and `phi.py tree` by a shell line. No `/phi-pane` is declared there, so ezexe reads the three pages as files.
