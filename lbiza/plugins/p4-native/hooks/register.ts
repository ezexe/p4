// p4-native's hooks module: the host layer of ezexe/p4, the one place that knows what this host can do. It runs
// inside Claude Code and starts no process, so a session's start costs it a handful of the engine's own calls.
//
// At a session's start it works out the capability map of the session: the desktop app or a terminal, interactive
// or scripted, the Claude Code version, and which of the desktop app's tools and of Claude Code's own tools answer
// here. Each fact is asked of the engine: `e.isInteractive` of `session.start`, `$.session.surfaces`,
// `$.session.version`, `$.session.info` and `$.tool.list`. No environment variable is read, since a `claude -p` run
// started from a desktop session's shell inherits that session's variables. The map is read again at the first turn
// of the main conversation, when a tool server that was still connecting has answered, and whenever the session's
// id has changed, as a `/clear` changes it with no `session.start` after it.
//
// The map is kept in the project's store, in `.claude/p4/native/host.json`, under `sessions.<session id>`, where
// the session id is `$.session.id()`, which a command hook reads as `session_id` and a shell as
// `CLAUDE_CODE_SESSION_ID`. That file is the one way to read it: a hooks module reads it by `$.fs.read`, a script
// opens it, and a session asks the tool `native` or ezexe types `/native`, each of which prints the same entry. The
// file holds the newest sessions, MOST at most, so it stays small with no sweep. A project with no `.claude/p4` gets
// no file, and the tool and the command still answer from the session's own reading. The plugin's folder holds a
// `.gitignore` of `*`, so nothing in it enters the store's own git repository.
//
// It also watches the conditions of probes.ts: one probe for each decision the platform blocked and each known
// fault of the host. The answers are kept in `.claude/p4/native/probes.json` by the kind of host, such as
// `desktop/interactive` and `terminal/scripted`, since the desktop app runs a Claude Code of its own beside the one
// on the PATH. The probes run when the version kept for this kind of host is not this session's, at the first turn
// of the main conversation, and on request, and never at a start. A probe that would compact the session where the
// platform allows it runs at the turn's end behind this module's own veto, so nothing is ever compacted. An answer
// that differs from the one kept, or from the one its decision was made on where none is kept, becomes a notice in
// the file, which the next prompt of any session of the project carries to the model once and which ezexe reads as
// a line of the transcript.

import type { EngineInterface, Register, ToolCallResult } from 'claude-code'

import {
  EVENTS,
  NO_COMPACTION,
  PROBES,
  SELF,
  SESSIONS,
  VETO,
  busyOf,
  fromMap,
  ofCompact,
  ofEvents,
  ofSelf,
  seenAtStart,
} from './probes'
import type { Answer, Called, Host, Probe, Said } from './probes'

// The project's store, and the map's file inside it.
const STORE = '.claude/p4'
const FILE = 'native/host.json'

// The file that keeps the plugin's folder out of the store's own git repository, and what it holds: what a host can
// do is a fact of one machine, and the store's commits travel to others.
const IGNORE = 'native/.gitignore'
const IGNORED = '*\n'

// The file of the probes' answers and of the notices not yet told.
const BOOK = 'native/probes.json'

// The most sessions the file holds, the newest kept.
const MOST = 24

// How often a write is tried again when another session's write took its place.
const TRIES = 3

// How long one call of a probe may take.
const CALL_MS = 8_000

// What the name of each tool of the desktop app begins with. A session the app hosts has them and no other has.
const APP = 'mcp__ccd_'

// What the commands are, for the slash command and for the tool.
const HINT = 'map | probes | probe'
const USAGE =
  `/native ${HINT}\n` +
  'map prints the capability map of this session, read anew, and where it is kept. probes lists every watched ' +
  'condition with the decision it belongs to and the answer kept for this kind of host. probe reads the probes ' +
  'anew and prints each answer.'

// The tool a session calls for the same commands. It waits behind ToolSearch as an MCP server's tool does, since
// few turns ask what the host is.
const TOOL = {
  name: 'native',
  description:
    'p4-native: what this host is and can do. `command` is map, probes or probe. map answers the capability map ' +
    'of this session, read anew: the desktop app or a terminal, interactive or scripted, the Claude Code version, ' +
    'the tools of the desktop app and of Claude Code that answer here, and the file that keeps it for scripts and ' +
    'other plugins. probes lists the watched conditions, one for each decision the platform blocked, with the ' +
    'answer kept for this kind of host. probe reads them anew, which changes nothing in the session, and says ' +
    'which answer changed.',
  inputSchema: {
    type: 'object',
    properties: { command: { type: 'string', enum: ['map', 'probes', 'probe'] } },
    required: ['command'],
  },
} as const
// The tool's name as a call carries it.
const TOOL_ID = 'mcp__p4-native__native'

