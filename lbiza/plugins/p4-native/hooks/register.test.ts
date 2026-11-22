// p4-native's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On, ToolInfo } from 'claude-code'

import { counted, recordOf, rowOf, unweighed, verdictOf, watched } from './inventory'
import { MISSES, atCall, atEnd } from './misses'
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
  // The main checkout of the repository, for a session in a git worktree of it, as `$.session.repo` answers it,
  // and whether that checkout has a store. With none given the session is in no repository.
  main?: string
  mainHasStore?: boolean
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
  // Each notification raised on ezexe's own channel, as `$.ui.notify` was called.
  notified: { text: string; title: string | undefined }[]
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
    notified: [],
  }
  on('ui.status', (_, e) => {
    seen.status.push(e.text)

    return { value: undefined }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  // A surface that joins the session or leaves it, the settings hooks beneath a notification, and ezexe's own
  // notification channel, which here is a terminal's bell.
  on('session.attach', (_, e) => ({ clientId: e.clientId }))
  on('session.detach', (_, e) => ({ clientId: e.clientId }))
  on('classic.Notification', () => ({}))
  on('ui.notify', (_, e) => {
    seen.notified.push({ text: e.text, title: e.title })

    return { value: { isSent: true, channel: 'terminal_bell' } as const }
  })
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  // What the settings hooks beneath the module answer after a tool call.
  on('classic.PostToolUse', () => ({ additionalContext: ['a settings hook said this'] }))
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
  on('session.repo', () => ({
    value: has.main === undefined ? null : { root: has.main, remote: null, internal: false, name: null },
  }))
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
  on('fs.exists', (_, e) => {
    const path = plain(e.path)
    if (path === `${ROOT}/.claude/p4`) return { value: has.hasStore !== false }
    if (has.main !== undefined && path === `${has.main}/.claude/p4`) return { value: has.mainHasStore !== false }

    return { value: files[path] !== undefined }
  })
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

test("in a git worktree the map and the probes' answers are kept in the main checkout's store", async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { main: '/work/main', tools: () => [...OWN, ...OF_THE_APP] })

  await $.session.start(HOSTED)
  await clock.settle()

  const kept = '/work/main/.claude/p4/native/host.json'
  expect(seen.written).toEqual(['/work/main/.claude/p4/native/.gitignore', kept])
  const mine = (JSON.parse(seen.files[kept] ?? '{}') as { sessions: Record<string, Entry> }).sessions['cli-0001']
  expect(mine?.host).toBe('desktop')
  const out = await $.command.run({ command: 'native', args: '', ...TYPED })
  expect(out.text).toContain(`kept: ${kept}, under sessions.cli-0001`)
  expect(seen.written.some(path => path.startsWith(`${ROOT}/`))).toBe(false)
})

test("where the main checkout has no store, a worktree's own store is the project's", async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { main: '/work/main', mainHasStore: false })

  await $.session.start(HOSTED)
  await clock.settle()

  expect(seen.written).toEqual([IGNORE, FILE])
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

