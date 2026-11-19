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
// worker Claude Code's own goal, which no command hook and no other session can. And it gives a session three of
// phi.py's commands as tools, `note`, `done` and `tree`, which it runs itself, so a session keeps a finding with
// no shell line.

import type {
  AgentSpawnInput,
  EngineInterface,
  PromptComposeResult,
  PromptOrigin,
  Register,
  SessionContextUsage,
  SessionRateLimit,
  Timer,
  ToolCallResult,
  ToolCheckInput,
  ToolCheckResult,
  TurnCompleteReason,
} from 'claude-code'

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
const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
const SHELL_TOOLS = new Set(['Bash', 'PowerShell'])
const CHECKED_TOOLS = new Set([
  'WebFetch',
  'WebSearch',
  'SendMessage',
  'mcp__ccd_session_mgmt__send_message',
  'mcp__ccd_session_mgmt__archive_session',
  'mcp__ccd_session__start_session',
])
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
// Where a store keeps the failure model a plain shell call is checked by, newest layout first, and how long what
// its first line said is believed: a training round's new model is read within this long.
const SHELL_MODELS = ['phi/models', 'recall/models', 'models']
const MODEL_MS = 60_000
// The calls whose check left words for the model, at most, each until its PostToolUse hooks run.
const MOST_TOLD = 256

// The commands of phi.py a session calls as tools, each `mcp__p4-phi__<name>`: what the model reads of it, and the
// input it takes. `note` and `done` are in a session's tool list from its start, since every session is asked for
// both, and `tree` waits behind ToolSearch as an MCP server's tool does.
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
] as const
// How long one of those commands may run.
const TOOL_MS = 30_000

