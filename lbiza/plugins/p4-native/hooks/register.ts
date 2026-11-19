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

import type { EngineInterface, Register, ToolCallResult } from 'claude-code'

// The project's store, and the map's file inside it.
const STORE = '.claude/p4'
const FILE = 'native/host.json'

// The file that keeps the plugin's folder out of the store's own git repository, and what it holds: what a host can
// do is a fact of one machine, and the store's commits travel to others.
const IGNORE = 'native/.gitignore'
const IGNORED = '*\n'

// The most sessions the file holds, the newest kept.
const MOST = 24

// How often a write is tried again when another session's write took its place.
const TRIES = 3

// What the name of each tool of the desktop app begins with. A session the app hosts has them and no other has.
const APP = 'mcp__ccd_'

// What the commands are, for the slash command and for the tool.
const HINT = 'map'
const USAGE = `/native ${HINT}\nmap prints the capability map of this session, read anew, and where it is kept.`

// The tool a session calls for the same commands. It waits behind ToolSearch as an MCP server's tool does, since
// few turns ask what the host is.
const TOOL = {
  name: 'native',
  description:
    'p4-native: what this host is and can do. `command` is map. map answers the capability map of this session, ' +
    'read anew: the desktop app or a terminal, interactive or scripted, the Claude Code version, the tools of the ' +
    'desktop app and of Claude Code that answer here, and the file that keeps it for scripts and other plugins.',
  inputSchema: {
    type: 'object',
    properties: { command: { type: 'string', enum: ['map'] } },
    required: ['command'],
  },
} as const
// The tool's name as a call carries it.
const TOOL_ID = 'mcp__p4-native__native'

// One session's entry of the map. `host` is `desktop` for a session the desktop app hosts, `terminal` for one a
// terminal runs, a `claude -p` run among them, and for any other host the name of the surface it draws on. `run`
// is `interactive` where a person is at a prompt and `scripted` where a program hands the session its prompts.
// `tools.app` holds the desktop app's tools by name, `tools.native` Claude Code's own, and `tools.servers` counts
// the tools of every other server by the server's name.
export type Host = {
  at: string
  host: string
  run: 'interactive' | 'scripted'
  claude: string
  base?: string
  platform?: string
  surfaces: string[]
  tools: { app: string[]; native: string[]; servers: Record<string, number> }
}

// What the engine answered, from which an entry is read.
export type Facts = {
  isRepl: boolean
  surfaces: readonly string[]
  tools: readonly { name: string; mcp: boolean }[]
  version?: { version: string; base?: string }
  platform?: string
}

// Whether a person is at the prompt of a terminal, as `session.start` said. A reload of the module starts over.
let isRepl = false
// The session id the map was last read for, the entry read then, and the file it was written to, if any.
let keptFor: string | undefined
let kept: Host | undefined
let keptIn: string | undefined
// A reading is in flight: there is never a second one from this module.
let reading: Promise<void> | undefined

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

// Asks the engine each fact. A call that rejects leaves its fact out, so one refusal never costs the whole map.
async function survey($: EngineInterface): Promise<Host> {
  const [version, info, surfaces, tools, now] = await Promise.all([
    $.session.version().catch(() => undefined),
    $.session.info().catch(() => undefined),
    $.session.surfaces().catch(() => []),
    $.tool.list().catch(() => []),
    $.clock.now().catch(() => 0),
  ])
  const facts: Facts = { isRepl, surfaces, tools, version, platform: info?.platform }

  return hostOf(facts, new Date(now).toISOString())
}

// Writes one session's entry into the store's file and answers the file, or nothing where the project has no store
// or the write did not hold. Another session may write between this one's read and its write, so the file is read
// back, and the write is made again where this session's entry is not in it.
async function keep($: EngineInterface, id: string, host: Host): Promise<string | undefined> {
  const store = `${slashed(await $.session.root())}/${STORE}`
  if (!(await $.fs.exists(store).catch(() => false))) return undefined
  const file = `${store}/${FILE}`
  if (!(await $.fs.exists(`${store}/${IGNORE}`).catch(() => true))) await $.fs.write(`${store}/${IGNORE}`, IGNORED)
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

// One command, for the slash command and the tool: what it printed, or the usage for a word that is no command.
async function answer($: EngineInterface, typed: string): Promise<string> {
  const name = typed.trim() || 'map'
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
      description: 'Prints what this host is and can do, as p4-native read it.',
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
    keptFor = undefined
    void look($)
    await offer($)

    return next(e)
  })

  // The first turn of the main conversation under a session id reads the map again. The turn does not wait for it.
  let turnOf: string | undefined
  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) {
      const id = await $.session.id().catch(() => undefined)
      if (id !== undefined && id !== turnOf) {
        turnOf = id
        void look($)
      }
    }

    return next(e)
  })

  on('command.run', { command: 'native' }, async ($, e) => ({ text: await answer($, e.args) }))

  // A call of the tool. It is served ahead of the permission check, as the docs serve a tool, since it reads the
  // host and changes nothing. Nothing runs beneath, since the tool is nothing but that command.
  on('tool.call', { tool: TOOL_ID }, async ($, e): Promise<ToolCallResult> => ({
    result: await answer($, field(e, 'command')),
  })).catch(() => ({ deny: 'p4-native could not read the capability map.' }))
}
