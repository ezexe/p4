// p4-native's hooks module: the host layer of ezexe/p4, the one place that knows what this host can do. It runs
// inside Claude Code and starts no process, so a session's start costs it a handful of the engine's own calls.
//
// At a session's start it works out the capability map of the session: the desktop app or a terminal, interactive
// or scripted, the Claude Code version, and which of the desktop app's tools and of Claude Code's own tools answer
// here. Each fact is asked of the engine: `e.isInteractive` of `session.start`, `$.session.surfaces`,
// `$.session.version`, `$.session.info` and `$.tool.list`. No environment variable is read, since a `claude -p` run
// started from a desktop session's shell inherits that session's variables. The map is read again at the first turn
// of the main conversation, when a tool server that was still connecting has answered, whenever the session's
// id has changed, as a `/clear` changes it with no `session.start` after it, and when a surface joins the session
// or leaves it, at `session.attach` and `session.detach`.
//
// The map is kept in the project's store, in `.claude/p4/native/host.json`, under `sessions.<session id>`, where
// the session id is `$.session.id()`, which a command hook reads as `session_id` and a shell as
// `CLAUDE_CODE_SESSION_ID`. That file is the one way to read it: a hooks module reads it by `$.fs.read`, a script
// opens it, and a session asks the tool `native` or ezexe types `/native`, each of which prints the same entry. The
// file holds the newest sessions, MOST at most, so it stays small with no sweep. For a session in a git worktree
// the project's store is the main checkout's, by storeOf. A project with no `.claude/p4` gets
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
//
// Two native features that fit neither p4-phi nor p4-temportal are here, each behind an option of the plugin's
// `userConfig` that is off unless ezexe turns it on, and each a call of Claude Code's own: a push notification by
// the `PushNotification` tool when a turn of a session ezexe is at ends, and a status line that names the host.
// The module wraps neither. With the push on, a session with no such tool notifies on ezexe's own channel by
// `$.ui.notify` at the turn's end, and a session that waits on ezexe, at a permission prompt or idle, pushes when
// Claude Code raises its own notification of that, which the module hears at the classic event `Notification`.
//
// And it hands one line at the moment of a miss, a situation of misses.ts in which a session does by hand what a
// native feature of this host does: after the tool call that shows it, as context beside that call's result, or
// with the next prompt for a miss a turn's end shows. Each situation is told once in a session, a line names only
// a tool the map says answers here, and the option `hints` turns it off. Every row of the record that a p4 plugin
// uses names the rows of misses.ts that watch it, or says why none does. A line refuses nothing. A row checked at a
// The record also tells a session what a native thing is: a word given to the command or the tool is looked up in
// it, and each row found says what the thing does, in Claude Code's own words, and whether it is in this session.
// At a change of version the module keeps the names of the build's commands and tools, tells once what the new
// build holds that the one before did not, and hands that as one line at each later session's start. It fetches
// the docs index then too, by `$.http.fetch`, and names the pages the record has no row for.
//
// call also has an option of its own, `refuse_` and its id, off unless ezexe turns it on: with it on, the by-hand
// call is refused at `tool.call`, before it runs, with the row's line as the refusal, and only where a tool the
// line names answers here. With no such option on, the module hooks no call of another tool.

import type { EngineInterface, Register, ToolCallResult } from 'claude-code'

import {
  EVENTS,
  EVENTS_LIMITS,
  NO_COMPACTION,
  PROBES,
  SELF,
  SESSIONS,
  VETO,
  busyOf,
  fromMap,
  isUnattended,
  ofAllEvents,
  ofCompact,
  ofSelf,
  seenAtStart,
} from './probes'
import type { Answer, Called, Host, Probe, Said } from './probes'
import { counted, findRows, pagesOf, recordOf, rowLines, strayed, unweighed, watched } from './inventory'
import { MISSES, READ_OFF, TERMINAL, WATCHED, WRAP_UP, atCall, atEnd, isNotice, isWake, isWorker, optionOf, scriptOf } from './misses'
import type { Record_ } from './inventory'

// The project's store, and the map's file inside it.
const STORE = '.claude/p4'
const FILE = 'native/host.json'

// The file that keeps the plugin's folder out of the store's own git repository, and what it holds: what a host can
// do is a fact of one machine, and the store's commits travel to others.
const IGNORE = 'native/.gitignore'
const IGNORED = '*\n'

// The file of the probes' answers and of the notices not yet told.
const BOOK = 'native/probes.json'

// The record of what the p4 plugins weighed, in the plugin's own folder.
const RECORD = 'hooks/weighed.json'

// The docs index of Claude Code, one line for a page, which the record's rows of the kind `doc` stand for.
const INDEX = 'https://code.claude.com/docs/llms.txt'
// The most names one line holds, and the most characters of a description in a row's line.
const SHOWN = 12
const BRIEF = 300

// The most sessions the file holds, the newest kept.
const MOST = 24

// How often a write is tried again when another session's write took its place.
const TRIES = 3

