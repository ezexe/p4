// p4-native's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On, ToolInfo } from 'claude-code'

import { counted, recordOf, rowOf, unweighed, verdictOf } from './inventory'
import { PROBES, START, VETO, busyOf, fromMap, ofAllEvents, ofCompact, ofEvents, ofSelf, seenAtStart } from './probes'

const ROOT = '/work/project'
const FILE = `${ROOT}/.claude/p4/native/host.json`
const IGNORE = `${ROOT}/.claude/p4/native/.gitignore`
const BOOK = `${ROOT}/.claude/p4/native/probes.json`
// The module's tool as a call names it.
const TOOL = 'mcp__p4-native__native'
// What the engine stamps on a command a person types: Enter at the prompt, on the main screen at 80 columns.
const TYPED = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as const

// A session the desktop app hosts, as `session.start` begins one: a program hands it its prompts, and it draws
// nowhere yet.
const HOSTED = { cwd: '/', surface: null, isInteractive: false } as const
// A session at a terminal's prompt.
const AT_A_PROMPT = { cwd: '/', surface: 'terminal', isInteractive: true } as const
// A turn of the main conversation, as the engine starts one and ends it.
const BEGUN = { text: 'go on', turnId: 't1' } as const
const TURN = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const

function tool(name: string): ToolInfo {
  return { name, description: '', mcp: name.startsWith('mcp__') }
}

// The tools of a `claude -p` run, and those the desktop app adds to a session it hosts.
const OWN = ['Read', 'Bash', 'Agent', 'PushNotification'].map(tool)
const OF_THE_APP = ['mcp__ccd_session__start_session', 'mcp__ccd_session_mgmt__get_session', 'mcp__terminal__read_terminal'].map(tool)

// What the desktop app's tools print: this session, the sessions of the account with one at work, and the events
// of a session.
const SELF = '{\n  "sessionId": "local_1",\n  "isRunning": true\n}'
const SESSIONS = JSON.stringify([
  { sessionId: 'local_2', isRunning: false },
  { sessionId: 'local_3', isRunning: true },
])
const NO_MESSAGES = '(no messages)'
// The header is there whether or not anything is under it: a session at work answered with the stub of a tool
// call alone, and one whose rows hold what its assistant said.
const HEADER = 'Session "worker" (running) — showing 20 of 1020 messages\nPass before_uuid="c_1" to page further back.\n\n'
const STUB = `${HEADER}[assistant] (called Write)`
const MESSAGES = `${HEADER}[user] port the flush\n[assistant] (called Read)\n[assistant] The flush is ported.\n[result] done (success), 3 turns`
// The app's refusal of a start on a turn no person began.
const REFUSAL =
  "Start sessions only on the user's own words to you here; this turn runs an automated event, another session's " +
  'message, or the task another session gave you.'

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

// The probes' file as the module keeps it.
type Book = {
  hosts: Record<string, { claude: string; at: string; answers: Record<string, { answer: string; saw: string; claude: string }>; unweighed?: string[] }>
  notices: string[]
}

// A machine: the session's id, the surfaces it draws on, its tools, its version, the files by path, whether the
// project has a store, whether the names /native and native are taken, and what each tool of the desktop app
// answers a call.
type Machine = {
  id?: () => string
  surfaces?: () => string[]
  tools?: () => ToolInfo[] | Promise<ToolInfo[]>
  version?: () => string
  files?: Record<string, string>
  hasStore?: boolean
  isTaken?: boolean
  // What a write does in place of landing, for a write another session's took the place of.
  lost?: () => boolean
  // The record of what was weighed, as the plugin's own file holds it, and the session's slash commands.
  record?: unknown
  commands?: () => { name: string; source: string }[]
  // What a call of a tool answers: its text, or the text of a result that is an error.
  app?: (name: string, input: Record<string, unknown>) => string | { error: string }
}

// What the module registered, wrote, logged and called, how often it asked for the tools, the prompts as they
// reached the engine, and the compactions that reached it.
type Seen = {
  offered: string[]
  tools: { name: string; isDeferred: unknown }[]
  written: string[]
  listed: number
  debugged: string[]
  shown: string[]
  calls: string[]
  prompts: { text: string; context: readonly string[] | undefined }[]
  compacted: number
  files: Record<string, string>
  // Each call of a tool with its input, and the status lines pinned.
  inputs: { tool: string; input: Record<string, unknown> }[]
  status: (string | undefined)[]
}

