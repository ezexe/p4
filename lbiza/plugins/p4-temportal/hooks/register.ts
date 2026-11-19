// p4-temportal's hooks module: the part of the plugin that runs inside Claude Code, where a command hook runs once
// at its event and is gone. It runs the retention sweep, `lifetime.py tick`, at a session's start, on a timer while
// the session runs, and in a process let go of at the session's end. It registers lifetime.py's four commands as the
// slash command `/lifetime`, which a person runs and the model cannot: the Skill tool refuses a command a module
// registers. It finds the python that find-python.sh proved for the plugin's runner, as p4-phi's module does, and it
// starts no `sh`.
//
// It registers the same four commands as the tool `lifetime` for the model, `mcp__p4-temportal__lifetime`, so a
// session sets, clears and lists lifetimes itself. The tool is served at `tool.run`, the event that fires once
// Claude Code allowed the call, so its permission check stands before a `set`, a `clear` and a `now`, which end in
// deleted files. plugins/mods/api.md, "Add a tool", serves a tool at `tool.call`, where an answer skips that
// check. `tool.run` is in the API types of Claude Code 2.1.326 and is no event on 2.1.322, where a module that
// hooks it does not load.
//
// It also keeps a compaction from losing what a session needs afterwards, at `session.compact`, the event of every
// compaction, whoever started it. On the way down it adds the keep list to what the summary is told. On the way up
// it adds one message after the summary, the ledger: the paths of the files the session wrote or edited, read from
// the transcript's own tool calls with no model, an earlier ledger's paths among them. And it starts a compaction
// itself in a quiet moment, a minute after a turn of the main conversation ended with none begun since, once the
// context is at or past the line `temportal.compact_at`: 70 percent unless the store's p4.json sets it, and 0 for
// none. It starts one as the slash command `/compact`, by `$.command.run`. Seen in the desktop app on Claude Code
// 2.1.326: `$.session.compact` is refused in a session a program started, "compaction here runs inside a turn (a
// /compact prompt)", and the command compacts there, with this module's own `session.compact` hook hearing it.

import type {
  EngineInterface,
  ProcessRunResult,
  Register,
  SessionMessage,
  Timer,
  ToolCallResult,
} from 'claude-code'

// What find-python.sh runs to prove an interpreter: the interpreter prints its own path.
const PROOF = "import sys; print(sys.executable.replace(chr(92), '/'))"

// How long a sweep may run before Claude Code ends it.
const SWEEP_MS = 120_000

// The timer's wait after a sweep that answered none, and the least and the most an answer sets it to, which are
// lifetime.py's LEAST_WAIT_S and MOST_WAIT_S.
const WAIT_MS = 600_000
const LEAST_WAIT_MS = 60_000
const MOST_WAIT_MS = 3_600_000

// The wait before the sweep that was asked for while one ran.
const ASKED_MS = 1_000

// How long the start of the last sweep may take where nothing meters a session's end.
const END_MS = 10_000

// The lifetime commands, each with the count of words it takes after its name, and what an ask that fits none is
// answered.
const TAKES = new Map([
  ['list', 0],
  ['set', 2],
  ['clear', 1],
  ['now', 0],
])
const HINT = 'list | set <path> <lifetime> | clear <path> | now'
const USAGE =
  `/lifetime ${HINT}\n` +
  'list shows every cookie and cache rule. set gives a file or folder under .claude/p4/temportal/ a lifetime of ' +
  '30m, 12h, 7d, 2w or an ISO date, after which the retention sweep deletes it. clear removes a lifetime and keeps ' +
  'the file. now runs the retention sweep, which deletes what is past its lifetime. A path is read from the ' +
  'working folder, or from temportal/ as list prints it, and one with a space goes in quotes.'