// How long one call of a probe may take.
const CALL_MS = 8_000

// Claude Code's own tool that notifies ezexe, on the desktop and, with Remote Control connected, on the phone.
const PUSH = 'PushNotification'
// The most characters of a notification, under the 200 the tool's own description gives.
const PUSH_MOST = 180
// The notifications of Claude Code that say a session waits on ezexe, by the `notification_type` hooks.md lists: a
// permission prompt that has waited about six seconds, and a session idle for about a minute after its answer.
const WAITING = new Set(['permission_prompt', 'idle_prompt'])

// What the name of each tool of the desktop app begins with. A session the app hosts has them and no other has.
const APP = 'mcp__ccd_'

// The settings sources a deny rule can stand in, the highest first, each with where a person finds it.
const SOURCES = [
  ['policy', 'the managed settings'],
  ['local', '.claude/settings.local.json'],
  ['project', '.claude/settings.json'],
  ['user', '~/.claude/settings.json'],
] as const

// What the commands are, for the slash command and for the tool.
const HINT = 'map | probes | probe | weighed | docs | new | <name>'
const USAGE =
  `/native ${HINT}\n` +
  'map prints the capability map of this session, read anew, and where it is kept. probes lists every watched ' +
  'condition with the decision it belongs to and the answer kept for this kind of host. probe reads the probes ' +
  'anew and prints each answer. weighed holds the commands and tools of this session against the record of what ' +
  'the p4 plugins weighed, and names each that has no row. docs holds the docs index against the record. new says ' +
  'what this build holds that the build before did not. Any other word is looked up in the record: each command, ' +
  'tool, hook event, module event, module method and docs page it finds, with what it does.'

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
    'which answer changed. weighed names the slash commands and tools of this session that no p4 plugin has ' +
    'weighed, against the record of what each plugin uses and what it declined. docs holds the docs index of ' +
    'Claude Code against the record and names each page with no row. new says what this build of Claude Code ' +
    'holds that the build before did not. Any other word is looked up: the name of a slash command, a tool, a ' +
    'hook event, an event or a method of the hooks module or a docs page, or a word one of them holds, and each ' +
    'row found says what the thing does, in Claude Code\'s own words, and whether it is in this session.',
  inputSchema: {
    type: 'object',
    properties: {
      command: { type: 'string', description: 'map, probes, probe, weighed, docs or new, or a name or a word to look up.' },
    },
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
type Kept = Said & { claude: string; at: string; reads?: number }
// What a build holds that the build kept before it did not, and what it no longer holds, by name.
type Fresh = { claude: string; since: string; names: string[]; gone: string[] }
type Ran = {
  claude: string
  at: string
  answers: Record<string, Kept>
  unweighed?: string[]
  // The commands and tools of the build, what changed against the build before, and the docs pages told.
  names?: string[]
  fresh?: Fresh
  pages?: string[]
}
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
// The origin of the prompt that began the turn under way, and nothing where that is not told: a prompt that came
// into a running turn may be read inside it or begin the turn after it, and `turn.start` names no origin. Nothing
// too once a prompt that a person may have written came into the turn, which then holds a person's words.
let origin: string | undefined
// A prompt came into the turn under way.
let isJoined = false
// The session id whose first turn of the main conversation was seen.
let turnOf: string | undefined

// The options ezexe turned on, read at each load of the module. Each is off by default.
let wants = { push: false, status: false, hints: true }
// The rows whose by-hand call ezexe chose to have refused, by id.
let refused = new Set<string>()
// In the desktop app: the session id this was asked for, whether that session was started by another, and its
// title.
let askedFor: string | undefined
let isChild = false
let title = ''
// Whether the push of the last turn's end went out, so a session that then sits idle pushes no second time.
let wasSent = false

// What this session's own calls showed: a scripted worker started in a Terminal tab, a notice asked for another
// session's exit, something set that wakes this session, the plugin's own tool or command asked, the deferred
// tools searched, and, in the turn under way, a question put to ezexe by a tool.
let isWorkerOut = false
let isNoticed = false
let isWoken = false
let hasAsked = false
let hasSearched = false
let isPut = false
// The situations a line was handed for in this session, and the lines a turn's end made for the next prompt.
const hinted = new Set<string>()
let waiting: string[] = []

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

// What one question to the engine answered, or nothing where the call rejects or this Claude Code has no such
// method: a call of a method a build lacks throws where it is made, before there is a promise to catch.
async function asked<T>(ask: () => Promise<T>): Promise<T | undefined> {
  try {
    return await ask()
  } catch {
    return undefined
  }
}

// Asks the engine each fact. A call that rejects leaves its fact out, and so does a method this Claude Code lacks,
// so one refusal never costs the whole map. Seen on Claude Code 2.1.322 and 2.1.311, which have no
// `$.session.info`: the entry is written with no `platform`.
async function survey($: EngineInterface): Promise<Host> {
  const [version, info, surfaces, tools, at] = await Promise.all([
    asked(() => $.session.version()),
    asked(() => $.session.info()),
    asked(() => $.session.surfaces()),
    asked(() => $.tool.list()),
    now($),
  ])
  const facts: Facts = { isRepl, surfaces: surfaces ?? [], tools: tools ?? [], version, platform: info?.platform }

  return hostOf(facts, at)
}

// The folders whose store may be the project's: the main checkout's first, where the session runs in a git
// worktree, and then the session's own root. `$.session.repo` gives the main checkout: its `root` is, by the API
// types, "The repository's root, absolute: the main working tree's for a worktree". A session in no repository,
// and a Claude Code that lacks the call, have the session's own root alone.
async function roots($: EngineInterface): Promise<string[]> {
  const own = slashed(await $.session.root())
  let main: string | undefined
  try {
    main = slashed((await $.session.repo())?.root ?? '') || undefined
  } catch {
    main = undefined
  }

  return main === undefined || main === own ? [own] : [main, own]
}

// The project's store with the plugin's `.gitignore` in it, or nothing where the project has no store. For a
// session in a git worktree it is the main checkout's store: the map and the probes' answers say what a host is
// and can do, which is no fact about one checkout, and a worktree's own store goes with the worktree, so each new
// worktree session would start with no answer kept and probe again. Where the main checkout has no store, the
// worktree's own is the project's.
async function storeOf($: EngineInterface): Promise<string | undefined> {
  for (const root of await roots($)) {
    const store = `${root}/${STORE}`
    if (!(await $.fs.exists(store).catch(() => false))) continue
    if (!(await $.fs.exists(`${store}/${IGNORE}`).catch(() => true))) await $.fs.write(`${store}/${IGNORE}`, IGNORED)

    return store
  }

  return undefined
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
    if (wants.status) $.ui.status(`${host.host}, ${host.run}, Claude Code ${host.claude}`)
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
    // What is new in this build, as it was kept at the change of version: one line for this session's first prompt.
    const fresh = opened.book.hosts[kindOf(kept)]?.fresh
    const line = !wants.hints || isDue || fresh?.claude !== kept.claude ? undefined : freshLine(kindOf(kept), fresh)
    if (line !== undefined) waiting.push(line)
  } catch (error) {
    note($, `the probes' file was not read: ${reason(error)}`)
  }
}