function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const files = has.files ?? {}
  const seen: Seen = {
    offered: [],
    tools: [],
    written: [],
    listed: 0,
    debugged: [],
    shown: [],
    calls: [],
    prompts: [],
    compacted: 0,
    files,
    inputs: [],
    status: [],
  }
  on('ui.status', (_, e) => {
    seen.status.push(e.text)

    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('prompt.submit', (_, e) => {
    seen.prompts.push({ text: e.text, context: e.context })

    return { text: e.text }
  })
  on('session.compact', (_, e) => {
    seen.compacted += 1

    return { messages: e.messages }
  })
  on('session.id', () => ({ value: (has.id ?? (() => 'cli-0001'))() }))
  on('session.root', () => ({ value: ROOT }))
  on('session.surfaces', () => ({ value: (has.surfaces ?? (() => []))() as never }))
  on('session.version', () => {
    const version = (has.version ?? (() => '2.1.326'))()

    return { value: { version, base: version } }
  })
  on('session.info', () => ({ value: { transcriptPath: '', platform: 'windows' as const, isHosted: false } }))
  on('tool.list', async () => {
    seen.listed += 1

    return { value: await (has.tools ?? (() => OWN))() }
  })
  on('tool.call', (_, e) => {
    const { tool: name, tool_use_id: _id, ...input } = e as Record<string, unknown>
    seen.calls.push(String(name))
    seen.inputs.push({ tool: String(name), input })
    const said = has.app?.(String(name), input)
    // A session with no such tool: nothing beneath answers, and the plugin's call rejects.
    if (said === undefined) throw new Error(`no tool named "${String(name)}" in this session`)
    const text = typeof said === 'string' ? said : said.error

    return { result: [{ type: 'text', text }], text, ...(typeof said === 'string' ? {} : { isError: true }) } as never
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
    const lines = e.to === 'debug' ? seen.debugged : seen.shown
    lines.push(e.text)

    return { value: undefined }
  })
  on('fs.exists', (_, e) => ({
    value: plain(e.path) === `${ROOT}/.claude/p4` ? has.hasStore !== false : files[plain(e.path)] !== undefined,
  }))
  on('command.list', () => ({
    value: (has.commands ?? (() => [])).call(undefined).map(command => ({ ...command, description: '' })) as never,
  }))
  on('fs.read', (_, e) => {
    if (plain(e.path).endsWith('/hooks/weighed.json') && has.record !== undefined) return { value: JSON.stringify(has.record) }
    const text = files[plain(e.path)]

    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.write', (_, e) => {
    seen.written.push(plain(e.path))
    if (plain(e.path) !== FILE || has.lost?.() !== true) files[plain(e.path)] = e.text

    return { value: undefined }
  })

  return seen
}

function entries(seen: Seen): Record<string, Entry> {
  return (JSON.parse(seen.files[FILE] ?? '{"sessions":{}}') as { sessions: Record<string, Entry> }).sessions
}

function book(seen: Seen): Book {
  return JSON.parse(seen.files[BOOK] ?? '{"hosts":{},"notices":[]}') as Book
}

// How often the map's file was written.
function maps(seen: Seen): number {
  return seen.written.filter(path => path === FILE).length
}

// A probes' file that holds a version for one kind of host, with the answers each decision was made on.
function ranOn(kind: string, claude: string, answers: Record<string, string> = {}): string {
  const kept = Object.fromEntries(Object.entries(answers).map(([id, answer]) => [id, { answer, saw: 'earlier', claude, at: '' }]))

  return JSON.stringify({ hosts: { [kind]: { claude, at: '', answers: kept } }, notices: [] })
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
  await $.turn.start(BEGUN)
  await clock.settle()
  expect(seen.listed).toBe(2)
  expect(maps(seen)).toBe(2)
  expect(entries(seen)['cli-0001']?.host).toBe('desktop')

  // A later turn under the same id asks nothing, and a subagent's turn never does.
  await $.turn.start({ ...BEGUN, turnId: 't2' })
  await $.turn.start({ ...BEGUN, turnId: 't3', agentId: 'a1' })
  await clock.settle()
  expect(seen.listed).toBe(2)
  expect(maps(seen)).toBe(2)
})