// The desktop app's tool that starts a session, which probes.ts names START. It is spelled here too, so that
// `claude plugin validate` reads the tool the module's hook stands on.
const START_ID = 'mcp__ccd_session__start_session'

// What the engine answered, from which an entry is read.
export type Facts = {
  isRepl: boolean
  surfaces: readonly string[]
  tools: readonly { name: string; mcp: boolean }[]
  version?: { version: string; base?: string }
  platform?: string
}

// One probe's answer as the file keeps it, the answers of one kind of host with the version they were read on, and
// the file: the kinds of host by name, and the notices no prompt has carried yet.
type Kept = Said & { claude: string; at: string }
type Ran = { claude: string; at: string; answers: Record<string, Kept> }
type Book = { hosts: Record<string, Ran>; notices: string[] }

// Whether a person is at the prompt of a terminal, and the names of the fields `session.start` carried. A reload of
// the module starts over.
let isRepl = false
let startKeys: string[] = []
// The session id the map was last read for, the entry read then, and the file it was written to, if any.
let keptFor: string | undefined
let kept: Host | undefined
let keptIn: string | undefined
// A reading is in flight: there is never a second one from this module.
let reading: Promise<void> | undefined
// The start's own reading with its look into the probes' file, which the first turn waits for.
let starting: Promise<void> | undefined

// The version kept for this kind of host is not this session's, so the probes run at the first turn.
let isDue = false
// The file holds a notice no prompt has carried yet.
let hasNotices = false
// The probes that wait for the end of the turn, and whether their run stamps the version.
let owed: Probe[] = []
// The origin of the prompt that began the turn under way.
let origin: string | undefined
// The session id whose first turn of the main conversation was seen.
let turnOf: string | undefined

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

// The entry the facts come to, at the moment `at`.
export function hostOf(facts: Facts, at: string): Host {
  const app: string[] = []
  const native: string[] = []
  const servers: Record<string, number> = {}
  for (const tool of facts.tools) {
    if (tool.name.startsWith(APP)) app.push(tool.name)
    else if (!tool.mcp) native.push(tool.name)
    else {
      const server = tool.name.split('__')[1] ?? tool.name
      servers[server] = (servers[server] ?? 0) + 1
    }
  }
  const isDesktop = app.length > 0 || facts.surfaces.includes('desktop')
  const host = isDesktop ? 'desktop' : (facts.surfaces.find(surface => surface !== 'terminal') ?? 'terminal')
  const sorted = Object.fromEntries(Object.entries(servers).sort(([a], [b]) => (a < b ? -1 : 1)))

  return {
    at,
    host,
    run: facts.isRepl || host !== 'terminal' ? 'interactive' : 'scripted',
    claude: facts.version?.version ?? '',
    ...(facts.version?.base === undefined ? {} : { base: facts.version.base }),
    ...(facts.platform === undefined ? {} : { platform: facts.platform }),
    surfaces: [...facts.surfaces],
    tools: { app: app.sort(), native: native.sort(), servers: sorted },
  }
}

// The kind of host an entry is of, by which the probes' answers are kept.
function kindOf(host: Host): string {
  return `${host.host}/${host.run}`
}

// Whether two entries say the same of the host, whenever each was read.
function isSame(a: Host | undefined, b: Host): boolean {
  return a !== undefined && JSON.stringify({ ...a, at: '' }) === JSON.stringify({ ...b, at: '' })
}

// The sessions a file's text holds, and none for a file that is missing or is no such JSON.
function sessionsOf(text: string): Record<string, Host> {
  try {
    const held = (JSON.parse(text) as { sessions?: unknown }).sessions
    return typeof held === 'object' && held !== null ? { ...(held as Record<string, Host>) } : {}
  } catch {
    return {}
  }
}