// The answer kept for a probe, where it was read by the rule the probe reads by now. One kept under an older rule
// counts as none, so a verdict the older rule got wrong starts no notice when the newer rule corrects it.
function keptOf(ran: Ran | undefined, probe: Probe): Kept | undefined {
  const last = ran?.answers[probe.id]

  return last !== undefined && (last.reads ?? 1) === (probe.reads ?? 1) ? last : undefined
}

// Names in one line: the first SHOWN of them, and how many more there are.
function some(names: readonly string[]): string {
  return names.length > SHOWN ? `${names.slice(0, SHOWN).join(', ')} and ${names.length - SHOWN} more` : names.join(', ')
}

// What is new in a build, as one line, and nothing where the build holds the same names as the one before.
function freshLine(kind: string, fresh: Fresh): string | undefined {
  if (fresh.names.length === 0 && fresh.gone.length === 0) return undefined
  const parts: string[] = []
  if (fresh.names.length > 0) {
    parts.push(`holds ${fresh.names.length} commands and tools that ${fresh.since} did not: ${some(fresh.names)}`)
  }
  if (fresh.gone.length > 0) parts.push(`no longer holds ${some(fresh.gone)}`)

  return (
    `p4-native: Claude Code ${fresh.claude} on ${kind} ${parts.join(', and ')}. /native new lists them, and /native ` +
    'with a name says what one does and whether it is in this session.'
  )
}

// The docs index, fetched through the host, or nothing where no answer came within CALL_MS or the fetch was
// refused. The host is declared under `network.hosts` in the plugin's manifest.
function fetched($: EngineInterface): Promise<string | undefined> {
  return new Promise(resolve => {
    const timer = $.clock.after(CALL_MS, () => resolve(undefined))
    const done = (text: string | undefined, why?: string): void => {
      timer.cancel()
      if (why !== undefined) note($, `the docs index was not fetched: ${why}`)
      resolve(text)
    }
    try {
      $.http.fetch(INDEX).then(
        got => (got.ok ? done(got.text) : done(undefined, `status ${got.status}`)),
        error => done(undefined, reason(error)),
      )
    } catch (error) {
      done(undefined, reason(error))
    }
  })
}

// The docs index held against the record's pages, or nothing where the index was not fetched.
async function pages($: EngineInterface, record: Record_): Promise<{ fresh: string[]; gone: string[]; count: number } | undefined> {
  const index = await fetched($)
  if (index === undefined) return undefined
  const named = pagesOf(index)

  return { ...strayed(record.rows, named), count: named.length }
}