test('a new session id, as a /clear gives, gets an entry of its own at its first turn', async ($, on) => {
  const clock = mock.clock(on)
  let id = 'cli-0001'
  const seen = machine(on, { id: () => id })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()
  expect(maps(seen)).toBe(1)

  id = 'cli-0002'
  await $.turn.start({ ...BEGUN, turnId: 't2' })
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

  expect(maps(seen)).toBe(3)
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
  expect(out.text).toContain('/native map | probes | probe')
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

test('no probe runs at a start, and the first turn runs them where no version is kept for this kind of host', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(HOSTED)
  await clock.settle()
  expect(seen.written).toEqual([IGNORE, FILE])
  expect(seen.calls).toEqual([])

  await $.turn.start(BEGUN)
  await clock.settle()

  const ran = book(seen).hosts['terminal/scripted']
  expect(ran?.claude).toBe('2.1.326')
  expect(Object.keys(ran?.answers ?? {}).sort()).toEqual([
    'app-tools-in-a-terminal-session',
    'fullscreen-at-session-start',
    'set-goal-tool',
  ])
  expect(ran?.answers['set-goal-tool']).toMatchObject({ answer: 'blocked', claude: '2.1.326' })
  expect(ran?.answers['fullscreen-at-session-start']?.saw).toBe('`session.start` carried cwd, surface, isInteractive')
  // Each answer is the one its decision was made on, so nothing is told.
  expect(book(seen).notices).toEqual([])
  expect(seen.shown).toEqual([])
})

test('a turn that begins before the start\'s reading ended still runs the probes that are due', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: async () => {
      await clock.sleep(1_000)

      return OWN
    },
  })

  await $.session.start(HOSTED)
  const turn = $.turn.start(BEGUN)
  await clock.advance(2_000)
  await turn
  await clock.settle()

  expect(book(seen).hosts['terminal/scripted']?.claude).toBe('2.1.326')
  expect(Object.keys(book(seen).hosts['terminal/scripted']?.answers ?? {}).length).toBe(3)
})

test('a session on the version kept runs no probe, at its start or at its turns', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await $.turn.complete(TURN)
  await clock.settle()

  expect(seen.written.filter(path => path === BOOK)).toEqual([])
  expect(book(seen).hosts['terminal/scripted']?.answers).toEqual({})
})

test('a change of version runs the probes once and names the conditions read by hand beside /release-notes', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { version: () => '2.1.328', files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()

  const notices = book(seen).notices
  expect(notices.length).toBe(1)
  expect(notices[0]).toContain('Claude Code changed from 2.1.326 to 2.1.328 on terminal/scripted.')
  expect(notices[0]).toContain('3 probes ran and 0 answers changed.')
  expect(notices[0]).toContain('skills-copy-named-like-an-installed-plugin')
  expect(notices[0]).toContain('/release-notes says what changed')
  expect(notices[0]).not.toContain('agent-teams-in-the-desktop-app')
  expect(seen.shown).toEqual(notices)
  expect(book(seen).hosts['terminal/scripted']?.claude).toBe('2.1.328')

  // The version is kept now, so a second turn and a second session run nothing.
  const written = seen.written.filter(path => path === BOOK).length
  await $.turn.start({ ...BEGUN, turnId: 't2' })
  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start({ ...BEGUN, turnId: 't3' })
  await clock.settle()
  expect(seen.written.filter(path => path === BOOK).length).toBe(written)
})

test('an answer that changed is told once, at the next prompt, with the decision that can be reopened', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    version: () => '2.1.330',
    tools: () => [...OWN, tool('SetGoal')],
    files: { [BOOK]: ranOn('terminal/scripted', '2.1.328', { 'set-goal-tool': 'blocked' }) },
  })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.prompt.submit({ text: 'first', origin: { kind: 'sdk' }, wait: false } as never)
  await $.turn.start(BEGUN)
  await clock.settle()
  expect(seen.prompts[0]?.context).toBeUndefined()

  const told = book(seen).notices
  expect(told.length).toBe(2)
  expect(told[1]).toContain('the watched condition set-goal-tool changed on terminal/scripted, Claude Code 2.1.330')
  expect(told[1]).toContain('it was blocked and is open. Saw: `SetGoal` is in the tool list.')
  expect(told[1]).toContain("The decision it belongs to can be reopened: p4-phi sets a worker's goal by running `/goal`")
  expect(told[0]).toContain('3 probes ran and 1 answers changed.')

  await $.prompt.submit({ text: 'second', origin: { kind: 'sdk' }, wait: false } as never)
  expect(seen.prompts[1]?.context).toEqual([told.join('\n')])
  expect(book(seen).notices).toEqual([])
  expect(book(seen).hosts['terminal/scripted']?.answers['set-goal-tool']?.answer).toBe('open')

  await $.prompt.submit({ text: 'third', origin: { kind: 'sdk' }, wait: false } as never)
  expect(seen.prompts[2]?.context).toBeUndefined()
})