// The probes' file as its text holds it, and an empty one for a file that is missing or is no such JSON.
function bookOf(text: string): Book {
  try {
    const held = JSON.parse(text) as Partial<Book>
    const hosts = typeof held.hosts === 'object' && held.hosts !== null ? held.hosts : {}
    const notices = Array.isArray(held.notices) ? held.notices.filter(line => typeof line === 'string') : []

    return { hosts: { ...hosts }, notices }
  } catch {
    return { hosts: {}, notices: [] }
  }
}

async function now($: EngineInterface): Promise<string> {
  return new Date(await $.clock.now().catch(() => 0)).toISOString()
}

// Asks the engine each fact. A call that rejects leaves its fact out, so one refusal never costs the whole map.
async function survey($: EngineInterface): Promise<Host> {
  const [version, info, surfaces, tools, at] = await Promise.all([
    $.session.version().catch(() => undefined),
    $.session.info().catch(() => undefined),
    $.session.surfaces().catch(() => []),
    $.tool.list().catch(() => []),
    now($),
  ])
  const facts: Facts = { isRepl, surfaces, tools, version, platform: info?.platform }

  return hostOf(facts, at)
}

// The project's store with the plugin's `.gitignore` in it, or nothing where the project has no store.
async function storeOf($: EngineInterface): Promise<string | undefined> {
  const store = `${slashed(await $.session.root())}/${STORE}`
  if (!(await $.fs.exists(store).catch(() => false))) return undefined
  if (!(await $.fs.exists(`${store}/${IGNORE}`).catch(() => true))) await $.fs.write(`${store}/${IGNORE}`, IGNORED)

  return store
}

// Writes one session's entry into the store's file and answers the file, or nothing where the project has no store
// or the write did not hold. Another session may write between this one's read and its write, so the file is read
// back, and the write is made again where this session's entry is not in it.
async function keep($: EngineInterface, id: string, host: Host): Promise<string | undefined> {
  const store = await storeOf($)
  if (store === undefined) return undefined
  const file = `${store}/${FILE}`
  for (let tries = 0; tries < TRIES; tries++) {
    const sessions = sessionsOf(await $.fs.read(file).catch(() => ''))
    sessions[id] = host
    const newest = Object.entries(sessions)
      .sort(([, a], [, b]) => (String(a?.at) < String(b?.at) ? 1 : -1))
      .slice(0, MOST)
    await $.fs.write(file, `${JSON.stringify({ sessions: Object.fromEntries(newest) }, null, 1)}\n`)
    if (sessionsOf(await $.fs.read(file).catch(() => ''))[id]?.at === host.at) return file
  }
  note($, `the capability map was not kept in ${file}: another write took its place ${TRIES} times`)

  return undefined
}

// One reading of the map: the facts asked, and the entry written where it says something new or was never written
// for this session id.
async function read($: EngineInterface): Promise<void> {
  try {
    const id = await $.session.id()
    const host = await survey($)
    const isNew = id !== keptFor || keptIn === undefined || !isSame(kept, host)
    if (isNew) keptIn = await keep($, id, host)
    keptFor = id
    kept = host
  } catch (error) {
    note($, `the capability map was not read: ${reason(error)}`)
  }
}

// The reading in flight, or a new one.
function look($: EngineInterface): Promise<void> {
  reading ??= read($).finally(() => {
    reading = undefined
  })

  return reading
}

// The probes' file of the project and what it holds, or nothing where the project has no store.
async function open($: EngineInterface): Promise<{ file: string; book: Book } | undefined> {
  const store = await storeOf($)
  if (store === undefined) return undefined
  const file = `${store}/${BOOK}`

  return { file, book: bookOf(await $.fs.read(file).catch(() => '')) }
}

// Once the map is read at a session's start: whether the probes are due, and whether a notice waits. One read of
// the probes' file, and no probe.
async function check($: EngineInterface): Promise<void> {
  try {
    if (kept === undefined || kept.claude === '') return
    const opened = await open($)
    if (opened === undefined) return
    hasNotices = opened.book.notices.length > 0
    isDue = opened.book.hosts[kindOf(kept)]?.claude !== kept.claude
  } catch (error) {
    note($, `the probes' file was not read: ${reason(error)}`)
  }
}

// What a changed answer tells the session.
function changed(probe: Probe, was: Answer, now: Said, host: Host): string {
  const head =
    `p4-native: the watched condition ${probe.id} changed on ${kindOf(host)}, Claude Code ${host.claude}: it was ` +
    `${was} and is ${now.answer}. Saw: ${now.saw}.`

  return now.answer === 'open'
    ? `${head} The decision it belongs to can be reopened: ${probe.decision}`
    : `${head} What this decision rests on no longer holds: ${probe.decision}`
}