// The tool a session calls for the same four commands: what the model reads of it, and the input it takes. It
// waits behind ToolSearch as an MCP server's tool does, since few sessions set a lifetime.
const TOOL = {
  name: 'lifetime',
  description:
    'p4-temportal: list, set or clear the lifetimes of the files kept under .claude/p4/temportal/, or run the ' +
    'retention sweep. `command` is list, set, clear or now. list shows every cookie and cache rule. set gives ' +
    'the file or folder at `path` a `lifetime` of 30m, 12h, 7d, 2w or an ISO date, after which the retention ' +
    'sweep deletes it. clear removes the lifetime of `path` and keeps the file. now runs the retention sweep, ' +
    'which deletes what is past its lifetime. A path is read from the working folder, or from temportal/ as list ' +
    'prints it.',
  inputSchema: {
    type: 'object',
    properties: {
      command: { type: 'string', enum: ['list', 'set', 'clear', 'now'] },
      path: { type: 'string' },
      lifetime: { type: 'string' },
    },
    required: ['command'],
  },
} as const
// The tool's name as a call carries it.
const TOOL_ID = 'mcp__p4-temportal__lifetime'
// What a call that fits none of the four commands is refused with.
const TOOL_USAGE =
  'p4-temportal: `command` is list, set, clear or now. set takes `path` and `lifetime`, clear takes `path`, and ' +
  'list and now take neither.'

// What a summary is told to keep, added to the instructions of every compaction.
// compact.py holds the same words for the PreCompact command hook, which prints them where no module loads and is
// silent where the instructions it is handed already hold them.
const KEEP =
  'Keep each of these verbatim in the summary, one to a line: every session id, every file path, every branch, ' +
  'every commit hash, every decision with its source, every open item, and the path of every state page and ' +
  'hand-over note.'

// The ledger: its first line, by which the next compaction finds it, the line above its paths, and the line that
// counts the paths it left out.
const LEDGER =
  'p4-temportal kept this list across a compaction. Nobody typed it: the plugin built it from the tool calls of ' +
  'the session.'
const LEDGER_FILES = 'Files this session wrote or edited, the latest last:'
const LEFT_OUT = 'Older paths left out of this list: '

// The tools whose call writes a file, each with the argument that names the file.
const WRITES = new Map([
  ['Write', 'file_path'],
  ['Edit', 'file_path'],
  ['NotebookEdit', 'notebook_path'],
])

// The most paths a ledger lists.
const MOST_PATHS = 60

// The line until a sweep answered the store's own, which is lifetime.py's COMPACT_AT.
const COMPACT_AT = 70

// How long the main conversation is quiet before the module looks at the context. It is well inside the five
// minutes a prompt cache entry lives, so the summary's request reads the conversation from the cache.
const QUIET_MS = 60_000

// What `lifetime.py tick` prints: the lines of what it moved and cleared, the seconds until the next sweep, and
// the line `temportal.compact_at`.
type Answer = { said?: unknown; wait_s?: unknown; let_go?: unknown; compact_at?: unknown }

// The python that runs the plugin's scripts, searched for once. A reload of the module starts all of this over.
let finding: Promise<string | undefined> | undefined

// A sweep is in flight: there is never a second one from this module.
let isSweeping = false
// A sweep was asked for while one ran.
let isAsked = false
let timer: Timer | undefined

// The percent of the context at which the module compacts a quiet session, and 0 for none.
let line = COMPACT_AT
// The wait that runs while the main conversation is quiet.
let quiet: Timer | undefined
// A compaction this module started is in flight.
let isCompacting = false
// The main conversation was compacted and its context has not been read since.
let isFresh = false
// The first reading after a compaction was already at or past the line, so compacting does not reach under it.
let isHeld = false

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

function reason(error: unknown): string {
  return String((error as Error)?.message ?? error).slice(0, 200)
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
    note($, 'no working python found, so no retention sweep runs')
  }
  return python
}