test('a notice another session left is carried by this session\'s first prompt', async ($, on) => {
  const clock = mock.clock(on)
  const left = JSON.stringify({ hosts: { 'terminal/scripted': { claude: '2.1.326', at: '', answers: {} } }, notices: ['p4-native: one thing changed.'] })
  const seen = machine(on, { files: { [BOOK]: left } })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.prompt.submit({ text: 'first', origin: { kind: 'sdk' }, wait: false } as never)

  expect(seen.prompts[0]?.context).toEqual(['p4-native: one thing changed.'])
  expect(book(seen).notices).toEqual([])
})

test('in a desktop session the probes call the app tools that read, and a fault that went away is told', async ($, on) => {
  const clock = mock.clock(on)
  let events = NO_MESSAGES
  let version = '2.1.326'
  const seen = machine(on, {
    version: () => version,
    tools: () => [...OWN, ...OF_THE_APP],
    surfaces: () => ['desktop'],
    app: name => (name.endsWith('get_session') ? SELF : name.endsWith('list_sessions') ? SESSIONS : events),
  })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()

  expect(seen.calls).toEqual([
    'mcp__ccd_session_mgmt__list_sessions',
    'mcp__ccd_session_mgmt__list_events',
    'mcp__ccd_session_mgmt__list_events',
    'mcp__ccd_session_mgmt__list_events',
    'mcp__ccd_session_mgmt__get_session',
  ])
  const first = book(seen).hosts['desktop/interactive']
  expect(first?.answers['list-events-of-a-session-at-work']).toMatchObject({
    answer: 'blocked',
    saw: 'asked for 3 messages: "(no messages)" for a session at work',
    reads: 2,
  })
  expect(seen.inputs.slice(1, 4).map(call => call.input)).toEqual([
    { session_id: 'local_3', limit: 3 },
    { session_id: 'local_3', limit: 14 },
    { session_id: 'local_3', limit: 30 },
  ])
  expect(first?.answers['module-call-of-an-app-tool']?.answer).toBe('open')
  expect(first?.answers['app-tools-in-a-terminal-session']).toBeUndefined()
  expect(book(seen).notices).toEqual([])

  // The app's next build answers the events of a session at work.
  events = MESSAGES
  version = '2.1.340'
  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start({ ...BEGUN, turnId: 't2' })
  await clock.settle()

  const told = book(seen).notices.join('\n')
  expect(told).toContain('list-events-of-a-session-at-work changed on desktop/interactive, Claude Code 2.1.340')
  expect(told).toContain("can be reopened: p4-phi keeps a worker's reports itself")
  expect(told).toContain('Saw: each of 3 readings held assistant text. 1 of the 4 rows under the header hold assistant text')
})

test('a header with only the stub of a tool call under it is blocked, and an answer kept under an older rule starts no notice', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, ...OF_THE_APP],
    // What the first rule kept, which read the header alone.
    files: { [BOOK]: ranOn('desktop/interactive', '2.1.320', { 'list-events-of-a-session-at-work': 'open' }) },
    app: name => (name.endsWith('get_session') ? SELF : name.endsWith('list_sessions') ? SESSIONS : STUB),
  })

  await $.session.start(HOSTED)
  await clock.settle()
  const before = await $.command.run({ command: 'native', args: 'probes', ...TYPED })
  expect(before.text).toContain('list-events-of-a-session-at-work, asked: not read here')

  await $.turn.start(BEGUN)
  await clock.settle()

  const kept = book(seen).hosts['desktop/interactive']?.answers['list-events-of-a-session-at-work']
  expect(kept).toMatchObject({ answer: 'blocked', reads: 2 })
  expect(kept?.saw).toBe('asked for 3 messages: 0 of the 1 rows under the header hold assistant text, and the last row read: [assistant] (called Write)')
  expect(book(seen).notices.join('\n')).not.toContain('list-events-of-a-session-at-work')
})

test('a call of an app tool that is refused where it answered before is told as what no longer holds', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, ...OF_THE_APP],
    files: { [BOOK]: ranOn('desktop/interactive', '2.1.320', { 'module-call-of-an-app-tool': 'open' }) },
  })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()

  const told = book(seen).notices.join('\n')
  expect(told).toContain('module-call-of-an-app-tool changed on desktop/interactive')
  expect(told).toContain('it was open and is blocked.')
  expect(told).toContain("What this decision rests on no longer holds: p4-phi's hooks module asks the app's own")
})