// Keeps the answers of one run for this kind of host, and makes a notice of each that differs from the one kept or,
// where none is kept, from the one its decision was made on. A run that read every probe that fits stamps the
// version, and where another version was kept it names the change of version and the probes read by hand. It
// answers the notices it made. With no store nothing is kept, and the notices are answered all the same.
async function settle($: EngineInterface, host: Host, answers: ReadonlyMap<Probe, Said>, isWhole: boolean): Promise<string[]> {
  const opened = await open($)
  const book = opened?.book ?? { hosts: {}, notices: [] }
  const kind = kindOf(host)
  const ran: Ran = book.hosts[kind] ?? { claude: '', at: '', answers: {} }
  const at = await now($)
  const made: string[] = []
  for (const [probe, now] of answers) {
    const was = ran.answers[probe.id]?.answer ?? probe.was
    if (was !== now.answer) made.push(changed(probe, was, now, host))
    ran.answers[probe.id] = { ...now, claude: host.claude, at }
  }
  if (isWhole) {
    const byHand = PROBES.filter(probe => probe.kind !== 'asked' && probe.fits(host)).map(probe => probe.id)
    if (ran.claude !== '' && ran.claude !== host.claude) {
      made.unshift(
        `p4-native: Claude Code changed from ${ran.claude} to ${host.claude} on ${kind}. ${answers.size} probes ran ` +
          `and ${made.length} answers changed. ${byHand.length} watched conditions have no probe that runs by itself: ` +
          `${byHand.join(', ')}. /release-notes says what changed, and /native probes names the check for each.`,
      )
    }
    ran.claude = host.claude
    ran.at = at
  }
  if (opened !== undefined) {
    book.hosts[kind] = ran
    book.notices = [...book.notices, ...made]
    await $.fs.write(opened.file, `${JSON.stringify(book, null, 1)}\n`)
    if (made.length > 0) hasNotices = true
  }
  for (const line of made) $.ui.log(line)

  return made
}

// One call of a tool by the module, for a probe: its text, or the words it was refused or rejected with, or nothing
// where no answer came within CALL_MS.
function call($: EngineInterface, tool: string, input: Record<string, unknown>): Promise<Called | undefined> {
  return new Promise(resolve => {
    const timer = $.clock.after(CALL_MS, () => resolve(undefined))
    const done = (value: Called): void => {
      timer.cancel()
      resolve(value)
    }
    $.tool.call({ ...input, tool } as never).then(
      out => {
        const got = out as { text?: unknown; deny?: unknown; isError?: unknown }
        const text = typeof got.text === 'string' ? got.text : ''
        if (typeof got.deny === 'string') done({ refused: got.deny })
        else done(got.isError === true ? { refused: text } : { text })
      },
      error => done({ refused: reason(error) }),
    )
  })
}

// One probe's reading, and nothing where this session cannot tell. Each call a probe makes reads and changes
// nothing, and the compaction it asks for is vetoed by this module's own hook.
async function askOne($: EngineInterface, probe: Probe, host: Host): Promise<Said | undefined> {
  if (probe.id === 'list-events-of-a-session-at-work') {
    const busy = busyOf((await call($, SESSIONS, { limit: 20 }))?.text)

    return busy === undefined ? undefined : ofEvents(await call($, EVENTS, { session_id: busy, limit: 1 }))
  }
  if (probe.id === 'module-call-of-an-app-tool') return ofSelf(await call($, SELF, { session_id: 'self' }))
  if (probe.id === 'session-compact-from-a-module') {
    try {
      return ofCompact({ skip: (await $.session.compact({ instructions: NO_COMPACTION })).skip })
    } catch (error) {
      return ofCompact({ rejected: reason(error) })
    }
  }

  return fromMap(probe.id, { host, startKeys })
}

// Reads each of the probes given, and leaves out one that cannot tell here or that failed.
async function ask($: EngineInterface, probes: readonly Probe[], host: Host): Promise<Map<Probe, Said>> {
  const answers = new Map<Probe, Said>()
  for (const probe of probes) {
    try {
      const now = await askOne($, probe, host)
      if (now !== undefined) answers.set(probe, now)
    } catch (error) {
      note($, `the probe ${probe.id} failed: ${reason(error)}`)
    }
  }

  return answers
}