test('a start after a task notice came into a turn a person began leaves the condition as it was', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, ...OF_THE_APP],
    files: { [BOOK]: ranOn('desktop/interactive', '2.1.326', { 'start-on-an-unattended-turn': 'blocked' }) },
    app: () => '{"sessionId":"local_9","name":"worker"}',
  })
  await $.session.start(HOSTED)
  await clock.settle()

  // ezexe's own message begins the turn, and a background task's notice is delivered into it.
  await $.prompt.submit({ text: 'start two sessions', ...TYPED, wait: false } as never)
  await $.turn.start({ text: 'start two sessions', turnId: 'turn-1' })
  const notice = { text: 'a task ended', origin: { kind: 'task-notification' }, turnId: 'turn-1', wait: false }
  await $.prompt.submit(notice as never)
  const started = await $.tool.call({ tool: START, initiation: 'user_asked', title: 'worker', prompt: 'do it' } as never)
  await clock.settle()

  expect((started as { text?: unknown }).text).toBe('{"sessionId":"local_9","name":"worker"}')
  expect(book(seen).notices).toEqual([])
  expect(book(seen).hosts['desktop/interactive']?.answers['start-on-an-unattended-turn']?.answer).toBe('blocked')

  // The turn after it may have been begun by that notice or by nothing told, so a start in it says nothing.
  await $.turn.complete({ ...TURN, turnId: 'turn-1' })
  await $.turn.start({ text: '', turnId: 'turn-2' })
  await $.tool.call({ tool: START, initiation: 'user_asked', title: 'worker', prompt: 'do it' } as never)
  await clock.settle()
  expect(book(seen).notices).toEqual([])

  // A notice that arrives while the session is idle begins a turn, and a start on that turn is told.
  await $.turn.complete({ ...TURN, turnId: 'turn-2' })
  await $.prompt.submit({ text: 'a task ended', origin: { kind: 'task-notification' }, wait: false } as never)
  await $.tool.call({ tool: START, initiation: 'user_asked', title: 'worker', prompt: 'do it' } as never)
  await clock.settle()
  expect(book(seen).notices.join('\n')).toContain('a prompt of the origin task-notification began')
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
  // A used row is watched by a row of misses.ts, says why no by-hand call exists, or says neither.
  const some = { '/a': { kind: 'command', used: ['p4-phi'], miss: ['x'] }, B: { kind: 'tool', used: ['p4-phi'], nowatch: 'Why.' },
    C: { kind: 'tool', used: ['p4-phi'] }, D: { kind: 'tool', declined: { 'p4-phi': 'no' } } }
  expect(watched(recordOf(JSON.stringify({ claude: '2.1.326', rows: some })))).toBe(
    'used: 3 rows, 1 watched by a row of misses.ts, 1 with no by-hand call to watch, 1 with neither',
  )
})

// A tool call of the session, as the classic event after it carries it.
function after(name: string, input: Record<string, unknown>, id = 'toolu_01'): Record<string, unknown> {
  return { tool_name: name, tool_input: input, tool_response: '', tool_use_id: id }
}
const POLL = 'while true; do gh run list --limit 3; sleep 30; done'
const OTHERS = '/home/u/.claude/projects/-work-project/9f3a0000-0000-4000-8000-000000000000.jsonl'

test('a shell loop that polls gh run gets one line beside its result, once, and the hooks beneath keep their say', async ($, on) => {
  const clock = mock.clock(on)
  machine(on, { files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()

  const first = await $.classic.PostToolUse(after('Bash', { command: POLL }) as never)
  expect(first.additionalContext?.[0]).toBe('a settings hook said this')
  expect(first.additionalContext?.[1]).toContain('`gh run watch <run id> --exit-status` ends by itself')
  expect(first.additionalContext?.length).toBe(2)

  // The same situation again in this session, a call that shows none, and a call the module made itself.
  expect((await $.classic.PostToolUse(after('Bash', { command: POLL }) as never)).additionalContext).toEqual(['a settings hook said this'])
  expect((await $.classic.PostToolUse(after('Bash', { command: 'gh run watch 7 --exit-status' }) as never)).additionalContext?.length).toBe(1)
  const own = after('Bash', { command: 'gh run list --commit 81eae97' }, 'toolu_plugin_1')
  expect((await $.classic.PostToolUse(own as never)).additionalContext?.length).toBe(1)

  const short = await $.classic.PostToolUse(after('PowerShell', { command: 'gh run list --repo ezexe/p4 --commit 81eae97' }) as never)
  expect(short.additionalContext?.[1]).toContain('takes the full 40 characters of a commit hash')
  const full = after('Bash', { command: 'gh run list --commit 81eae97e0e0b6c0d6a7d2f1b9c3a4d5e6f708192' })
  expect((await $.classic.PostToolUse(full as never)).additionalContext?.length).toBe(1)
})

test('with hints off no line is handed, and what the hooks beneath answered is passed on', { options: { hints: false } }, async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {})
  await $.session.start(HOSTED)
  await clock.settle()

  const out = await $.classic.PostToolUse(after('Bash', { command: POLL }) as never)
  expect(out.additionalContext).toEqual(['a settings hook said this'])
  await $.turn.complete({ ...TURN, answer: 'The desktop app cannot start a session here.' })
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)
  expect(seen.prompts[0]?.context).toBeUndefined()
})

