// p4-phi's hooks module: the part of the plugin that runs inside Claude Code, where a command hook can only print.
// It finds the python that find-python.sh proved for the plugin's runners, and it is an orchestrator's watcher: it
// runs `phi.py look`, one pass over the session's subtree that writes its ledger, at a turn's end, at a message's
// arrival and on a timer. It keeps the session's usage, which no command hook is given, in usage.json in the
// session's folder in the store, for the python scripts to read. And it wakes an idle session, which no command
// hook can: at a worker's turn end it sends the worker's report to the session that started it, and where a look
// answers work that a turn's wait left unmoved, or upkeep that is due while every session it started is idle, it
// starts a turn of the session's own for it. And it sets the rules built into p4-phi as a section of the system
// prompt, where a command hook can only hand text beside a start. And it keeps the origin Claude Code stamps on
// each prompt, which no command hook is given, for the UserPromptSubmit hooks of that prompt to read. And it is the
// guard around a tool call: it tells by plain tests which calls python has a check for, and starts python for
// those alone, so no process starts before a call that has none. And where a project turns `goal` on it gives a
// worker Claude Code's own goal, which no command hook and no other session can, and it gives any session the goal
// that session asks for with a condition it states. And it gives a session four of phi.py's commands as tools,
// `note`, `done`, `tree` and `goal`, which it runs itself, so a session keeps a finding with no shell line. And it
// is a pane beside the chat, which no command hook can draw: a puppeteer's board, the ledger of ezexe's requests
// and an orchestrator's ledger of its sessions, as python wrote them into the session's folder, opened by the
// command `/phi-pane` and read anew after each look while it is open.
// And unless a project turns `app_tools` off it asks the desktop app's own tools for the session and the sessions
// linked to it, which no command hook can call, and keeps the answers for python.

import { atom, read, update } from 'claude-code'
import type {
  AgentSpawnInput,
  EngineInterface,
  PromptComposeResult,
  PromptOrigin,
  Register,
  RenderElement,
  SessionContextUsage,
  SessionRateLimit,
  Settings,
  Timer,
  ToolCallResult,
  ToolCheckInput,
  ToolCheckResult,
  TurnCompleteReason,
} from 'claude-code'

import type { PhiNode, PhiPage } from '../types'

// What find-python.sh runs to prove an interpreter: the interpreter prints its own path.
const PROOF = "import sys; print(sys.executable.replace(chr(92), '/'))"

// How long a look may run before Claude Code ends it. A slow look reads GitHub once for each issue of the subtree,
// and a puppeteer's once more for each repository its controlled sessions work in, to list its open issues.
const LOOK_MS = 60_000
const SLOW_LOOK_MS = 300_000

// A session with nothing to watch is checked again after a wait that doubles, to this at most.
const MOST_WAIT_MS = 600_000

// The most of a report that is sent to a starter: what phi.py keeps of one, its REPORT_CHARS.
const REPORT_CHARS = 4_000

// The id of the system prompt's section that holds the rules built into p4-phi. A plugin's own section is named
// `<plugin>:<name>`, by the types of `prompt.compose`.
const RULES_SECTION = 'p4-phi:rules'

// A project's store, and under it where hook.py keeps a launch's lines for its subagent's start: hook.pending_dir
// in python, `served/start-<session>` under the store's models folder. A file `bound-<agent id>` there holds the
// id of the Agent call that launched the subagent, which hook.launch_of reads at the subagent's SubagentStart.
const MODELS = '.claude/p4/phi/models'
// p4-native's capability map, from the project's root: what the host is as that plugin asked the engine, a
// session's entry under `sessions.<session id>`. p4-phi reads it first where it is there, and its own reading
// stays for a machine with no p4-native.
const MAP = '.claude/p4/native/host.json'

// The field of a SessionStart hook's input under which a p4 hooks module hands the plugins' python the settings
// Claude Code loaded, one object a source, as p4conf.py's HANDED_KEY and HANDED_SOURCES name them. The settings
// keeper takes the managed settings from there, every managed tier merged, where it knows one managed file a
// platform by itself.
const HANDED = 'p4_settings'
const SOURCES = ['user', 'project', 'local', 'policy'] as const

// The keys of a source the plugins' python reads whole. Of `env` it reads the P4_ variables, of `enabledPlugins`
// the p4 plugins, and of `permissions` the write block and the directories added to it.
const WHOLE = ['autoMemoryDirectory', 'plansDirectory', 'autoMemoryEnabled'] as const
const PERMISSIONS = ['blockWritesOutsideWorkingDirectories', 'additionalDirectories'] as const
const BOUND = 'bound-'
// How long a subagent's SubagentStart hooks are held for the `agent.spawn` that started it to answer, where they
// are raised first. Seen in the desktop app on Claude Code 2.1.326, the spawn answers first and nothing is held.
const SPAWN_WAIT_MS = 500
// The subagents kept in mind, at most: a session starts far fewer at a time.
const MOST_SPAWNED = 256

// The file that holds the origin of the session's latest prompt, with the prompt's id: rows.ORIGIN_FILE in python,
// where rows.origin_of reads it for a UserPromptSubmit hook whose input carries the same `prompt_id`.
const ORIGIN_FILE = 'origin.json'
// The prompts kept in mind for their origin, at most: one is in flight at a time, and a few arrive inside a turn.
const MOST_SUBMITTED = 16