// One run of the probes the module asks itself, over the map as it was last read: those that fit this host are read
// now, but for those that wait for the end of the turn, which are owed. It answers what was read and the notices
// made.
async function run($: EngineInterface): Promise<{ answers: Map<Probe, Said>; made: string[]; host: Host } | undefined> {
  const host = kept
  if (host === undefined) return undefined
  isDue = false
  const fit = PROBES.filter(probe => probe.kind === 'asked' && probe.fits(host))
  owed = fit.filter(probe => probe.atTurnEnd === true)
  const answers = await ask($, fit.filter(probe => probe.atTurnEnd !== true), host)

  return { answers, made: await settle($, host, answers, true), host }
}

// The probes owed at the end of a turn of the main conversation.
async function pay($: EngineInterface): Promise<void> {
  const host = kept
  const due = owed
  owed = []
  if (host === undefined || due.length === 0) return
  try {
    await settle($, host, await ask($, due, host), false)
  } catch (error) {
    note($, `the probes at the turn's end were not kept: ${reason(error)}`)
  }
}

// What a call the session made itself showed of a `seen` probe.
async function seen($: EngineInterface, id: string, now: Said | undefined): Promise<void> {
  try {
    const probe = PROBES.find(one => one.id === id)
    if (now === undefined || probe === undefined) return
    await look($)
    if (kept === undefined || !probe.fits(kept)) return
    await settle($, kept, new Map([[probe, now]]), false)
  } catch (error) {
    note($, `what a call showed of ${id} was not kept: ${reason(error)}`)
  }
}

// The notices of the file, taken out of it: each is told once, by whichever session's prompt comes first.
async function take($: EngineInterface): Promise<string[]> {
  hasNotices = false
  const opened = await open($)
  if (opened === undefined || opened.book.notices.length === 0) return []
  await $.fs.write(opened.file, `${JSON.stringify({ ...opened.book, notices: [] }, null, 1)}\n`)

  return opened.book.notices
}

// The map as lines, for ezexe and for the model alike.
function shown(host: Host, id: string, file: string | undefined): string {
  const servers = Object.entries(host.tools.servers).map(([name, count]) => `${name} ${count}`)
  const lines = [
    `host: ${host.host}, ${host.run}, Claude Code ${host.claude || 'of no known version'}` +
      (host.platform === undefined ? '' : ` on ${host.platform}`),
    `surfaces: ${host.surfaces.join(', ') || 'none'}`,
    `tools of the desktop app: ${host.tools.app.length}${host.tools.app.length > 0 ? `: ${host.tools.app.join(', ')}` : ''}`,
    `tools of Claude Code: ${host.tools.native.length}${host.tools.native.length > 0 ? `: ${host.tools.native.join(', ')}` : ''}`,
    `tools of other servers: ${servers.join(', ') || 'none'}`,
    file === undefined
      ? `kept: for this session alone, since the project has no ${STORE}`
      : `kept: ${file}, under sessions.${id}`,
  ]

  return lines.join('\n')
}

// Every watched condition that fits this host, each with its kind, the answer kept, the decision and the fault.
async function listed($: EngineInterface): Promise<string> {
  await look($)
  const host = kept
  if (host === undefined) return 'p4-native could not read the capability map.'
  const opened = await open($)
  const ran = opened?.book.hosts[kindOf(host)]
  const head =
    ran === undefined || ran.claude === ''
      ? `No probe was read on ${kindOf(host)} yet.`
      : `Probes last read on ${kindOf(host)} with Claude Code ${ran.claude}, at ${ran.at}.`
  const lines = PROBES.filter(probe => probe.fits(host)).flatMap(probe => {
    const last = ran?.answers[probe.id]

    return [
      `${probe.id}, ${probe.kind}: ${last === undefined ? 'not read here' : `${last.answer}, ${last.saw}`}`,
      `  decision: ${probe.decision}`,
      `  made on: ${probe.was}. ${probe.fault}`,
      ...(probe.check === undefined ? [] : [`  read by: ${probe.check}`]),
    ]
  })

  return [head, ...lines].join('\n')
}