test('a read of another session\'s transcript file names the app\'s tools that answer here, and none where none does', async ($, on) => {
  const clock = mock.clock(on)
  let tools = [...OWN, tool('mcp__ccd_session_mgmt__list_events'), tool('mcp__ccd_session_mgmt__export_transcript')]
  machine(on, { tools: () => tools, files: { [BOOK]: ranOn('desktop/interactive', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()

  // This session's own transcript file is its own to read.
  const mine = after('Read', { file_path: '/home/u/.claude/projects/-work-project/cli-0001.jsonl' })
  expect((await $.classic.PostToolUse(mine as never)).additionalContext?.length).toBe(1)

  const out = await $.classic.PostToolUse(after('Read', { file_path: OTHERS }) as never)
  const line = out.additionalContext?.[1] ?? ''
  expect(line).toContain("The desktop app's own tools read a session: `mcp__ccd_session_mgmt__list_events`, `mcp__ccd_session_mgmt__export_transcript`.")
  expect(line).not.toContain('search_session_transcripts')

  // In a session with none of those tools the line would name nothing, so none is handed.
  tools = OWN
  await $.session.start(HOSTED)
  await clock.settle()
  const bare = await $.classic.PostToolUse(after('Bash', { command: `tail -5 ${OTHERS}` }) as never)
  expect(bare.additionalContext).toEqual(['a settings hook said this'])
})

test('a worker started in a Terminal tab with nothing asked for its exit is told at the next prompt, once', async ($, on) => {
  const clock = mock.clock(on)
  const script = '/notes/terminal-workers/start-upkeep-1.ps1'
  const seen = machine(on, {
    tools: () => [...OWN, tool('SendMessage'), tool('CronCreate'), tool('mcp__terminal__run_in_terminal')],
    files: { [BOOK]: ranOn('terminal/scripted', '2.1.326'), [script]: "Set-Location 'E:/p'\nclaude -p '/goal do it' --worktree upkeep-1\n" },
  })
  await $.session.start(HOSTED)
  await clock.settle()

  await $.classic.PostToolUse(after('mcp__terminal__run_in_terminal', { command: `& '${script}'`, title: 'upkeep-1' }) as never)
  await $.turn.complete(TURN)
  expect(seen.shown.length).toBe(2)
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)
  const context = seen.prompts[0]?.context?.[0] ?? ''
  expect(context).toContain('`SendMessage` with `notify_when_idle` set to true')
  expect(context).toContain('`CronCreate` schedules a prompt that looks in on the worker.')

  await $.turn.complete(TURN)
  await $.prompt.submit({ text: 'again', origin: { kind: 'sdk' }, wait: false } as never)
  expect(seen.prompts[1]?.context).toBeUndefined()
})

test('a worker whose exit was asked for, and a tab that runs no scripted session, start no line', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, tool('SendMessage'), tool('CronCreate'), tool('mcp__terminal__run_in_terminal')],
    files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') },
  })
  await $.session.start(HOSTED)
  await clock.settle()

  await $.classic.PostToolUse(after('mcp__terminal__run_in_terminal', { command: 'npm run dev' }) as never)
  await $.turn.complete(TURN)
  await $.classic.PostToolUse(after('mcp__terminal__run_in_terminal', { command: "claude -p 'do it' --worktree w1" }) as never)
  await $.classic.PostToolUse(after('SendMessage', { to: 'w1', notify_when_idle: true }) as never)
  await $.turn.complete(TURN)
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)

  expect(seen.shown).toEqual([])
  expect(seen.prompts[0]?.context).toBeUndefined()
})