test('the probe of a plugin\'s compaction runs at the turn\'s end, and its compaction never reaches the engine', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()
  expect(book(seen).hosts['terminal/scripted']?.answers['session-compact-from-a-module']).toBeUndefined()

  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await clock.settle()
  expect(book(seen).hosts['terminal/scripted']?.answers['session-compact-from-a-module']).toBeUndefined()

  await $.turn.complete(TURN)
  await clock.settle()

  // No engine refuses the call here, so it reaches the hooks, where the module's own veto ends it.
  expect(seen.compacted).toBe(0)
  expect(book(seen).hosts['terminal/scripted']?.answers['session-compact-from-a-module']).toMatchObject({ answer: 'open' })
  expect(book(seen).notices.join('\n')).toContain('session-compact-from-a-module changed on terminal/scripted')

  // A later turn's end asks nothing again.
  const written = seen.written.length
  await $.turn.complete(TURN)
  await clock.settle()
  expect(seen.written.length).toBe(written)
})

test('a compaction that is no probe\'s goes on to the engine', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {})
  await $.session.start(HOSTED)
  await clock.settle()

  const asked = { role: 'user' as const, text: 'Port the flush.', toolUses: [] }
  await $.session.compact({ trigger: 'manual', messages: [asked], instructions: 'keep the plan' })
  expect(seen.compacted).toBe(1)
})

test('a start the app refuses is passed on untouched and kept, and a start that goes through on such a turn is told', async ($, on) => {
  const clock = mock.clock(on)
  let isRefused = true
  const seen = machine(on, {
    tools: () => [...OWN, ...OF_THE_APP],
    files: { [BOOK]: ranOn('desktop/interactive', '2.1.326') },
    app: () => (isRefused ? { error: REFUSAL } : '{"sessionId":"local_9","name":"worker"}'),
  })
  await $.session.start(HOSTED)
  await clock.settle()

  await $.prompt.submit({ text: 'a report', origin: { kind: 'peer' }, wait: false } as never)
  const refused = await $.tool.call({ tool: START, initiation: 'user_asked', title: 'worker', prompt: 'do it' } as never)
  await clock.settle()
  expect(refused).toMatchObject({ isError: true, text: REFUSAL })
  expect(book(seen).hosts['desktop/interactive']?.answers['start-on-an-unattended-turn']?.answer).toBe('blocked')
  expect(book(seen).notices).toEqual([])

  // A card, which starts nothing, says nothing of the condition.
  isRefused = false
  await $.tool.call({ tool: START, initiation: 'own_initiative', title: 'worker', prompt: 'do it' } as never)
  await clock.settle()
  expect(book(seen).notices).toEqual([])

  const started = await $.tool.call({ tool: START, initiation: 'user_asked', title: 'worker', prompt: 'do it' } as never)
  await clock.settle()
  expect((started as { text?: unknown }).text).toBe('{"sessionId":"local_9","name":"worker"}')
  expect(book(seen).notices.join('\n')).toContain('start-on-an-unattended-turn changed on desktop/interactive')
  expect(book(seen).notices.join('\n')).toContain('a start went through on a turn a prompt of the origin peer began')
})

test('probe reads the probes on request and prints each answer, and probes lists each decision', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()

  const ran = await $.tool.call({ tool: TOOL, command: 'probe' } as never)
  const lines = String((ran as { result?: unknown }).result)
  expect(lines).toContain('Probes read on terminal/scripted with Claude Code 2.1.326.')
  expect(lines).toContain('set-goal-tool: blocked, `SetGoal` is not in the tool list')
  expect(lines).toContain('session-compact-from-a-module: read at the end of this turn, and kept then')
  expect(lines).toContain('No answer changed.')
  expect(book(seen).hosts['terminal/scripted']?.answers['set-goal-tool']?.answer).toBe('blocked')

  const list = await $.command.run({ command: 'native', args: 'probes', ...TYPED })
  expect(list.text).toContain('Probes last read on terminal/scripted with Claude Code 2.1.326')
  expect(list.text).toContain('set-goal-tool, asked: blocked, `SetGoal` is not in the tool list')
  expect(list.text).toContain('skills-copy-named-like-an-installed-plugin, by hand: not read here')
  expect(list.text).toContain('  read by: run `claude plugin list` in a project that holds the copy')
  expect(list.text).not.toContain('agent-teams-in-the-desktop-app')
})

test('with no store the probes never run by themselves, and a run on request keeps nothing', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { hasStore: false })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await $.turn.complete(TURN)
  await clock.settle()
  expect(seen.written).toEqual([])

  const ran = await $.command.run({ command: 'native', args: 'probe', ...TYPED })
  expect(ran.text).toContain('set-goal-tool: blocked')
  expect(ran.text).toContain('Nothing was kept, since the project has no .claude/p4.')
  expect(seen.written).toEqual([])
})