// Runs one command of lifetime.py for this session's project, as the plugin's runner runs it. The project is told
// to lifetime.py as a command hook's environment tells it, and a relative path is read from the session's folder.
async function run(
  $: EngineInterface,
  args: readonly string[],
  timeoutMs: number,
): Promise<ProcessRunResult | undefined> {
  const python = await findPython($)
  if (python === undefined) return undefined
  const script = `${slashed($.plugin.root)}/hooks/lifetime.py`
  const env = { CLAUDE_PROJECT_DIR: await $.session.root() }
  try {
    return await $.process.run([python, '-I', '-X', 'utf8', script, ...args], { env, timeoutMs })
  } catch (error) {
    finding = undefined
    note($, `lifetime.py ${args[0] ?? ''} did not run: ${reason(error)}`)
    return undefined
  }
}

// Runs `lifetime.py tick` and reads the one JSON line it prints.
async function ask($: EngineInterface, args: readonly string[], timeoutMs: number): Promise<Answer | undefined> {
  const ran = await run($, args, timeoutMs)
  if (ran === undefined) return undefined
  const printed = ran.stdout.trim().split('\n').at(-1) ?? ''
  try {
    const answer: unknown = JSON.parse(printed)
    return typeof answer === 'object' && answer !== null ? (answer as Answer) : undefined
  } catch {
    return undefined
  }
}

// How long the timer waits after a sweep: what the sweep answered, within lifetime.py's own bounds.
function waitOf(answer: Answer | undefined): number {
  const seconds = answer?.wait_s
  if (typeof seconds !== 'number' || !(seconds > 0)) return WAIT_MS
  return Math.min(Math.max(Math.round(seconds * 1000), LEAST_WAIT_MS), MOST_WAIT_MS)
}

// The line a sweep answered, and the line as it was where the sweep answered none.
function lineOf(answer: Answer | undefined): number {
  const at = answer?.compact_at

  return typeof at === 'number' && at >= 0 && at < 100 ? at : line
}

// The timer, set anew to fire `wait` milliseconds from this moment. No timer runs while a sweep does.
function arm($: EngineInterface, wait: number): void {
  timer?.cancel()
  timer = $.clock.every(Math.max(1, Math.round(wait)), () => {
    void sweep($)
  })
}

// One retention sweep, and then the timer for the next. What the sweep moved or cleared is a line of the transcript,
// which ezexe reads and the model does not.
async function sweep($: EngineInterface): Promise<void> {
  if (isSweeping) {
    isAsked = true
    return
  }
  isSweeping = true
  isAsked = false
  timer?.cancel()
  timer = undefined
  let wait = WAIT_MS
  try {
    const answer = await ask($, ['tick'], SWEEP_MS)
    const lines = Array.isArray(answer?.said) ? answer.said : []
    for (const text of lines) if (typeof text === 'string' && text) $.ui.log(text)
    wait = waitOf(answer)
    line = lineOf(answer)
  } catch (error) {
    note($, `the retention sweep failed: ${reason(error)}`)
  } finally {
    isSweeping = false
  }
  arm($, isAsked ? ASKED_MS : wait)
}

// The last sweep of a session, started in a process that lifetime.py lets go of, since every `session.end` hook
// shares one short bound and a sweep cut at it would leave files half cleared. `left` is what the bound has left.
async function lastSweep($: EngineInterface, left: number): Promise<void> {
  try {
    const within = Number.isFinite(left) ? Math.min(left, END_MS) : END_MS
    if (within < 1) return
    await ask($, ['tick', '--let-go'], Math.round(within))
  } catch (error) {
    note($, `the last retention sweep did not start: ${reason(error)}`)
  }
}