test('an answer that states a limit of the host is told of the map, unless the session asked the plugin', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, tool('mcp__p4-native__native')],
    files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') },
  })
  await $.session.start(HOSTED)
  await clock.settle()

  await $.turn.complete({ ...TURN, answer: 'The flush is ported and its tests pass.' })
  await $.turn.complete({ ...TURN, answer: 'I left the pane out, since the desktop app does not support a pane that opens unasked.' })
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)
  expect(seen.prompts[0]?.context?.[0]).toContain('call `mcp__p4-native__native` with `map` or `probes` before stating one')

  await $.session.start(HOSTED)
  await clock.settle()
  await $.tool.call({ tool: TOOL, command: 'map' } as never)
  await $.turn.complete({ ...TURN, answer: 'Claude Code cannot list its own hook events from a module.' })
  await $.prompt.submit({ text: 'next', origin: { kind: 'sdk' }, wait: false } as never)
  expect(seen.prompts[1]?.context).toBeUndefined()
})

// What each shell command shows, by the ids of the rows it sets off: one line for each row written from the record,
// and beside it the commands that look alike and are no miss.
const MINE = '/home/u/.claude/projects/-work-project/cli-0001.jsonl'
const SHELL: readonly [string, string, readonly string[]][] = [
  ['Bash', 'cat src/app.ts', ['file-read-by-a-shell']],
  ['Bash', 'head -20 README.md && git status', ['file-read-by-a-shell']],
  ['PowerShell', 'Get-Content -Path notes.md -TotalCount 5', ['file-read-by-a-shell']],
  ['PowerShell', 'type notes.md', ['file-read-by-a-shell']],
  ['Bash', 'type python', []],
  ['Bash', 'git log --oneline | head -5', []],
  ['Bash', 'find . -name "*.ts" -type f', ['files-found-by-a-shell']],
  ['PowerShell', 'Get-ChildItem src -Recurse -Filter *.ts', ['files-found-by-a-shell']],
  ['Bash', 'find build -name "*.tmp" -delete', []],
  ['Bash', 'grep -rn "TODO" src', ['text-searched-by-a-shell']],
  ['PowerShell', 'Select-String -Path *.md -Pattern lifetime', ['text-searched-by-a-shell']],
  ['Bash', 'git diff | grep "^+"', []],
  ['Bash', "sed -i 's/old/new/' config.json", ['file-edited-by-a-shell']],
  ['PowerShell', "(Get-Content a.txt) -replace 'a', 'b' | Set-Content a.txt", ['file-edited-by-a-shell']],
  ['Bash', "sed -n '1,20p' file.txt", []],
  ['Bash', 'echo "hello" > out.txt', ['file-written-by-a-shell']],
  ['Bash', "cat > notes.md <<'EOF'\nline\nEOF", ['file-written-by-a-shell']],
  ['Bash', 'echo "failed" >&2', []],
  ['Bash', 'npm test > test.log 2>&1', []],
  ['Bash', 'powershell -NoProfile -Command "Get-Date"', ['powershell-run-from-bash']],
  ['PowerShell', 'bash -c "ls -la"', ['bash-run-from-powershell']],
  ['PowerShell', 'pwsh -Command "Get-Date"', []],
  ['Bash', 'curl -s https://example.com/docs/page.html', ['page-fetched-by-a-shell']],
  ['Bash', 'curl -s http://localhost:3000/health', []],
  ['Bash', 'curl -X POST https://api.example.com/items -d "{}"', []],
  ['Bash', 'curl -sL -o tool.zip https://example.com/tool.zip', []],
  ['Bash', 'curl -s "https://www.google.com/search?q=claude+code+hooks"', ['search-engine-fetched']],
  ['Bash', 'curl -s https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md', ['release-notes-fetched-by-hand']],
  ['Bash', 'claude -p "port the flush" --output-format json', ['claude-run-in-a-shell']],
  ['Bash', 'for f in a b c; do claude -p "port $f" & done; wait', ['claude-runs-fanned-out-in-a-shell']],
  ['Bash', 'claude --resume 9f3a0000 -p "carry on"', ['session-messaged-in-a-shell']],
  ['Bash', 'claude --resume 9f3a0000 --fork-session', ['session-resumed-in-a-shell']],
  ['Bash', 'claude plugin validate plugins/p4-native --strict', []],
  ['PowerShell', 'start report.html', ['page-opened-from-a-shell']],
  ['Bash', 'ps aux | grep claude', ['sessions-found-by-their-processes']],
  ['PowerShell', 'New-BurntToastNotification -Text "done"', ['notification-raised-from-a-shell']],
  ['Bash', 'sleep 300', ['long-sleep-in-a-shell']],
  ['PowerShell', 'Start-Sleep -Seconds 120', ['long-sleep-in-a-shell']],
  ['Bash', 'sleep 5 && curl -s http://localhost:3000/', []],
  ['PowerShell', 'Start-Sleep -Milliseconds 500', []],
  ['Bash', 'while true; do npm test; sleep 30; done', ['loop-with-a-sleep-in-a-shell']],
  ['Bash', 'cat ~/.claude/skills/review/SKILL.md', ['skill-read-as-a-file']],
  ['Bash', 'kill -9 4242', ['process-killed-in-a-shell']],
  ['PowerShell', 'Get-Process node | Stop-Process -Force', ['process-killed-in-a-shell']],
  ['Bash', 'git commit -m "kill the flaky test"', []],
  ['Bash', 'cp config.json config.json.bak', ['backup-copy-made-by-hand']],
  ['Bash', 'git worktree remove ../feature', ['worktree-removed-in-a-shell']],
  ['Bash', 'du -sh ~/.claude', ['store-measured-in-a-shell']],
  ['Bash', `cp ${MINE} /tmp/mine.jsonl`, ['transcript-copied-by-hand']],
  ['Bash', `wc -c ${MINE}`, ['transcript-measured-by-hand']],
  ['Bash', 'export ANTHROPIC_MODEL=claude-opus-5-5', ['model-set-by-hand']],
  ['Bash', 'rm .claude/p4/temportal/notebook/old.md', ['store-file-removed-by-hand']],
  ['Bash', 'rm -rf ~/.claude/plugins/cache/p4-marketplace', ['plugin-files-changed-by-hand']],
  ['Bash', 'ls ~/.claude/plugins/cache', []],
  ['Bash', 'npm test && git push', []],
]