// How long python may take over one call's check.
const CHECK_MS = 10_000
// The tools hook.py has a check for, as its PHI_CHECK and lookups.py read them. An edit is checked only for a
// session that owes a nudge or is a puppeteer, a shell call only where a filter below passes it, and the rest
// always: a web call, a message to another session, a session archiving itself and a session's start.
const EDIT_TOOLS = new Set(['Edit', 'Write', 'NotebookEdit'])
const SHELL_TOOLS = new Set(['Bash', 'PowerShell'])
const CHECKED_TOOLS = new Set([
  'WebFetch',
  'WebSearch',
  'SendMessage',
  'mcp__ccd_session_mgmt__send_message',
  'mcp__ccd_session_mgmt__archive_session',
  'mcp__ccd_session__start_session',
])
// The tools that send a message to another session, and how the desktop app's answer names a message that waits.
// The older tool's own text: "queued" means it is waiting behind that session's current work and runs when that
// finishes, and every result ends with "(delivery: ...; message_id: ...)". Seen in the desktop app on Claude Code
// 2.1.326: "Message queued for session ...: that session is holding it (a turn is in progress there, or its host
// or process is away) and runs it when that clears."
const SEND_TOOLS = new Set(['SendMessage', 'mcp__ccd_session_mgmt__send_message'])
const QUEUED = /\(delivery: queued\b/
// The desktop app's tool that ends another session's turn, by its own text "the same as the user pressing Stop
// there. The session stays open and idle afterwards; a message already queued in it runs next", and "Usually no
// prompt when the target is a session this session started". p4-phi calls it nowhere: it names it to a sender.
const APP_STOP = 'mcp__ccd_session_mgmt__stop_session'
// What a sender is told beside a queued answer, once for each such send. Seen on 2026-11-19 and again on
// 2026-11-22: a worker waited inside its turn for an answer, the answer sat queued behind that wait, and it ran
// only once the worker's starter stopped the turn.
// The line says what the stop costs too. plugins/mods/api.md, "Calls and background work after the user
// interrupts a turn": "calls that start new work in the session are refused until the user's next input, such as
// a message at the prompt", and "What refused calls return" gives `$.command.run` as rejected and
// `$.prompt.submit` as resolved with `{ drop }`, "and queues no prompt". Those are the two calls this module
// starts work with, setGoal and wake. Seen on 2026-11-22 in the desktop app on Claude Code 2.1.326: after a
// starter's stop, the starter's own message began a turn in the stopped session and the goal command of the look
// at that turn's end was refused still, "the session was stopped and nobody has sent input since".
const QUEUED_LINE =
  'phi (p4-phi): this message is queued and not read yet: it waits for that session\'s turn to end and begins ' +
  'its next turn then, so no answer comes sooner. Where that session waits only on this message, and this session ' +
  `started it, \`${APP_STOP}\` with its session id ends that turn and the queued message runs next. The stop ` +
  'has a cost in that session: until a person types there, Claude Code refuses what a plugin starts in it, so ' +
  'p4-phi sets no goal there and begins no turn of its own there, and no message from a session lifts that.'

// A shell call phi.py's branch guard reads: `git` as a word of the call's JSON text, where a newline, tab or
// return beside it is the escape \n, \t or \r, so `cd a && git push` and `cd repo\ngit push` count, a `.` or `-`
// after it counts, as in git.exe and git-lfs, and so does git after a path separator, as in /usr/bin/git and in
// quotes. A path that holds `github` or `.gitignore` does not.
const GIT_WORD = [
  /[^A-Za-z0-9_./\\-]git[^A-Za-z0-9_/\\]/,
  /\\[ntr]git[^A-Za-z0-9_/\\]/,
  /[^A-Za-z0-9_./\\-]git\\[ntr]/,
  /\\[ntr]git\\[ntr]/,
  /[^A-Za-z0-9_.-]git[.-]/,
  /\/git[\\ "';).]/,
  /\\git[\\ "';).]/,
]
// What may land work however git or gh is called, such as /usr/bin/git push, gh pr merge or a gh api ref update.
const LANDS = /push|merge|[^A-Za-z0-9_.-]gh[^A-Za-z0-9_-]|\\[ntr]gh[^A-Za-z0-9_-]/
// A command started in the background, which phi.py's restart check reads.
const IN_BACKGROUND = /"run_in_background":\s?true/
// `phi.py cards on`, which puts in force the set of what p4-phi settles with no approval card: phi.py's guard
// raises the one approval card the set has, so the yes is ezexe's own. Between the script's name and the word
// stand the closing quote, as the call's JSON text escapes it, and a space.
const CARDS_ON = /phi\.py[^A-Za-z0-9]+cards[^A-Za-z0-9]+on[^A-Za-z0-9]/
// Where a store keeps the failure model a plain shell call is checked by, newest layout first, and how long what
// its first line said is believed: a training round's new model is read within this long.
const SHELL_MODELS = ['phi/models', 'recall/models', 'models']
const MODEL_MS = 60_000
// The calls whose check left words for the model, at most, each until its PostToolUse hooks run.
const MOST_TOLD = 256

// The commands of phi.py a session calls as tools, each `mcp__p4-phi__<name>`: what the model reads of it, and the
// input it takes. `note` and `done` are in a session's tool list from its start, since every session is asked for
// both, and `tree` and `goal` wait behind ToolSearch as an MCP server's tool does. `goal` is the one that sets
// nothing by itself: phi.py keeps the condition, the next look answers it, and setGoal runs the command.
const TOOLS = [
  {
    name: 'note',
    description:
      'p4-phi: keep a finding for every session below this one, as `phi.py note` does. `claim` is the finding in a ' +
      'sentence. `source` is what showed it: the file and line, the command or the measurement. `kind` labels it ' +
      'with a free word, such as decision, waiting, parked, ruled-out, machine or code.',
    inputSchema: {
      type: 'object',
      properties: { claim: { type: 'string' }, source: { type: 'string' }, kind: { type: 'string' } },
      required: ['claim', 'source'],
    },
    isDeferred: false,
  },
  {
    name: 'done',
    description:
      'p4-phi: keep this turn as done, as `phi.py done` does. `text` says what was run and what it showed.',
    inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] },
    isDeferred: false,
  },
  {
    name: 'tree',
    description:
      'p4-phi: every session of this tree that is not archived, with its state, as `phi.py tree` prints it.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'goal',
    description:
      "p4-phi: ask for Claude Code's own goal for this session, as `phi.py goal ask` does. `condition` is what " +
      'holds when the work is done and what shows it in the conversation, in up to 4,000 characters. p4-phi sets ' +
      'it with the command `/goal` once the session is idle, in place of a goal already set, and from then on a ' +
      'model checks the condition after every turn and sends the session back until it holds.',
    inputSchema: { type: 'object', properties: { condition: { type: 'string' } }, required: ['condition'] },
  },
] as const
// How long one of those commands may run.
const TOOL_MS = 30_000
// The four as a call names them, and PLAN_TOOL below as its name stands, which the one glob hook that holds them is
// matched on: an array matches any of its names, by the API types of a matcher, and it is written out so that the
// validator reads each name.
const GLOB_TOOLS = ['mcp__p4-phi__note', 'mcp__p4-phi__done', 'mcp__p4-phi__tree', 'mcp__p4-phi__goal', 'EnterPlanMode']

// The tool the model of a session another session started is not offered, where python's answer to `rules` says so:
// the plan rule tells such a session to enter no plan mode, since no person answers a plan's approval there, and
// `tool.offer` keeps the tool out of what its model is given. By the types of `claude-code`, a hook of that event
// answers "whether the loop's model is offered the tool, in its tool list and at its call", and it comes "Before
// the loop's first request (or when the tool joins the pool later) and when the model calls the tool". The event is
// in the types from Claude Code 2.1.328 on. Seen in a scripted session on 2.1.328 and on 2.1.330, with a probe
// plugin that answered `{ isOffered: false }` for `Read` under a glob `tool.*`: the model replied that it has no
// such tool. On a build with no such event the glob is handed none, and the rule's sentence stands alone.
// `ExitPlanMode` is offered as before, so a plan made where ezexe typed `/plan` in such a session is still put to
// ezexe.
const PLAN_TOOL = 'EnterPlanMode'
// The first Claude Code whose API types declare `tool.run`: the types of 2.1.325 have none.
const RUNS_FROM = [2, 1, 326] as const

// The pane's id, which is its `ui.render` request id too, and its tab's label beside another plugin's pane.
const PANE = 'p4-phi'
const PANE_TITLE = 'p4-phi'
// The pages the pane shows, in its order, each a file python writes into the session's folder in the store:
// controls.board_path, asks.page_path and puppeteer.ledger_path. A session has the ones its part gives it: a
// puppeteer the first two, an orchestrator the last, a worker none.
const PAGES = [
  { name: 'board', file: 'board.md', title: 'Board' },
  { name: 'asks', file: 'asks.md', title: 'Requests of ezexe' },
  { name: 'ledger', file: 'ledger.md', title: 'Sessions' },
] as const
// The most of one page that is drawn: a surface draws 100,000 characters in one drawing, by the types of Markdown.
const PAGE_CHARS = 24_000
// The pages as the pane draws them, kept in `$.state`, where a write draws the open pane again. The tag declines
// what another version of this module stored, which outlives a reload.
const shown = atom({ plugin: 'p4-phi', key: 'pages' } as const, [], { shape: 'pages-1' })
// The session tree as the pane draws it, kept in `$.state` beside the pages: scripts/progress.py writes it into
// progress.json in the session's folder, and the module reads that file after each run of `phi.py progress`.
const grown = atom({ plugin: 'p4-phi', key: 'tree' } as const, [], { shape: 'tree-1' })
// How often the open pane checks the times of the files the tree was read from, how long one run of
// `phi.py progress` may take, and the most files checked. plugins/mods/interface.md, "Redraw on a timer", has a
// site that follows something no event tells redraw from `$.clock.every(1000, ...)`.
const PANE_MS = 1_000
const PROGRESS_MS = 10_000
const MOST_SOURCES = 400
// While no tree was read, as for a session whose folder is not made yet and after a reload of the module, the
// open pane asks for one again every so many ticks.
const EMPTY_TICKS = 10
// The app's tool for a session's task list, whose record hook.py's WAITED has the call wait on.
const STEP_TOOL = 'mcp__ccd_turn__update_plan'

// The desktop app's own tools for sessions, which a session of the app has and no other session does. Unless a
// store's phi.json turns `app_tools` off, the module asks them what phi.py otherwise reads from the app's record
// files, which no docs page describes, and keeps the answers in this file for python: phi.APP_FILE. `get_session`
// answers this session, and `list_sessions` the sessions linked to it, the archived ones too.
const APP_FILE = 'app.json'
const APP_SELF = 'mcp__ccd_session_mgmt__get_session'
const APP_LIST = 'mcp__ccd_session_mgmt__list_sessions'
// The app's tools for the sidebar, asked for a puppeteer, whose filing p4-phi otherwise reads from the app's
// `claude_desktop_config.json`: the sections with their ids, and where that answers nothing the custom groups,
// whose ids are the same.
const APP_SECTIONS = 'mcp__ccd_sidebar__list_sections'
const APP_GROUPS = 'mcp__ccd_sidebar__list_groups'
// The most sessions one answer lists, the least time between two rounds of calls, and how long one call is waited
// for. Python believes the file for phi.APP_FRESH_S, which is longer than the time between two rounds.
const APP_MOST = 100
const APP_MS = 60_000
const APP_CALL_MS = 5_000

// What `phi.py look` prints, as puppeteer.look answers it: the times are seconds. `starter` is the session that
// started this one, as the address `$.session.send` takes, and `move` the prompt that starts a turn here. `upkeep`
// is the prompt of a turn for the upkeep of the sessions this one started, answered only where a project turns
// `phi.upkeep` on, every one of those sessions is idle and python's count of such turns is inside its budget.
// `rules` is what `phi.py rules` prints alone: the text of the system prompt's section. `goal` is the condition of
// the native goal this session is to be given, answered once: the one the session asked for with the tool `goal`,
// or a worker's from its brief where a store's phi.json turns `goal` on.
// `app_tools` is true unless that file turns `app_tools` off: the app's own tools are asked after such a look.
// `app_sections` is true with it for a puppeteer: the sidebar's sections are asked for too.
type Answer = {
  // What `phi.py progress` prints: the file that holds the tree, and whether the run rewrote it.
  path?: string
  app_tools?: boolean
  app_sections?: boolean
  rules?: string
  withholds?: unknown
  dir?: string
  starter?: string
  move?: string
  upkeep?: string
  goal?: string
  watching?: boolean
  off?: boolean
  changed?: boolean
  net?: boolean
  watch_s?: number
  wait_s?: number
  net_s?: number
}

// The python that runs the plugin's scripts, searched for once. A reload of the module starts all of this over.
let finding: Promise<string | undefined> | undefined

// P4_PHI=0 turns the module's work off, and P4_PHI_WATCH=0 the watcher alone. Both are read once.
type Switches = { isPhiOff: boolean; isWatchOff: boolean }
let switches: Promise<Switches> | undefined

// The watcher.
let isOff = false
// A look is in flight: there is never a second one.
let isLooking = false
// An event asked for a look that has not started.
let isAsked = false
// The last look went over a subtree, so this session is an orchestrator.
let isWatching = false
// When the last look started, and the last slow one, in the milliseconds of `$.clock.now()`: never, at first.
let lookedAt = Number.NEGATIVE_INFINITY
let slowAt = Number.NEGATIVE_INFINITY
// The least time between two looks, which is `phi.watch_s`, how long the timer waits after a look, and how often a
// look is a slow one, each as the last look answered it.
let tickMs = 5_000
let waitMs = 5_000
let slowMs = 120_000
let timer: Timer | undefined

// The session's own folder in the store, as phi.py answers it, asked for once.
let folder: string | undefined
// The session that started this one, as phi.py answers it with the folder: never asked yet, or '' for none.
let starter: string | undefined
// The look in flight, and the question of the folder and the starter in flight.
let looking: Promise<Answer | undefined> | undefined
let asking: Promise<void> | undefined
// The main conversation is inside a turn, and that turn was begun by the notice Claude Code sends a session whose
// message to another session was held, refused or dropped.
let isInTurn = false
let isNoticeTurn = false
// How such a notice opens, as the SendMessage tool's own text names it: "a `[Cross-session delivery notice]` tells
// you when that happens". cross-session-messaging.md, "Control inbound messages": a session that bypasses
// permission prompts holds each message of one that does not, and the other way round, and past the deadline it
// "drops the message and reports it as expired to a sender it can reach".
const DELIVERY_NOTICE = /^\s*\[Cross-session delivery notice\]/
// Whether the main conversation's turn was begun by a prompt the person typed in this session, by the origin
// Claude Code stamped on it: the kinds rows.OWN_KINDS names in python, Enter in a terminal, a Remote Control
// client and a ping from Slack.
let isOwnTurn = false
const OWN_KINDS: ReadonlySet<string> = new Set(['composer', 'bridge', 'slack-ping'])
// Where an agent of the session's own stands while its work is not done, as AgentStatus names it in the types of
// `claude-code`: `pending` not started, `running` a turn, `waiting` held on its own background work, a plan's
// approval or an Agent call. A teammate that is `idle` waits for a message and has ended its turn.
const UNFINISHED: ReadonlySet<string> = new Set(['pending', 'running', 'waiting'])
// The condition of the goal command that has not answered yet: `$.command.run` queues the command until the session
// is idle, so the call can stay open through a whole turn.
let goalFlying: string | undefined
// The last report handed to `$.session.send` for the starter, as its whole text.
let reported: string | undefined
// The whole points of the usage last written to usage.json, and the writes, one after another.
let written: string | undefined
let writing: Promise<void> = Promise.resolve()

// The subagents whose start `agent.spawn` answered, each with the write of its binding, by the subagent's id, and
// what a SubagentStart raised ahead of that answer waits on.
const spawned = new Map<string, Promise<void>>()
const awaited = new Map<string, () => void>()

// The prompts `prompt.submit` was raised for, the newest last, each with the origin Claude Code stamped on it. The
// UserPromptSubmit command hooks of a prompt run inside that event's `next(e)`, so the prompt in flight is theirs.
type Submitted = { text: string; origin: PromptOrigin; isInFlight: boolean }
const submitted: Submitted[] = []

// What a check said beside a call that runs, by the call's id, until a PostToolUse hook hands it to the model.
const told = new Map<string, string>()

// The ids of the calls that failed and whose batch has not ended yet, heard at `classic.PostToolUseFailure`. The
// PostToolBatch command hook beneath writes the lookup row of every call of a batch that worked, and by hooks.md,
// "PostToolBatch input", a call of `tool_calls` carries its tool, its input, its id and its response and nothing
// that says whether it failed, so the module names the failed ones under FAILED in that hook's input. A failed
// call whose batch never ends, as one a stop cut short, would stay here, so the set is emptied past FAILED_MAX.
const failed = new Set<string>()
const FAILED = 'p4_failed'
const FAILED_MAX = 500
// Whether the store's failure model weighs shell calls, as its first line said when it was last read.
let shellModel: { at: number; isWeighted: boolean } | undefined

// The pane was opened by its command or drawn, so each look's end reads the pages anew, and what was last set in
// `$.state`, as JSON: the same pages write nothing, so they draw nothing.
let isPaneOpen = false
let paged: string | undefined
// The tree last set in `$.state`, as JSON, the files it was read from and the folders whose names are watched, and
// their times and sizes at the last run of `phi.py progress`. One run is in flight at most, one more is owed where
// a change came meanwhile, one check of the times is in flight at most, and the timer of those checks runs while
// the pane is open.
let treed: string | undefined
let sources: readonly string[] = []
let folders: readonly string[] = []
let stamp = ''
let isProgressing = false
let isProgressOwed = false
let isStamping = false
let emptyTicks = 0
let paneTimer: Timer | undefined
// The teammates last written to team.json, as its text: none written yet where this session has led no team.
const TEAM_FILE = 'team.json'
let teamed: string | undefined
// One read of the team is in flight at most, and one more is owed where an event came meanwhile.
let isTeaming = false
let isTeamOwed = false

// One line of the Progress view: a session's title, the step in progress, a plain or a dim line, or a count of a
// whole, which a surface with a `Progress` element draws as one and any other as `bar` draws it.
export type PhiLine =
  | { kind: 'title' | 'now' | 'text' | 'dim'; text: string; color?: string }
  | { kind: 'bar'; label: string; value: number; max: number; text: string }

// How a goal's state reads, and the colour of the states that ask for a look.
const GOAL_WORDS: Record<string, string> = { asked: 'asked for', set: 'set', met: 'met', failed: 'failed', cleared: 'cleared' }
const GOAL_COLORS: Record<string, string> = { asked: 'yellow', met: 'green', failed: 'red' }

// A count of a whole as ten characters, for a surface whose table holds no `Progress`.
export function bar(value: number, max: number): string {
  const full = max > 0 ? Math.min(10, Math.max(0, Math.round((value / max) * 10))) : 0

  return `[${'#'.repeat(full)}${'.'.repeat(10 - full)}]`
}

// The tree as lines, in its order: each session indented by its depth, then its goal, its steps and its plan.
export function treeLines(nodes: readonly PhiNode[]): PhiLine[] {
  const lines: PhiLine[] = []
  for (const one of nodes) {
    const pad = '  '.repeat(Math.min(Math.max(one.depth, 0), 6))
    const state = one.working ? 'working' : one.done ? 'idle, shown done' : 'idle'
    lines.push({ kind: 'title', text: `${pad}${one.title}: ${state}${one.apart === true ? ', a terminal session' : ''}` })
    if (one.goal !== null) {
      const word = GOAL_WORDS[one.goal.state] ?? one.goal.state
      const color = GOAL_COLORS[one.goal.state]
      lines.push({ kind: 'text', text: `${pad}goal ${word}: ${one.goal.condition}`, ...(color === undefined ? {} : { color }) })
      if (one.goal.reason) lines.push({ kind: 'dim', text: `${pad}  ${one.goal.reason}` })
    }
    if (one.steps.length > 0) {
      const done = one.steps.filter(step => step.status === 'completed').length
      lines.push({ kind: 'bar', label: `${pad}steps`, value: done, max: one.steps.length, text: `${done} of ${one.steps.length} steps` })
      for (const step of one.steps) {
        const mark = step.status === 'completed' ? 'x' : step.status === 'in_progress' ? '>' : ' '
        const agents = step.agents > 0 ? `, ${step.agents} ${step.agents === 1 ? 'agent' : 'agents'} running` : ''
        lines.push({ kind: step.status === 'in_progress' ? 'now' : 'text', text: `${pad}[${mark}] ${step.addr} ${step.content}${agents}` })
      }
    }
    for (const worker of one.workers ?? []) {
      const kind = worker.state === 'running' ? 'now' : 'text'
      lines.push({ kind, text: `${pad}terminal worker ${worker.name}, ${worker.state}: ${worker.task}` })
    }
    for (const mate of one.team ?? []) {
      const kind = mate.state === 'running' ? 'now' : 'text'
      lines.push({ kind, text: `${pad}teammate ${mate.name}, ${mate.state}: ${mate.task}` })
      if (mate.doing !== '') lines.push({ kind: 'dim', text: `${pad}  ${mate.doing}` })
    }
    if (one.plan !== null) {
      lines.push({ kind: 'text', text: `${pad}plan: ${one.plan.title}` })
      lines.push({ kind: 'dim', text: `${pad}  ${one.plan.path}` })
      const loop = one.plan.loop
      if (loop !== null) {
        const held = loop.state === 'clean' ? 'clean' : `${loop.held} held`
        const text = `round ${loop.round}, ${held}${loop.state === 'stopped' ? ', stopped' : ''}`
        // A loop that goes on has no last round to draw a bar against: a level count is followed by a next round.
        if (loop.ended) lines.push({ kind: 'bar', label: `${pad}loop`, value: loop.round, max: loop.of, text })
        else lines.push({ kind: 'text', text: `${pad}loop: ${text}` })
        if (loop.last !== '') lines.push({ kind: 'dim', text: `${pad}  last round: ${loop.last}` })
      }
      for (const section of one.plan.sections) {
        const kind = section.lands ? 'text' : 'dim'
        lines.push({ kind, text: `${pad}[${section.done ? 'x' : ' '}] ${section.head}` })
      }
    }
  }

  return lines
}

// The tree in one line, for the desktop app's widget.
export function treeGlance(nodes: readonly PhiNode[]): string {
  const steps = nodes.flatMap(one => one.steps)
  const done = steps.filter(step => step.status === 'completed').length
  const working = nodes.filter(one => one.working).length

  return `${nodes.length} ${nodes.length === 1 ? 'session' : 'sessions'}, ${working} working, ${done} of ${steps.length} steps`
}

// What a close of a pane leaves of that, given how it stood, and it is all the hook at `ui.close` does: a close of
// p4-phi's own pane leaves it closed, so a look reads its pages no more, and a close of any other pane leaves it
// as it was. By the
// types of `claude-code` every close raises `ui.close` with the pane's `id` and an `origin`: `person` for the
// person's close mark or close key, `plugin` for a plugin's `$.ui.close`, and `unload` for a pane nothing draws any
// more, "its plugin unloaded, or its drawing threw", at which "its opener's hooks do not run". p4-phi's drawing
// answers for its own faults, so its pane goes at `unload` only with the plugin itself, and a module that is told
// of an `unload` of its pane all the same leaves it closed too.
// Until p4-phi 0.11.130 a look asked `$.ui.panes` whether the pane was still there, once after each look.
// `claude plugin test` has no call that raises the event, and the module a test file imports is a second copy of
// the one the kit loads, so the function takes how the pane stood and a test calls it with the event's input.
// Seen in the desktop app on Claude Code 2.1.326, with a probe plugin: a person's click on a placed pane's own
// close mark raised `ui.close` with `{ id, origin: { kind: "person" } }` at a hook of the plugin, by name and by
// glob, and the pane was gone from `$.ui.panes` at the next turn. Seen in scripted sessions on 2.1.326, 2.1.328
// and 2.1.330 and in the desktop app, with the same probe: a `$.ui.close` asked for inside an event raised
// `ui.close` with `{ id, origin: { kind: "plugin" } }` at a hook of the plugin. A plugin's own `$.ui.close` asked
// for outside an event, as from a timer, closed the pane and reached no hook on 2.1.326, 2.1.328 and 2.1.330, and
// this module makes no such call, since it closes no pane.
export function paneAfterClose(isOpen: boolean, e: { id: string; origin?: { kind?: string } }): boolean {
  return e.id === PANE ? false : isOpen
}

// The app's own tools: one of them rejected or refused a call, so none is called again while the module lives.
// The calls not yet settled, since a call given up on can still be running, and when the last round began. The
// sidebar's tools are another server's, which a session can lack by itself.
let isAppAbsent = false
let isSidebarAbsent = false
// p4-native's capability map was asked whether the app's tools answer here, which is done once, before the first
// round of calls. Where the map has no entry for the session the first call's own answer tells, as before.
let isMapAsked = false
let appFlying = 0
let appAt = Number.NEGATIVE_INFINITY

// What was said to the debug log, each line once.
const said = new Set<string>()

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function slashed(path: string): string {
  return path.replaceAll('\\', '/').replace(/\/+$/, '')
}

function note($: EngineInterface, text: string): void {
  if (said.has(text)) return
  said.add(text)
  $.ui.log(text, { to: 'debug' })
}

// The variables that name the session and this plugin for a child, as a command hook of the session gets them. The
// API types say of `$.process.hookEnv`: "Returns the variables that name the session and this plugin, as its
// command hook gets them, to pass as a child's `env`", and list `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PROJECT_DIR`,
// `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA` among them. None on a Claude Code with no such method, as 2.1.311
// and 2.1.322 have none, and where the call rejects.
async function hookEnv($: EngineInterface): Promise<Record<string, string> | undefined> {
  try {
    const env: unknown = await $.process.hookEnv()
    const isWhole = isRecord(env) && typeof env.CLAUDE_PROJECT_DIR === 'string' && env.CLAUDE_PROJECT_DIR !== ''

    return isWhole ? (env as Record<string, string>) : undefined
  } catch {
    return undefined
  }
}

// What a python child of the module is started with: the engine's own variables, so a script the module runs and a
// command hook of the same session name one project and read one store. Until this the module built the two
// variables by hand from the session's root. Seen in the desktop app on Claude Code 2.1.326, in a session whose
// folder is a git worktree: its command hooks ran with `CLAUDE_PROJECT_DIR` at the main checkout's root, as
// worktrees.md, "What worktrees share with the main checkout", has it, so the module's scripts read and wrote the
// worktree's store while the hooks read the main checkout's. Where the engine gives none, the session's id and
// root as before.
async function childEnv($: EngineInterface): Promise<Record<string, string>> {
  const env = await hookEnv($)

  return env ?? { CLAUDE_CODE_SESSION_ID: await $.session.id(), CLAUDE_PROJECT_DIR: await $.session.root() }
}

// The project's folder as the session's command hooks have it, whose `.claude/p4` is the store python reads: every
// file the module keeps for python, and every marker of python's it reads, lies under it.
async function projectOf($: EngineInterface): Promise<string> {
  return slashed((await hookEnv($))?.CLAUDE_PROJECT_DIR ?? (await $.session.root()))
}

// The entries of an object whose name starts with `prefix`, or nothing where the value is no object.
function prefixed(value: unknown, prefix: string): Record<string, unknown> | undefined {
  if (!isRecord(value)) return undefined

  return Object.fromEntries(Object.entries(value).filter(([name]) => name.startsWith(prefix)))
}

// What of one source's settings is handed on: the keys the plugins' python reads and no other, since a source
// crosses with its `env` and its helper commands unfiltered. A `permissions` that is no object is handed as null,
// which python reads as a permissions object it cannot read. It is p4-temportal's own filter, so the two modules
// hand one shape.
function keptOf(settings: Settings): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const key of WHOLE) if (settings[key] !== undefined) out[key] = settings[key]
  const plugins = prefixed(settings.enabledPlugins, 'p4-')
  if (plugins !== undefined) out.enabledPlugins = plugins
  const env = prefixed(settings.env, 'P4_')
  if (env !== undefined) out.env = env
  const permissions: unknown = settings.permissions
  if (isRecord(permissions)) {
    const held = PERMISSIONS.filter(key => key in permissions)
    out.permissions = Object.fromEntries(held.map(key => [key, permissions[key]]))
  } else if (permissions !== undefined) {
    out.permissions = null
  }

  return out
}