// The record of what was weighed, the commands and tools of this session, and those that have no row in it: the
// slash commands Claude Code ships, its own tools, and the desktop app's. A plugin's command and another server's
// tool are no part of the host. Nothing where the record cannot be read.
async function weigh(
  $: EngineInterface,
  host: Host,
): Promise<{ record: Record_; missing: string[]; names: string[] } | undefined> {
  try {
    const record = recordOf(await $.fs.read(`${slashed($.plugin.root)}/${RECORD}`))
    if (Object.keys(record.rows).length === 0) return undefined
    const commands = (await $.command.list().catch(() => []))
      .filter(command => command.source === 'builtin')
      .map(command => `/${command.name}`)

    const names = [...commands, ...host.tools.native, ...host.tools.app]

    return { record, missing: unweighed(record.rows, names), names }
  } catch (error) {
    note($, `the record of what was weighed was not read: ${reason(error)}`)

    return undefined
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
async function settle(
  $: EngineInterface,
  host: Host,
  answers: ReadonlyMap<Probe, Said>,
  isWhole: boolean,
  missing?: readonly string[],
  more?: { names?: readonly string[]; pages?: { fresh: readonly string[] } },
): Promise<string[]> {
  const opened = await open($)
  const book = opened?.book ?? { hosts: {}, notices: [] }
  const kind = kindOf(host)
  const ran: Ran = book.hosts[kind] ?? { claude: '', at: '', answers: {} }
  const at = await now($)
  const made: string[] = []
  for (const [probe, now] of answers) {
    const was = keptOf(ran, probe)?.answer ?? probe.was
    if (was !== now.answer) made.push(changed(probe, was, now, host))
    ran.answers[probe.id] = { ...now, claude: host.claude, at, ...(probe.reads === undefined ? {} : { reads: probe.reads }) }
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
    if (more?.names !== undefined) {
      // What this build holds that the build kept before it did not, told once here and kept for the first prompt
      // of each later session on this build.
      const before = ran.names
      if (before !== undefined && ran.claude !== '' && ran.claude !== host.claude) {
        const had = new Set(before)
        const has = new Set(more.names)
        const names = more.names.filter(name => !had.has(name))
        ran.fresh = { claude: host.claude, since: ran.claude, names, gone: before.filter(name => !has.has(name)) }
        const line = freshLine(kind, ran.fresh)
        if (line !== undefined) made.push(line)
      }
      ran.names = [...more.names]
    }
    ran.claude = host.claude
    ran.at = at
  }
  if (more?.pages !== undefined) {
    // A page of the docs index with no row is told once for a kind of host, as a name with no row is.
    const told = new Set(ran.pages ?? [])
    const fresh = more.pages.fresh.filter(key => !told.has(key))
    if (fresh.length > 0) {
      made.push(
        `p4-native: the docs index of Claude Code holds ${fresh.length} pages that have no row in the record: ` +
          `${some(fresh)}. Each can be a feature the record does not know, so tell ezexe, and /native docs lists ` +
          'them until lbiza/scripts/native_says.py has given each a row.',
      )
    }
    ran.pages = [...more.pages.fresh]
  }
  if (missing !== undefined) {
    // A name with no row is told once for a kind of host, and again only after it left the build and came back.
    const told = new Set(ran.unweighed ?? [])
    const fresh = missing.filter(name => !told.has(name))
    if (fresh.length > 0) {
      made.push(
        `p4-native: Claude Code ${host.claude} on ${kind} holds ${fresh.length} commands and tools that no p4 plugin ` +
          `has weighed: ${fresh.join(', ')}. Each is in this build with no row in the record, so tell ezexe, and ` +
          `/native weighed lists them until each has a row in hooks/weighed.json.`,
      )
    }
    ran.unweighed = [...missing]
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

    if (busy === undefined) return undefined
    const readings: (Called | undefined)[] = []
    for (const limit of EVENTS_LIMITS) readings.push(await call($, EVENTS, { session_id: busy, limit }))

    return ofAllEvents(readings)
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
  const weighed = await weigh($, host)
  const more = { names: weighed?.names, pages: weighed === undefined ? undefined : await pages($, weighed.record) }

  return { answers, made: await settle($, host, answers, true, weighed?.missing, more), host }
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

// In the desktop app, whether another session started this one, and this session's title, asked once for a
// session id of the app's own `get_session`.
async function place($: EngineInterface): Promise<void> {
  if (askedFor === keptFor) return
  askedFor = keptFor
  isChild = false
  title = ''
  try {
    const own = JSON.parse((await call($, SELF, { session_id: 'self' }))?.text ?? '{}') as Record<string, unknown>
    isChild = typeof own.parentSessionId === 'string' && own.detached !== true
    title = typeof own.title === 'string' ? own.title : ''
  } catch {
    // no answer: the session is taken as one ezexe is at
  }
}

// One push to ezexe, where ezexe turned the option on: in a session with a person at it, which a scripted run is
// not, and not in a session another session started, whose turn's end is told to that session. `said` is what
// the push says: the answer of a turn that ended, or Claude Code's own words for a session that waits. The tool
// itself sends nothing while ezexe is at the keyboard. In a session with no such tool, a turn's end is told on
// ezexe's own notification channel by `$.ui.notify`, the one `preferredNotifChannel` names. A session that waits
// is told by the tool alone, since Claude Code has then raised its own notification on that channel. It answers
// whether the push went out.
async function push($: EngineInterface, said: string, isTurnEnd: boolean): Promise<boolean> {
  try {
    const host = kept
    if (host === undefined || host.run !== 'interactive') return false
    const hasTool = host.tools.native.includes(PUSH)
    if (!hasTool && !isTurnEnd) return false
    if (host.host === 'desktop') await place($)
    if (isChild) return false
    const where = title || slashed(await $.session.root()).split('/').at(-1) || 'Claude Code'
    const line = (said.trim().split('\n')[0] ?? '').replace(/[*_`#]/g, '').trim() || 'the turn ended'
    if (!hasTool) {
      const sent = await $.ui.notify(line.length > PUSH_MOST ? `${line.slice(0, PUSH_MOST - 3)}...` : line, { title: where })
      $.ui.log(`notify: ${sent.isSent ? sent.channel : sent.reason}`, { to: 'debug' })

      return sent.isSent
    }
    const message = `${where}: ${line}`
    const cut = message.length > PUSH_MOST ? `${message.slice(0, PUSH_MOST - 3)}...` : message
    const out = await call($, PUSH, { message: cut, status: 'proactive' })
    $.ui.log(`push: ${out?.text ?? out?.refused ?? 'no answer'}`, { to: 'debug' })

    return out?.text !== undefined && !/\bnot sent\b/i.test(out.text)
  } catch (error) {
    note($, `the push was not sent: ${reason(error)}`)

    return false
  }
}

// The map read once more after the reading in flight, if any, for a change that reading may have come before.
async function again($: EngineInterface): Promise<void> {
  await reading?.catch(() => undefined)
  await look($)
}

// Whether a tool answers in this session, by the map: one of Claude Code's own, one of the desktop app's, or one of
// a server the session holds tools of.
function answersHere(host: Host, name: string): boolean {
  if (host.tools.native.includes(name) || host.tools.app.includes(name)) return true
  const server = /^mcp__(.+?)__/.exec(name)?.[1]

  return server !== undefined && (host.tools.servers[server] ?? 0) > 0
}

// The lines for the situations given: each once in a session, and only where a tool the line names answers here.
function hints(ids: readonly string[]): string[] {
  const host = kept
  if (host === undefined) return []
  const lines: string[] = []
  for (const id of ids) {
    const miss = MISSES.find(one => one.id === id)
    if (miss === undefined || hinted.has(id)) continue
    const here = miss.names.filter(name => answersHere(host, name))
    if (miss.names.length > 0 && here.length === 0) continue
    hinted.add(id)
    lines.push(miss.line.replace('{names}', here.map(name => `\`${name}\``).join(', ')))
  }

  return lines
}

// The refusal of a call about to run, or nothing for a call that goes on: the line of the first row the call
// sets off whose option is on, where a tool the line names answers here, so a session is never refused the
// by-hand way on a host that has no other. A call a hooks module made itself is never refused.
async function refusal($: EngineInterface, e: unknown): Promise<string | undefined> {
  const { tool, tool_use_id: use, ...input } = e as Record<string, unknown>
  if (typeof tool !== 'string' || !READ_OFF.has(tool) || String(use ?? '').startsWith('toolu_plugin_')) return undefined
  await starting?.catch(() => undefined)
  const host = kept
  if (host === undefined) return undefined
  for (const id of atCall(tool, input, keptFor ?? '')) {
    const miss = MISSES.find(one => one.id === id)
    if (miss === undefined || !refused.has(id)) continue
    const here = miss.names.filter(name => answersHere(host, name))
    if (miss.names.length > 0 && here.length === 0) continue
    const line = miss.line.replace('{names}', here.map(name => `\`${name}\``).join(', '))

    return `${line} p4-native refused this call before it ran, since ezexe turned the option \`${optionOf(id)}\` on.`
  }

  return undefined
}

// What one call of this session showed: what it set for later, and the lines for the misses it shows. A command
// typed into a Terminal tab is read for a scripted run, in its own line or in the one script file it runs.
async function called($: EngineInterface, tool: string, input: unknown): Promise<string[]> {
  const given = typeof input === 'object' && input !== null ? (input as Record<string, unknown>) : {}
  if (isNotice(tool, given)) isNoticed = true
  if (isWake(tool, given)) isWoken = true
  if (tool === 'ToolSearch') hasSearched = true
  if (tool === 'AskUserQuestion' || tool === WRAP_UP) isPut = true
  if (tool === TERMINAL) {
    const command = typeof given.command === 'string' ? given.command : ''
    const script = scriptOf(command)
    const source = script === undefined ? '' : await $.fs.read(script).catch(() => '')
    if (isWorker(command) || isWorker(source)) isWorkerOut = true

    return []
  }
  await starting?.catch(() => undefined)

  return hints(atCall(tool, given, keptFor ?? ''))
}

// The notices of the file, taken out of it: each is told once, by whichever session's prompt comes first.
async function take($: EngineInterface): Promise<string[]> {
  hasNotices = false
  const opened = await open($)
  if (opened === undefined || opened.book.notices.length === 0) return []
  await $.fs.write(opened.file, `${JSON.stringify({ ...opened.book, notices: [] }, null, 1)}\n`)

  return opened.book.notices
}

// The deny rules of the settings that take a tool out of a session whole, each with where it stands: a rule with no
// bracket, which by permissions.md "removes the tool from Claude's context entirely". A source that cannot be read
// gives none, so a refused read costs a line and nothing else.
async function denials($: EngineInterface): Promise<[string, string][]> {
  const out: [string, string][] = []
  for (const [source, where] of SOURCES) {
    const held: unknown = await asked(() => $.settings.read({ source }))
    const deny: unknown = (held as { permissions?: { deny?: unknown } } | undefined)?.permissions?.deny
    for (const rule of Array.isArray(deny) ? deny : []) {
      if (typeof rule === 'string' && !rule.includes('(')) out.push([rule, where])
    }
  }

  return out
}

// Where the deny rule that names a tool stands, or nothing: the tool's own name, its server as `mcp__<server>`, or
// a name with `*` in it.
function deniedIn(rules: readonly [string, string][], name: string): string | undefined {
  for (const [rule, where] of rules) {
    const glob = new RegExp(`^${rule.replace(/[.+?^$(){}|[\]\\]/g, '\\$&').replaceAll('*', '.*')}$`)
    if (rule === name || name.startsWith(`${rule}__`) || (rule.includes('*') && glob.test(name))) return where
  }

  return undefined
}

// What a session reads of a tool a deny rule took out of it: the limit is the settings' own.
function deniedLine(where: string): string {
  return (
    `  a deny rule in ${where} takes it out of this session: that is a rule of the settings, which a person or a ` +
    'plugin wrote, and says nothing of what the host can do'
  )
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
    const last = keptOf(ran, probe)

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

// The record held against this session, as lines: its counts, and each command and tool here that has no row.
async function inventory($: EngineInterface): Promise<string> {
  await look($)
  const host = kept
  if (host === undefined) return 'p4-native could not read the capability map.'
  const weighed = await weigh($, host)
  if (weighed === undefined) return 'p4-native could not read the record of what was weighed.'
  const { record, missing } = weighed
  const lines = [
    `The record lists the hook events and the events and methods of the hooks module of Claude Code ${record.claude}, ` +
      'which a module cannot list for the build it runs on, and every slash command and tool an audit weighed.',
    ...counted(record),
    watched(record),
    missing.length === 0
      ? `Every slash command and tool of this session, ${kindOf(host)} on Claude Code ${host.claude}, has a row.`
      : `In this session, ${kindOf(host)} on Claude Code ${host.claude}, and weighed by nobody: ${missing.join(', ')}.`,
    'A plugin that declined a row built nothing on it, which is no advice against using it: /native with a name says what one does.',
    `The record is ${slashed($.plugin.root)}/${RECORD}.`,
  ]

  return lines.join('\n')
}

// A description as one line of a row: its first line, cut at BRIEF characters.
function brief(text: string | undefined): string | undefined {
  const line = (text ?? '').trim().split('\n')[0]?.trim() ?? ''
  if (line === '') return undefined

  return line.length > BRIEF ? `${line.slice(0, BRIEF - 3)}...` : line
}

// A word looked up in the record, as lines: each row it finds, with what the thing does and, for a command or a
// tool, whether it is in this session. A command's and a tool's line is its own description, read from the
// session now, so it is the build's own at every version. What the p4 plugins made of a row comes after, marked
// as theirs: a row a plugin declined is one it built nothing on, and a session may use it all the same.
async function lookedUp($: EngineInterface, word: string): Promise<string> {
  const record = recordOf(await $.fs.read(`${slashed($.plugin.root)}/${RECORD}`).catch(() => ''))
  if (Object.keys(record.rows).length === 0) return `p4-native could not read the record of what was weighed.\n${USAGE}`
  const { keys, count } = findRows(record.rows, word)
  if (keys.length === 0) return `No row of the record holds "${word}".\n${USAGE}`
  const commands = await $.command.list().catch(() => [])
  const tools = (await asked(() => $.tool.list())) ?? []
  const denied = await denials($)
  const lines = keys.flatMap(key => {
    const row = record.rows[key]
    if (row === undefined) return []
    if (row.kind === 'command') {
      const live = commands.find(command => `/${command.name}` === key)

      return rowLines(key, row, { description: brief(live?.description), isHere: live !== undefined })
    }
    if (row.kind === 'tool' && !key.endsWith('__')) {
      const live = tools.find(tool => tool.name === key)
      const where = live === undefined ? deniedIn(denied, key) : undefined
      const [head = '', ...rest] = rowLines(key, row, { description: brief(live?.description), isHere: live !== undefined })

      return where === undefined ? [head, ...rest] : [head, deniedLine(where), ...rest]
    }

    return rowLines(key, row, {})
  })
  if (count > keys.length) lines.push(`${count - keys.length} more rows hold the word, and a longer word finds fewer.`)
  lines.push('What the p4 plugins made of a row says who builds on it, and is no advice against using it.')

  return lines.join('\n')
}

// The docs index held against the record, as lines: each page with no row, and each row whose page is gone.
async function documented($: EngineInterface): Promise<string> {
  const record = recordOf(await $.fs.read(`${slashed($.plugin.root)}/${RECORD}`).catch(() => ''))
  if (Object.keys(record.rows).length === 0) return 'p4-native could not read the record of what was weighed.'
  const held = await pages($, record)
  if (held === undefined) return `p4-native could not fetch the docs index, ${INDEX}.`
  const rows = Object.values(record.rows).filter(row => row.kind === 'doc').length

  return [
    `The docs index, ${INDEX}, holds ${held.count} pages, and the record holds a row for ${rows}.`,
    held.fresh.length === 0 ? 'Every page of the index has a row.' : `With no row: ${held.fresh.join(', ')}.`,
    held.gone.length === 0 ? 'Every row has its page.' : `Rows whose page the index dropped: ${held.gone.join(', ')}.`,
    'lbiza/scripts/native_says.py writes the rows, and /native with a word finds a page by its title or its description.',
  ].join('\n')
}

// What this build holds that the build before did not, as it was kept for this kind of host at the change.
async function newHere($: EngineInterface): Promise<string> {
  await look($)
  const host = kept
  if (host === undefined) return 'p4-native could not read the capability map.'
  const fresh = (await open($))?.book.hosts[kindOf(host)]?.fresh
  if (fresh === undefined || fresh.claude !== host.claude) {
    return `Nothing is kept of a build before Claude Code ${host.claude} on ${kindOf(host)}, so nothing is known to be new.`
  }

  return [
    `Claude Code ${fresh.claude} on ${kindOf(host)}, held against ${fresh.since}.`,
    fresh.names.length === 0 ? 'No new command or tool.' : `New: ${fresh.names.join(', ')}.`,
    fresh.gone.length === 0 ? 'None is gone.' : `Gone: ${fresh.gone.join(', ')}.`,
    '/native with a name says what one does, and /release-notes says what else changed.',
  ].join('\n')
}

// One command, for the slash command and the tool: what it printed. A word that is no command is looked up.
async function answer($: EngineInterface, typed: string): Promise<string> {
  const name = typed.trim() || 'map'
  if (name === 'probes') return listed($)
  if (name === 'probe') return probed($)
  if (name === 'weighed') return inventory($)
  if (name === 'docs') return documented($)
  if (name === 'new') return newHere($)
  if (name !== 'map') return lookedUp($, name)
  await look($)
  if (kept === undefined || keptFor === undefined) return 'p4-native could not read the capability map.'
  const denied = (await denials($)).map(([rule, where]) => `${rule} in ${where}`)
  const more =
    denied.length === 0
      ? []
      : [`deny rules of the settings that take a tool out of a session, which say nothing of what the host can do: ${denied.join(', ')}`]

  return [shown(kept, keptFor, keptIn), ...more].join('\n')
}

// The slash command and the tool, registered at each start of the module. A name that is taken is refused with a
// throw, and each is registered whatever became of the other.
// The command's name is no skill's of this plugin: Claude Code refuses a module's command that is named as one of
// the plugin's own skills, which is why the skill is `host`.
async function offer($: EngineInterface): Promise<void> {
  try {
    await $.command.register({
      name: 'native',
      description: 'Prints what this host is and can do, and looks a native command, tool, event or docs page up by name.',
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

export const register: Register = (on, options) => {
  wants = { push: options.push === true, status: options.status === true, hints: options.hints !== false }
  refused = new Set(MISSES.filter(miss => miss.at === 'call' && options[optionOf(miss.id)] === true).map(miss => miss.id))

  // The session does not wait for the map, and it does wait for the command and the tool, which are then listed
  // from the first prompt.
  on('session.start', async ($, e, next) => {
    isRepl = e.isInteractive
    startKeys = Object.keys(e)
    keptFor = undefined
    turnOf = undefined
    isWorkerOut = false
    isNoticed = false
    isWoken = false
    hasAsked = false
    hasSearched = false
    isPut = false
    hinted.clear()
    waiting = []
    starting = look($).then(() => check($))
    await offer($)

    return next(e)
  })

  // A prompt of the main conversation: it carries the notices that wait, each told once, and the origin of one
  // submitted while the session was idle is kept for the turn it begins. One that carries a `turnId` was typed
  // over a running turn or delivered into it, as a background task's notice is, and began no turn: its origin is
  // not the turn's. Seen in the desktop app on Claude Code 2.1.326: a task's notice arrived in the middle of a turn
  // ezexe's own message began, and a start later in that turn was read as one on an unattended turn. The other
  // way round was seen there too, on 2026-11-22: a task's notice began a turn, ezexe wrote into it twice, and the
  // app then started a session on it, which was read as a start on a turn no person began. So a prompt that came
  // into a turn and is not known to be unattended leaves the turn with no origin, and a start on it says nothing.
  on('prompt.submit', async ($, e, next) => {
    if (e.turnId === undefined) origin = e.origin?.kind
    else {
      isJoined = true
      if (!isUnattended(e.origin?.kind)) origin = undefined
    }
    const notices = hasNotices ? await take($).catch(() => []) : []
    const lines = [...notices, ...waiting]
    waiting = []
    if (lines.length === 0) return next(e)

    return next({ ...e, context: [...(e.context ?? []), lines.join('\n')] })
  })

  // The first turn of the main conversation under a session id reads the map again, without the turn waiting for
  // it. Where the probes are due, which is once for a version of Claude Code on a kind of host, the turn waits for
  // the map and for them, so a scripted run that ends with its turn keeps their answers.
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      isPut = false
      wasSent = false
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
    if (e.agentId === undefined && isJoined) {
      isJoined = false
      origin = undefined
    }
    if (e.agentId === undefined && owed.length > 0) await pay($)
    if (e.agentId === undefined && wants.push && !e.isAborted) {
      void push($, e.answer, true).then(isSent => {
        wasSent = isSent
      })
    }
    if (e.agentId === undefined && wants.hints && !e.isAborted) {
      const lines = hints(atEnd({ isWorkerOut, isNoticed, isWoken, hasAsked, hasSearched, isPut }, e.answer))
      for (const line of lines) $.ui.log(line)
      waiting.push(...lines)
    }

    return out
  })

  // A notification Claude Code raises, heard after the settings hooks beneath: where it says the session waits on
  // ezexe and the push is on, the tool tells ezexe so, in Claude Code's own words. A session that sits idle after
  // a turn whose push went out says nothing twice, and a plugin's own notification is no wait.
  on('classic.Notification', async ($, e, next) => {
    const out = await next(e)
    const isTold = e.notification_type === 'idle_prompt' && wasSent
    if (wants.push && WAITING.has(e.notification_type) && !isTold) void push($, e.message, false)

    return out
  }).catch(($, e, next) => next(e))

  // A surface joined the session or left it, as a phone that opens it or the desktop app that connects: the map
  // is read again once the engine has the change, without the hook waiting for the reading.
  on('session.attach', async ($, e, next) => {
    const out = await next(e)
    void again($)

    return out
  }).catch(($, e, next) => next(e))
  on('session.detach', async ($, e, next) => {
    const out = await next(e)
    void again($)

    return out
  }).catch(($, e, next) => next(e))

  // A compaction a probe asked for is vetoed, so the probe learns only whether the call reached the hooks.
  on('session.compact', ($, e, next) => (e.instructions === NO_COMPACTION ? { skip: VETO } : next(e)))

  // A start the session makes itself is passed on untouched, and what the app answered is read for the probe that
  // watches it.
  on('tool.call', { tool: START_ID }, async ($, e, next) => {
    const out = await next(e)
    void seen($, 'start-on-an-unattended-turn', seenAtStart(e, out, origin))

    return out
  }).catch(($, e, next) => next(e))

  // After a tool call of the session: the hooks beneath answer first and their answer is passed on whole, and a
  // line for a miss the call shows is added to its context. A call a hooks module made itself is no miss.
  on('classic.PostToolUse', async ($, e, next) => {
    const out = await next(e)
    const isOwn = String(e.tool_use_id ?? '').startsWith('toolu_plugin_')
    if (!wants.hints || isOwn || !WATCHED.has(e.tool_name)) return out
    const lines = await called($, e.tool_name, e.tool_input)

    return lines.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...lines] }
  }).catch(($, e, next) => next(e))

  // Before a tool call of the session, and only where ezexe turned a row's option on: a call that does by hand
  // what a native feature does is refused with the line that names the feature, and every other call goes on.
  if (refused.size > 0) {
    on('tool.call', async ($, e, next) => {
      const line = await refusal($, e)

      return line === undefined ? next(e) : { deny: line }
    }).catch(($, e, next) => next(e))
  }

  on('command.run', { command: 'native' }, async ($, e) => {
    hasAsked = true

    return { text: await answer($, e.args) }
  })

  // A call of the tool. It is served ahead of the permission check, as the docs serve a tool, since it reads the
  // host and changes nothing. Nothing runs beneath, since the tool is nothing but that command.
  on('tool.call', { tool: TOOL_ID }, async ($, e): Promise<ToolCallResult> => {
    hasAsked = true

    return { result: await answer($, field(e, 'command')) }
  }).catch(() => ({ deny: 'p4-native could not read the host.' }))
}