// The same for a call of another tool.
const OTHER: readonly [string, Record<string, unknown>, readonly string[]][] = [
  ['Edit', { file_path: '/work/analysis.ipynb', old_string: 'a', new_string: 'b' }, ['notebook-edited-as-a-file']],
  ['Write', { file_path: '/work/project/.claude/settings.json', content: '{"model": "opus"}' }, ['model-set-by-hand']],
  ['Edit', { file_path: '/work/project/.claude/settings.json', old_string: '"x"', new_string: '"hooks": {}' }, []],
  ['Edit', { file_path: '/work/project/.claude/p4/temportal/expires.json', old_string: 'a', new_string: 'b' }, ['store-file-removed-by-hand']],
  ['Write', { file_path: '/home/u/.claude/plugins/installed_plugins.json', content: '{}' }, ['plugin-files-changed-by-hand']],
  ['Read', { file_path: '/home/u/.claude/skills/review/SKILL.md' }, ['skill-read-as-a-file']],
  ['Read', { file_path: '/work/project/src/app.ts' }, []],
  ['WebFetch', { url: 'https://duckduckgo.com/?q=claude+code', prompt: 'results' }, ['search-engine-fetched']],
  ['WebFetch', { url: 'https://github.com/anthropics/claude-code/releases', prompt: 'new' }, ['release-notes-fetched-by-hand']],
  ['WebFetch', { url: 'https://code.claude.com/docs/en/hooks.md', prompt: 'events' }, []],
  ['Agent', { description: 'Review the diff', prompt: 'Review this diff for bugs.' }, ['review-handed-to-an-agent']],
  ['Agent', { description: 'Find the callers', prompt: 'List every caller of flush().' }, []],
  ['TaskCreate', { subject: 'port the flush' }, ['task-list-kept-by-another-tool']],
]