// One run on request, as lines: each answer read, what waits for the turn's end, and the notices made.
async function probed($: EngineInterface): Promise<string> {
  await look($)
  const ran = await run($)
  if (ran === undefined) return 'p4-native could not read the capability map.'
  const lines = [`Probes read on ${kindOf(ran.host)} with Claude Code ${ran.host.claude}.`]
  for (const [probe, now] of ran.answers) lines.push(`${probe.id}: ${now.answer}, ${now.saw}`)
  for (const probe of owed) lines.push(`${probe.id}: read at the end of this turn, and kept then`)
  lines.push(ran.made.length === 0 ? 'No answer changed.' : 'Changed:', ...ran.made)
  if (keptIn === undefined) lines.push(`Nothing was kept, since the project has no ${STORE}.`)

  return lines.join('\n')
}

// One command, for the slash command and the tool: what it printed, or the usage for a word that is no command.
async function answer($: EngineInterface, typed: string): Promise<string> {
  const name = typed.trim() || 'map'
  if (name === 'probes') return listed($)
  if (name === 'probe') return probed($)
  if (name !== 'map') return USAGE
  await look($)
  if (kept === undefined || keptFor === undefined) return 'p4-native could not read the capability map.'

  return shown(kept, keptFor, keptIn)
}

// The slash command and the tool, registered at each start of the module. A name that is taken is refused with a
// throw, and each is registered whatever became of the other.
async function offer($: EngineInterface): Promise<void> {
  try {
    await $.command.register({
      name: 'native',
      description: 'Prints what this host is and can do, and the watched conditions, as p4-native read them.',
      argumentHint: HINT,
    })
  } catch (error) {
    note($, `/native was not registered: ${reason(error)}`)
  }
  try {
    await $.tool.register(TOOL)
  } catch (error) {
    note($, `the tool native was not registered: ${reason(error)}`)
  }
}

// One text field of a tool call's input, trimmed, and '' for one left out.
function field(e: unknown, name: string): string {
  const value = (e as Record<string, unknown>)[name]

  return typeof value === 'string' ? value.trim() : ''
}

export const register: Register = on => {
  // The session does not wait for the map, and it does wait for the command and the tool, which are then listed
  // from the first prompt.
  on('session.start', async ($, e, next) => {
    isRepl = e.isInteractive
    startKeys = Object.keys(e)
    keptFor = undefined
    turnOf = undefined
    starting = look($).then(() => check($))
    await offer($)

    return next(e)
  })

  // A prompt of the main conversation: its origin is kept for the turn, and it carries the notices that wait, each
  // told once.
  on('prompt.submit', async ($, e, next) => {
    origin = e.origin?.kind
    if (!hasNotices) return next(e)
    const notices = await take($).catch(() => [])
    if (notices.length === 0) return next(e)

    return next({ ...e, context: [...(e.context ?? []), notices.join('\n')] })
  })

  // The first turn of the main conversation under a session id reads the map again, without the turn waiting for
  // it. Where the probes are due, which is once for a version of Claude Code on a kind of host, the turn waits for
  // the map and for them, so a scripted run that ends with its turn keeps their answers.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      const id = await $.session.id().catch(() => undefined)
      if (id !== undefined && id !== turnOf) {
        turnOf = id
        await starting?.catch(() => undefined)
        if (isDue) await look($).then(() => run($)).catch(error => note($, `the probes did not run: ${reason(error)}`))
        else void look($)
      }
    }

    return next(e)
  })

  // The end of a turn of the main conversation, where a call that compacts is allowed: the probes owed are read,
  // and the hook waits for them, which happens once for a version.
  on('turn.complete', async ($, e, next) => {
    const out = await next(e)
    if (e.agentId === undefined && owed.length > 0) await pay($)

    return out
  })

  // A compaction a probe asked for is vetoed, so the probe learns only whether the call reached the hooks.
  on('session.compact', ($, e, next) => (e.instructions === NO_COMPACTION ? { skip: VETO } : next(e)))

  // A start the session makes itself is passed on untouched, and what the app answered is read for the probe that
  // watches it.
  on('tool.call', { tool: START_ID }, async ($, e, next) => {
    const out = await next(e)
    void seen($, 'start-on-an-unattended-turn', seenAtStart(e, out, origin))

    return out
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'native' }, async ($, e) => ({ text: await answer($, e.args) }))

  // A call of the tool. It is served ahead of the permission check, as the docs serve a tool, since it reads the
  // host and changes nothing. Nothing runs beneath, since the tool is nothing but that command.
  on('tool.call', { tool: TOOL_ID }, async ($, e): Promise<ToolCallResult> => ({
    result: await answer($, field(e, 'command')),
  })).catch(() => ({ deny: 'p4-native could not read the host.' }))
}