test('each probe names its decision, and an asked probe is read off what the engine answered', () => {
  const ids = PROBES.map(probe => probe.id)
  expect(new Set(ids).size).toBe(ids.length)
  for (const probe of PROBES) {
    expect(probe.decision.length).toBeGreaterThan(40)
    expect(probe.fault.length).toBeGreaterThan(40)
    if (probe.kind !== 'asked') expect(probe.check?.length ?? 0).toBeGreaterThan(20)
  }

  expect(busyOf(SESSIONS)).toBe('local_3')
  expect(busyOf('not json')).toBeUndefined()
  expect(ofEvents({ text: NO_MESSAGES })?.answer).toBe('blocked')
  expect(ofEvents({ text: STUB })?.answer).toBe('blocked')
  expect(ofEvents({ text: HEADER.trim() })?.answer).toBe('blocked')
  expect(ofEvents({ text: `${HEADER}[result] done (success), 15 turns` })?.answer).toBe('blocked')
  expect(ofEvents({ text: MESSAGES })?.answer).toBe('open')
  expect(ofEvents({ text: 'no such session' })).toBeUndefined()
  // The fault comes and goes, so one reading that shows it is enough, and one that says nothing leaves it unread.
  expect(ofAllEvents([{ text: MESSAGES }, { text: MESSAGES }, { text: MESSAGES }])?.answer).toBe('open')
  expect(ofAllEvents([{ text: MESSAGES }, { text: STUB }, { text: MESSAGES }])).toMatchObject({ answer: 'blocked' })
  expect(ofAllEvents([{ text: MESSAGES }, { text: STUB }, { text: MESSAGES }])?.saw.startsWith('asked for 14 messages: 0 of the 1 rows')).toBe(true)
  expect(ofAllEvents([{ text: MESSAGES }, undefined, { text: MESSAGES }])).toBeUndefined()
  expect(ofEvents({ refused: 'no such session' })).toBeUndefined()
  expect(ofSelf({ text: SELF })?.answer).toBe('open')
  expect(ofSelf({ refused: 'no tool named "mcp__ccd_session_mgmt__get_session" in this session' })?.answer).toBe('blocked')
  expect(ofSelf(undefined)).toBeUndefined()

  // The refusal seen in the desktop app on Claude Code 2.1.326, the veto, and a rejection that says neither.
  const headless = 'session.compact: not available in a headless (-p / SDK) session yet: compaction here runs inside a turn'
  expect(ofCompact({ rejected: headless })?.answer).toBe('blocked')
  expect(ofCompact({ skip: VETO })?.answer).toBe('open')
  expect(ofCompact({ rejected: 'session.compact: called from a tool.call hook' })).toBeUndefined()
  expect(ofCompact({ skip: 'a PreCompact hook blocked it' })).toBeUndefined()

  const host = { at: '', host: 'terminal', run: 'scripted' as const, claude: '2.1.328', surfaces: [], tools: { app: [], native: ['Read'], servers: {} } }
  expect(fromMap('fullscreen-at-session-start', { host, startKeys: [] })).toBeUndefined()
  expect(fromMap('fullscreen-at-session-start', { host, startKeys: ['cwd', 'isFullscreen'] })?.answer).toBe('open')
  expect(fromMap('app-tools-in-a-terminal-session', { host, startKeys: [] })?.answer).toBe('blocked')

  expect(seenAtStart({ initiation: 'user_asked' }, { isError: true, text: REFUSAL }, 'peer')?.answer).toBe('blocked')
  const started = { text: '{"sessionId":"local_9f3a","name":"worker"}' }
  expect(seenAtStart({ initiation: 'user_asked' }, started, 'sdk')).toBeUndefined()
  expect(seenAtStart({ initiation: 'offer' }, started, 'peer')).toBeUndefined()
  expect(seenAtStart({ initiation: 'user_asked' }, started, 'task-notification')?.answer).toBe('open')
  // A refusal in words the probe does not know is no start.
  expect(seenAtStart({ initiation: 'user_asked' }, { text: 'Not started: ask the user first.' }, 'peer')).toBeUndefined()
})

// A session at a terminal's prompt in the project, with Claude Code's own tool that notifies.
const PROMPT = { surfaces: () => ['terminal'], files: { [BOOK]: ranOn('terminal/interactive', '2.1.326') } }

test('with no option on, a session pushes nothing and pins no status line', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { ...PROMPT, app: () => 'sent' })

  await $.session.start(AT_A_PROMPT)
  await clock.settle()
  await $.turn.start(BEGUN)
  await $.turn.complete(TURN)
  await clock.settle()

  expect(seen.calls).toEqual([])
  expect(seen.status).toEqual([])
})