test('each row written from the record is set off by its by-hand call and by none that only looks alike', () => {
  const set = new Set<string>()
  for (const [name, command, ids] of SHELL) {
    expect([name, command, atCall(name, { command }, 'cli-0001')]).toEqual([name, command, [...ids]])
    for (const id of ids) set.add(id)
  }
  for (const [name, input, ids] of OTHER) {
    expect([name, input, atCall(name, input, 'cli-0001')]).toEqual([name, input, [...ids]])
    for (const id of ids) set.add(id)
  }
  // Every row checked at a call is set off by at least one line above, but for the three seen live, which have
  // tests of their own.
  const live = ['gh-run-polled-in-a-loop', 'gh-run-list-short-commit', 'transcript-read-from-disk']
  const atACall = MISSES.filter(miss => miss.at === 'call' && !live.includes(miss.id)).map(miss => miss.id)
  expect(atACall.filter(id => !set.has(id))).toEqual([])
  expect(atACall.length).toBe(32)
})

test('a turn\'s answer sets off the rows read off it, and a session that used the tool sets off none', () => {
  const quiet = { isWorkerOut: false, isNoticed: false, isWoken: false, hasAsked: true, hasSearched: false, isPut: false }
  const asked = 'Two ways to go.\n\n- A) keep the cache\n- B) drop the cache\n\nWhich one should I take?'
  expect(atEnd(quiet, asked)).toEqual(['question-asked-in-prose'])
  expect(atEnd({ ...quiet, isPut: true }, asked)).toEqual([])
  expect(atEnd(quiet, 'Done. Should I push it?')).toEqual([])
  expect(atEnd(quiet, "I don't have a tool for reading the browser here.")).toEqual(['tool-said-missing-with-no-search'])
  expect(atEnd({ ...quiet, hasSearched: true }, "I don't have a tool for reading the browser here.")).toEqual([])
  expect(atEnd(quiet, 'This conversation is getting long, so start a new session for the next part.')).toEqual(['context-said-full'])
  expect(atEnd(quiet, 'Can you paste the error output from the build?')).toEqual(['terminal-output-asked-of-ezexe'])
  expect(atEnd(quiet, 'Run `npm install` in your terminal and tell me when it is done.')).toEqual(['command-handed-to-ezexe'])
  expect(atEnd(quiet, 'The flush is ported and its tests pass.')).toEqual([])
  expect(MISSES.filter(miss => miss.at === 'end').length).toBe(8)
})

test('a row written from the record hands its line beside the call, and only where the tool it names answers here', async ($, on) => {
  const clock = mock.clock(on)
  let tools = [...OWN, tool('Grep'), tool('WebFetch')]
  const seen = machine(on, { tools: () => tools, files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()

  const grep = await $.classic.PostToolUse(after('Bash', { command: 'grep -rn "TODO" src' }) as never)
  expect(grep.additionalContext?.[1]).toContain('`Grep` is the same search with ripgrep')
  // `Read` and `Agent` answer here, so a command that shows two misses hands two lines.
  const two = await $.classic.PostToolUse(after('Bash', { command: 'cat a.txt; claude -p "go"' }) as never)
  expect(two.additionalContext?.length).toBe(3)
  expect(two.additionalContext?.[2]).toContain('is started by `Agent`.')
  // No `Glob`, no `Workflow` and no tool of the desktop app here, so those rows hand nothing.
  expect((await $.classic.PostToolUse(after('Bash', { command: 'find . -name "*.ts"' }) as never)).additionalContext?.length).toBe(1)
  expect((await $.classic.PostToolUse(after('TaskCreate', { subject: 'x' }) as never)).additionalContext?.length).toBe(1)
  // A row that names a command alone needs no tool.
  const kept = await $.classic.PostToolUse(after('Bash', { command: 'cp a.json a.json.bak' }) as never)
  expect(kept.additionalContext?.[1]).toContain('`/rewind` brings one back')

  // A question put by a tool in the turn is no question in prose, and the next turn starts over.
  tools = [...tools, tool('AskUserQuestion'), tool('ToolSearch')]
  await $.session.start(HOSTED)
  await clock.settle()
  const asked = 'Two ways.\n\n1. keep it\n2. drop it\n\nWhich one?'
  await $.turn.start(BEGUN)
  await $.classic.PostToolUse(after('AskUserQuestion', { questions: [] }) as never)
  await $.turn.complete({ ...TURN, answer: asked })
  expect(seen.shown).toEqual([])
  await $.turn.start({ ...BEGUN, turnId: 't2' })
  await $.turn.complete({ ...TURN, turnId: 't2', answer: asked })
  expect(seen.shown.length).toBe(1)
  expect(seen.shown[0]).toContain('put to ezexe as buttons by `AskUserQuestion`.')
})

const REFUSING = { refuse_text_searched_by_a_shell: true, refuse_files_found_by_a_shell: true, refuse_backup_copy_made_by_hand: true }

test('with a row\'s option on, its by-hand call is refused before it runs, with the line that names the native tool', { options: REFUSING }, async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, tool('Grep')],
    app: () => 'ran',
    files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') },
  })
  await $.session.start(HOSTED)
  await clock.settle()

  const out = (await $.tool.call({ tool: 'Bash', command: 'grep -rn "TODO" src' } as never)) as { deny?: string }
  expect(out.deny).toContain('`Grep` is the same search with ripgrep')
  expect(out.deny).toContain('p4-native refused this call before it ran, since ezexe turned the option `refuse_text_searched_by_a_shell` on.')
  expect(seen.calls).toEqual([])

  // A call that shows no miss, one whose row's option is off, and one whose tool, `Glob`, does not answer here go on.
  for (const command of ['npm test', 'cat a.txt', 'find . -name "*.ts"']) {
    const ran = (await $.tool.call({ tool: 'Bash', command } as never)) as { deny?: string; text?: string }
    expect([command, ran.deny, ran.text]).toEqual([command, undefined, 'ran'])
  }
  expect(seen.calls).toEqual(['Bash', 'Bash', 'Bash'])

  // A row that names a slash command alone needs no tool, and a call a hooks module made itself is never refused.
  const kept = (await $.tool.call({ tool: 'Bash', command: 'cp a.json a.json.bak' } as never)) as { deny?: string }
  expect(kept.deny).toContain('`/rewind` brings one back')
  const own = (await $.tool.call({ tool: 'Bash', tool_use_id: 'toolu_plugin_1', command: 'grep -rn "TODO" src' } as never)) as { deny?: string }
  expect(own.deny).toBeUndefined()
  expect(seen.calls.length).toBe(4)
})