// The words of a command as typed. A part in double or single quotes is one word, so a path may hold a space.
function words(text: string): string[] {
  const found = text.match(/"[^"]*"|'[^']*'|\S+/g) ?? []

  return found.map(word => (/^(["']).*\1$/s.test(word) ? word.slice(1, -1) : word))
}

// One command of lifetime.py with its words: whether it ended well, and what it printed or the line it refused
// with. A new cookie can be due before the timer's next sweep, so a `set` is followed by a sweep, which sets the
// timer by that cookie.
async function command(
  $: EngineInterface,
  name: string,
  rest: readonly string[],
): Promise<{ isDone: boolean; text: string }> {
  const ran = await run($, [name, ...rest], SWEEP_MS)
  if (ran === undefined) return { isDone: false, text: `lifetime.py ${name} did not run, and the debug log says why.` }
  const isDone = ran.exitCode === 0
  if (name === 'set' && isDone) void sweep($)
  const printed = (isDone ? ran.stdout : ran.stderr || ran.stdout).trim()

  return { isDone, text: printed || `lifetime.py ${name} printed nothing and exited ${ran.exitCode}.` }
}

// One command of `/lifetime` as typed: what lifetime.py printed for it, or the line it refused with.
async function lifetime($: EngineInterface, typed: string): Promise<string> {
  const [name = '', ...rest] = words(typed)
  if (TAKES.get(name) !== rest.length) return USAGE

  return (await command($, name, rest)).text
}

// One text field of a tool call's input, trimmed, and '' for one left out.
function field(e: unknown, name: string): string {
  const value = (e as Record<string, unknown>)[name]

  return typeof value === 'string' ? value.trim() : ''
}

// One call of the tool, once Claude Code allowed it: the command of lifetime.py it names, with the words that
// command takes and no others. What the command printed is the tool's result, and what it refused with is the
// call's error. The words come after `--`, so a path that opens with a dash is no option.
async function called($: EngineInterface, e: unknown): Promise<ToolCallResult> {
  const name = field(e, 'command')
  const given = { set: ['path', 'lifetime'], clear: ['path'], list: [], now: [] }[name]
  const rest = (given ?? []).map(key => field(e, key))
  const others = ['path', 'lifetime'].filter(key => !(given ?? []).includes(key) && field(e, key))
  if (given === undefined || rest.includes('') || others.length > 0) return { deny: TOOL_USAGE }
  const { isDone, text } = await command($, name, rest.length > 0 ? ['--', ...rest] : [])

  return isDone ? { result: text } : { deny: text }
}

// The slash command and the tool, registered at each start of the module. A name that is taken is refused with a
// throw, and each is registered whatever became of the other.
async function offer($: EngineInterface): Promise<void> {
  try {
    await $.command.register({
      name: 'lifetime',
      description: 'Lists, sets and clears the lifetimes of the files p4-temportal keeps, or runs its sweep now.',
      argumentHint: HINT,
    })
  } catch (error) {
    note($, `/lifetime was not registered: ${reason(error)}`)
  }
  try {
    await $.tool.register(TOOL)
  } catch (error) {
    note($, `the tool lifetime was not registered: ${reason(error)}`)
  }
}

// What the summarizer is told: what it was told already, and the keep list after it once.
function told(instructions: string | undefined): string {
  if (!instructions) return KEEP

  return instructions.includes(KEEP) ? instructions : `${instructions}\n\n${KEEP}`
}

function isLedger(message: SessionMessage): boolean {
  return message.role === 'user' && message.text.startsWith(LEDGER)
}

// The ledger of a transcript: one message that lists the files it wrote or edited, each once in the order of its
// last write, or none where it wrote no file. An earlier ledger among the messages gives its paths first, since a
// compaction leaves only the messages after the one before it. A call that reported an error wrote nothing.
function ledger(messages: readonly SessionMessage[]): SessionMessage | undefined {
  const paths = new Map<string, string>()
  let left = 0
  const add = (path: unknown): void => {
    if (typeof path !== 'string' || !path.trim() || path.includes('\n')) return
    const key = path.trim().replaceAll('\\', '/')
    paths.delete(key)
    paths.set(key, path.trim())
  }
  for (const message of messages) {
    if (isLedger(message)) {
      for (const text of message.text.split('\n')) {
        if (text.startsWith('- ')) add(text.slice(2))
        else if (text.startsWith(LEFT_OUT)) left += Number.parseInt(text.slice(LEFT_OUT.length), 10) || 0
      }
    }
    for (const use of message.toolUses ?? []) {
      const named = WRITES.get(use.tool)
      if (named !== undefined && use.isError !== true) add(use.input[named])
    }
  }
  if (paths.size === 0) return undefined
  const all = [...paths.values()]
  const kept = all.slice(-MOST_PATHS)
  const out = left + all.length - kept.length
  const lines = [LEDGER, LEDGER_FILES, ...kept.map(path => `- ${path}`)]
  if (out > 0) lines.push(`${LEFT_OUT}${out}.`)

  return { role: 'user', text: lines.join('\n'), toolUses: [] }
}

// Runs when the main conversation was quiet for QUIET_MS: it compacts the session where its context is at or past
// the line. It starts none where ezexe turned Claude Code's own compaction off, none at the point where Claude Code
// compacts by itself, and none where the first reading after a compaction is already at or past the line, since a
// compaction then does not reach under it: Claude Code's own is the next one. A context not measured since the last
// compaction reads as nothing and starts none.
async function compactWhenDue($: EngineInterface): Promise<void> {
  quiet = undefined
  if (isCompacting || !(line > 0)) return
  try {
    const { percent, tokens, breakdown } = (await $.session.usage({ breakdown: 'summary' })).context
    if (percent === undefined || tokens === undefined || breakdown === undefined) return
    const isFirst = isFresh
    isFresh = false
    if (percent < line) return
    if (isFirst) {
      isHeld = true
      note($, `the context is at ${percent} percent right after a compaction, so temportal.compact_at ${line} starts none`)
    }
    const isNear = breakdown.autoCompactThreshold !== undefined && tokens >= breakdown.autoCompactThreshold
    if (isHeld || !breakdown.isAutoCompactEnabled || isNear) return
    isCompacting = true
    $.ui.log(`The context is at ${percent} percent, at or past temportal.compact_at ${line}, so the session compacts.`)
    await $.command.run({ command: 'compact', args: KEEP })
  } catch (error) {
    note($, `the compaction at a quiet moment did not run: ${reason(error)}`)
  } finally {
    isCompacting = false
  }
}

export const register: Register = on => {
  // The session does not wait for its first sweep, and it does wait for the command, which is then listed from the
  // first prompt.
  on('session.start', async ($, e, next) => {
    void sweep($)
    await offer($)

    return next(e)
  })

  // Every compaction, of the main conversation and of a subagent's own transcript. A `precompute` installs
  // nothing, and its result is kept for the compaction that follows, so the ledger is added at that one. A ledger
  // the result already holds is replaced, so there is never a second. A ledger that cannot be built is left out
  // and said, and the compaction stands as Claude Code made it.
  on('session.compact', async ($, e, next) => {
    const out = await next({ ...e, instructions: told(e.instructions) })
    if (out.skip !== undefined || e.trigger === 'precompute') return out
    if (e.agentId === undefined) {
      isFresh = true
      isHeld = false
    }
    try {
      const kept = ledger(e.messages)
      if (kept === undefined) return out

      return { ...out, messages: [...out.messages.filter(message => !isLedger(message)), kept] }
    } catch (error) {
      note($, `the list of written files was not added after a compaction: ${reason(error)}`)

      return out
    }
  })

  // A turn of the main conversation ends the quiet, and the end of one starts it.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      quiet?.cancel()
      quiet = undefined
    }

    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const out = await next(e)
    if (e.agentId === undefined) {
      quiet?.cancel()
      quiet = $.clock.after(QUIET_MS, () => {
        void compactWhenDue($)
      })
    }

    return out
  })

  on('command.run', { command: 'lifetime' }, async ($, e) => ({ text: await lifetime($, e.args) }))

  // A call of the tool, once it is allowed. Nothing runs beneath, since the tool is nothing but that command.
  on('tool.run', { tool: TOOL_ID }, ($, e) => called($, e)).catch(() => ({
    deny: 'p4-temportal could not run lifetime.py.',
  }))

  // After a /clear or a resume the process goes on, and the timer with it. Every other reason ends the process.
  on('session.end', async ($, e, next) => {
    const isOver = e.reason !== 'clear' && e.reason !== 'resume'
    if (isOver) await lastSweep($, next.budget.remainingMs)

    return next(e)
  })
}