test('push calls PushNotification once at the end of a turn of a session ezexe is at', { options: { push: true } }, async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { ...PROMPT, app: () => 'sent' })

  await $.session.start(AT_A_PROMPT)
  await clock.settle()
  await $.turn.start(BEGUN)
  await $.turn.complete({ ...TURN, answer: '**The flush is ported.**\nThree files changed.' })
  await clock.settle()

  expect(seen.inputs).toEqual([
    { tool: 'PushNotification', input: { message: 'project: The flush is ported.', status: 'proactive' } },
  ])

  // A turn that was stopped and a subagent's turn push nothing.
  await $.turn.complete({ ...TURN, isAborted: true })
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await clock.settle()
  expect(seen.inputs.length).toBe(1)
})

test('push sends nothing in a scripted run, and cuts a long line under the tool\'s 200 characters', { options: { push: true } }, async ($, on) => {
  const clock = mock.clock(on)
  let surfaces: string[] = []
  const seen = machine(on, { surfaces: () => surfaces, files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') }, app: () => 'sent' })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.complete(TURN)
  await clock.settle()
  expect(seen.inputs).toEqual([])

  surfaces = ['terminal']
  await $.session.start(AT_A_PROMPT)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: 'x'.repeat(400) })
  await clock.settle()
  const message = String(seen.inputs[0]?.input.message)
  expect(message.length).toBe(180)
  expect(message.endsWith('...')).toBe(true)
})

test('in the desktop app push names the session by its title and leaves out a session another session started', { options: { push: true } }, async ($, on) => {
  const clock = mock.clock(on)
  let own: Record<string, unknown> = { sessionId: 'local_1', title: 'Port the flush', parentSessionId: 'local_0', detached: false }
  let id = 'cli-0001'
  const seen = machine(on, {
    id: () => id,
    tools: () => [...OWN, ...OF_THE_APP],
    files: { [BOOK]: ranOn('desktop/interactive', '2.1.326') },
    app: name => (name.endsWith('get_session') ? JSON.stringify(own) : 'sent'),
  })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.complete(TURN)
  await clock.settle()
  expect(seen.calls).toEqual(['mcp__ccd_session_mgmt__get_session'])

  own = { sessionId: 'local_2', title: 'Port the flush' }
  id = 'cli-0002'
  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.complete(TURN)
  await $.turn.complete(TURN)
  await clock.settle()
  const pushes = seen.inputs.filter(call => call.tool === 'PushNotification')
  expect(pushes.map(call => call.input.message)).toEqual(['Port the flush: done', 'Port the flush: done'])
  expect(seen.calls.filter(name => name.endsWith('get_session')).length).toBe(2)
})

test('status pins one line that names the host and the version', { options: { status: true } }, async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { ...PROMPT })

  await $.session.start(AT_A_PROMPT)
  await clock.settle()

  expect(seen.status).toEqual(['terminal, interactive, Claude Code 2.1.326'])
})

// A record of what was weighed: a command a plugin uses, one declined, a server's tools and a stem of commands.
const RECORD = {
  claude: '2.1.326',
  rows: {
    '/compact': { kind: 'command', used: ['p4-temportal'] },
    '/color': { kind: 'command', declined: { 'p4-phi': "ezexe's interface." } },
    '/design*': { kind: 'command', declined: { 'p4-phi': 'design work.' } },
    Read: { kind: 'tool', used: ['p4-phi'] },
    Bash: { kind: 'tool', used: ['p4-phi'] },
    Agent: { kind: 'tool', used: ['p4-phi'] },
    PushNotification: { kind: 'tool', used: ['p4-native'] },
    SetGoal: { kind: 'tool', nobody: true },
    mcp__ccd_session__: { kind: 'tool', used: ['p4-phi'] },
    '$.mcp.call': { kind: 'method', nobody: true },
    '$.settings.read': { kind: 'method', open: ['p4-phi'] },
  },
}
const BUILTIN = ['compact', 'color', 'design-sync'].map(name => ({ name, source: 'builtin' }))