// What `phi.py look` prints, as puppeteer.look answers it: the times are seconds. `starter` is the session that
// started this one, as the address `$.session.send` takes, and `move` the prompt that starts a turn here. `upkeep`
// is the prompt of a turn for the upkeep of the sessions this one started, answered only where a project turns
// `phi.upkeep` on, every one of those sessions is idle and python's count of such turns is inside its budget.
// `rules` is what `phi.py rules` prints alone: the text of the system prompt's section. `goal` is the condition of
// the native goal this session is to be given, answered once and only where a store's phi.json turns `goal` on.
type Answer = {
  rules?: string
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
// The main conversation is inside a turn.
let isInTurn = false
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
// Whether the store's failure model weighs shell calls, as its first line said when it was last read.
let shellModel: { at: number; isWeighted: boolean } | undefined

// What was said to the debug log, each line once.
const said = new Set<string>()

function slashed(path: string): string {
  return path.replaceAll('\\', '/').replace(/\/+$/, '')
}

function note($: EngineInterface, text: string): void {
  if (said.has(text)) return
  said.add(text)
  $.ui.log(text, { to: 'debug' })
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
// own folder where a runner had no data folder. A data folder is named after the plugin's id, `<name>@<origin>`
// with `@` as `-`, and the module is told only the name, so each folder that starts with the name is read.
async function keptFiles($: EngineInterface): Promise<string[]> {
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

// With nothing kept, the search of find-python.sh: the launcher first on Windows, where `python3` can be the Store's
// stub, and `python3` first elsewhere. Each candidate is proven by one run, since a module has no `command -v`.
async function provenPython($: EngineInterface): Promise<string | undefined> {
  const isWindows = /^[A-Za-z]:[\\/]/.test($.plugin.root)
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
  const env = { CLAUDE_CODE_SESSION_ID: await $.session.id(), CLAUDE_PROJECT_DIR: await $.session.root() }
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
async function ran($: EngineInterface, isSlow: boolean): Promise<Answer | undefined> {
  try {
    const answer = await ask($, isSlow ? ['look', '--net'] : ['look'], isSlow ? SLOW_LOOK_MS : LOOK_MS)
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
    // One turn at most for one look: a goal to set first, whose command starts its own turn, then the work a wait
    // left unmoved, else the upkeep that is due.
    const prompt = answer?.move || answer?.upkeep
    if (answer?.goal) setGoal($, answer.goal)
    else if (prompt) wake($, prompt)
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

// At the end of a turn of a session another session started: its report goes to that session, where a message
// starts a turn when the session is idle. A turn the person stopped is theirs to speak of. A starter that runs under
// a new id since a clear or a resume is asked of python once more.
async function report($: EngineInterface, answer: string, reason: TurnCompleteReason): Promise<void> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff || reason === 'aborted') return
    const to = await starterOf($)
    if (!to) return
    const text = reportText(answer, reason)
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
// the goal is set, and from then on its Stop hook sends no turn back. Nothing waits on the call.
function setGoal($: EngineInterface, condition: string): void {
  $.command.run({ command: 'goal', args: condition }).then(
    ran => {
      const answered = ran.text ?? ''
      if (answered.startsWith('Goal set')) void ask($, ['goal', 'set'], LOOK_MS)
      else note($, `the goal command did not set the goal: ${answered.slice(0, 200)}`)
    },
    error => note($, `the goal was not set: ${String((error as Error)?.message ?? error).slice(0, 200)}`),
  )
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
async function withRules($: EngineInterface, composed: PromptComposeResult): Promise<PromptComposeResult> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff) return composed
    const text = ((await ask($, ['rules'], LOOK_MS))?.rules ?? '').trim()
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
  const models = `${slashed(await $.session.root())}/${MODELS}`
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

// One call's check: `hook.py lookup-check`, run only for a call python has a check for, with the input a
// PreToolUse command hook is given on stdin. Retrieval's check does not obey P4_PHI=0, and phi.py's own checks
// read the switch themselves. Whatever fails here, the call goes on unjudged.
async function check($: EngineInterface, e: ToolCheckInput): Promise<Said> {
  try {
    const root = slashed(await $.session.root())
    const sessionId = await $.session.id()
    const call = { tool_name: String(e.tool), tool_input: e.input }
    if (!(await isChecked($, e, root, sessionId, JSON.stringify(call)))) return {}
    const python = await findPython($)
    if (python === undefined) return {}
    const plugin = slashed($.plugin.root)
    const payload = {
      session_id: sessionId,
      transcript_path: (await $.session.info()).transcriptPath,
      cwd: root,
      hook_event_name: 'PreToolUse',
      ...call,
      tool_use_id: e.tool_use_id,
      ...(e.agentId === undefined ? {} : { agent_id: e.agentId }),
    }
    const env = { CLAUDE_CODE_SESSION_ID: sessionId, CLAUDE_PROJECT_DIR: root, CLAUDE_PLUGIN_ROOT: plugin }
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

// Declares the three tools, at a session's start and at each reload of the module. A session with P4_PHI=0 gets
// none, since phi.py keeps nothing for it.
async function offer($: EngineInterface): Promise<void> {
  try {
    switches ??= readSwitches($)
    if ((await switches).isPhiOff) return
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

// Runs one command of phi.py for a tool call, for this session, in the session's working folder as a shell line
// ran it. What it prints is the tool's result, and what it says on a failure is the call's error. The words of
// the call come after `--`, so a finding that opens with a dash is no option.
async function served($: EngineInterface, args: readonly string[]): Promise<ToolCallResult> {
  try {
    const python = await findPython($)
    if (python === undefined) return { deny: 'p4-phi found no working python to run phi.py with.' }
    const script = `${slashed($.plugin.root)}/scripts/phi.py`
    const env = { CLAUDE_CODE_SESSION_ID: await $.session.id(), CLAUDE_PROJECT_DIR: await $.session.root() }
    const ran = await $.process.run([python, '-I', '-X', 'utf8', script, ...args], { env, timeoutMs: TOOL_MS })
    if (ran.exitCode !== 0) return { deny: (ran.stderr.trim() || ran.stdout.trim() || 'phi.py failed').slice(0, 4_000) }

    return { result: ran.stdout.trim() }
  } catch (error) {
    return { deny: `phi.py did not run: ${String((error as Error)?.message ?? error).slice(0, 200)}` }
  }
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
    const models = `${slashed(await $.session.root())}/${MODELS}`
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

  // Claude Code raises this after each turn and when a plan limit's percent used changes.
  on('session.measure', ($, e, next) => {
    record($, e.context, e.rateLimits)

    return next(e)
  })

  // After a /clear or a resume the process goes on under another session id, whose folder can be another one.
  on('session.end', ($, e, next) => {
    if (e.reason === 'clear' || e.reason === 'resume') {
      folder = undefined
      starter = undefined
      written = undefined
    }

    return next(e)
  })

  on('turn.start', ($, e, next) => {
    if (e.agentId === undefined) isInTurn = true

    return next(e)
  })

  // A turn's end changes what the ledger shows: the main conversation's for every session, since it is where a
  // session comes to have a task or a child, and a subagent's for an orchestrator, whose ledger names what it wrote.
  // The main conversation's end is also where a worker's report goes to its starter. Claude Code raises this once a
  // turn, after its last Stop hook answered, so phi.py's Stop hook has written by then.
  on('turn.complete', ($, e, next) => {
    if (e.agentId === undefined) {
      isInTurn = false
      void report($, e.answer, e.reason)
    }
    if (e.agentId === undefined || isWatching) void look($, true)

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

  // A call of one of the plugin's own tools, once it is allowed: the command of phi.py it stands for is run, and
  // nothing runs beneath, since the tool is nothing but that command.
  on('tool.run', { tool: 'mcp__p4-phi__note' }, ($, e) => {
    const options = [
      ...(field(e, 'source') ? ['--source', field(e, 'source')] : []),
      ...(field(e, 'kind') ? ['--kind', field(e, 'kind')] : []),
    ]

    return served($, ['note', ...options, '--', field(e, 'claim')])
  }).catch(() => ({ deny: 'p4-phi could not run `phi.py note`.' }))

  on('tool.run', { tool: 'mcp__p4-phi__done' }, ($, e) => served($, ['done', '--', field(e, 'text')])).catch(() => ({
    deny: 'p4-phi could not run `phi.py done`.',
  }))

  on('tool.run', { tool: 'mcp__p4-phi__tree' }, $ => served($, ['tree'])).catch(() => ({
    deny: 'p4-phi could not run `phi.py tree`.',
  }))

  // The engine decides whether a tool call may run, after the PreToolUse hooks. The event carries the tool, its
  // input, the call's id and a subagent's id, which `classic.PreToolUse` does not hand a function, and no hook
  // here stands on `tool.call`, where one turns off a tool's move to the background and its live output. A check
  // that fails judges nothing, and the engine's verdict stands.
  on('tool.check', async ($, e, next) => judged($, e, await next(e))).catch(($, e, next) => next(e))

  // What a check said beside a call that ran, handed to the model with the call's result as a PreToolUse command
  // hook's context is. The PostToolUse command hooks run beneath, and their own context comes first.
  on('classic.PostToolUse', async ($, e, next) => {
    const out = await next(e)
    const words = toldOf(e.tool_use_id)

    return words.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...words] }
  }).catch(($, e, next) => next(e))

  on('classic.PostToolUseFailure', async ($, e, next) => {
    const out = await next(e)
    const words = toldOf(e.tool_use_id)

    return words.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...words] }
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

    return started
  }).catch(($, e, next) => next(e))

  // The SubagentStart command hooks run beneath this hook, so they run once the pair is written.
  on('classic.SubagentStart', async ($, e, next) => {
    await spawnBound($, e.agent_id)

    return next(e)
  }).catch(($, e, next) => next(e))
}
