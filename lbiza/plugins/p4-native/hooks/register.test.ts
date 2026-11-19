// p4-native's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On, ToolInfo } from 'claude-code'

const ROOT = '/work/project'
const FILE = `${ROOT}/.claude/p4/native/host.json`
const IGNORE = `${ROOT}/.claude/p4/native/.gitignore`
// The module's tool as a call names it.
const TOOL = 'mcp__p4-native__native'
// What the engine stamps on a command a person types: Enter at the prompt, on the main screen at 80 columns.
const TYPED = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as const

// A session the desktop app hosts, as `session.start` begins one: a program hands it its prompts, and it draws
// nowhere yet.
const HOSTED = { cwd: '/', surface: null, isInteractive: false } as const
// A session at a terminal's prompt.
const AT_A_PROMPT = { cwd: '/', surface: 'terminal', isInteractive: true } as const

function tool(name: string): ToolInfo {
  return { name, description: '', mcp: name.startsWith('mcp__') }
}

// The tools of a `claude -p` run, and those the desktop app adds to a session it hosts.
const OWN = ['Read', 'Bash', 'Agent', 'PushNotification'].map(tool)
const OF_THE_APP = ['mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__get_session', 'mcp__terminal__read_terminal'].map(tool)

// One session's entry as the file holds it.
type Entry = {
  at: string
  host: string
  run: string
  claude: string
  base?: string
  platform?: string
  surfaces: string[]
  tools: { app: string[]; native: string[]; servers: Record<string, number> }
}

// A machine: the session's id, the surfaces it draws on, its tools, its version, the files by path, whether the
// project has a store, and whether the names /native and native are taken.
type Machine = {
  id?: () => string
  surfaces?: () => string[]
  tools?: () => ToolInfo[] | Promise<ToolInfo[]>
  version?: string
  files?: Record<string, string>
  hasStore?: boolean
  isTaken?: boolean
  // What a write does in place of landing, for a write another session's took the place of.
  lost?: () => boolean
}

// What the module registered, wrote and logged, and how often it asked for the tools.
type Seen = {
  offered: string[]
  tools: { name: string; isDeferred: unknown }[]
  written: string[]
  listed: number
  debugged: string[]
  files: Record<string, string>
}

function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const files = has.files ?? {}
  const seen: Seen = { offered: [], tools: [], written: [], listed: 0, debugged: [], files }
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('session.id', () => ({ value: (has.id ?? (() => 'cli-0001'))() }))
  on('session.root', () => ({ value: ROOT }))
  on('session.surfaces', () => ({ value: (has.surfaces ?? (() => []))() as never }))
  on('session.version', () => ({ value: { version: has.version ?? '2.1.326', base: has.version ?? '2.1.326' } }))
  on('session.info', () => ({ value: { transcriptPath: '', platform: 'windows' as const, isHosted: false } }))
  on('tool.list', async () => {
    seen.listed += 1

    return { value: await (has.tools ?? (() => OWN))() }
  })
  on('command.register', (_, e) => {
    if (has.isTaken === true) return { deny: '"/native" refused: the name is taken' }
    seen.offered.push(e.name)

    return { value: { command: e.name } }
  })
  on('tool.register', (_, e) => {
    if (has.isTaken === true) return { deny: '"native" refused: the name is taken' }
    seen.tools.push({ name: e.name, isDeferred: e.isDeferred })

    return { value: { tool: `mcp__p4-native__${e.name}` } }
  })
  on('ui.log', (_, e) => {
    if (e.to === 'debug') seen.debugged.push(e.text)

    return { value: undefined }
  })
  on('fs.exists', (_, e) => ({
    value: plain(e.path) === `${ROOT}/.claude/p4` ? has.hasStore !== false : files[plain(e.path)] !== undefined,
  }))
  on('fs.read', (_, e) => {
    const text = files[plain(e.path)]

    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.write', (_, e) => {
    seen.written.push(plain(e.path))
    if (has.lost?.() !== true) files[plain(e.path)] = e.text

    return { value: undefined }
  })

  return seen
}