// A SessionStart hook's input with the settings Claude Code loaded added under HANDED, each source read by
// `$.settings.read({ source })`, "one source's settings as loaded". The input goes down as it came where a module
// above this one handed them already, as p4-temportal's does, and where a read fails: a source left out would read
// as a source that holds nothing, and python then reads the settings files itself, as it does where no module
// loads.
async function withSettings<E>($: EngineInterface, e: E): Promise<E> {
  if (isRecord(e) && isRecord(e[HANDED])) return e
  try {
    const settings: Record<string, unknown> = {}
    for (const source of SOURCES) settings[source] = keptOf(await $.settings.read({ source }))

    return { ...e, [HANDED]: settings }
  } catch (error) {
    note($, `the settings were not read, so python reads the settings files: ${String(error)}`)

    return e
  }
}

// The folders that hold each plugin's data folder. The manifest reference puts `${CLAUDE_PLUGIN_DATA}` at
// `~/.claude/plugins/data/<id>/`, and the loading reference puts an installed plugin at
// `cache/<marketplace>/<plugin>/<version>/` under the same plugins root, which `CLAUDE_CODE_PLUGIN_CACHE_DIR` moves.
async function dataRoots($: EngineInterface): Promise<string[]> {
  const roots: string[] = []
  const installed = /^(.+)\/cache\/[^/]+\/[^/]+\/[^/]+$/.exec(slashed($.plugin.root))
  if (installed?.[1]) roots.push(`${installed[1]}/data`)
  const moved = await $.env.get('CLAUDE_CODE_PLUGIN_CACHE_DIR')
  if (moved) roots.push(`${slashed(moved)}/data`)
  const config = await $.env.get('CLAUDE_CONFIG_DIR')
  if (config) roots.push(`${slashed(config)}/plugins/data`)
  const home = (await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME'))
  if (home) roots.push(`${slashed(home)}/.claude/plugins/data`)
  return [...new Set(roots)]
}

// Where find-python.sh keeps the interpreter it proved: `.python` in the plugin's data folder, and in the plugin's
// own folder where a runner had no data folder. The data folder is the engine's to name: `CLAUDE_PLUGIN_DATA` of
// `$.process.hookEnv`, "this plugin's data folder, kept across updates". Where the engine gives none, the folders
// are searched: a data folder is named after the plugin's id, `<name>@<origin>` with `@` as `-`, and the module is
// told only the name, so each folder that starts with the name is read.
async function keptFiles($: EngineInterface): Promise<string[]> {
  const own = (await hookEnv($))?.CLAUDE_PLUGIN_DATA
  if (own) return [`${slashed(own)}/.python`, `${slashed($.plugin.root)}/.python`]
  const files: string[] = []
  const data = await $.env.get('CLAUDE_PLUGIN_DATA')
  if (data) files.push(`${slashed(data)}/.python`)
  for (const root of await dataRoots($)) {
    const entries = await $.fs.list(root).catch(() => [])
    for (const entry of entries) {
      const isOwn = entry.kind === 'dir' && entry.name.startsWith(`${$.plugin.name}-`)
      if (isOwn) files.push(`${root}/${entry.name}/.python`)
    }
  }
  files.push(`${slashed($.plugin.root)}/.python`)
  return files
}

// The interpreter a runner proved and kept, as find-python.sh reads it back: an absolute path that still exists.
async function keptPython($: EngineInterface): Promise<string | undefined> {
  for (const file of await keptFiles($)) {
    const text = await $.fs.read(file).catch(() => '')
    const path = (text.split('\n')[0] ?? '').trim()
    const isKept = path.includes('/') && (await $.fs.exists(path).catch(() => false))
    if (isKept) return path
  }
  return undefined
}

// This session's entry of p4-native's capability map, which that plugin's README gives as the one way to read what
// the host is: the file MAP in the project's store, with a session's entry under `sessions.<session id>`. None
// where p4-native is not installed, where the project has no store, where the map is no JSON, and where the entry
// is not written yet, since that plugin's start does not wait for it. Another session's entry is never read: one
// folder can be open in the desktop app and in a terminal, on Windows and under WSL.
//
// The map is read where p4-native keeps it: in the main checkout's store for a session in a git worktree, and in
// the session's own root where the main checkout holds no entry of this session, as where it has no store.
// `$.session.repo` gives the main checkout: its `root` is, by the API types, "The repository's root, absolute:
// the main working tree's for a worktree". A session in no repository reads its own root alone, as before.
async function mapped($: EngineInterface): Promise<Record<string, unknown> | undefined> {
  try {
    const id = await $.session.id()
    for (const root of await mapRoots($)) {
      const entry = entryOf(await $.fs.read(`${root}/${MAP}`).catch(() => ''), id)
      if (entry !== undefined) return entry
    }

    return undefined
  } catch {
    return undefined
  }
}

// The folders whose store may hold the map, in p4-native's own order: the main checkout's, then the session's root.
async function mapRoots($: EngineInterface): Promise<string[]> {
  const own = slashed(await $.session.root())
  let main: string | undefined
  try {
    main = slashed((await $.session.repo())?.root ?? '') || undefined
  } catch {
    main = undefined
  }

  return main === undefined || main === own ? [own] : [main, own]
}

// One session's entry of a map's text, or nothing where the text is no JSON or holds no such entry.
function entryOf(text: string, id: string): Record<string, unknown> | undefined {
  try {
    const map: unknown = JSON.parse(text)
    const sessions = isRecord(map) ? map.sessions : undefined
    const entry = isRecord(sessions) ? sessions[id] : undefined

    return isRecord(entry) ? entry : undefined
  } catch {
    return undefined
  }
}

// Whether this is Windows: the map's `platform` first, which p4-native asks of the engine by `$.session.info`,
// and the shape of the plugin's own folder where the map has no entry for this session or its entry says `unknown`.
async function onWindows($: EngineInterface): Promise<boolean> {
  const platform = (await mapped($))?.platform
  const isMapped = typeof platform === 'string' && platform !== '' && platform !== 'unknown'

  return isMapped ? platform === 'windows' : /^[A-Za-z]:[\\/]/.test($.plugin.root)
}

// Whether the map says that no tool of the desktop app answers in this session: its entry reads a host other than
// the desktop app and lists no such tool. An entry that reads `desktop` and lists none was read before the app's
// tool server had connected, which p4-native reads again at the first turn, so it decides nothing here.
async function isMappedOffTheApp($: EngineInterface): Promise<boolean> {
  const entry = await mapped($)
  const tools = isRecord(entry?.tools) ? entry.tools.app : undefined
  const host = entry?.host

  return typeof host === 'string' && host !== '' && host !== 'desktop' && Array.isArray(tools) && tools.length === 0
}

// With nothing kept, the search of find-python.sh: the launcher first on Windows, where `python3` can be the Store's
// stub, and `python3` first elsewhere. Each candidate is proven by one run, since a module has no `command -v`.
async function provenPython($: EngineInterface): Promise<string | undefined> {
  const isWindows = await onWindows($)
  const order = isWindows ? [['py', '-3'], ['python'], ['python3']] : [['python3'], ['python'], ['py', '-3']]
  for (const head of order) {
    try {
      const ran = await $.process.run([...head, '-I', '-c', PROOF], { timeoutMs: 10_000 })
      const path = ran.stdout.trim()
      if (ran.exitCode === 0 && path) return path
    } catch {
      // not on PATH: the next name
    }
  }
  return undefined
}

async function searchPython($: EngineInterface): Promise<string | undefined> {
  try {
    return (await keptPython($)) ?? (await provenPython($))
  } catch {
    return undefined
  }
}

// The python, searched for once while it is found. With none found, the next call searches again.
async function findPython($: EngineInterface): Promise<string | undefined> {
  finding ??= searchPython($)
  const python = await finding
  if (python === undefined) {
    finding = undefined
    note($, 'no working python found, so no look runs')
  }
  return python
}

// Runs one command of phi.py for this session, as a hook's runner runs it, and reads the one JSON line it prints.
// The session is told to phi.py as a command hook's environment tells it.
async function ask($: EngineInterface, args: readonly string[], timeoutMs: number): Promise<Answer | undefined> {
  const python = await findPython($)
  if (python === undefined) return undefined
  const script = `${slashed($.plugin.root)}/scripts/phi.py`
  const env = await childEnv($)
  let printed = ''
  try {
    const ran = await $.process.run([python, '-I', '-X', 'utf8', script, ...args], { env, timeoutMs })
    printed = ran.stdout.trim().split('\n').at(-1) ?? ''
  } catch (error) {
    finding = undefined
    note($, `phi.py ${args.join(' ')} did not run: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
    return undefined
  }
  try {
    const answer: unknown = JSON.parse(printed)
    return typeof answer === 'object' && answer !== null ? (answer as Answer) : undefined
  } catch {
    return undefined
  }
}

// What an answer says of the session itself. Only an answer that names the session's folder speaks of its starter.
function keep(answer: Answer | undefined): void {
  if (answer?.dir === undefined) return
  folder = answer.dir
  starter = answer.starter ?? ''
}

function milliseconds(seconds: number | undefined, otherwise: number): number {
  return typeof seconds === 'number' && seconds > 0 ? Math.max(50, Math.round(seconds * 1000)) : otherwise
}

// What a look answered, kept for the pace of the next ones. An orchestrator's timer waits as the look says, and
// one tick after an event's look, which can start before the command hooks of that event have written. A session
// with nothing to watch backs off: its wait doubles at each such answer.
function paceBy(answer: Answer | undefined, startedAt: number, wasSlow: boolean, wasAsked: boolean): void {
  if (answer?.off === true) {
    isOff = true
    isWatching = false
    return
  }
  const wasWatching = isWatching
  isWatching = answer?.watching === true
  tickMs = milliseconds(answer?.watch_s, tickMs)
  slowMs = milliseconds(answer?.net_s, slowMs)
  const told = milliseconds(answer?.wait_s, tickMs)
  if (isWatching) {
    if (wasSlow) slowAt = startedAt
    waitMs = wasAsked ? tickMs : told
  } else {
    waitMs = wasWatching ? told : Math.min(Math.max(waitMs * 2, told), Math.max(MOST_WAIT_MS, told))
  }
}

// The watcher's timer, set anew to fire `wait` milliseconds from this moment. No timer runs while a look does.
function arm($: EngineInterface, wait: number): void {
  timer?.cancel()
  timer = isOff
    ? undefined
    : $.clock.every(Math.max(1, Math.round(wait)), () => {
        void look($, false)
      })
}

// How long after a look's start the next one is due: one tick when an event asked for it, else the timer's wait.
function dueAfter(): number {
  return isAsked ? tickMs : Math.max(tickMs, waitMs)
}

async function readSwitches($: EngineInterface): Promise<Switches> {
  try {
    const isPhiOff = (await $.env.get('P4_PHI')) === '0'

    return { isPhiOff, isWatchOff: isPhiOff || (await $.env.get('P4_PHI_WATCH')) === '0' }
  } catch {
    return { isPhiOff: false, isWatchOff: false }
  }
}

// One run of `phi.py look`. What it says of the session is kept before anything that waited on the run goes on.
// While the goal command has not answered, python is told so and answers no condition.
async function ran($: EngineInterface, isSlow: boolean): Promise<Answer | undefined> {
  try {
    const args = ['look', ...(isSlow ? ['--net'] : []), ...(goalFlying === undefined ? [] : ['--goal-flying'])]
    const answer = await ask($, args, isSlow ? SLOW_LOOK_MS : LOOK_MS)
    keep(answer)

    return answer
  } catch (error) {
    note($, `the watcher's look failed: ${String((error as Error)?.message ?? error).slice(0, 200)}`)

    return undefined
  }
}

// One look, when one is due: never two in flight, and never two within the watcher's tick. A look asked for too
// early is taken by the timer when it is due.
async function look($: EngineInterface, isEvent: boolean): Promise<void> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isWatchOff) isOff = true
    if (isOff) return
    if (isEvent) isAsked = true
    const now = await $.clock.now()
    // The look in flight arms the timer at its end for what was asked meanwhile.
    if (isLooking) return
    const since = now - lookedAt
    if (since < dueAfter()) {
      arm($, dueAfter() - since)
      return
    }
    const wasAsked = isAsked
    const isSlow = now - slowAt >= slowMs
    isLooking = true
    isAsked = false
    lookedAt = now
    timer?.cancel()
    timer = undefined
    looking = ran($, isSlow)
    const answer = await looking
    isLooking = false
    looking = undefined
    paceBy(answer, now, isSlow, wasAsked)
    if (isPaneOpen) {
      void page($)
      watchPane($)
    }
    // One turn at most for one look: a goal to set first, whose command starts its own turn, then the work a wait
    // left unmoved, else the upkeep that is due.
    const prompt = answer?.move || answer?.upkeep
    if (answer?.goal) setGoal($, answer.goal)
    else if (prompt) wake($, prompt)
    // The app's own tools are asked after a look that starts no turn, unless the store turns them off.
    if (answer?.app_tools === true && !answer.goal && !prompt) void askApp($, answer.app_sections === true)
    arm($, dueAfter() - ((await $.clock.now()) - now))
  } catch (error) {
    note($, `the watcher's timer failed: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// The whole points of a session's usage. A figure that moves inside one point changes nothing here, so it writes
// nothing: the context's percent is whole as Claude Code gives it, and a window's percent used has one decimal.
function points(context: SessionContextUsage, limits: readonly SessionRateLimit[]): string {
  const windows = limits.map(limit => `${limit.kind}:${Math.floor(limit.percentUsed)}:${limit.resetsAt ?? ''}`)

  return [context.window, context.percent ?? '', ...windows.sort()].join('|')
}

// Asks python where the session's folder is and who started it. A look in flight answers both, so it is waited
// for, and there is never a second such question in flight.
async function learn($: EngineInterface): Promise<void> {
  if (looking !== undefined) await looking
  if (folder !== undefined) return
  asking ??= ask($, ['look', '--folder'], LOOK_MS)
    .then(keep, () => undefined)
    .finally(() => {
      asking = undefined
    })
  await asking
}

// The session's folder in the store. Python is asked where it is, once, and again while the session has none.
async function folderOf($: EngineInterface): Promise<string | undefined> {
  if (folder === undefined) await learn($)

  return folder
}

// The session that started this one. Python answers it with the folder, so it is asked once, and again while the
// session has no folder.
async function starterOf($: EngineInterface): Promise<string | undefined> {
  if (starter === undefined) await learn($)

  return starter
}

// A turn's report as its starter reads it. The first line is all a person sees of a message until they open it.
function reportText(answer: string, reason: TurnCompleteReason): string {
  const said = answer.trim()
  if (said === '') return `phi (p4-phi): this session ended a turn with no report: the turn's end was ${reason}.`
  const cut = said.length > REPORT_CHARS ? `${said.slice(0, REPORT_CHARS)} ...` : said

  return `phi (p4-phi): this session ended a turn. Its report follows, and needs no reply.\n\n${cut}`
}

// Whether an agent of the session's own, a subagent or a teammate, has work that is not done, by `$.agent.list()`.
// A Claude Code with no `$.agent.list`, or a list that fails, has nothing running, so the turn reports as before.
async function isRunningOwn($: EngineInterface): Promise<boolean> {
  try {
    const agents = await $.agent.list()

    return agents.some(one => UNFINISHED.has(String(one.status)))
  } catch {
    return false
  }
}

// At the end of a turn of a session another session started: its report goes to that session, where a message
// starts a turn when the session is idle. The desktop app sends the starter its own note of each turn's end of a
// session it started, so a report goes only where the turn's end is worth a turn of the starter.
// A turn that ends while a subagent or a teammate of the session's own has work that is not done sends none: it is
// an interim turn, and the turn that follows that agent's report speaks. A planner that waited on its subagents
// ended a dozen turns saying it still waited, and each one started a turn of its starter twice.
// A turn begun by a prompt the person typed in this session sends none: a session the person talks to is theirs to
// follow, and it tells its starter what it wants told with its own SendMessage. A side chat the person forked and
// typed in sent every one of its answers to the session it was forked from.
// Every other turn sends its report: one begun by its brief, by another session's message, by a background event or
// by a plugin's prompt, with nothing of its own running. That keeps a turn that is done, blocked, asks, finds or
// hands over.
// A turn the person stopped is theirs to speak of. A starter that runs under a new id since a clear or a resume is
// asked of python once more. A turn begun by a delivery notice sends none: seen in the desktop app on Claude Code
// 2.1.326, a worker in auto mode whose starter bypassed permission prompts had each report held there, the notice
// of each started a turn of the worker, and that turn's report was held in its turn, 44 times in five minutes,
// until the worker was detached.
async function report(
  $: EngineInterface,
  answer: string,
  reason: TurnCompleteReason,
  isNotice: boolean,
  isOwn: boolean,
): Promise<void> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff || reason === 'aborted' || isNotice || isOwn) return
    if (await isRunningOwn($)) return
    const to = await starterOf($)
    if (!to) return
    const text = reportText(answer, reason)
    // A report that repeats the one before it is not sent. Seen in the desktop app on Claude Code 2.1.326: the
    // receiver's inbox dropped such a message, "it repeated your previous message", and the app's notice of that
    // started a turn of the worker, whose own report then went to the starter.
    if (text === reported) return
    reported = text
    let sent = await $.session.send({ to: { sessionId: to }, text })
    if (!sent.isDelivered) {
      keep(await ask($, ['look', '--folder'], LOOK_MS))
      if (starter && starter !== to) sent = await $.session.send({ to: { sessionId: starter }, text })
    }
    if (!sent.isDelivered) note($, `the turn's report did not reach the starter: ${sent.reason.slice(0, 200)}`)
  } catch (error) {
    note($, `the turn's report was not sent: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// Starts a turn of the session's own with what a look answered. A turn that began since is left alone, and its own
// end is looked at. The call resolves when the turn has started, so nothing waits on it.
// After a stop the prompt is refused as the goal command is, until a person types in the session: the API types of
// Claude Code 2.1.326 give `{ drop }` of PromptSubmitResult as "the engine's own (a Stop stands, a host's limit
// reached)", and plugins/mods/api.md, "What refused calls return", says the call "Resolves with `{ drop:
// '<reason>' }` and queues no prompt". Python answered that prompt once for the turn that ended, so that turn's
// move is not made, and it answers anew for the next turn that ends on a wait. Not seen in a session.
function wake($: EngineInterface, text: string): void {
  if (isInTurn) return
  $.prompt.submit({ text }).then(
    entered => {
      if (entered.drop !== undefined) note($, `the wake did not start a turn: ${entered.drop.slice(0, 200)}`)
    },
    error => note($, `the wake was not submitted: ${String((error as Error)?.message ?? error).slice(0, 200)}`),
  )
}

// Gives the session Claude Code's own goal, with the condition a look answered: the command a person types, `/goal
// <condition>`, which `$.command.run` queues until the session is idle and which starts a turn with the condition
// as its directive. Seen in the desktop app on Claude Code 2.1.326, in a session another session started: the goal
// was set with no dialog, where `SetGoal` is no tool of the session. Python is told once the command answered that
// the goal is set, and from then on its Stop hook sends no turn back. Nothing waits on the call. The condition is
// a worker's from its brief, or the one a session asked for itself with the tool `goal`, a session nobody started
// too: the ask is made inside a turn, and the look at that turn's end answers it.
// The call can stay open a long while and can fail. The API types of Claude Code 2.1.326 say of `$.command.run`:
// "queued and run once the session is idle", and "Rejects an unknown name, inside a hook the turn or the session's
// start waits on, past a Stop or a host's limit". plugins/mods/api.md, "Work your mod started before the
// interruption": a command still in the queue when a turn is stopped is "Dropped. The call rejects with an error
// whose message includes `the command was removed from the queue before it ran`", and "Calls stay refused until
// the user's next input, and nothing queues or repeats them for you". Seen on 2026-11-19: a command waited four
// minutes behind a turn a queued message had begun and then set the goal, and one in the queue at a stop_session
// was never run. So while the call is open each look is told so and python answers no condition, there is never a
// second command beside it, and a call that rejects or answers other than `Goal set` is told to python with what
// it said, which answers the condition again to the look after a later turn's end, three looks in all. A command
// a stop took counts as none of the three: python reads the stop in what the call said, and where the call was
// refused it answers the condition again only at the end of a turn a person's own words began.
function setGoal($: EngineInterface, condition: string): void {
  if (goalFlying !== undefined) return
  goalFlying = condition
  const failed = (why: string): void => {
    goalFlying = undefined
    note($, `the goal command did not set the goal: ${why.slice(0, 200)}`)
    void ask($, ['goal', 'failed', '--', why.slice(0, 300)], LOOK_MS)
  }
  try {
    $.command.run({ command: 'goal', args: condition }).then(
      ran => {
        const answered = (ran.text ?? '').trim()
        if (!answered.startsWith('Goal set')) return failed(answered === '' ? 'the command printed nothing' : answered)
        goalFlying = undefined
        void ask($, ['goal', 'set'], LOOK_MS)
      },
      error => failed(String((error as Error)?.message ?? error)),
    )
  } catch (error) {
    failed(String((error as Error)?.message ?? error))
  }
}

// Writes the figures to usage.json in the session's folder when one of them moved a whole point. `$.fs.write` makes
// the folders of the file it writes, so a session folder that was deleted is left alone, and asked for again.
async function writeUsage(
  $: EngineInterface,
  context: SessionContextUsage,
  limits: readonly SessionRateLimit[],
): Promise<void> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff) return
    const moved = points(context, limits)
    if (moved === written) return
    const dir = await folderOf($)
    if (dir === undefined) return
    if (!(await $.fs.exists(`${dir}/session.json`))) {
      folder = undefined

      return
    }
    const record = {
      at: await $.clock.now(),
      context: { tokens: context.tokens, window: context.window, percent: context.percent },
      rateLimits: limits.map(limit => ({
        kind: limit.kind,
        percentUsed: limit.percentUsed,
        resetsAt: limit.resetsAt,
      })),
    }
    await $.fs.write(`${dir}/usage.json`, `${JSON.stringify(record)}\n`)
    written = moved
  } catch (error) {
    note($, `usage.json was not written: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

function record($: EngineInterface, context: SessionContextUsage, limits: readonly SessionRateLimit[]): void {
  writing = writing.then(() => writeUsage($, context, limits))
}

// The system prompt as composed beneath, with the rules built into p4-phi as its last section, on the session's
// side of the cache boundary since a project's settings choose the rules. Python holds the rules' words and reads
// the settings that turn one off, so it is asked for the text at each render: a system prompt is rendered for a
// conversation's first request and after a compaction, not at every turn. With no text, as where a setting turns
// the rules off or no python runs, the prompt is left as composed.
// What python last answered to `rules`, asked once at a time: the render of a system prompt and an offer of
// PLAN_TOOL that come together start one process, and a later render asks anew, since a setting may have changed.
let rulesAsked: Promise<Answer | undefined> | undefined
let withheld: readonly string[] | undefined

function askRules($: EngineInterface): Promise<Answer | undefined> {
  rulesAsked ??= ask($, ['rules'], LOOK_MS)
    .then(answer => {
      const named: unknown = answer?.withholds
      withheld = Array.isArray(named) ? named.filter((tool): tool is string => typeof tool === 'string') : []

      return answer
    })
    .finally(() => {
      rulesAsked = undefined
    })

  return rulesAsked
}

// Whether this session's model is not offered a tool, by python's last answer, asked for where none came yet. With
// p4-phi off, or with no answer, every tool is offered.
async function isWithheld($: EngineInterface, tool: string): Promise<boolean> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff) return false
    if (withheld === undefined) await askRules($)

    return (withheld ?? []).includes(tool)
  } catch {
    return false
  }
}

async function withRules($: EngineInterface, composed: PromptComposeResult): Promise<PromptComposeResult> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff) return composed
    const text = ((await askRules($))?.rules ?? '').trim()
    if (text === '') return composed
    const others = composed.sections.filter(section => section.id !== RULES_SECTION)

    return { sections: [...others, { id: RULES_SECTION, text, scope: 'session' }] }
  } catch (error) {
    note($, `the rules were not set in the system prompt: ${String((error as Error)?.message ?? error).slice(0, 200)}`)

    return composed
  }
}

// The origin of the prompt a UserPromptSubmit event carries: that of the prompt in flight with the same text, else
// of the one prompt in flight, else of the newest prompt kept with that text.
function originOf(prompt: string): PromptOrigin | undefined {
  const flying = submitted.filter(kept => kept.isInFlight)
  const sameText = (kept: Submitted): boolean => kept.text === prompt
  const found =
    flying.filter(sameText).at(-1) ?? (flying.length === 1 ? flying[0] : undefined) ?? submitted.filter(sameText).at(-1)

  return found?.origin
}

// Where a prompt's origin is kept for the command hooks: in the session's folder under the store's served folder,
// rows.origin_dir in python, for a project that has a store, and in the session's folder in the tree's store for
// one that has none, where phi.py alone reads it. No prompt waits for python to say where that folder is: until a
// look has answered it, a project with no store keeps no origin, and the hooks read the prompt's text as before.
async function originFile($: EngineInterface, sessionId: string): Promise<string | undefined> {
  const models = `${await projectOf($)}/${MODELS}`
  if (await $.fs.exists(models)) return `${models}/served/start-${named(sessionId)}/${ORIGIN_FILE}`
  switches ??= readSwitches($)
  if ((await switches).isPhiOff || folder === undefined) return undefined

  return `${folder}/${ORIGIN_FILE}`
}

// Writes the origin of a prompt for its UserPromptSubmit command hooks, which run beneath: the kind, and what else
// the kind carries, with the prompt's id, which the hooks' input holds too. A prompt with no id, or one no
// `prompt.submit` was raised for, keeps none, and a hook then finds no record of its prompt's id.
async function keepOrigin($: EngineInterface, prompt: string, promptId: string | undefined, sessionId: string): Promise<void> {
  try {
    const origin = originOf(prompt)
    if (!promptId || origin === undefined) return
    const file = await originFile($, sessionId)
    if (file === undefined) return
    await $.fs.write(file, `${JSON.stringify({ promptId, ...origin })}\n`)
  } catch (error) {
    note($, `a prompt's origin was not kept: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// A session's or a subagent's id as phi.py writes it into a marker's name: phi.SAFE, cut to 80 characters.
function safe(id: string): string {
  return id.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 80)
}

// Whether phi.py left a marker of this name in a folder of the project's store.
async function isMarked($: EngineInterface, folder: string, id: string): Promise<boolean> {
  return id !== '' && (await $.fs.exists(`${folder}/${safe(id)}`).catch(() => false))
}

// Whether the store has a failure model that weighs shell calls: a store has one only once a training round passed
// it, and one whose first line holds no shell weight checks nothing.
async function weighsShell($: EngineInterface, root: string): Promise<boolean> {
  const now = await $.clock.now()
  if (shellModel !== undefined && now - shellModel.at < MODEL_MS) return shellModel.isWeighted
  let isWeighted = false
  for (const models of SHELL_MODELS) {
    const file = `${root}/.claude/p4/${models}/lookups-model.json`
    if (!(await $.fs.exists(file).catch(() => false))) continue
    const first = (await $.fs.read(file).catch(() => '')).split('\n')[0] ?? ''
    isWeighted = !first.includes('"shell":{"w":{}')
    break
  }
  shellModel = { at: now, isWeighted }

  return isWeighted
}

// Whether python has a check for a call, by tests that start no process. A
// subagent phi.py marked open is checked at each call, for phi.py's word of what changed since its launch. `text`
// is the call's tool and input as JSON, which the shell filters read.
async function isChecked(
  $: EngineInterface,
  e: ToolCheckInput,
  root: string,
  sessionId: string,
  text: string,
): Promise<boolean> {
  const tool = String(e.tool)
  const isEdit = EDIT_TOOLS.has(tool)
  const isShell = SHELL_TOOLS.has(tool)
  const isListed = isEdit || isShell || CHECKED_TOOLS.has(tool)
  if (!isListed && e.agentId === undefined) return false
  const phi = `${root}/.claude/p4/phi`
  if (e.agentId !== undefined && (await isMarked($, `${phi}/.agents`, e.agentId))) return true
  if (!isListed) return false
  if (!isEdit && !isShell) return true
  if (isShell && (GIT_WORD.some(word => word.test(text)) || LANDS.test(text) || IN_BACKGROUND.test(text))) return true
  if (isShell && CARDS_ON.test(text)) return true
  // A top-level session that owes a nudge, and a puppeteer, whose every edit and shell call phi.py reads.
  if ((await isMarked($, `${phi}/.nudge`, sessionId)) || (await isMarked($, `${phi}/.puppeteers`, sessionId))) return true

  return isShell && (await weighsShell($, root))
}

// What python said of a call: a refusal, a question for the person, and words for the model beside the result.
type Said = { deny?: string; ask?: string; context?: string }

// What hook.py printed, read as a PreToolUse command hook's output is.
function saidBy($: EngineInterface, printed: string): Said {
  let out: unknown
  try {
    out = JSON.parse(printed.trim() || 'null')
  } catch {
    return {}
  }
  if (typeof out !== 'object' || out === null) return {}
  const { hookSpecificOutput: specific, systemMessage } = out as Record<string, unknown>
  if (typeof systemMessage === 'string' && systemMessage !== '') note($, systemMessage.slice(0, 300))
  const { permissionDecision: decision, permissionDecisionReason: reason, additionalContext: context } = (
    typeof specific === 'object' && specific !== null ? specific : {}
  ) as Record<string, unknown>
  const why = typeof reason === 'string' ? reason : ''

  return {
    deny: decision === 'deny' ? why : undefined,
    ask: decision === 'ask' ? why : undefined,
    context: typeof context === 'string' && context !== '' ? context : undefined,
  }
}

// The main conversation's transcript file, which a PreToolUse command hook's input holds as `transcript_path`, or
// '' where the build has no `$.session.info`, as 2.1.311 and 2.1.322 have none: a call of a method a build lacks
// throws where it is made, and a check that throws would judge no call there. Python then reads no transcript.
async function transcriptOf($: EngineInterface): Promise<string> {
  try {
    return (await $.session.info()).transcriptPath ?? ''
  } catch {
    return ''
  }
}

// One call's check: `hook.py lookup-check`, run only for a call python has a check for, with the input a
// PreToolUse command hook is given on stdin. Retrieval's check does not obey P4_PHI=0, and phi.py's own checks
// read the switch themselves. Whatever fails here, the call goes on unjudged. Python's markers are read in the
// project's store, as the command hooks have the project, and the input's `cwd` is the session's own folder, which
// in a worktree session is the worktree: worktrees.md, "To reach the files Claude is working on, read the
// worktree's path from the hook's `cwd` input field."
async function check($: EngineInterface, e: ToolCheckInput): Promise<Said> {
  try {
    const project = await projectOf($)
    const sessionId = await $.session.id()
    const call = { tool_name: String(e.tool), tool_input: e.input }
    if (!(await isChecked($, e, project, sessionId, JSON.stringify(call)))) return {}
    const python = await findPython($)
    if (python === undefined) return {}
    const plugin = slashed($.plugin.root)
    const payload = {
      session_id: sessionId,
      transcript_path: await transcriptOf($),
      cwd: slashed(await $.session.root()),
      hook_event_name: 'PreToolUse',
      ...call,
      tool_use_id: e.tool_use_id,
      ...(e.agentId === undefined ? {} : { agent_id: e.agentId }),
    }
    const env = { CLAUDE_PLUGIN_ROOT: plugin, ...(await childEnv($)) }
    const argv = [python, '-I', '-X', 'utf8', `${plugin}/scripts/hook.py`, 'lookup-check']
    const ran = await $.process.run(argv, { env, stdin: JSON.stringify(payload), timeoutMs: CHECK_MS })

    return saidBy($, ran.stdout)
  } catch (error) {
    note($, `a tool call was not checked: ${String((error as Error)?.message ?? error).slice(0, 200)}`)

    return {}
  }
}

// The verdict on a call the engine is about to run, with python's check laid over the engine's own. A refusal is
// the call's error and a question goes to the person. Words for the model wait for the call's PostToolUse hooks,
// since a verdict carries none, and go into the reason of a refusal, which has no such hooks. A question a plugin
// asks of a call nobody made carries no call id and is passed on, and so is a call the engine refused already.
async function judged($: EngineInterface, e: ToolCheckInput, verdict: ToolCheckResult): Promise<ToolCheckResult> {
  if (!e.tool_use_id || verdict.decision === 'deny') return verdict
  const said = await check($, e)
  if (said.deny !== undefined) {
    return { decision: 'deny', reason: [said.deny, said.context].filter(Boolean).join('\n\n') }
  }
  if (said.context !== undefined) {
    told.set(e.tool_use_id, said.context)
    for (const oldest of told.keys()) {
      if (told.size <= MOST_TOLD) break
      told.delete(oldest)
    }
  }

  return said.ask === undefined ? verdict : { decision: 'ask', reason: said.ask }
}

// What a check said beside a call, taken once the call has run or failed.
function toldOf(toolUseId: string): string[] {
  const words = told.get(toolUseId)
  told.delete(toolUseId)

  return words === undefined ? [] : [words]
}

// What a sender is told of a message that was queued: the line, where the call is one of the send tools and its
// answer says the message waits. No process starts for it, and a session with P4_PHI=0 is told nothing.
async function queued($: EngineInterface, tool: unknown, response: unknown): Promise<string[]> {
  try {
    if (!SEND_TOOLS.has(String(tool))) return []
    const answer = typeof response === 'string' ? response : (JSON.stringify(response) ?? '')
    if (!QUEUED.test(answer)) return []
    switches ??= readSwitches($)

    return (await switches).isPhiOff ? [] : [QUEUED_LINE]
  } catch {
    return []
  }
}

// Whether this Claude Code raises `tool.run`, by the release its version is built from. A version that cannot be
// read or is spelled as no release counts as one that does, which every build since 2.1.326 is.
async function hasRun($: EngineInterface): Promise<boolean> {
  try {
    const { base, version } = await $.session.version()
    const parts = /^(\d+)\.(\d+)\.(\d+)/.exec(base ?? version)
    if (parts === null) return true
    for (const [at, least] of RUNS_FROM.entries()) {
      const part = Number(parts[at + 1])
      if (part !== least) return part > least
    }

    return true
  } catch {
    return true
  }
}

// Declares the pane's command and the four tools, at a session's start and at each reload of the module. A session
// with P4_PHI=0 gets none, since phi.py keeps nothing for it. Each is declared whatever became of the other. The
// tools are left out on a Claude Code with no `tool.run`, 2.1.311 and 2.1.322 among them, where nothing was seen to
// serve one once its call is allowed: a session there keeps a finding by the shell line `phi.py note`, as before
// the tools.
async function offer($: EngineInterface): Promise<void> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff) return
  } catch {
    return
  }
  try {
    await $.command.register({
      name: 'phi-pane',
      description: "p4-phi: this session's board, its ledger of requests and its ledger of sessions, in a pane",
    })
  } catch (error) {
    note($, `/phi-pane was not declared: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
  if (!(await hasRun($))) {
    note($, "p4-phi's tools are not declared: this Claude Code has no `tool.run` event to serve them at")

    return
  }
  try {
    for (const tool of TOOLS) await $.tool.register(tool)
  } catch (error) {
    note($, `p4-phi's tools were not declared: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// One text field of a tool call's input, trimmed, and '' for one left out.
function field(e: unknown, name: string): string {
  const value = (e as Record<string, unknown>)[name]

  return typeof value === 'string' ? value.trim() : ''
}

// What Claude Code answers a call of a registered tool that came to its run and found no hook to serve it, as
// 2.1.326 to 2.1.330 word it: "p4-phi registered the tool note but no hook answered this call: add on("tool.run",
// ...) to the plugin." It is an error of the call that names one of the plugin's own tools.
const UNSERVED = /registered the tool (?:note|done|tree|goal) but no hook answered this call/

// Whether what came back up to `tool.call` is that answer: an error of the call, or a refusal, with those words.
function isUnserved(out: unknown): boolean {
  if (!isRecord(out) || !(out.isError === true || typeof out.deny === 'string')) return false

  return [out.deny, out.text, out.result].some(said => typeof said === 'string' && UNSERVED.test(said))
}

// One call of a tool of the plugin's own, as the command of phi.py it stands for. `goal` is the session's own ask
// for a goal: python keeps the condition and the look at this turn's end answers it, so the goal is set by the
// same call as a worker's, once the session is idle.
function ownTool($: EngineInterface, e: unknown): Promise<ToolCallResult> {
  const tool = isRecord(e) ? String(e.tool) : ''
  if (tool === 'mcp__p4-phi__note') {
    const options = [
      ...(field(e, 'source') ? ['--source', field(e, 'source')] : []),
      ...(field(e, 'kind') ? ['--kind', field(e, 'kind')] : []),
    ]

    return served($, ['note', ...options, '--', field(e, 'claim')])
  }
  if (tool === 'mcp__p4-phi__done') return served($, ['done', '--', field(e, 'text')])
  if (tool === 'mcp__p4-phi__tree') return served($, ['tree'])
  if (tool === 'mcp__p4-phi__goal') return served($, ['goal', 'ask', '--', field(e, 'condition')])

  return Promise.resolve({ deny: `p4-phi has no tool named ${tool}.` })
}

// Runs one command of phi.py for a tool call, for this session, in the session's working folder as a shell line
// ran it. What it prints is the tool's result, and what it says on a failure is the call's error. The words of
// the call come after `--`, so a finding that opens with a dash is no option.
async function served($: EngineInterface, args: readonly string[]): Promise<ToolCallResult> {
  try {
    const python = await findPython($)
    if (python === undefined) return { deny: 'p4-phi found no working python to run phi.py with.' }
    const script = `${slashed($.plugin.root)}/scripts/phi.py`
    const env = await childEnv($)
    const ran = await $.process.run([python, '-I', '-X', 'utf8', script, ...args], { env, timeoutMs: TOOL_MS })
    if (ran.exitCode !== 0) return { deny: (ran.stderr.trim() || ran.stdout.trim() || 'phi.py failed').slice(0, 4_000) }

    return { result: ran.stdout.trim() }
  } catch (error) {
    return { deny: `phi.py did not run: ${String((error as Error)?.message ?? error).slice(0, 200)}` }
  }
}

// The pages of the session's folder as they stand, put where the pane reads them. The files are read with no
// process: python wrote them at the look or at the hook before it. A page that is missing or empty is left out.
async function page($: EngineInterface): Promise<void> {
  try {
    const dir = await folderOf($)
    const pages: PhiPage[] = []
    for (const { name, file, title } of dir === undefined ? [] : PAGES) {
      const path = `${dir}/${file}`
      const text = (await $.fs.read(path).catch(() => '')).trim()
      const cut = text.length > PAGE_CHARS ? `${text.slice(0, PAGE_CHARS)}\n\n... the rest is in ${path}` : text
      if (text !== '') pages.push({ name, title, path, text: cut })
    }
    const now = JSON.stringify(pages)
    if (now === paged) return
    await update($, shown, () => pages)
    paged = now
  } catch (error) {
    note($, `the pane's pages were not read: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// The teammates of the agent team this session leads, as `$.agent.list()` answers them, kept in team.json in the
// session's folder for scripts/progress.py: each one's name, the task its lead gave it, its state and what it is
// doing. A session with no teammate writes nothing, and `isOver` writes an empty list at the session's end.
async function team($: EngineInterface, isOver = false): Promise<void> {
  if (isTeaming && !isOver) {
    isTeamOwed = true

    return
  }
  isTeaming = true
  try {
    const agents = isOver ? [] : await $.agent.list()
    const mates = agents
      .filter(one => one.kind === 'in_process_teammate' || one.teammateId !== undefined)
      .map(one => ({
        name: one.name ?? one.id,
        task: one.description,
        state: String(one.status),
        doing: one.label === one.description ? '' : one.label.slice(0, 200),
      }))
    const now = `${JSON.stringify({ teammates: mates })}\n`
    if (now === teamed || (teamed === undefined && mates.length === 0)) return
    const dir = await folderOf($)
    if (dir === undefined) return
    await $.fs.write(`${dir}/${TEAM_FILE}`, now)
    teamed = now
  } catch {
    // a Claude Code with no `$.agent.list`, or a folder that cannot be written: no team is shown
  } finally {
    isTeaming = false
    if (isTeamOwed && !isOver) {
      isTeamOwed = false
      void team($)
    }
  }
}

// The time and size of each file the tree was read from, and the names in each watched folder, as one string. A
// file's time is read from its folder's list, one call a folder, and a folder that cannot be listed reads as empty.
async function stamped($: EngineInterface): Promise<string> {
  const files = sources.slice(0, MOST_SOURCES)
  const dirs = [...new Set(files.map(path => path.slice(0, path.lastIndexOf('/'))))]
  const lists = new Map<string, Map<string, string>>()
  await Promise.all(
    [...new Set([...dirs, ...folders])].map(async dir => {
      // plugins/mods/api.md gives an entry `{ name, kind, size, isLink }`, and the types of 2.1.326 `mtimeMs` too
      const entries: readonly { name: string; size: number; mtimeMs?: number }[] = await $.fs.list(dir).catch(() => [])
      const seen = new Map<string, string>()
      for (const entry of entries) seen.set(entry.name, `${String(entry.mtimeMs ?? '')}:${entry.size}`)
      lists.set(dir, seen)
    }),
  )
  const times = files.map(path => lists.get(path.slice(0, path.lastIndexOf('/')))?.get(path.slice(path.lastIndexOf('/') + 1)) ?? '-')
  const names = folders.map(dir => [...(lists.get(dir)?.keys() ?? [])].sort().join(','))

  return [...times, ...names].join('|')
}

// One run of `phi.py progress`, which writes the tree into progress.json, and that file put where the pane reads
// it. One run is in flight at most: a second asked for meanwhile runs once the first has ended.
async function progress($: EngineInterface): Promise<void> {
  if (isProgressing) {
    isProgressOwed = true

    return
  }
  isProgressing = true
  try {
    // The times as they stand before python reads the files, and the lists they are the times of.
    const before = await stamped($)
    const listed = JSON.stringify([sources, folders])
    const answer = await ask($, ['progress'], PROGRESS_MS)
    // No answer, as from a run that was too slow or a python not found: the tree that is drawn stands.
    if (answer === undefined) return
    const text = typeof answer.path === 'string' ? await $.fs.read(answer.path).catch(() => '') : ''
    let kept: { nodes?: unknown; sources?: unknown; folders?: unknown } = {}
    try {
      kept = text === '' ? {} : (JSON.parse(text) as typeof kept)
    } catch {
      kept = {}
    }
    const paths = (list: unknown): string[] =>
      Array.isArray(list) ? list.filter((path): path is string => typeof path === 'string') : []
    const nodes = Array.isArray(kept.nodes) ? (kept.nodes as PhiNode[]) : []
    sources = paths(kept.sources)
    folders = paths(kept.folders)
    stamp = JSON.stringify([sources, folders]) === listed ? before : await stamped($)
    const now = JSON.stringify(nodes)
    if (now !== treed) {
      await update($, grown, () => nodes)
      treed = now
    }
  } catch (error) {
    note($, `the pane's tree was not read: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  } finally {
    isProgressing = false
    if (isProgressOwed) {
      isProgressOwed = false
      void progress($)
    }
  }
}

// One check of the open pane's files: `phi.py progress` runs only where one of them changed since its last run.
// With no tree read yet there is no file to check, and the command is asked again every EMPTY_TICKS ticks.
async function glanceAt($: EngineInterface): Promise<void> {
  if (!isPaneOpen || isProgressing || isStamping) return
  if (sources.length === 0) {
    emptyTicks += 1
    if (emptyTicks < EMPTY_TICKS) return
    emptyTicks = 0
    await progress($)

    return
  }
  isStamping = true
  try {
    if ((await stamped($)) !== stamp) await progress($)
  } catch {
    // the next tick checks again
  } finally {
    isStamping = false
  }
}

// The open pane's timer, started once. A close of the pane cancels it, and so does a reload of the module.
function watchPane($: EngineInterface): void {
  paneTimer ??= $.clock.every(PANE_MS, () => {
    void glanceAt($)
  })
}

// The command `/phi-pane`: the pages as they stand, and then the pane. A pane a command of the person's opens is
// placed at any width, by the types of `$.ui.open`, and where no surface places one the answer says why.
async function openPane($: EngineInterface): Promise<string> {
  isPaneOpen = true
  await page($)
  watchPane($)
  const opened = await $.ui.open({ id: PANE, title: PANE_TITLE })
  // The pane is up with its pages, and the tree joins it once python has answered.
  await progress($)

  return opened.isPlaced ? "p4-phi's pane is open." : `p4-phi's pane is open and not drawn: ${opened.reason}`
}

// One line of a page for a glance: its first line that is not blank, less a heading's marks, cut to the room.
function glance(text: string, columns: number): string {
  const first = (text.split('\n').find(line => line.trim() !== '') ?? '').replace(/^#+\s*/, '').trim()

  return first.length > columns ? `${first.slice(0, Math.max(1, columns - 3))}...` : first
}

// A name as hook.py writes it into a file's name: every character but a letter, a digit, `_` and `-` as `_`.
function named(id: string): string {
  return id.replace(/[^\w-]/g, '_')
}

// Writes which Agent call launched a subagent, where the project has a store: with none, hook.py keeps no line for
// a launch either. This is retrieval's own record, which P4_PHI=0 does not turn off, as it does not turn off the
// runner that reads it.
async function bind($: EngineInterface, toolUseId: string, agentId: string): Promise<void> {
  try {
    const models = `${await projectOf($)}/${MODELS}`
    if (!(await $.fs.exists(models))) return
    const folder = `${models}/served/start-${named(await $.session.id())}`
    await $.fs.write(`${folder}/${BOUND}${named(agentId)}`, `${toolUseId}\n`)
  } catch (error) {
    note($, `a subagent was not bound to its launch: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// A subagent `agent.spawn` answered. One an Agent call launched is bound to that call's id. A workflow's agent
// carries the id of its run's Workflow call, and a resumed run started long ago, so neither is bound.
function keepSpawn($: EngineInterface, e: AgentSpawnInput, agentId: string): void {
  const isLaunch = e.tool_use_id !== '' && e.workflow === undefined && e.resume === undefined
  spawned.set(agentId, isLaunch ? bind($, e.tool_use_id, agentId) : Promise.resolve())
  for (const oldest of spawned.keys()) {
    if (spawned.size <= MOST_SPAWNED) break
    spawned.delete(oldest)
  }
  awaited.get(agentId)?.()
}

// Resolves once the binding of a subagent is written, so the SubagentStart command hooks, which run beneath, read
// it. A subagent `agent.spawn` has not answered yet is waited for, a short while.
async function spawnBound($: EngineInterface, agentId: string): Promise<void> {
  try {
    if (!spawned.has(agentId)) {
      await new Promise<void>(resolve => {
        awaited.set(agentId, resolve)
        $.clock.after(SPAWN_WAIT_MS, resolve)
      })
      awaited.delete(agentId)
    }
    await spawned.get(agentId)
  } catch (error) {
    note($, `a subagent's start was not held: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// What a tool of the app answered, as the JSON it printed: the text the model would read, else the tool's own
// result, whether a text or text blocks. Nothing for an error, or for an answer that is no JSON object or list.
function answered(out: ToolCallResult): unknown {
  if (out.deny !== undefined || out.isError === true) return undefined
  const result: unknown = out.result
  const blocks = Array.isArray(result) ? result.map(block => String((block as { text?: unknown })?.text ?? '')) : []
  for (const text of [out.text, typeof result === 'string' ? result : undefined, blocks.join('')]) {
    try {
      const parsed: unknown = JSON.parse(text ?? '')
      if (typeof parsed === 'object' && parsed !== null) return parsed
    } catch {
      // no JSON: the next form
    }
  }

  return undefined
}

// One call of a tool of the app, through `$.tool.call`: the session's hooks and its permission check run for it,
// with no dialog. A session the app did not start has no such tool, and the call rejects: from then on none is
// called again. So it is after a refusal, as of a session off the person's machine. A call that outlasts its wait
// is given up on, and answers nothing.
async function appCall($: EngineInterface, tool: string, input: Record<string, unknown>): Promise<unknown> {
  let wait: Timer | undefined
  const isLate = new Promise<'late'>(resolve => {
    wait = $.clock.after(APP_CALL_MS, () => resolve('late'))
  })
  appFlying += 1
  const call = $.tool.call({ ...input, tool } as never).finally(() => {
    appFlying -= 1
  })
  try {
    const out = await Promise.race([call, isLate])
    if (out === 'late') {
      note($, `${tool} did not answer in ${APP_CALL_MS} ms`)

      return undefined
    }
    if (out.deny !== undefined) {
      if (tool.startsWith('mcp__ccd_sidebar__')) isSidebarAbsent = true
      else isAppAbsent = true
      note($, `${tool} was refused, so the app's tools are not asked again: ${out.deny.slice(0, 200)}`)
    }

    return answered(out)
  } catch (error) {
    if (tool.startsWith('mcp__ccd_sidebar__')) isSidebarAbsent = true
    else isAppAbsent = true
    note($, `${tool} is no tool of this session: ${String((error as Error)?.message ?? error).slice(0, 200)}`)

    return undefined
  } finally {
    wait?.cancel()
  }
}

// Where the app's answers are kept for python: beside a prompt's origin, in the session's folder under the store's
// served folder, rows.origin_dir in python, which phi.py finds by the session's id before it knows the tree's
// store, and in the session's folder in the tree's store for a project that has none.
async function appFile($: EngineInterface, sessionId: string): Promise<string | undefined> {
  const models = `${await projectOf($)}/${MODELS}`
  if (await $.fs.exists(models)) return `${models}/served/start-${named(sessionId)}/${APP_FILE}`

  return folder === undefined ? undefined : `${folder}/${APP_FILE}`
}

// The sidebar's sections for a puppeteer's filing: `list_sections`, and where that answers nothing, as while no
// window of the app is open, `list_groups`. Nothing where the session has neither tool.
async function askSections($: EngineInterface): Promise<unknown> {
  const sections = isSidebarAbsent ? undefined : await appCall($, APP_SECTIONS, {})

  return sections !== undefined || isSidebarAbsent ? sections : appCall($, APP_GROUPS, {})
}

// One round of calls after a look that answered `app_tools`: this session as the app holds it, and the sessions
// linked to it, written as the tools answered them, with the sidebar's sections where the look asked for them. No
// round runs while a turn of the main conversation does, nor within a minute of the last, nor while a call of an
// earlier round has not settled. Nothing waits on it. Before the first round p4-native's capability map is asked
// whether a tool of the app answers here, and where it says none does no call is made.
async function askApp($: EngineInterface, withSections = false): Promise<void> {
  try {
    if (isAppAbsent || isInTurn || appFlying > 0) return
    const now = await $.clock.now()
    if (now - appAt < APP_MS) return
    appAt = now
    if (!isMapAsked) {
      isMapAsked = true
      if (await isMappedOffTheApp($)) {
        isAppAbsent = true
        isSidebarAbsent = true
        note($, "p4-native's map reads no tool of the desktop app in this session, so the app's tools are not asked")

        return
      }
    }
    const file = await appFile($, await $.session.id())
    if (file === undefined) return
    const own = await appCall($, APP_SELF, { session_id: 'self' })
    const linked = isAppAbsent
      ? undefined
      : await appCall($, APP_LIST, { linked: true, include_archived: true, limit: APP_MOST })
    const sections = withSections ? await askSections($) : undefined
    if (own === undefined && linked === undefined && sections === undefined) return
    await $.fs.write(file, `${JSON.stringify({ at: now, self: own, sessions: linked, sections })}\n`)
  } catch (error) {
    note($, `the app's tools were not asked: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

// At a session's start, and at each reload of the module: the first look, which arms the timer and answers the
// session's folder, and then the usage as it stands.
async function begin($: EngineInterface): Promise<void> {
  await look($, true)
  try {
    const usage = await $.session.usage()
    record($, usage.context, usage.rateLimits)
  } catch (error) {
    note($, `the session's usage was not read: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

export const register: Register = on => {
  // The session does not wait for its first look, nor for its tools to be declared.
  on('session.start', ($, e, next) => {
    void offer($)
    void begin($)

    return next(e)
  })

  // Above every SessionStart command hook: the settings as Claude Code loaded them, added to the input those hooks
  // read on stdin, where no module above handed them. With none read the input goes down as it came.
  on('classic.SessionStart', async ($, e, next) => next(await withSettings($, e))).catch(($, e, next) => next(e))

  // Claude Code raises this after each turn and when a plan limit's percent used changes.
  on('session.measure', ($, e, next) => {
    record($, e.context, e.rateLimits)

    return next(e)
  })

  // After a /clear or a resume the process goes on under another session id, whose folder can be another one.
  on('session.end', async ($, e, next) => {
    await team($, true)
    if (e.reason === 'clear' || e.reason === 'resume') {
      folder = undefined
      starter = undefined
      written = undefined
    }

    return next(e)
  })

  on('turn.start', ($, e, next) => {
    if (e.agentId === undefined) {
      isInTurn = true
      isNoticeTurn = DELIVERY_NOTICE.test(e.text ?? '')
      isOwnTurn = OWN_KINDS.has(originOf(e.text ?? '')?.kind ?? '')
    }

    return next(e)
  })

  // A turn's end changes what the ledger shows: the main conversation's for every session, since it is where a
  // session comes to have a task or a child, and a subagent's for an orchestrator, whose ledger names what it wrote.
  // The main conversation's end is also where a worker's report goes to its starter. Claude Code raises this once a
  // turn, after its last Stop hook answered, so phi.py's Stop hook has written by then.
  on('turn.complete', ($, e, next) => {
    if (e.agentId === undefined) {
      isInTurn = false
      void report($, e.answer, e.reason, isNoticeTurn, isOwnTurn)
      isNoticeTurn = false
      isOwnTurn = false
    }
    if (e.agentId === undefined || isWatching) void look($, true)
    void team($)

    return next(e)
  })

  // A message's arrival is a child's report or another session's word, which an orchestrator's ledger shows. The
  // delivery is queued whatever becomes of the look.
  on('session.receive', ($, e, next) => {
    if (isWatching) void look($, true)

    return next(e)
  }).catch(($, e, next) => next(e))

  // A prompt is submitted: the user's own, another session's, a background task's notice or a plugin's. The event
  // carries its origin, a closed set the engine stamps, which the UserPromptSubmit command hooks are not given.
  // It is kept while the prompt is in flight, and the prompt enters whatever becomes of that.
  on('prompt.submit', async ($, e, next) => {
    const mine: Submitted = { text: e.text, origin: e.origin, isInFlight: true }
    submitted.push(mine)
    if (submitted.length > MOST_SUBMITTED) submitted.shift()
    try {
      return await next(e)
    } finally {
      mine.isInFlight = false
    }
  }).catch(($, e, next) => next(e))

  // A call of one of the plugin's own tools: the command of phi.py it stands for is run, and only once Claude Code
  // allowed the call, so its permission check stands. One hook holds the four, since a module names a glob once.
  // `tool.run` fires once a call is allowed, and there the command runs: on Claude Code 2.1.326 to 2.1.328 the glob
  // selects that event. On 2.1.330 no glob selects it, `tool.*` and `*` alike, seen there under `claude plugin
  // test`: the allowed call comes to its run, finds no hook, and Claude Code answers with the words of UNSERVED.
  // That answer comes back up to `tool.call`, where the module runs the command in its place, and a call the
  // permission check refused comes back with its refusal and goes up as it came. The glob stands for `tool.run`
  // because a module that names an event its Claude Code lacks is refused whole, as 2.1.311 and 2.1.322 refuse one
  // that names `tool.run`. Tried on those builds and on 2.1.330: a second file under `modules` in hooks.json is
  // refused, "names one hooks module per plugin", and an event name that is no string literal is refused.
  //
  // The same glob holds PLAN_TOOL, for its one event `tool.offer`, which only the glob can name on a build that
  // lacks it: where python says this session's model is not offered the tool, the answer says so, and every other
  // event of that tool, and its offer in any other session, goes down as it came.
  on('tool.*', { tool: GLOB_TOOLS }, async ($, e, next) => {
    if ((e as { tool?: string }).tool === PLAN_TOOL) {
      // the name as a plain string: the types of a build older than 2.1.328 hold no such event
      const isKept = (next.event as string) === 'tool.offer' && (await isWithheld($, PLAN_TOOL))

      return isKept ? ({ isOffered: false } as never) : next(e)
    }
    if (next.event === 'tool.run') return ownTool($, e)
    const out = await next(e)

    return next.event === 'tool.call' && isUnserved(out) ? ownTool($, e) : out
  }).catch(($, e, next) => {
    if ((e as { tool?: string }).tool === PLAN_TOOL) return next(e)

    return next.event === 'tool.run' || (next.event === 'tool.call' && next.called)
      ? { deny: 'p4-phi could not run phi.py.' }
      : next(e)
  })

  // The command a person types to see the pane. Nothing runs beneath, since the command is nothing but this.
  on('command.run', { command: 'phi-pane' }, async $ => ({ text: await openPane($) })).catch(() => ({
    text: 'p4-phi could not open its pane.',
  }))

  // A pane closes: p4-phi's own counts as closed from here, and the close goes on as it came, since a hook that
  // answers without `next` keeps the pane open.
  on('ui.close', ($, e, next) => {
    isPaneOpen = paneAfterClose(isPaneOpen, e)
    if (!isPaneOpen) {
      paneTimer?.cancel()
      paneTimer = undefined
    }

    return next(e)
  }).catch(($, e, next) => next(e))

  // The pane's body, drawn from the pages a look or the command put in `$.state`: the read subscribes the drawing,
  // so a later write draws it again, and a drawing writes nothing. The tree is built with `h`, the factory JSX
  // compiles to, so the module keeps its name. Docked or inline it is each page whole, as markdown under its
  // title, and as the desktop app's widget one line a page, cut to the body's columns.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    isPaneOpen = true
    const table = $.ui.resolve(e)
    const { Box, Text, Markdown } = table
    // `Progress` is in the tables of Claude Code 2.1.326 and not on plugins/mods/reference.md, "Elements".
    const Progress = (table as unknown as Record<string, typeof Text | undefined>).Progress
    const pages = await read($, shown)
    const nodes = await read($, grown)
    const isGlance = e.props.placement === 'widget'
    const none = isGlance
      ? 'p4-phi: no board and no ledger.'
      : 'This session keeps no board and no ledger: it is no puppeteer and no orchestrator, or no look has run yet.'
    const tree = isGlance
      ? nodes.length === 0
        ? []
        : [h(Text, { wrap: 'truncate-end' }, treeGlance(nodes).slice(0, Math.max(1, e.props.bodyColumns)))]
      : [
          ...(nodes.length === 0 ? [] : [h(Text, { bold: true }, 'Progress')]),
          ...treeLines(nodes).map(line =>
            line.kind === 'bar'
              ? Progress === undefined
                ? h(Text, {}, `${line.label} ${bar(line.value, line.max)} ${line.text}`)
                : h(Progress, { label: line.label, value: line.value, max: line.max, valueText: line.text } as never)
              : h(
                  Text,
                  {
                    bold: line.kind === 'title' || line.kind === 'now',
                    dimColor: line.kind === 'dim',
                    ...(line.color === undefined ? {} : { color: line.color }),
                  },
                  line.text,
                ),
          ),
        ]
    const rows =
      pages.length === 0
        ? tree.length === 0
          ? [h(Text, { dimColor: true }, none)]
          : []
        : isGlance
          ? pages.map(one => h(Text, { wrap: 'truncate-end' }, glance(one.text, e.props.bodyColumns)))
          : pages.flatMap(one => [h(Text, { bold: true }, one.title), h(Markdown, { text: one.text })])

    return h(Box, { flexDirection: 'column' }, ...tree, ...rows) as RenderElement
  }).catch(($, e) => {
    const { Text } = $.ui.resolve(e)

    return h(Text, { dimColor: true }, "p4-phi's pane could not be drawn.") as RenderElement
  })

  // The engine decides whether a tool call may run, after the PreToolUse hooks. The event carries the tool, its
  // input, the call's id and a subagent's id, which `classic.PreToolUse` does not hand a function, and no hook
  // here stands on `tool.call` for any tool but the plugin's own four, where one turns off a tool's move to the
  // background and its live output. A check that fails judges nothing, and the engine's verdict stands.
  on('tool.check', async ($, e, next) => judged($, e, await next(e))).catch(($, e, next) => next(e))

  // What a check said beside a call that ran, handed to the model with the call's result as a PreToolUse command
  // hook's context is. The PostToolUse command hooks run beneath, and their own context comes first. A send whose
  // answer says the message was queued gets the line that says what that means.
  on('classic.PostToolUse', async ($, e, next) => {
    const out = await next(e)
    // The open pane's timer, where a reload of the module ended it. The task list changed and its record is
    // written: the open pane shows it now, inside the turn.
    if (isPaneOpen) watchPane($)
    if (isPaneOpen && e.tool_name === STEP_TOOL) void progress($)
    const words = [...toldOf(e.tool_use_id), ...(await queued($, e.tool_name, e.tool_response))]

    return words.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...words] }
  }).catch(($, e, next) => next(e))

  on('classic.PostToolUseFailure', async ($, e, next) => {
    if (failed.size >= FAILED_MAX) failed.clear()
    failed.add(e.tool_use_id)
    const out = await next(e)
    const words = toldOf(e.tool_use_id)

    return words.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...words] }
  }).catch(($, e, next) => next(e))

  // Above the PostToolBatch command hooks, which write a batch's lookup rows: the calls of the batch that failed,
  // by their ids, added to the input those hooks read on stdin. The list is added where it is empty too, so python
  // can tell a batch the module read from one no module read.
  on('classic.PostToolBatch', ($, e, next) => {
    const ids = e.tool_calls.map(call => call.tool_use_id).filter(id => failed.has(id))
    for (const id of ids) failed.delete(id)

    return next({ ...e, [FAILED]: ids } as typeof e)
  }).catch(($, e, next) => next(e))

  // The UserPromptSubmit command hooks run beneath this hook, so they run once the prompt's origin is written.
  on('classic.UserPromptSubmit', async ($, e, next) => {
    await keepOrigin($, e.prompt, e.prompt_id, e.session_id)

    return next(e)
  }).catch(($, e, next) => next(e))

  // Claude Code raises this when it renders a system prompt. A hook that fails here is skipped, and the prompt goes
  // out as composed beneath.
  on('prompt.compose', async ($, e, next) => withRules($, await next(e))).catch(($, e, next) => next(e))

  // An agent is about to start. The event carries the id of the Agent call that launches it, and `next(e)` answers
  // the id the subagent runs under, which a SubagentStart command hook's input holds with no word of the call. The
  // pair is kept for hook.py, in place of its guess that a start belonged to the oldest launch of its agent type.
  on('agent.spawn', async ($, e, next) => {
    const started = await next(e)
    if (started.agentId !== undefined) keepSpawn($, e, started.agentId)
    void team($)

    return started
  }).catch(($, e, next) => next(e))

  // The SubagentStart command hooks run beneath this hook, so they run once the pair is written.
  on('classic.SubagentStart', async ($, e, next) => {
    await spawnBound($, e.agent_id)
    void team($)

    return next(e)
  }).catch(($, e, next) => next(e))
}