test('with no such option on, a by-hand call goes on and gets its line, and with hints off it is refused all the same', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, {
    tools: () => [...OWN, tool('Grep')],
    app: () => 'ran',
    files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') },
  })
  await $.session.start(HOSTED)
  await clock.settle()

  const out = (await $.tool.call({ tool: 'Bash', command: 'grep -rn "TODO" src' } as never)) as { deny?: string; text?: string }
  expect([out.deny, out.text]).toEqual([undefined, 'ran'])
  expect(seen.calls).toEqual(['Bash'])
  const after_ = await $.classic.PostToolUse(after('Bash', { command: 'grep -rn "TODO" src' }) as never)
  expect(after_.additionalContext?.[1]).toContain('`Grep` is the same search with ripgrep')
})

test('a refusal needs no line: with hints off and a row\'s option on the call is still refused', { options: { hints: false, refuse_text_searched_by_a_shell: true } }, async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { tools: () => [...OWN, tool('Grep')], app: () => 'ran', files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()

  const out = (await $.tool.call({ tool: 'Bash', command: 'grep -rn "TODO" src' } as never)) as { deny?: string }
  expect(out.deny).toContain('refuse_text_searched_by_a_shell')
  expect(seen.calls).toEqual([])
})

test('a surface that joins the session or leaves it has the map read again', async ($, on) => {
  const clock = mock.clock(on)
  let surfaces: string[] = []
  const seen = machine(on, { surfaces: () => surfaces, files: { [BOOK]: ranOn('terminal/scripted', '2.1.326') } })
  await $.session.start(HOSTED)
  await clock.settle()
  expect(entries(seen)['cli-0001']?.surfaces).toEqual([])
  expect(entries(seen)['cli-0001']?.host).toBe('terminal')

  // The desktop app connects: the hook passes the engine's answer on and the entry holds the surface.
  surfaces = ['desktop']
  const joined = await $.session.attach({ surface: 'desktop', clientId: 'desktop:default' } as never)
  expect(joined).toEqual({ clientId: 'desktop:default' })
  await clock.settle()
  expect(entries(seen)['cli-0001']?.surfaces).toEqual(['desktop'])
  expect(entries(seen)['cli-0001']?.host).toBe('desktop')

  surfaces = []
  await $.session.detach({ surface: 'desktop', clientId: 'desktop:default', reason: 'detach' } as never)
  await clock.settle()
  expect(entries(seen)['cli-0001']?.surfaces).toEqual([])
  expect(maps(seen)).toBe(3)
})