function entries(seen: Seen): Record<string, Entry> {
  return (JSON.parse(seen.files[FILE] ?? '{"sessions":{}}') as { sessions: Record<string, Entry> }).sessions
}

test('a session the desktop app hosts is read as desktop and interactive, with the app tools by name', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { tools: () => [...OWN, ...OF_THE_APP] })

  await $.session.start(HOSTED)
  await clock.settle()

  const mine = entries(seen)['cli-0001']
  expect(mine?.host).toBe('desktop')
  expect(mine?.run).toBe('interactive')
  expect(mine?.claude).toBe('2.1.326')
  expect(mine?.platform).toBe('windows')
  expect(mine?.tools.app).toEqual(['mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__get_session'])
  expect(mine?.tools.native).toEqual(['Agent', 'Bash', 'PushNotification', 'Read'])
  expect(mine?.tools.servers).toEqual({ terminal: 1 })
  expect(seen.written).toEqual([IGNORE, FILE])
  expect(seen.files[IGNORE]).toBe('*\n')
})

test('a claude -p run is read as a terminal and scripted, and a session at a prompt as interactive', async ($, on) => {
  const clock = mock.clock(on)
  let surfaces: string[] = []
  let id = 'cli-0001'
  const seen = machine(on, { surfaces: () => surfaces, id: () => id })

  await $.session.start(HOSTED)
  await clock.settle()
  expect(entries(seen)['cli-0001']).toMatchObject({ host: 'terminal', run: 'scripted', surfaces: [] })
  expect(entries(seen)['cli-0001']?.tools.app).toEqual([])

  surfaces = ['terminal']
  id = 'cli-0002'
  await $.session.start(AT_A_PROMPT)
  await clock.settle()
  expect(entries(seen)['cli-0002']).toMatchObject({ host: 'terminal', run: 'interactive', surfaces: ['terminal'] })
})

test('the session does not wait for the map, and the command and the tool are registered before it goes on', async ($, on) => {
  const clock = mock.clock(on)
  let isListed = false
  const seen = machine(on, {
    tools: async () => {
      await clock.sleep(5_000)
      isListed = true

      return OWN
    },
  })

  await $.session.start(HOSTED)
  expect(isListed).toBe(false)
  expect(seen.offered).toEqual(['native'])
  expect(seen.tools).toEqual([{ name: 'native', isDeferred: undefined }])

  await clock.advance(5_000)
  await clock.settle()
  expect(isListed).toBe(true)
  expect(entries(seen)['cli-0001']?.host).toBe('terminal')
})

test('the first turn reads the map again, and writes it only where it says something new', async ($, on) => {
  const clock = mock.clock(on)
  let tools = OWN
  const seen = machine(on, { tools: () => tools })

  await $.session.start(HOSTED)
  await clock.settle()
  expect(seen.written).toEqual([IGNORE, FILE])

  // The app's tool server answered after the start.
  tools = [...OWN, ...OF_THE_APP]
  await $.turn.start({ text: 'go on', turnId: 't1' })
  await clock.settle()
  expect(seen.listed).toBe(2)
  expect(seen.written).toEqual([IGNORE, FILE, FILE])
  expect(entries(seen)['cli-0001']?.host).toBe('desktop')

  // A later turn under the same id asks nothing, and a subagent's turn never does.
  await $.turn.start({ text: 'and on', turnId: 't2' })
  await $.turn.start({ text: 'look', turnId: 't3', agentId: 'a1' })
  await clock.settle()
  expect(seen.listed).toBe(2)
  expect(seen.written.length).toBe(3)
})

test('a new session id, as a /clear gives, gets an entry of its own at its first turn', async ($, on) => {
  const clock = mock.clock(on)
  let id = 'cli-0001'
  const seen = machine(on, { id: () => id })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start({ text: 'go on', turnId: 't1' })
  await clock.settle()
  expect(seen.written).toEqual([IGNORE, FILE])

  id = 'cli-0002'
  await $.turn.start({ text: 'afresh', turnId: 't2' })
  await clock.settle()
  expect(Object.keys(entries(seen)).sort()).toEqual(['cli-0001', 'cli-0002'])
})