test('a change of version names once each command and tool of the build that has no row in the record', async ($, on) => {
  const clock = mock.clock(on)
  let version = '2.1.328'
  let commands = [...BUILTIN, { name: 'whiteboard', source: 'builtin' }, { name: 'lifetime', source: 'plugin' }]
  let tools = [...OWN, tool('Brand'), tool('mcp__ccd_session__start_session'), tool('mcp__ccd_view__show_pane'), tool('mcp__other__thing')]
  const seen = machine(on, {
    version: () => version,
    tools: () => tools,
    commands: () => commands,
    record: RECORD,
    files: { [BOOK]: ranOn('desktop/interactive', '2.1.326') },
    app: name => (name.endsWith('get_session') ? SELF : name.endsWith('list_sessions') ? '[]' : NO_MESSAGES),
  })

  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()

  // A plugin's command and another server's tool are no part of the host, and a key that stands for a server or
  // a stem covers each name under it.
  const told = book(seen).notices.join('\n')
  expect(told).toContain('Claude Code 2.1.328 on desktop/interactive holds 3 commands and tools that no p4 plugin has weighed: /whiteboard, Brand, mcp__ccd_view__show_pane.')
  expect(book(seen).hosts['desktop/interactive']?.unweighed).toEqual(['/whiteboard', 'Brand', 'mcp__ccd_view__show_pane'])

  // The next build holds the same three and one more: the one is told, alone.
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)
  version = '2.1.330'
  commands = [...commands, { name: 'motion', source: 'builtin' }]
  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start({ ...BEGUN, turnId: 't2' })
  await clock.settle()
  const next = book(seen).notices.join('\n')
  expect(next).toContain('holds 1 commands and tools that no p4 plugin has weighed: /motion.')
  expect(next).not.toContain('Brand')

  // A build with nothing new says nothing of the record.
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)
  version = '2.1.331'
  tools = tools.filter(one => one.name !== 'Brand')
  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start({ ...BEGUN, turnId: 't3' })
  await clock.settle()
  expect(book(seen).notices.join('\n')).not.toContain('no p4 plugin has weighed')
  expect(book(seen).hosts['desktop/interactive']?.unweighed).toEqual(['/whiteboard', '/motion', 'mcp__ccd_view__show_pane'])
})

test('weighed prints the record\'s counts and each command and tool of this session with no row', async ($, on) => {
  const clock = mock.clock(on)
  machine(on, { record: RECORD, commands: () => [...BUILTIN, { name: 'whiteboard', source: 'builtin' }] })
  await $.session.start(HOSTED)
  await clock.settle()

  const out = await $.tool.call({ tool: TOOL, command: 'weighed' } as never)
  const lines = String((out as { result?: unknown }).result)
  expect(lines).toContain('of Claude Code 2.1.326, which a module cannot list for the build it runs on')
  expect(lines).toContain('command: 3 rows, 1 used, 0 open, 2 declined, 0 weighed by nobody')
  expect(lines).toContain('tool: 6 rows, 5 used, 0 open, 0 declined, 1 weighed by nobody')
  expect(lines).toContain('method: 2 rows, 0 used, 1 open, 0 declined, 1 weighed by nobody')
  expect(lines).toContain('In this session, terminal/scripted on Claude Code 2.1.326, and weighed by nobody: /whiteboard.')
})

test('with no record to read, a run of the probes says nothing of it and weighed says so', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { version: () => '2.1.328', files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()
  await $.turn.start(BEGUN)
  await clock.settle()
  expect(book(seen).notices.join('\n')).not.toContain('no p4 plugin has weighed')
  expect(book(seen).hosts['terminal/scripted']?.unweighed).toBeUndefined()

  const out = await $.command.run({ command: 'native', args: 'weighed', ...TYPED })
  expect(out.text).toBe('p4-native could not read the record of what was weighed.')
})

test('a row is found by its own key, by a server\'s key and by a stem, and comes to one verdict', () => {
  const { rows } = recordOf(JSON.stringify(RECORD))
  expect(rowOf(rows, '/compact')?.used).toEqual(['p4-temportal'])
  expect(rowOf(rows, 'mcp__ccd_session__start_session')?.used).toEqual(['p4-phi'])
  expect(rowOf(rows, '/design-sync')?.declined).toEqual({ 'p4-phi': 'design work.' })
  expect(rowOf(rows, 'mcp__ccd_view__show_pane')).toBeUndefined()
  expect(unweighed(rows, ['/compact', '/motion', 'Read', 'Brand'])).toEqual(['/motion', 'Brand'])
  expect(verdictOf({ kind: 'tool', used: ['p4-phi'], declined: { 'p4-temportal': 'sessions.' } })).toBe('used')
  expect(verdictOf({ kind: 'method', open: ['p4-phi'] })).toBe('open')
  expect(verdictOf({ kind: 'tool', nobody: true })).toBe('nobody')
  expect(recordOf('not json')).toEqual({ claude: '', rows: {} })
  expect(counted(recordOf(JSON.stringify(RECORD))).length).toBe(5)
})