test('with the push on, a session with no PushNotification tool notifies on ezexe\'s own channel at a turn\'s end', { options: { push: true } }, async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { surfaces: () => ['terminal'], tools: () => ['Read', 'Bash'].map(tool) })
  await $.session.start(AT_A_PROMPT)
  await clock.settle()
  await $.turn.start(BEGUN)
  await $.turn.complete({ ...TURN, answer: '**The flush is ported.**\nThree files changed.' })
  await clock.settle()

  expect(seen.notified).toEqual([{ text: 'The flush is ported.', title: 'project' }])
  expect(seen.calls).toEqual([])
  expect(seen.debugged).toContain('notify: terminal_bell')

  // A notification of Claude Code's own for a session that waits is not notified again on that channel.
  await $.classic.Notification({ hook_event_name: 'Notification', notification_type: 'permission_prompt', message: 'Claude needs your permission to use Bash' } as never)
  await clock.settle()
  expect(seen.notified.length).toBe(1)
})

test('with the push on, a session that waits at a permission prompt or sits idle pushes in Claude Code\'s own words', { options: { push: true } }, async ($, on) => {
  const clock = mock.clock(on)
  let answer = 'Not sent: the terminal is active.'
  const seen = machine(on, { ...PROMPT, app: () => answer })
  await $.session.start(AT_A_PROMPT)
  await clock.settle()
  await $.turn.start(BEGUN)

  const waits = { hook_event_name: 'Notification', notification_type: 'permission_prompt', message: 'Claude needs your permission to use Bash' }
  const out = await $.classic.Notification(waits as never)
  await clock.settle()
  expect(out).toEqual({})
  expect(seen.inputs).toEqual([
    { tool: 'PushNotification', input: { message: 'project: Claude needs your permission to use Bash', status: 'proactive' } },
  ])

  // A plugin's own notification and a sign-in are no wait.
  await $.classic.Notification({ ...waits, notification_type: 'plugin_notification' } as never)
  await $.classic.Notification({ ...waits, notification_type: 'auth_success' } as never)
  await clock.settle()
  expect(seen.inputs.length).toBe(1)

  // The turn's end was not pushed, since ezexe was at the keyboard, so the idle minute after it is.
  await $.turn.complete(TURN)
  await clock.settle()
  await $.classic.Notification({ ...waits, notification_type: 'idle_prompt', message: 'Claude is waiting for your input' } as never)
  await clock.settle()
  expect(seen.inputs.map(one => one.input.message)).toEqual([
    'project: Claude needs your permission to use Bash',
    'project: done',
    'project: Claude is waiting for your input',
  ])

  // A turn whose end was pushed is not told again when the session sits idle.
  answer = 'Sent.'
  await $.turn.start({ ...BEGUN, turnId: 't2' })
  await $.turn.complete({ ...TURN, turnId: 't2' })
  await clock.settle()
  await $.classic.Notification({ ...waits, notification_type: 'idle_prompt', message: 'Claude is waiting for your input' } as never)
  await clock.settle()
  expect(seen.inputs.length).toBe(4)
})

test('with the push off, a notification of Claude Code\'s own starts nothing', async ($, on) => {
  const clock = mock.clock(on)
  const seen = machine(on, { ...PROMPT, app: () => 'sent' })
  await $.session.start(AT_A_PROMPT)
  await clock.settle()

  await $.classic.Notification({ hook_event_name: 'Notification', notification_type: 'permission_prompt', message: 'Claude needs your permission to use Bash' } as never)
  await $.turn.complete(TURN)
  await clock.settle()
  expect(seen.inputs).toEqual([])
  expect(seen.notified).toEqual([])
})