test('the file keeps the newest sessions and every entry another session wrote', async ($, on) => {
  const clock = mock.clock(on)
  const old = (day: number): Entry => ({
    at: `2026-01-${String(day).padStart(2, '0')}T00:00:00.000Z`,
    host: 'terminal',
    run: 'scripted',
    claude: '2.1.300',
    surfaces: [],
    tools: { app: [], native: [], servers: {} },
  })
  const sessions = Object.fromEntries(Array.from({ length: 24 }, (_, i) => [`old-${i + 1}`, old(i + 1)]))
  const seen = machine(on, { files: { [FILE]: JSON.stringify({ sessions }) } })
  await clock.advance(Date.parse('2026-11-19T12:00:00Z'))

  await $.session.start(HOSTED)
  await clock.settle()

  const kept = Object.keys(entries(seen))
  expect(kept.length).toBe(24)
  expect(kept[0]).toBe('cli-0001')
  expect(kept).not.toContain('old-1')
  expect(kept).toContain('old-2')
})

test('a file that is no JSON is written anew', async ($, on) => {
  const clock = mock.clock(on)
  const broken = machine(on, { files: { [FILE]: 'not json' } })
  await $.session.start(HOSTED)
  await clock.settle()
  expect(entries(broken)['cli-0001']?.host).toBe('terminal')
})

test('a write another session took the place of is made again, three times at most', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { lost: () => true })

  await $.session.start(HOSTED)
  await clock.settle()

  expect(seen.written.filter(path => path === FILE).length).toBe(3)
  expect(seen.debugged.length).toBe(1)
  expect(seen.debugged[0]).toContain('was not kept')
})

test('a project with no store gets no file, and the command still prints the map', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { hasStore: false, tools: () => [...OWN, ...OF_THE_APP], surfaces: () => ['desktop'] })

  await $.session.start(HOSTED)
  await clock.settle()
  expect(seen.written).toEqual([])

  const out = await $.command.run({ command: 'native', args: '', ...TYPED })
  expect(out.text).toContain('host: desktop, interactive, Claude Code 2.1.326 on windows')
  expect(out.text).toContain('surfaces: desktop')
  expect(out.text).toContain('tools of the desktop app: 2: mcp__ccd_session__start_session, mcp__ccd_session_mgmt__get_session')
  expect(out.text).toContain('tools of other servers: terminal 1')
  expect(out.text).toContain('kept: for this session alone, since the project has no .claude/p4')
  expect(seen.written).toEqual([])
})

test('the tool answers the same map as the command, read anew, and names the file', async ($, on) => {
  const clock = mock.clock(on)
  let tools = OWN
  const seen = machine(on, { tools: () => tools })
  await $.session.start(HOSTED)
  await clock.settle()

  tools = [...OWN, ...OF_THE_APP]
  const called = await $.tool.call({ tool: TOOL, command: 'map' } as never)
  const typed = await $.command.run({ command: 'native', args: 'map', ...TYPED })

  expect((called as { result?: unknown }).result).toBe(typed.text)
  expect(typed.text).toContain('host: desktop, interactive')
  expect(typed.text).toContain(`kept: ${FILE}, under sessions.cli-0001`)
  expect(entries(seen)['cli-0001']?.host).toBe('desktop')
})

test('a word that is no command is answered the usage', async ($, on) => {
  const clock = mock.clock(on)
  machine(on, {})
  await $.session.start(HOSTED)
  await clock.settle()

  const out = await $.command.run({ command: 'native', args: 'nosuch', ...TYPED })
  expect(out.text).toContain('/native map')
})

test('a name that is taken costs the session nothing', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { isTaken: true })

  await $.session.start(HOSTED)
  await clock.settle()

  expect(seen.offered).toEqual([])
  expect(seen.debugged.some(text => text.includes('/native was not registered'))).toBe(true)
  expect(seen.debugged.some(text => text.includes('the tool native was not registered'))).toBe(true)
  expect(entries(seen)['cli-0001']?.host).toBe('terminal')
})
