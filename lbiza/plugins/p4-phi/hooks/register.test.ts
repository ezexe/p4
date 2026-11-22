// p4-phi's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On, SessionUsage } from 'claude-code'

const DATA = '/home/u/.claude/plugins/data/p4-phi-inline'
const KEPT = '/opt/python/bin/python3'
const FOLDER = '/work/project/.claude/p4/phi/sessions/local_top00001'
const START = { cwd: '/', surface: 'desktop', isInteractive: true } as const
const TURN = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const
const WORD = { origin: { kind: 'peer' }, text: 'the flush is ported' } as const
const TRANSCRIPT = '/home/u/.claude/projects/-work-project/cli-0001.jsonl'

// What `phi.py look` prints.
type Answer = Record<string, string | number | boolean>

// An orchestrator whose sources change, and a session with nothing to watch, as puppeteer.look answers them.
const ORCHESTRATOR: Answer = {
  dir: FOLDER,
  watching: true,
  changed: false,
  net: false,
  watch_s: 5,
  wait_s: 5,
  net_s: 120,
}
const WORKER: Answer = { dir: FOLDER, watching: false, why: 'no orchestrator', watch_s: 5, wait_s: 30, net_s: 120 }
// A worker as its look answers it: `starter` is what `$.session.id()` answers in the session that started it.
const STARTER = 'cli-starter-0001'
const STARTED: Answer = { ...WORKER, starter: STARTER }
const REPORT = 'The flush is ported and pushed as 4f1c2aa.'
const MOVE = 'phi (p4-phi): the turn before this one ended on step 2, which waits on other sessions.'

// What `$.session.usage()` answered a live probe in the desktop app on Claude Code 2.1.325.
const USAGE: SessionUsage = {
  startedAt: 1794938960087,
  context: { tokens: 575167, window: 1000000, percent: 58 },
  rateLimits: [{ kind: 'seven_day', percentUsed: 82, resetsAt: '2026-11-21T06:00:00.000Z' }],
  cost: { usd: 138.67 },
}
// The same figures as the module writes them to usage.json, less the time of the record: test_phi.py reads this
// line back through phi.usage_of.
const RECORD =
  '"context":{"tokens":575167,"window":1000000,"percent":58},' +
  '"rateLimits":[{"kind":"seven_day","percentUsed":82,"resetsAt":"2026-11-21T06:00:00.000Z"}]}'

// The files of a machine by path, the commands on its PATH that prove themselves as a python, and what a look
// answers there.
type Machine = {
  files?: Record<string, string>
  pythons?: Record<string, string>
  look?: (args: readonly string[]) => Answer | Promise<Answer>
  // What `phi.py rules` prints as the system prompt's section: none where a setting turns the rules off.
  rules?: string
  // What a write waits on before it lands, as a slow disk does.
  write?: (path: string) => Promise<void>
  usage?: SessionUsage
  // Why a message to an address is not delivered there, where it is not.
  refuses?: (to: string) => string | undefined
  // What the engine does with a prompt beneath every plugin, before it enters: it raises the UserPromptSubmit
  // hooks there.
  enters?: (text: string) => Promise<void>
  // How a command of phi.py that a tool stands for ends: what it prints, and its exit code where it fails.
  runs?: (args: readonly string[]) => { stdout?: string; stderr?: string; exitCode?: number }
  // What `hook.py lookup-check` prints for a call's input: a PreToolUse command hook's output, or nothing.
  check?: (payload: Record<string, unknown>) => unknown
  // What the goal command prints for a condition, where it is not `Goal set: <condition>`.
  goalSays?: (condition: string) => string
  // Why the engine rejects a run of the goal command, where it does, as for one a stop removed from the queue.
  goalRejects?: () => string | undefined
  // What a run of the goal command waits on before it answers, as a command queued behind a turn does.
  goalWaits?: () => Promise<void>
  // What the engine does at `tool.run` beneath every plugin, where a test stands for a build's own run of a tool.
  toolRuns?: (tool: string) => unknown
  // Why a surface draws no pane it is asked to open, where it draws none.
  unplaced?: string
}

// What the module read, the pythons it tried, each look it ran and each other phi.py command it asked, every one
// with its whole call, what it wrote, the messages it sent to other sessions and the prompts it submitted.
type Seen = {
  files: Record<string, string>
  read: string[]
  tried: string[][]
  looks: string[][]
  asked: string[][]
  calls: { argv: readonly string[]; env: Readonly<Record<string, string>> | undefined }[]
  wrote: { path: string; text: string }[]
  logged: string[]
  sent: { to: string; text: string }[]
  submitted: string[]
  // The tools the module declared, each as it was given to the engine.
  tools: { name: string; description: string; inputSchema?: Record<string, unknown>; isDeferred?: boolean }[]
  // Each run of `hook.py lookup-check`: its command line past the script, its environment and its input.
  checks: { args: string[]; env: Readonly<Record<string, string>> | undefined; payload: Record<string, unknown> }[]
  // The slash commands it ran, each as a person would type it.
  ran: { command: string; args: string }[]
  // The slash commands it declared, and the panes it opened and has not seen closed, each with its title.
  commands: { name: string; description: string }[]
  panes: { id: string; title?: string }[]
}

// A path as the test wrote it: the engine hands a hook the path resolved on the machine the test runs on.
function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const files = has.files ?? { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '', [`${FOLDER}/session.json`]: '{}' }
  const seen: Seen = {
    files,
    read: [],
    tried: [],
    looks: [],
    asked: [],
    calls: [],
    wrote: [],
    logged: [],
    sent: [],
    submitted: [],
    tools: [],
    checks: [],
    ran: [],
    commands: [],
    panes: [],
  }
  on('command.register', (_, e) => {
    seen.commands.push({ name: e.name, description: e.description })

    return { value: { command: e.name } }
  })
  on('ui.open', (_, e) => {
    seen.panes.push({ id: e.id, title: e.title })

    return { value: has.unplaced === undefined ? { isPlaced: true } : { isPlaced: false, reason: has.unplaced } }
  })
  on('ui.panes', () => ({
    value: seen.panes.map(pane => ({
      id: pane.id,
      title: pane.title ?? pane.id,
      isShown: true,
      isFocused: false,
      isPlaced: has.unplaced === undefined,
    })),
  }))
  on('command.run', async (_, e) => {
    seen.ran.push({ command: e.command, args: e.args })
    await has.goalWaits?.()
    const rejected = has.goalRejects?.()
    // A throw beneath the plugins rejects the plugin's call. The kit skips the hook that threw and rejects with
    // its own words, `no implementation for command.run`, so a test reads that a reason was told, not which.
    if (rejected !== undefined) throw new Error(rejected)

    return { text: has.goalSays?.(e.args) ?? `Goal set: ${e.args}` }
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.measure', (_, e) => ({ changed: e.changed }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('session.usage', () => ({ value: has.usage ?? USAGE }))
  on('fs.write', async (_, e) => {
    await has.write?.(plain(e.path))
    seen.wrote.push({ path: plain(e.path), text: e.text })
    files[plain(e.path)] = e.text

    return { value: undefined }
  })
  on('session.id', () => ({ value: 'cli-0001' }))
  on('session.root', () => ({ value: '/work/project' }))
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('session.receive', (_, e) => ({ text: e.text }))
  on('session.send', (_, e) => {
    seen.sent.push({ to: e.to, text: e.text })
    const reason = has.refuses?.(e.to)

    return reason === undefined ? { isDelivered: true } : { isDelivered: false, reason }
  })
  on('prompt.submit', async (_, e) => {
    seen.submitted.push(e.text)
    await has.enters?.(e.text)

    return { text: e.text }
  })
  on('ui.log', (_, e) => {
    seen.logged.push(e.text)

    return { value: undefined }
  })
  on('fs.list', (_, e) => {
    const folder = plain(e.path)
    const below = Object.keys(files).filter(path => path.startsWith(`${folder}/`))
    const names = [...new Set(below.map(path => path.slice(folder.length + 1).split('/')[0] ?? ''))]

    return {
      value: names.map(name => ({
        name,
        kind: files[`${folder}/${name}`] === undefined ? ('dir' as const) : ('file' as const),
        size: 0,
        mtimeMs: 0,
        isLink: false,
      })),
    }
  })
  on('fs.read', (_, e) => {
    seen.read.push(plain(e.path))
    const text = files[plain(e.path)]

    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  // A file, or a folder that holds one.
  on('fs.exists', (_, e) => {
    const path = plain(e.path)

    return { value: Object.keys(files).some(file => file === path || file.startsWith(`${path}/`)) }
  })
  on('session.info', () => ({ value: { transcriptPath: TRANSCRIPT } }))
  on('tool.register', (_, e) => {
    seen.tools.push({ name: e.name, description: e.description, inputSchema: e.inputSchema, isDeferred: e.isDeferred as never })

    return { value: { tool: `mcp__p4-phi__${e.name}` } }
  })
  on('process.run', async (_, e) => {
    const at = e.argv.findIndex(arg => arg.endsWith('/scripts/phi.py'))
    const hook = e.argv.findIndex(arg => arg.endsWith('/scripts/hook.py'))
    let stdout = ''
    let stderr = ''
    let exitCode = 0
    if (hook >= 0) {
      const payload = JSON.parse(e.init?.stdin ?? '{}') as Record<string, unknown>
      seen.checks.push({ args: e.argv.slice(hook + 1), env: e.init?.env, payload })
      const out = has.check?.(payload)
      stdout = out === undefined ? '' : `${JSON.stringify(out)}\n`
    } else if (at >= 0) {
      const args = e.argv.slice(at + 1)
      seen.calls.push({ argv: e.argv, env: e.init?.env })
      if (args[0] === 'rules') {
        seen.asked.push([...args])
        stdout = `${JSON.stringify({ rules: has.rules ?? '' })}\n`
      } else if (args[0] === 'goal' && args[1] !== 'ask') {
        seen.asked.push([...args])
        stdout = `${JSON.stringify({ set: true })}\n`
      } else if (args[0] === 'note' || args[0] === 'done' || args[0] === 'tree' || args[0] === 'goal') {
        seen.asked.push([...args])
        const ended = has.runs?.(args) ?? {}
        stdout = ended.stdout ?? ''
        stderr = ended.stderr ?? ''
        exitCode = ended.exitCode ?? 0
      } else {
        seen.looks.push([...args])
        stdout = `${JSON.stringify(has.look === undefined ? ORCHESTRATOR : await has.look(args))}\n`
      }
    } else {
      seen.tried.push([...e.argv])
      const path = (has.pythons ?? {})[e.argv[0] ?? '']
      if (path === undefined) return { deny: 'ENOENT' }
      stdout = `${path}\n`
    }

    return { value: { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false } }
  })

  return seen
}

test('the python a runner kept in the data folder is found, and none is searched for', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.read).toEqual([`${DATA}/.python`])
  expect(seen.tried).toEqual([])
  expect(seen.calls[0]?.argv[0]).toBe(KEPT)
})

test('the data folder is found under the plugins root by the plugin name', async ($, on) => {
  mock.env(on, { HOME: '/home/u' })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.read).toEqual([`${DATA}/.python`])
  expect(seen.tried).toEqual([])
})

test('with none kept, the search of find-python.sh proves the first python that runs', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: { python: KEPT } })

  await $.session.start(START)
  await clock.settle()

  const names = seen.tried.map(argv => argv[0])
  expect(names.at(-1)).toBe('python')
  expect(names.slice(0, -1).every(name => name === 'py' || name === 'python3')).toBe(true)
  expect(seen.tried.at(-1)?.slice(-3, -1)).toEqual(['-I', '-c'])
  expect(seen.calls[0]?.argv[0]).toBe(KEPT)
})

// p4-native's capability map, as that plugin writes it into the project's store: this session's entry, which the
// fake engine names `cli-0001` in the project `/work/project`, and another session's, which is never read.
const MAP_FILE = '/work/project/.claude/p4/native/host.json'
function mapOf(entry: Record<string, unknown>): string {
  const other = { host: 'desktop', run: 'interactive', platform: 'macos', tools: { app: ['mcp__ccd_x'], native: [], servers: {} } }

  return JSON.stringify({ sessions: { 'another-session': other, 'cli-0001': entry } })
}

test("the python search asks p4-native's map whether this is Windows, and the plugin's folder where it does not say", async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  // The map says Windows: the launcher is tried first, whatever the folder the plugin runs from looks like.
  const windows = machine(on, { files: { [MAP_FILE]: mapOf({ platform: 'windows' }) }, pythons: { python: KEPT } })
  await $.session.start(START)
  await clock.settle()
  expect(windows.tried.map(argv => argv[0])).toEqual(['py', 'python'])
  expect(windows.read).toContain(MAP_FILE)
})

test("where the map says Linux the search tries python3 first, and another session's entry is not read", async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const linux = machine(on, { files: { [MAP_FILE]: mapOf({ platform: 'linux' }) }, pythons: { python: KEPT } })
  await $.session.start(START)
  await clock.settle()
  expect(linux.tried.map(argv => argv[0])).toEqual(['python3', 'python'])
})

// The map absent, or saying nothing of this session's platform: p4-phi's own reading stays, the shape of the folder
// the plugin runs from. Another session's entry says the other system each time, and is never taken for this one.
const UNMAPPED: [string, (own: boolean) => string][] = [
  ['no entry for the session', own => JSON.stringify({ sessions: { 'another-session': { platform: own ? 'linux' : 'windows' } } })],
  ['an entry that says unknown', () => mapOf({ platform: 'unknown' })],
  ['an entry with no platform', () => mapOf({ host: 'terminal' })],
  ['a map cut short', () => '{"sessions":'],
  ['a map that is a list', () => '[]'],
]
for (const [name, mapFor] of UNMAPPED) {
  test(`with no map, and then with ${name}, the plugin's own folder tells the python search whether this is Windows`, async ($, on) => {
    mock.env(on, {})
    const clock = mock.clock(on)
    // No python is found, so each look searches again: first with no map, which gives the order the plugin's own
    // folder tells on the machine the test runs on, then with the map, which must leave that order as it is.
    const seen = machine(on, { files: {}, pythons: {} })

    await $.session.start(START)
    await clock.settle()
    const before = seen.tried.length
    const own = seen.tried.slice(0, 3).map(argv => argv[0])
    expect([['py', 'python', 'python3'], ['python3', 'python', 'py']]).toContainEqual(own)

    seen.files[MAP_FILE] = mapFor(own[0] === 'py')
    await $.turn.complete(TURN)
    await clock.advance(700_000)
    const later = seen.tried.slice(before).map(argv => argv[0])
    expect(later.length).toBeGreaterThanOrEqual(3)
    expect(later.slice(0, 3)).toEqual(own)
    expect(seen.read).toContain(MAP_FILE)
  })
}

test('with no python at all no look runs, and the debug log says so once', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: {} })

  await $.session.start(START)
  await clock.advance(3_600_000)

  expect(seen.looks).toEqual([])
  expect(seen.logged).toEqual(['no working python found, so no look runs'])
})

test('a look is phi.py run as a hook runs it, and the first one is a slow one', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  const call = seen.calls[0]
  expect(call?.argv.slice(0, 4)).toEqual([KEPT, '-I', '-X', 'utf8'])
  expect(call?.argv.slice(5)).toEqual(['look', '--net'])
  expect(call?.env).toEqual({ CLAUDE_CODE_SESSION_ID: 'cli-0001', CLAUDE_PROJECT_DIR: '/work/project' })
})

test('the timer waits as the look answers, and a slow look comes once every net_s', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  // The second look finds the sources still, as ledger.sig tells after ten minutes.
  const seen = machine(on, { look: () => ({ ...ORCHESTRATOR, wait_s: seen.looks.length > 1 ? 30 : 5 }) })

  await $.session.start(START)
  await clock.settle()
  expect(seen.looks).toEqual([['look', '--net']])

  // One tick after the start's look, which can run before the SessionStart hooks have written.
  await clock.advance(4_999)
  expect(seen.looks.length).toBe(1)
  await clock.advance(1)
  expect(seen.looks).toEqual([['look', '--net'], ['look']])

  await clock.advance(29_999)
  expect(seen.looks.length).toBe(2)
  await clock.advance(1)
  expect(seen.looks.length).toBe(3)

  // Looks at 65, 95 and 125 seconds: the last is the first one two minutes after the slow look at the start.
  await clock.advance(90_000)
  expect(seen.looks.map(args => args.includes('--net'))).toEqual([true, false, false, false, false, true])
})

test('there is never a second look in flight, and never two within the tick', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {
    look: async () => {
      await clock.sleep(2_000)

      return ORCHESTRATOR
    },
  })

  await $.session.start(START)
  await clock.settle()
  expect(seen.looks.length).toBe(1)

  // Three turns end and a message arrives while the look runs.
  await $.turn.complete(TURN)
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await $.turn.complete(TURN)
  await $.session.receive(WORD)
  await clock.advance(2_000)
  expect(seen.looks.length).toBe(1)

  // The look they asked for starts one tick after the first one started, not sooner.
  await clock.advance(2_999)
  expect(seen.looks.length).toBe(1)
  await clock.advance(1)
  expect(seen.looks.length).toBe(2)

  // A turn that ends inside the tick is taken at the tick's end, once.
  await clock.advance(2_000)
  await $.turn.complete(TURN)
  await $.turn.complete(TURN)
  await clock.advance(2_999)
  expect(seen.looks.length).toBe(2)
  await clock.advance(1)
  expect(seen.looks.length).toBe(3)
})

test('a session that is no orchestrator pays one cheap check and then backs off', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => WORKER })

  await $.session.start(START)
  await clock.settle()
  expect(seen.looks.length).toBe(1)

  // The timer's wait doubles: 30 seconds, then 60, then 120.
  await clock.advance(29_999)
  expect(seen.looks.length).toBe(1)
  await clock.advance(1)
  expect(seen.looks.length).toBe(2)
  await clock.advance(59_999)
  expect(seen.looks.length).toBe(2)
  await clock.advance(1)
  expect(seen.looks.length).toBe(3)

  // A subagent's turn and a message's arrival make no orchestrator of it, so neither asks for a look.
  await clock.advance(10_000)
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await $.session.receive(WORD)
  await clock.settle()
  expect(seen.looks.length).toBe(3)

  // Its own turn's end is where it comes to have a task or a child.
  await $.turn.complete(TURN)
  await clock.settle()
  expect(seen.looks.length).toBe(4)

  // Ten minutes at most between two checks.
  await clock.advance(3_600_000)
  const before = seen.looks.length
  await clock.advance(599_999)
  expect(seen.looks.length - before).toBeLessThan(2)
  await clock.advance(600_001)
  expect(seen.looks.length - before).toBeGreaterThan(0)
})

test("an orchestrator's look is asked for by a subagent's turn end and by a message's arrival", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ({ ...ORCHESTRATOR, wait_s: 30 }) })

  await $.session.start(START)
  await clock.advance(5_000)
  expect(seen.looks.length).toBe(2)

  await clock.advance(15_000)
  await $.session.receive(WORD)
  await clock.settle()
  expect(seen.looks.length).toBe(3)

  await clock.advance(6_000)
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await clock.settle()
  expect(seen.looks.length).toBe(4)
})

test('P4_PHI_WATCH=0 runs no look and arms no timer, and the usage is still kept', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI_WATCH: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ({ dir: FOLDER, watching: false }) })

  await $.session.start(START)
  await $.turn.complete(TURN)
  await $.session.receive(WORD)
  await clock.advance(3_600_000)

  // The one command is the question of where the session's folder is.
  expect(seen.looks).toEqual([['look', '--folder']])
  expect(seen.wrote.map(file => file.path)).toEqual([`${FOLDER}/usage.json`])
})

test('P4_PHI=0 runs nothing and writes nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await $.turn.complete(TURN)
  await $.session.measure({ context: USAGE.context, rateLimits: USAGE.rateLimits, changed: ['context'] })
  await clock.advance(3_600_000)

  expect(seen.looks).toEqual([])
  expect(seen.read).toEqual([])
  expect(seen.wrote).toEqual([])
})

test('a look that answers off is the last one', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ({ dir: FOLDER, watching: false, off: true, why: 'off' }) })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete(TURN)
  await clock.advance(3_600_000)

  expect(seen.looks.length).toBe(1)
})

test('the usage is written once at the start, to the folder the first look answered', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on, { now: 1794942221358 })
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.wrote).toEqual([{ path: `${FOLDER}/usage.json`, text: `{"at":1794942221358,${RECORD}\n` }])
  expect(seen.looks).toEqual([['look', '--net']])
})

test('a figure writes when it moves a whole point, and not inside one', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})
  const week = { kind: 'seven_day', percentUsed: 82, resetsAt: '2026-11-21T06:00:00.000Z' }
  const measure = async (context: SessionUsage['context'], rateLimits: SessionUsage['rateLimits']) => {
    await $.session.measure({ context, rateLimits, changed: ['context'] })
    await clock.settle()

    return seen.wrote.length
  }

  await $.session.start(START)
  await clock.settle()
  expect(seen.wrote.length).toBe(1)

  // More tokens inside the same percent, and a window that moves inside its point.
  expect(await measure({ tokens: 579000, window: 1000000, percent: 58 }, [week])).toBe(1)
  expect(await measure({ tokens: 579000, window: 1000000, percent: 58 }, [{ ...week, percentUsed: 82.9 }])).toBe(1)

  // The context's next percent, then the window's next point, its reset, and a second window.
  expect(await measure({ tokens: 590000, window: 1000000, percent: 59 }, [week])).toBe(2)
  expect(await measure({ tokens: 590000, window: 1000000, percent: 59 }, [{ ...week, percentUsed: 83 }])).toBe(3)
  const reset = { kind: 'seven_day', percentUsed: 0, resetsAt: '2026-11-28T06:00:00.000Z' }
  expect(await measure({ tokens: 590000, window: 1000000, percent: 59 }, [reset])).toBe(4)
  const hours = { kind: 'five_hour', percentUsed: 7.5, resetsAt: '2026-11-17T22:00:00.000Z' }
  expect(await measure({ tokens: 590000, window: 1000000, percent: 59 }, [reset, hours])).toBe(5)

  // A fresh window after a compaction has no fill yet: the record holds the window alone.
  expect(await measure({ window: 1000000 }, [reset, hours])).toBe(6)
  expect(JSON.parse(seen.wrote.at(-1)?.text ?? '{}').context).toEqual({ window: 1000000 })
})

test('with no session folder nothing is written, and python is asked again at the next measure', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let hasFolder = false
  const seen = machine(on, {
    look: () => (hasFolder ? WORKER : { watching: false, why: 'no session folder', watch_s: 5, wait_s: 30 }),
  })

  await $.session.start(START)
  await clock.settle()
  expect(seen.wrote).toEqual([])
  expect(seen.looks).toEqual([['look', '--net'], ['look', '--folder']])

  hasFolder = true
  await $.session.measure({ context: USAGE.context, rateLimits: USAGE.rateLimits, changed: ['context'] })
  await clock.settle()
  expect(seen.looks.at(-1)).toEqual(['look', '--folder'])
  expect(seen.wrote.map(file => file.path)).toEqual([`${FOLDER}/usage.json`])
})

test('a session folder that was deleted is not made again by the usage record', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()
  expect(seen.wrote.length).toBe(1)

  delete seen.files[`${FOLDER}/session.json`]
  await $.session.measure({
    context: { tokens: 700000, window: 1000000, percent: 70 },
    rateLimits: USAGE.rateLimits,
    changed: ['context'],
  })
  await clock.settle()
  expect(seen.wrote.length).toBe(1)
})

test('after a clear the folder is asked for again and the usage is written again', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI_WATCH: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ({ dir: FOLDER, watching: false }) })

  await $.session.start(START)
  await clock.settle()
  await $.session.end({ reason: 'clear', sessionId: 'cli-0001', resume: { id: 'cli-0001' } })
  await $.session.measure({ context: USAGE.context, rateLimits: USAGE.rateLimits, changed: ['context'] })
  await clock.settle()

  expect(seen.looks).toEqual([['look', '--folder'], ['look', '--folder']])
  expect(seen.wrote.length).toBe(2)
})

test("a worker's report goes to the session that started it when its turn ends", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => STARTED })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: `  ${REPORT}\n` })
  await clock.settle()

  expect(seen.sent.length).toBe(1)
  expect(seen.sent[0]?.to.includes(STARTER)).toBe(true)
  const lines = seen.sent[0]?.text.split('\n') ?? []
  expect(lines[0]).toBe('phi (p4-phi): this session ended a turn. Its report follows, and needs no reply.')
  expect(lines.slice(1)).toEqual(['', REPORT])
  // The starter came with the first look's answer, so python was asked nothing more for it.
  expect(seen.looks.filter(args => args.includes('--folder'))).toEqual([])
})

test('each turn of a worker sends one report, a long one cut and an empty one named by its end', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => STARTED })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: 'x'.repeat(4_500) })
  await $.turn.complete({ ...TURN, turnId: 't2', answer: '', reason: 'error' })
  await clock.settle()

  expect(seen.sent.length).toBe(2)
  expect(seen.sent[0]?.text.split('\n\n')[1]).toBe(`${'x'.repeat(4_000)} ...`)
  expect(seen.sent[1]?.text).toBe("phi (p4-phi): this session ended a turn with no report: the turn's end was error.")
})

test('a report that repeats the one before it is not sent, and the same words after another report are', async ($, on) => {
  // Seen in the desktop app on Claude Code 2.1.326: two turns that both answered `ok` sent the same report twice,
  // the starter's inbox dropped the second with "it repeated your previous message", and the app's notice of that
  // started a turn of the worker.
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => STARTED })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: 'ok' })
  await $.turn.complete({ ...TURN, turnId: 't2', answer: ' ok\n' })
  await clock.settle()
  expect(seen.sent.length).toBe(1)

  await $.turn.complete({ ...TURN, turnId: 't3', answer: 'The flush is ported.' })
  await $.turn.complete({ ...TURN, turnId: 't4', answer: 'ok' })
  await clock.settle()
  expect(seen.sent.map(one => one.text.split('\n\n')[1])).toEqual(['ok', 'The flush is ported.', 'ok'])
})

test('a turn begun by the notice of a held message sends no report, and the turn after it does', async ($, on) => {
  // Seen in the desktop app on Claude Code 2.1.326: a worker in auto mode under a starter that bypassed permission
  // prompts had each report held, the notice of each started a turn of the worker, and that turn's report was
  // held in its turn, every six seconds until the worker was detached.
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => STARTED })
  const held =
    '[Cross-session delivery notice] Your message to another session was held by that session ' +
    '(recipient: uds:/tmp/cc-msg-1; msg_id: 0a1b). Not delivered yet.'

  await $.session.start(START)
  await clock.settle()
  await $.turn.start({ text: 'port the flush', turnId: 't1' })
  await $.turn.complete({ ...TURN, answer: REPORT })
  await clock.settle()
  expect(seen.sent.length).toBe(1)

  await $.turn.start({ text: held, turnId: 't2' })
  await $.turn.complete({ ...TURN, turnId: 't2', answer: 'Held: 0a1b, not delivered.' })
  await $.turn.start({ text: `  ${held.replace('was held by that session', 'was not approved before expiry')}`, turnId: 't3' })
  await $.turn.complete({ ...TURN, turnId: 't3', answer: 'Expired: 0a1b.' })
  await clock.settle()
  expect(seen.sent.length).toBe(1)

  // A notice in a subagent's turn leaves the main conversation's turn as it was, and a later turn reports again.
  await $.turn.start({ text: 'run the test of the flush', turnId: 't4' })
  await $.turn.start({ text: held, turnId: 's1', agentId: 'a1' })
  await $.turn.complete({ ...TURN, turnId: 't4', answer: 'The test of the flush passes.' })
  await clock.settle()
  expect(seen.sent.map(one => one.text.split('\n\n')[1])).toEqual([REPORT, 'The test of the flush passes.'])
})

test("a subagent's turn, a turn the person stopped and a session nobody started send no report", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isStarted = true
  const seen = machine(on, { look: () => (isStarted ? STARTED : ORCHESTRATOR) })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, agentId: 'a1', answer: REPORT })
  await $.turn.complete({ ...TURN, answer: REPORT, isAborted: true, reason: 'aborted' })
  await clock.settle()
  expect(seen.sent).toEqual([])

  // A look that names no starter is a session nobody started, or one detached from the session that did.
  isStarted = false
  await clock.advance(30_000)
  await $.turn.complete({ ...TURN, answer: REPORT })
  await clock.settle()
  expect(seen.sent).toEqual([])
})

test('a report whose turn ends while the first look runs waits for the starter that look answers', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {
    look: async () => {
      await clock.sleep(2_000)

      return STARTED
    },
  })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: REPORT })
  await clock.settle()
  expect(seen.sent).toEqual([])

  await clock.advance(2_000)
  expect(seen.sent.length).toBe(1)
  expect(seen.looks).toEqual([['look', '--net']])
})

test('a starter that runs under a new id is asked of python once more, and the report goes there', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const gone = `no live session on this machine has id ${STARTER}`
  const moved: Answer = { dir: FOLDER, watching: false, starter: 'cli-starter-0002' }
  const seen = machine(on, {
    look: args => (args.includes('--folder') ? moved : STARTED),
    refuses: to => (to.includes(STARTER) ? gone : undefined),
  })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: REPORT })
  await clock.settle()

  expect(seen.sent.map(message => message.to.includes('cli-starter-0002'))).toEqual([false, true])
  expect(seen.looks.filter(args => args.includes('--folder')).length).toBe(1)
  expect(seen.logged).toEqual([])
})

test('a report no live session takes is said to the debug log, and the turn ends as it would', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const gone = `no live session on this machine has id ${STARTER}`
  const seen = machine(on, { look: () => STARTED, refuses: () => gone })

  await $.session.start(START)
  await clock.settle()
  const ended = await $.turn.complete({ ...TURN, answer: REPORT })
  await clock.settle()

  expect(ended.text).toBe('')
  expect(seen.sent.length).toBe(1)
  expect(seen.logged).toEqual([`the turn's report did not reach the starter: ${gone}`])
})

test('P4_PHI_WATCH=0 still sends a report, from the starter the folder question answers', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI_WATCH: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ({ dir: FOLDER, watching: false, starter: STARTER }) })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete({ ...TURN, answer: REPORT })
  await clock.settle()

  expect(seen.looks).toEqual([['look', '--folder']])
  expect(seen.sent.length).toBe(1)
})

test('a look that answers work a wait left unmoved starts a turn of the session for it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isLeft = false
  const seen = machine(on, {
    look: () => {
      const answer = isLeft ? { ...ORCHESTRATOR, move: MOVE } : ORCHESTRATOR
      isLeft = false

      return answer
    },
  })

  await $.session.start(START)
  await clock.advance(5_000)
  expect(seen.submitted).toEqual([])

  // The turn ends on a wait, and the look its end asks for, one tick after the last one, answers what can move.
  await $.turn.start({ text: 'what came in?', turnId: 't1' })
  await clock.advance(6_000)
  isLeft = true
  await $.turn.complete(TURN)
  await clock.advance(5_000)
  expect(seen.submitted).toEqual([MOVE])
  expect(seen.sent).toEqual([])

  await clock.advance(60_000)
  expect(seen.submitted).toEqual([MOVE])
})

test('no turn is started for a wait while a turn of the session runs', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isLeft = false
  const seen = machine(on, { look: () => (isLeft ? { ...ORCHESTRATOR, move: MOVE } : ORCHESTRATOR) })

  await $.session.start(START)
  await clock.advance(5_000)
  await $.turn.start({ text: 'land the series', turnId: 't1' })
  isLeft = true
  await clock.advance(60_000)

  expect(seen.looks.length).toBeGreaterThan(2)
  expect(seen.submitted).toEqual([])
})

// The prompt upkeep.wake answers, which opens with plans.UPKEEP_MARK.
const UPKEEP = 'phi (p4-phi): upkeep is due for the sessions this one started: 1 act, each listed beside this prompt.'

test('a look that answers upkeep that is due starts a turn of the session for it, once', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDue = false
  const seen = machine(on, {
    // Python answers it once for an act and counts the turn, as it does for `move`.
    look: () => {
      const answer = isDue ? { ...ORCHESTRATOR, upkeep: UPKEEP } : ORCHESTRATOR
      isDue = false

      return answer
    },
  })

  await $.session.start(START)
  await clock.advance(5_000)
  expect(seen.submitted).toEqual([])

  // Every started session went idle with an act due: no event of this session says so, and the timer's look does.
  isDue = true
  await clock.advance(6_000)
  expect(seen.submitted).toEqual([UPKEEP])
  expect(seen.sent).toEqual([])

  await clock.advance(60_000)
  expect(seen.submitted).toEqual([UPKEEP])
})

test('with the setting off a look answers no upkeep, and the module starts no turn', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ORCHESTRATOR })

  await $.session.start(START)
  await clock.advance(120_000)

  expect(seen.looks.length).toBeGreaterThan(2)
  expect(seen.submitted).toEqual([])
})

test('work a wait left unmoved comes before upkeep, and one look starts one turn', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDue = false
  const seen = machine(on, {
    look: () => {
      const answer = isDue ? { ...ORCHESTRATOR, move: MOVE, upkeep: UPKEEP } : ORCHESTRATOR
      isDue = false

      return answer
    },
  })

  await $.session.start(START)
  await clock.advance(5_000)
  isDue = true
  await clock.advance(6_000)

  expect(seen.submitted).toEqual([MOVE])
})

test('no turn is started for upkeep while a turn of the session runs', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDue = false
  const seen = machine(on, { look: () => (isDue ? { ...ORCHESTRATOR, upkeep: UPKEEP } : ORCHESTRATOR) })

  await $.session.start(START)
  await clock.advance(5_000)
  await $.turn.start({ text: 'land the series', turnId: 't1' })
  isDue = true
  await clock.advance(60_000)

  expect(seen.looks.length).toBeGreaterThan(2)
  expect(seen.submitted).toEqual([])
})

// The condition phi.goal_due answers: the line `Done looks like:` of a worker's brief.
const CONDITION = 'the flush is ported, its test passes and the commit is on main'

test('a look that answers a goal sets it by the goal command, once, and python is told it is set', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDue = false
  const seen = machine(on, {
    look: () => {
      const answer = isDue ? { ...STARTED, goal: CONDITION, move: MOVE } : STARTED
      isDue = false

      return answer
    },
  })

  await $.session.start(START)
  await clock.advance(5_000)
  expect(seen.ran).toEqual([])

  // The worker's first turn ends, and the look its end asks for answers the goal. The goal command starts the
  // turn that follows, so no turn is started for what a wait left unmoved.
  await $.turn.start({ text: 'port the flush', turnId: 't1' })
  await clock.advance(6_000)
  isDue = true
  await $.turn.complete(TURN)
  await clock.advance(5_000)
  expect(seen.ran).toEqual([{ command: 'goal', args: CONDITION }])
  expect(seen.asked).toEqual([['goal', 'set']])
  expect(seen.submitted).toEqual([])

  await clock.advance(600_000)
  expect(seen.ran.length).toBe(1)
})

test('with the setting off a look answers no goal, and the module runs no command', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => STARTED })

  await $.session.start(START)
  await clock.advance(5_000)
  await $.turn.start({ text: 'port the flush', turnId: 't1' })
  await clock.advance(6_000)
  await $.turn.complete(TURN)
  await clock.advance(600_000)

  expect(seen.ran).toEqual([])
  expect(seen.asked).toEqual([])
  expect(seen.sent.length).toBe(1)
})

test('a goal the command did not set is said to the debug log, and python is told what the command said', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDue = true
  const seen = machine(on, {
    look: () => {
      const answer = isDue ? { ...STARTED, goal: CONDITION } : STARTED
      isDue = false

      return answer
    },
    goalSays: () => 'Goals are unavailable: hooks are disabled.',
  })

  await $.session.start(START)
  await clock.advance(5_000)

  expect(seen.ran).toEqual([{ command: 'goal', args: CONDITION }])
  expect(seen.asked).toEqual([['goal', 'failed', '--', 'Goals are unavailable: hooks are disabled.']])
  expect(seen.logged.filter(line => line.includes('did not set the goal')).length).toBe(1)
})

// What plugins/mods/api.md gives as the error of a command a stop found in the queue.
const REMOVED = 'the command was removed from the queue before it ran'

test('a goal command a stop removed from the queue is told to python, and the condition answered again is set', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDue = true
  let isStopped = true
  const seen = machine(on, {
    look: () => {
      const answer = isDue ? { ...STARTED, goal: CONDITION } : STARTED
      isDue = false

      return answer
    },
    goalRejects: () => (isStopped ? REMOVED : undefined),
  })

  // The look answers the condition, the command is queued, and a stop of the turn that began meanwhile drops it.
  await $.session.start(START)
  await clock.advance(5_000)
  expect(seen.ran).toEqual([{ command: 'goal', args: CONDITION }])
  expect(seen.asked.length).toBe(1)
  expect(seen.asked[0]?.slice(0, 3)).toEqual(['goal', 'failed', '--'])
  expect((seen.asked[0]?.[3] ?? '').length).toBeGreaterThan(0)
  expect(seen.logged.filter(line => line.includes('did not set the goal')).length).toBe(1)

  // No look answers it while no turn has ended since, so no command runs.
  await clock.advance(600_000)
  expect(seen.ran.length).toBe(1)

  // A later turn ends, python answers the condition to that look again, and the command sets the goal.
  isStopped = false
  await $.turn.start({ text: 'carry on', turnId: 't2' })
  await clock.advance(6_000)
  isDue = true
  await $.turn.complete({ ...TURN, turnId: 't2' })
  await clock.advance(5_000)
  expect(seen.ran).toEqual([
    { command: 'goal', args: CONDITION },
    { command: 'goal', args: CONDITION },
  ])
  expect(seen.asked.at(-1)).toEqual(['goal', 'set'])
})

test('while the goal command has not answered each look says so, and there is no second command beside it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isIdle: () => void = () => undefined
  const idle = new Promise<void>(resolve => {
    isIdle = resolve
  })
  const seen = machine(on, {
    // Python as it was before it read the flag: it answers the condition to every look.
    look: () => ({ ...STARTED, goal: CONDITION }),
    goalWaits: () => idle,
  })

  // The look answers the condition and the command waits in the queue, behind a turn that began at once.
  await $.session.start(START)
  await clock.advance(5_000)
  expect(seen.looks[0]).toEqual(['look', '--net'])
  expect(seen.ran.length).toBe(1)
  await $.turn.start({ text: 'a queued message', turnId: 't2' })
  await clock.advance(6_000)
  await $.turn.complete({ ...TURN, turnId: 't2' })
  await clock.advance(5_000)
  expect(seen.looks.length).toBeGreaterThan(1)
  expect(seen.looks.slice(1).every(args => args.includes('--goal-flying'))).toBe(true)
  expect(seen.ran.length).toBe(1)
  expect(seen.asked).toEqual([])

  // The session is idle, the command runs and answers, and the next look carries no flag.
  isIdle()
  await clock.settle()
  expect(seen.asked).toEqual([['goal', 'set']])
  const before = seen.looks.length
  await $.turn.start({ text: 'the goal as its directive', turnId: 't3' })
  await clock.advance(6_000)
  await $.turn.complete({ ...TURN, turnId: 't3' })
  await clock.advance(5_000)
  expect(seen.looks.length).toBeGreaterThan(before)
  expect(seen.looks.at(-1)?.includes('--goal-flying')).toBe(false)
})

// The rules built into p4-phi as `phi.py rules` prints them, under the head phi.builtin_text gives them.
const RULES =
  'phi (p4-phi): the rules built into p4-phi, for every session:\n' +
  "- built-in, act-don't-wait: A question that the code can answer is researched and decided by this session.\n" +
  '- built-in, levels: work is delegated to where Claude Code runs it best.'
// A system prompt as Claude Code composes it: its opening on the shared side, and a session's own sections after.
const COMPOSED = {
  sections: [
    { id: 'intro', text: 'You are Claude Code.', scope: 'shared' },
    { id: 'memory', text: 'The memory index of this project.', scope: 'session' },
  ],
} as const
const RENDER = {
  model: 'claude-fable-5-2',
  promptModel: 'claude-fable-5-2',
  surfaces: ['desktop'],
  tools: ['Bash', 'Agent'],
  outputStyle: null,
  traits: [],
} as const

test('the rules built into p4-phi are the last section of the system prompt, on the session side', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, { rules: RULES })
  on('prompt.compose', () => COMPOSED)

  const composed = await $.prompt.compose(RENDER)

  expect(composed.sections).toEqual([...COMPOSED.sections, { id: 'p4-phi:rules', text: RULES, scope: 'session' }])
  // Python holds the words and reads the settings, asked as a look is: for this session, in its project.
  expect(seen.asked).toEqual([['rules']])
  expect(seen.calls[0]?.argv.slice(0, 4)).toEqual([KEPT, '-I', '-X', 'utf8'])
  expect(seen.calls[0]?.env).toEqual({ CLAUDE_CODE_SESSION_ID: 'cli-0001', CLAUDE_PROJECT_DIR: '/work/project' })
  expect(seen.looks).toEqual([])
})

test('a prompt rendered again holds the section once, with the words of that render', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  machine(on, { rules: RULES })
  // A render beneath that already holds the section, as a plugin above another copy of this one would see it.
  const held = { id: 'p4-phi:rules', text: 'the rules as they read before', scope: 'session' } as const
  on('prompt.compose', () => ({ sections: [COMPOSED.sections[0], held, COMPOSED.sections[1]] }))

  const composed = await $.prompt.compose(RENDER)

  expect(composed.sections).toEqual([...COMPOSED.sections, { id: 'p4-phi:rules', text: RULES, scope: 'session' }])
})

test('where a setting turns the rules off the system prompt is left as composed', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  // `phi.py rules` prints no text where phi.json, p4.json or P4_PHI_RULES turns the rules off.
  const seen = machine(on, { rules: '' })
  on('prompt.compose', () => COMPOSED)

  expect(await $.prompt.compose(RENDER)).toEqual(COMPOSED)
  expect(seen.asked).toEqual([['rules']])
})

test('P4_PHI=0 sets no section, and python is not asked', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI: '0' })
  const seen = machine(on, { rules: RULES })
  on('prompt.compose', () => COMPOSED)

  expect(await $.prompt.compose(RENDER)).toEqual(COMPOSED)
  expect(seen.calls).toEqual([])
})

test('with no python the system prompt goes out as composed', async ($, on) => {
  mock.env(on, {})
  const seen = machine(on, { files: {}, pythons: {}, rules: RULES })
  on('prompt.compose', () => COMPOSED)

  expect(await $.prompt.compose(RENDER)).toEqual(COMPOSED)
  expect(seen.asked).toEqual([])
  expect(seen.logged).toEqual(['no working python found, so no look runs'])
})

// A project with a store: hook.py keeps a launch's lines under its models folder, in `served/start-<session>`.
const STORE = { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '', '/work/project/.claude/p4/phi/models/index.json': '{}' }
const BOUND_IN = '/work/project/.claude/p4/phi/models/served/start-cli-0001'
// An Agent call's launch and the subagent it starts, with the ids a live run in the desktop app gave both.
const LAUNCH = { prompt: 'Read flush.py and list its writes', description: 'flush reads', subagentType: 'Explore' }
const CALL = 'toolu_01TjNXV8xpTHFt4xgeeSvhDJ'
const AGENT = 'af120930b4bb4d7c6'
const SPAWNED = { model: 'claude-fable-5-2', agentId: AGENT } as const
const SUBAGENT_START = { agent_id: AGENT, agent_type: 'Explore' } as const

test('a subagent is bound to the Agent call that launched it, where hook.py reads the pair', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE } })
  on('agent.spawn', () => SPAWNED)

  const started = await $.agent.spawn({ ...LAUNCH, tool_use_id: CALL } as never)
  await clock.settle()

  expect(started).toEqual(SPAWNED)
  expect(seen.wrote).toEqual([{ path: `${BOUND_IN}/bound-${AGENT}`, text: `${CALL}\n` }])
  // The pair is retrieval's own record, so no python runs for it.
  expect(seen.calls).toEqual([])
})

test("a subagent's SubagentStart hooks run once its binding is written", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const order: string[] = []
  machine(on, {
    files: { ...STORE },
    write: async () => {
      await clock.sleep(200)
      order.push('bound')
    },
  })
  on('agent.spawn', () => SPAWNED)
  on('classic.SubagentStart', () => {
    order.push('SubagentStart hooks')

    return {}
  })

  await $.agent.spawn({ ...LAUNCH, tool_use_id: CALL } as never)
  const raised = $.classic.SubagentStart(SUBAGENT_START)
  await clock.advance(199)
  expect(order).toEqual([])
  await clock.advance(1)
  await raised

  expect(order).toEqual(['bound', 'SubagentStart hooks'])
})

test('a SubagentStart raised ahead of its spawn is held until the spawn answers', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const order: string[] = []
  const seen = machine(on, { files: { ...STORE }, write: async () => void order.push('bound') })
  on('agent.spawn', async () => {
    await clock.sleep(100)

    return SPAWNED
  })
  on('classic.SubagentStart', () => {
    order.push('SubagentStart hooks')

    return {}
  })

  const spawning = $.agent.spawn({ ...LAUNCH, tool_use_id: CALL } as never)
  const raised = $.classic.SubagentStart(SUBAGENT_START)
  await clock.advance(99)
  expect(order).toEqual([])
  await clock.advance(1)
  await Promise.all([spawning, raised])

  expect(order).toEqual(['bound', 'SubagentStart hooks'])
  expect(seen.wrote.length).toBe(1)
})

test('a start no spawn answers for passes after a short hold, bound to nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const order: string[] = []
  const seen = machine(on, { files: { ...STORE } })
  on('classic.SubagentStart', () => {
    order.push('SubagentStart hooks')

    return {}
  })

  const raised = $.classic.SubagentStart(SUBAGENT_START)
  await clock.advance(499)
  expect(order).toEqual([])
  await clock.advance(1)
  await raised

  expect(order).toEqual(['SubagentStart hooks'])
  expect(seen.wrote).toEqual([])
})

test('a spawn no Agent call launched and a project with no store are bound to nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE } })
  const raised: unknown[] = []
  on('agent.spawn', (_, e) => {
    raised.push({ tool_use_id: e.tool_use_id, workflow: e.workflow, resume: e.resume })

    return SPAWNED
  })

  // A fork no tool call starts carries an empty id. A workflow's agent carries the id of the Workflow call that
  // started its run, and a resumed run an old one: the engine alone sets `workflow` and `resume`, so a test raises
  // neither, and the hook leaves both unbound by the same test of the event's fields.
  await $.agent.spawn({ ...LAUNCH, tool_use_id: '' } as never)
  await clock.settle()
  expect(raised).toEqual([{ tool_use_id: '', workflow: undefined, resume: undefined }])
  expect(seen.wrote).toEqual([])

  delete seen.files['/work/project/.claude/p4/phi/models/index.json']
  await $.agent.spawn({ ...LAUNCH, tool_use_id: CALL } as never)
  await clock.settle()
  expect(seen.wrote).toEqual([])
})

// A prompt's id, as a UserPromptSubmit hook's input carries it, and where its origin is kept in a project with a
// store, beside a launch's lines.
const PROMPT_ID = 'ddebe1c3-8147-4a9b-add9-e5f50ecc08f5'
const ORIGIN_IN = `${BOUND_IN}/origin.json`

test("a prompt's origin is written with the prompt's id before its UserPromptSubmit hooks run", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const read: (string | undefined)[] = []
  const seen = machine(on, {
    files: { ...STORE },
    enters: async text => {
      await $.classic.UserPromptSubmit({ prompt: text, prompt_id: PROMPT_ID, session_id: 'cli-0001' })
    },
  })
  on('classic.UserPromptSubmit', () => {
    read.push(seen.files[ORIGIN_IN])

    return {}
  })

  await $.prompt.submit({ text: 'port the flush', origin: { kind: 'peer' }, wait: false } as never)
  await clock.settle()

  expect(read).toEqual([`{"promptId":"${PROMPT_ID}","kind":"peer"}
`])
  expect(seen.submitted).toEqual(['port the flush'])
  // The origin is the engine's own word, so no python runs for it.
  expect(seen.calls).toEqual([])
})


test('each prompt in flight keeps its own origin, with what the kind carries', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const ids: Record<string, string> = { 'port the flush': 'p-typed', [MOVE]: 'p-woken' }
  const seen = machine(on, {
    files: { ...STORE },
    enters: async text => {
      // The typed prompt is still entering when the plugin's own arrives.
      if (text === 'port the flush') await clock.sleep(50)
      await $.classic.UserPromptSubmit({ prompt: text, prompt_id: ids[text], session_id: 'cli-0001' })
    },
  })
  on('classic.UserPromptSubmit', () => ({}))

  const typed = $.prompt.submit({ text: 'port the flush', origin: { kind: 'composer' }, wait: false } as never)
  const woken = $.prompt.submit({ text: MOVE, origin: { kind: 'plugin', name: 'p4-phi' }, wait: false } as never)
  await clock.advance(50)
  await Promise.all([typed, woken])

  expect(seen.wrote.map(write => write.text)).toEqual([
    '{"promptId":"p-woken","kind":"plugin","name":"p4-phi"}\n',
    '{"promptId":"p-typed","kind":"composer"}\n',
  ])
})

test('a project with no store keeps the origin in the session folder, once a look has answered where it is', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {
    look: () => WORKER,
    enters: async text => {
      await $.classic.UserPromptSubmit({ prompt: text, prompt_id: PROMPT_ID, session_id: 'cli-0001' })
    },
  })
  on('classic.UserPromptSubmit', () => ({}))
  const origin = (): string[] => seen.wrote.filter(write => write.path.endsWith('/origin.json')).map(write => write.path)

  // No prompt waits for python: before a look answered, the folder is unknown and nothing is kept.
  await $.prompt.submit({ text: 'port the flush', origin: { kind: 'composer' }, wait: false } as never)
  expect(origin()).toEqual([])

  await $.session.start(START)
  await clock.settle()
  await $.prompt.submit({ text: 'and the rest', origin: { kind: 'composer' }, wait: false } as never)

  expect(origin()).toEqual([`${FOLDER}/origin.json`])
})

test('P4_PHI=0 keeps no origin in the session folder, and a store keeps it still', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, {
    look: () => WORKER,
    enters: async text => {
      await $.classic.UserPromptSubmit({ prompt: text, prompt_id: PROMPT_ID, session_id: 'cli-0001' })
    },
  })
  on('classic.UserPromptSubmit', () => ({}))

  await $.session.start(START)
  await clock.settle()
  await $.prompt.submit({ text: 'port the flush', origin: { kind: 'composer' }, wait: false } as never)
  expect(seen.wrote).toEqual([])

  // Retrieval's hook reads the origin too, and P4_PHI=0 does not turn retrieval off.
  seen.files['/work/project/.claude/p4/phi/models/index.json'] = '{}'
  await $.prompt.submit({ text: 'port the flush', origin: { kind: 'composer' }, wait: false } as never)
  expect(seen.wrote.map(write => write.path)).toEqual([ORIGIN_IN])
})

test('a prompt with no id, one no prompt.submit carried and a write that fails keep nothing and block nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let promptId: string | undefined
  let isDiskFull = false
  const hooked: string[] = []
  const seen = machine(on, {
    files: { ...STORE },
    write: async () => {
      if (isDiskFull) throw new Error('ENOSPC')
    },
    enters: async text => {
      await $.classic.UserPromptSubmit({ prompt: text, prompt_id: promptId, session_id: 'cli-0001' })
    },
  })
  on('classic.UserPromptSubmit', (_, e) => {
    hooked.push(e.prompt)

    return {}
  })

  await $.prompt.submit({ text: 'no id yet', origin: { kind: 'sdk' }, wait: false } as never)
  await $.classic.UserPromptSubmit({ prompt: 'raised alone', prompt_id: PROMPT_ID, session_id: 'cli-0001' })
  promptId = PROMPT_ID
  isDiskFull = true
  const entered = await $.prompt.submit({ text: 'disk full', origin: { kind: 'sdk' }, wait: false } as never)
  await clock.settle()

  expect(seen.wrote).toEqual([])
  expect(hooked).toEqual(['no id yet', 'raised alone', 'disk full'])
  expect(entered).toEqual({ text: 'disk full' })
  // The failed write is said to the debug log once, and the prompt entered all the same.
  expect(seen.logged.map(line => line.split(':')[0])).toEqual(["a prompt's origin was not kept"])
})

// The store of a project, where phi.py leaves its markers, and a tool call as the engine puts it to `tool.check`.
const PHI = '/work/project/.claude/p4/phi'
const ALLOW = { decision: 'allow' } as const
let calls = 0
function call(tool: string, input: Record<string, unknown>, agentId?: string): never {
  calls += 1

  return { tool, input, tool_use_id: `toolu_${calls}`, ...(agentId === undefined ? {} : { agentId }) } as never
}
function bash(command: string, more: Record<string, unknown> = {}): never {
  return call('Bash', { command, ...more })
}

test('a call python has no check for starts no process, and a listed one runs hook.py with the hook input', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, {})
  on('tool.check', () => ALLOW)

  for (const [tool, input] of [
    ['Read', { file_path: 'a.py' }],
    ['Grep', { pattern: 'git push' }],
    ['EnterWorktree', { name: 'the-flush' }],
    ['Agent', { prompt: 'git log', subagent_type: 'Explore' }],
    ['mcp__ccd_turn__update_plan', { advance: true }],
    ['Edit', { file_path: 'a.py', old_string: 'a', new_string: 'b' }],
  ] as const) {
    expect(await $.tool.check(call(tool, input))).toEqual(ALLOW)
  }
  expect(seen.checks).toEqual([])
  expect(seen.calls).toEqual([])
  expect(seen.tried).toEqual([])

  for (const [tool, input] of [
    ['WebFetch', { url: 'https://example.com' }],
    ['WebSearch', { query: 'flush' }],
    ['SendMessage', { to: 'local_x', message: 'go ahead' }],
    ['mcp__ccd_session_mgmt__send_message', { session_id: 'local_x', message: 'go ahead' }],
    ['mcp__ccd_session_mgmt__archive_session', { session_id: 'self' }],
    ['mcp__ccd_session__start_session', { title: 'x' }],
  ] as const) {
    expect(await $.tool.check(call(tool, input))).toEqual(ALLOW)
  }
  expect(seen.checks.map(check => check.payload.tool_name)).toEqual([
    'WebFetch',
    'WebSearch',
    'SendMessage',
    'mcp__ccd_session_mgmt__send_message',
    'mcp__ccd_session_mgmt__archive_session',
    'mcp__ccd_session__start_session',
  ])
  const first = seen.checks[0]
  expect(first?.args).toEqual(['lookup-check'])
  expect(first?.payload).toEqual({
    session_id: 'cli-0001',
    transcript_path: TRANSCRIPT,
    cwd: '/work/project',
    hook_event_name: 'PreToolUse',
    tool_name: 'WebFetch',
    tool_input: { url: 'https://example.com' },
    tool_use_id: first?.payload.tool_use_id,
  })
  expect(String(first?.payload.tool_use_id).startsWith('toolu_')).toBe(true)
  expect(first?.env?.CLAUDE_PROJECT_DIR).toBe('/work/project')
  expect(first?.env?.CLAUDE_CODE_SESSION_ID).toBe('cli-0001')
  expect(String(first?.env?.CLAUDE_PLUGIN_ROOT).length > 0).toBe(true)
})

test('git opens the check only as a word of a shell command, and so does what may land work', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, {})
  on('tool.check', () => ALLOW)

  // A path that holds `github` starts no python for a plain shell call.
  for (const command of ['ls', 'ls github', 'cat .gitignore', 'ls ~/git/x', 'digit', 'echo legit', 'ls C:/code/github/x']) {
    await $.tool.check(bash(command, { description: 'list github' }))
  }
  await $.tool.check(call('PowerShell', { command: 'Get-ChildItem digit' }))
  expect(seen.checks).toEqual([])

  const git = [
    'git status',
    'cd a && git log',
    'ls; git diff',
    'cd repo\ngit push',
    'cd repo\tgit push',
    'cd repo\r\ngit push',
    'git\npush',
    'git.exe push',
    'cd a && C:/Git/bin/git.exe push',
    'git-lfs push',
    'git.cmd push',
    'cd a && git-lfs push',
    'cd repo\ngit.cmd push',
    '/usr/bin/git pull',
    'C:\\Git\\bin\\git pull',
    '"C:/Program Files/Git/bin/git" pull',
    'gh pr view 7',
    'cd a && gh api repos/x/y/git/refs -X PATCH',
    'npm run merge-queue',
    'rsync push-target',
    // however git or gh is called, as test_relay.py puts them to phi.py's branch guard
    'gh pr merge 12',
    'gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc',
    '/usr/bin/git push',
    '/usr/bin/git rebase main',
    'C:\\Git\\bin\\git rebase main',
    '"/usr/bin/git" pull',
    '"/usr/bin/git" rebase main',
    'bash -lc "git push"',
    '{ git push; }',
    'sudo -u x git push',
    'cmd /c git push',
  ]
  for (const command of git) await $.tool.check(bash(command))
  expect(seen.checks.map(check => (check.payload.tool_input as { command: string }).command)).toEqual(git)

  await $.tool.check(bash('sleep 600', { run_in_background: true }))
  await $.tool.check(call('PowerShell', { command: 'git status' }))
  expect(seen.checks.length).toBe(git.length + 2)
})

test('a plain shell call is checked only where the store has a failure model that weighs shell calls', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const model = `${PHI}/models/lookups-model.json`
  const seen = machine(on, {})
  on('tool.check', () => ALLOW)

  await $.tool.check(bash('pytest -q'))
  expect(seen.checks).toEqual([])

  // A store has a model only once a training round passed one, and the last answer is believed for a minute.
  seen.files[model] = '{"shell":{"w":{"pytest":0.4}},"web":{}}\n{"more":1}\n'
  await $.tool.check(bash('pytest -q'))
  expect(seen.checks).toEqual([])
  await clock.advance(60_000)
  await $.tool.check(bash('pytest -q'))
  expect(seen.checks.length).toBe(1)

  seen.files[model] = '{"shell":{"w":{}},"web":{"w":{"a":1}}}\n'
  await clock.advance(60_000)
  await $.tool.check(bash('pytest -q'))
  expect(seen.checks.length).toBe(1)

  // An older layout's model is read where the newest has none.
  delete seen.files[model]
  seen.files['/work/project/.claude/p4/recall/models/lookups-model.json'] = '{"shell":{"w":{"ls":1}}}\n'
  await clock.advance(60_000)
  await $.tool.check(bash('ls'))
  expect(seen.checks.length).toBe(2)
})

test('a session that owes a nudge and a puppeteer are checked at each edit and shell call', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, {})
  on('tool.check', () => ALLOW)
  const edit = (): never => call('Edit', { file_path: 'a.py', old_string: 'a', new_string: 'b' })

  // Another session's marker opens nothing for this one.
  seen.files[`${PHI}/.nudge/cli-0002`] = ''
  seen.files[`${PHI}/.puppeteers/cli-0002`] = ''
  await $.tool.check(edit())
  await $.tool.check(bash('ls'))
  expect(seen.checks).toEqual([])

  seen.files[`${PHI}/.nudge/cli-0001`] = ''
  await $.tool.check(edit())
  await $.tool.check(call('Write', { file_path: 'a.py', content: 'x' }))
  await $.tool.check(call('NotebookEdit', { notebook_path: 'a.ipynb', new_source: 'x' }))
  await $.tool.check(bash('ls'))
  expect(seen.checks.map(check => check.payload.tool_name)).toEqual(['Edit', 'Write', 'NotebookEdit', 'Bash'])

  delete seen.files[`${PHI}/.nudge/cli-0001`]
  seen.files[`${PHI}/.puppeteers/cli-0001`] = ''
  await $.tool.check(call('NotebookEdit', { notebook_path: 'a.ipynb', new_source: '' }))
  expect(seen.checks.length).toBe(5)
  // A tool hook.py has no check for is not read for either.
  await $.tool.check(call('Read', { file_path: 'a.py' }))
  expect(seen.checks.length).toBe(5)
})

test("only a subagent's own marker opens the check for it, at any tool, with its id in the input", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, {})
  on('tool.check', () => ALLOW)
  // Ids as the Agent tool gives them. A marker a subagent left behind opens the check for no other subagent.
  const old = 'a5f0c2d9e8b7a6f41'
  const fresh = 'a389c1db97089b3bf'

  seen.files[`${PHI}/.agents/${old}`] = ''
  await $.tool.check(call('Read', { file_path: 'a.py' }, fresh))
  expect(seen.checks).toEqual([])

  seen.files[`${PHI}/.agents/${fresh}`] = ''
  await $.tool.check(call('Read', { file_path: 'a.py' }, fresh))
  expect(seen.checks.map(check => [check.payload.tool_name, check.payload.agent_id])).toEqual([['Read', fresh]])

  // The main conversation's own read beside it is not checked, and a subagent's listed call is, marked or not.
  await $.tool.check(call('Read', { file_path: 'a.py' }))
  await $.tool.check(call('WebFetch', { url: 'https://example.com' }, `${old}x`))
  expect(seen.checks.map(check => check.payload.agent_id)).toEqual([fresh, `${old}x`])
})

test("python's refusal is the call's error, and its words for the model ride on the reason", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const held = 'phi (p4-phi): this push lands on main, which another session holds.'
  const news = 'phi (p4-phi): flush.py changed since this subagent started.'
  let answer: unknown = {
    hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: held },
  }
  const seen = machine(on, { check: () => answer })
  on('tool.check', () => ALLOW)

  expect(await $.tool.check(bash('git push'))).toEqual({ decision: 'deny', reason: held })

  answer = {
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: held,
      additionalContext: news,
    },
  }
  expect(await $.tool.check(bash('git push'))).toEqual({ decision: 'deny', reason: `${held}\n\n${news}` })

  answer = { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'ask', permissionDecisionReason: held } }
  // The engine names the plugin whose hook asks, so the question is the person's to answer.
  expect(await $.tool.check(bash('git push'))).toEqual({ decision: 'ask', reason: held, plugin: 'p4-phi' })
  expect(seen.checks.length).toBe(3)
})

test('what a check says beside a call reaches the model with the result, once, after the hooks beneath', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const earlier = 'An earlier session fetched this page: the flush is described in section 4.'
  machine(on, {
    check: () => ({ hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: earlier } }),
  })
  on('tool.check', () => ALLOW)
  on('classic.PostToolUse', () => ({ additionalContext: ['a row was written'] }))
  on('classic.PostToolUseFailure', () => ({}))
  const ran = { tool_name: 'WebFetch', tool_input: { url: 'https://example.com' }, tool_response: 'ok' }

  const first = call('WebFetch', { url: 'https://example.com' }) as { tool_use_id: string }
  expect(await $.tool.check(first as never)).toEqual(ALLOW)
  expect(await $.classic.PostToolUse({ ...ran, tool_use_id: first.tool_use_id })).toEqual({
    additionalContext: ['a row was written', earlier],
  })
  expect(await $.classic.PostToolUse({ ...ran, tool_use_id: first.tool_use_id })).toEqual({
    additionalContext: ['a row was written'],
  })

  // A call that fails gets it with the failure, and a call no check spoke of gets nothing added.
  const second = call('WebFetch', { url: 'https://example.com/2' }) as { tool_use_id: string }
  await $.tool.check(second as never)
  expect(
    await $.classic.PostToolUseFailure({
      tool_name: 'WebFetch',
      tool_input: { url: 'https://example.com/2' },
      tool_use_id: second.tool_use_id,
      error: 'timeout',
    }),
  ).toEqual({ additionalContext: [earlier] })
  expect(
    await $.classic.PostToolUseFailure({ tool_name: 'Read', tool_input: {}, tool_use_id: 'toolu_other', error: 'x' }),
  ).toEqual({})
})

// What the desktop app's send tool answered a message to a session whose turn was running, and one that session
// began a turn on, each as seen on Claude Code 2.1.326.
const TOLD_QUEUED =
  '{"success":true,"message":"Forwarded to Claude Desktop\'s session messaging: Message queued for session ' +
  'local_kid00001 (\\"port the flush\\"): that session is holding it (a turn is in progress there, or its host or ' +
  "process is away) and runs it when that clears. Don't wait on it; check back with list_events if the outcome " +
  'matters. (delivery: queued; message_id: bb2fd1a2-0847-47e4-8f37-8e788219a530); not confirmed read"}'
const TOLD_DELIVERED =
  '{"success":true,"message":"Forwarded to Claude Desktop\'s session messaging: Message delivered to session ' +
  'local_kid00001 (\\"port the flush\\"); its turn has started on it. (delivery: delivered; message_id: ' +
  '5bebaf6f-fc60-4c30-b68d-4de03db4dbf0); not confirmed read — that session may hold it"}'

test('a sender whose message was queued is told what that means, and one whose message was delivered is told nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, {})
  on('classic.PostToolUse', () => ({ additionalContext: ['a row was written'] }))
  on('classic.PostToolUseFailure', () => ({}))
  const sent = { tool_input: { to: 'local_kid00001', message: 'the answer you wait on' }, tool_use_id: 'toolu_s1' }

  for (const tool_name of ['SendMessage', 'mcp__ccd_session_mgmt__send_message']) {
    const out = await $.classic.PostToolUse({ ...sent, tool_name, tool_response: TOLD_QUEUED })
    const words = out.additionalContext ?? []
    expect(words.length).toBe(2)
    expect(words[0]).toBe('a row was written')
    expect(words[1]).toContain("it waits for that session's turn to end")
    expect(words[1]).toContain('`mcp__ccd_session_mgmt__stop_session` with its session id ends that turn')
    expect(words[1]).toContain('this session started it')
    expect(words[1]?.includes('\n')).toBe(false)
  }
  // The answer as an object, as a tool's structured result reaches a hook.
  const whole = { success: true, message: 'Message queued for session local_kid00001. (delivery: queued; message_id: m1)' }
  const again = await $.classic.PostToolUse({ ...sent, tool_name: 'SendMessage', tool_response: whole })
  expect((again.additionalContext ?? []).length).toBe(2)

  // A message the session began a turn on, another tool that prints the same words, and a send that failed.
  expect(await $.classic.PostToolUse({ ...sent, tool_name: 'SendMessage', tool_response: TOLD_DELIVERED })).toEqual({
    additionalContext: ['a row was written'],
  })
  expect(await $.classic.PostToolUse({ ...sent, tool_name: 'Bash', tool_response: TOLD_QUEUED })).toEqual({
    additionalContext: ['a row was written'],
  })
  expect(
    await $.classic.PostToolUseFailure({ ...sent, tool_name: 'SendMessage', error: '(delivery: undelivered; message_id: m2)' }),
  ).toEqual({})
  // The line starts no process: nothing ran but what a session's start runs.
  expect(seen.checks).toEqual([])
  expect(seen.asked).toEqual([])
})

test('with P4_PHI=0 a queued message is told nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI: '0' })
  mock.clock(on)
  machine(on, {})
  on('classic.PostToolUse', () => ({}))

  expect(
    await $.classic.PostToolUse({
      tool_name: 'SendMessage',
      tool_input: { to: 'local_kid00001', message: 'x' },
      tool_use_id: 'toolu_s2',
      tool_response: TOLD_QUEUED,
    }),
  ).toEqual({})
})

test('a question about a call nobody made, a call already refused and a check that fails judge nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  let verdict: { decision: 'allow' | 'deny'; reason?: string } = ALLOW
  let isBroken = false
  const seen = machine(on, {
    check: () => {
      if (isBroken) return 'not a hook output'

      return { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: 'no' } }
    },
  })
  on('tool.check', () => verdict)

  // A plugin's `$.tool.check` asks of no call: by the types its question carries no call id. The test kit gives
  // every question an id, so an empty one stands for none here.
  expect(await $.tool.check({ tool: 'Bash', input: { command: 'git push' }, tool_use_id: '' } as never)).toEqual(ALLOW)
  expect(seen.checks).toEqual([])

  verdict = { decision: 'deny', reason: 'a rule refused it' }
  expect(await $.tool.check(bash('git push'))).toEqual(verdict)
  expect(seen.checks).toEqual([])

  verdict = ALLOW
  isBroken = true
  expect(await $.tool.check(bash('git push'))).toEqual(ALLOW)
  expect(seen.checks.length).toBe(1)

})

test('with no python found a call goes on unjudged', async ($, on) => {
  mock.env(on, {})
  mock.clock(on)
  const seen = machine(on, { files: {}, check: () => ({ hookSpecificOutput: { permissionDecision: 'deny' } }) })
  on('tool.check', () => ALLOW)

  expect(await $.tool.check(call('WebSearch', { query: 'flush' }))).toEqual(ALLOW)
  expect(seen.checks).toEqual([])
  expect(seen.logged).toEqual(['no working python found, so no look runs'])
})

test("note, done, tree and goal are declared as tools at a session's start", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.tools.map(tool => [tool.name, tool.isDeferred])).toEqual([
    ['note', false],
    ['done', false],
    ['tree', undefined],
    ['goal', undefined],
  ])
  expect(seen.tools.map(tool => (tool.inputSchema as { required?: string[] }).required)).toEqual([
    ['claim', 'source'],
    ['text'],
    undefined,
    ['condition'],
  ])
  expect(seen.logged).toEqual([])
})

test('P4_PHI=0 declares no tool', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.tools).toEqual([])
})

test('a call of the note tool runs phi.py note for this session, its words after the options', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, { runs: () => ({ stdout: 'kept\n' }) })

  // A finding that opens with a dash is still the finding, not an option of the command.
  const claim = '-x is no flag of flush.py'
  const kept = await $.tool.run({ tool: 'mcp__p4-phi__note', claim, source: ' flush.py:12 ', kind: 'decision' } as never)
  expect(kept).toEqual({ result: 'kept' })
  expect(seen.asked).toEqual([['note', '--source', 'flush.py:12', '--kind', 'decision', '--', claim]])
  expect(seen.calls[0]?.argv.slice(0, 4)).toEqual([KEPT, '-I', '-X', 'utf8'])
  expect(seen.calls[0]?.env).toEqual({ CLAUDE_CODE_SESSION_ID: 'cli-0001', CLAUDE_PROJECT_DIR: '/work/project' })

  // With no kind the command gets none, and phi.py itself refuses a finding with no source.
  await $.tool.run({ tool: 'mcp__p4-phi__note', claim: 'the flush is ported', source: 'git log -1' } as never)
  expect(seen.asked[1]).toEqual(['note', '--source', 'git log -1', '--', 'the flush is ported'])
})

test('done and tree run their commands, and what phi.py says on a failure is the call\'s error', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const short = 'phi: say what was run and what it showed'
  const seen = machine(on, {
    runs: args => {
      if (args[0] === 'tree') return { stdout: 'local_top00001  working  port the flush\n' }
      if (args.at(-1) === 'ok') return { exitCode: 2, stderr: `${short}\n` }

      return { stdout: 'this turn will be kept as done\n' }
    },
  })

  expect(await $.tool.run({ tool: 'mcp__p4-phi__done', text: 'pytest -q passed, 12 of 12' } as never)).toEqual({
    result: 'this turn will be kept as done',
  })
  expect(await $.tool.run({ tool: 'mcp__p4-phi__tree' } as never)).toEqual({
    result: 'local_top00001  working  port the flush',
  })
  expect(await $.tool.run({ tool: 'mcp__p4-phi__done', text: 'ok' } as never)).toEqual({ deny: short })
  expect(seen.asked).toEqual([['done', '--', 'pytest -q passed, 12 of 12'], ['tree'], ['done', '--', 'ok']])
})

// What phi.goal_ask answers a condition it kept, and what it says of one too short to be a condition.
const ASKED = "kept: p4-phi sets this condition as this session's goal once the session is idle"
const TOO_SHORT = "phi: state the goal's condition as a whole sentence"

test("a session's own ask is kept by phi.py, and the look at its turn's end has the goal command run", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  // A session nobody started: its look names no starter. Python answers the condition at the look after the ask.
  let asked = ''
  const seen = machine(on, {
    look: () => {
      const answer = asked === '' ? ORCHESTRATOR : { ...ORCHESTRATOR, goal: asked }
      asked = ''

      return answer
    },
    runs: args => {
      if (args.at(-1) === 'clear') return { exitCode: 2, stderr: `${TOO_SHORT}\n` }
      asked = args.at(-1) ?? ''

      return { stdout: `${ASKED}\n` }
    },
  })

  await $.session.start(START)
  await clock.advance(5_000)
  await $.turn.start({ text: 'land the six rows', turnId: 't1' })
  await clock.advance(6_000)

  // The call sets nothing by itself: the command is run for what a look answers, as it is for a worker.
  expect(await $.tool.run({ tool: 'mcp__p4-phi__goal', condition: ` ${CONDITION} ` } as never)).toEqual({ result: ASKED })
  expect(seen.asked).toEqual([['goal', 'ask', '--', CONDITION]])
  expect(seen.calls.at(-1)?.env).toEqual({ CLAUDE_CODE_SESSION_ID: 'cli-0001', CLAUDE_PROJECT_DIR: '/work/project' })
  expect(seen.ran).toEqual([])

  await $.turn.complete(TURN)
  await clock.advance(5_000)
  expect(seen.ran).toEqual([{ command: 'goal', args: CONDITION }])
  expect(seen.asked.at(-1)).toEqual(['goal', 'set'])
  expect(seen.sent).toEqual([])

  // A condition phi.py refuses is the call's error, and no command runs for it.
  expect(await $.tool.run({ tool: 'mcp__p4-phi__goal', condition: 'clear' } as never)).toEqual({ deny: TOO_SHORT })
  await clock.advance(600_000)
  expect(seen.ran.length).toBe(1)
})

test('with no python found a tool says so, and starts nothing', async ($, on) => {
  mock.env(on, {})
  mock.clock(on)
  const seen = machine(on, { files: {} })

  expect(await $.tool.run({ tool: 'mcp__p4-phi__tree' } as never)).toEqual({
    deny: 'p4-phi found no working python to run phi.py with.',
  })
  expect(seen.asked).toEqual([])
})

// The pane as a surface asks for it: docked beside the transcript, as the desktop app seated a probe's pane.
const PANE = {
  plugin: 'p4-phi',
  component: 'Pane',
  requestId: 'p4-phi',
  props: {
    title: 'p4-phi',
    isFocused: false,
    bodyColumns: 26,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const
const SURFACES = ['terminal', 'desktop', 'vscode', 'mobile'] as const
// The command as the engine raises it when a person types `/phi-pane` and presses Enter.
const TYPED = {
  command: 'phi-pane',
  args: '',
  origin: { kind: 'composer' },
  presentation: { isFullscreen: true, columns: 160 },
} as const
// A puppeteer's folder, which holds all three pages, as controls.board, asks.render and puppeteer.render write them.
const BOARD = '# Puppeteer board: "Phi integration" `local_top00001`\n\n## Controlled sessions\n\n- "flush" `local_a`: idle.\n'
const ASKS = '# Requests of ezexe\'s to "Phi integration" `local_top00001`\n\n- r1, 2026-11-19 10:02: port the flush | open\n'
const LEDGER = '# Ledger: Phi integration\n\n## Sessions\n\n- "flush" `local_a`: working; 2 turns\n'
const PUPPETEER = {
  [`${DATA}/.python`]: `${KEPT}\n`,
  [KEPT]: '',
  [`${FOLDER}/session.json`]: '{}',
  [`${FOLDER}/board.md`]: BOARD,
  [`${FOLDER}/asks.md`]: ASKS,
  [`${FOLDER}/ledger.md`]: LEDGER,
}

test("the pane's command is declared at a session's start, no pane opens unasked, and P4_PHI=0 declares none", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...PUPPETEER } })

  await $.session.start(START)
  await clock.advance(60_000)

  expect(seen.commands.map(command => command.name)).toEqual(['phi-pane'])
  expect(seen.panes).toEqual([])
  // With no pane open no look reads a page.
  expect(seen.read.filter(path => path.endsWith('.md'))).toEqual([])
  expect(seen.logged).toEqual([])
})

test('P4_PHI=0 declares no command', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...PUPPETEER } })

  await $.session.start(START)
  await clock.settle()

  expect(seen.commands).toEqual([])
})

test('the command opens the pane, which shows the board, the requests and the sessions on every surface', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...PUPPETEER } })

  await $.session.start(START)
  await clock.settle()
  const looks = seen.calls.length
  const ran = await $.command.run(TYPED)
  await clock.settle()

  expect(ran.text).toBe("p4-phi's pane is open.")
  expect(seen.panes).toEqual([{ id: 'p4-phi', title: 'p4-phi' }])
  // The pages are files python wrote already, so the command starts no process.
  expect(seen.calls.length).toBe(looks)
  expect(seen.ran).toEqual([])

  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })

    expect((await ui.findAll({ type: 'Text' })).map(title => title.text)).toEqual(['Board', 'Requests of ezexe', 'Sessions'])
    expect((await ui.findAll({ type: 'Markdown' })).map(page => page.text)).toEqual([BOARD.trim(), ASKS.trim(), LEDGER.trim()])
    await ui.unmount()
  }
})

test("as the desktop app's widget the pane is one line a page, cut to the body's columns", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  machine(on, { files: { ...PUPPETEER } })

  await $.session.start(START)
  await clock.settle()
  await $.command.run(TYPED)

  const ui = await $.ui.mount({ ...PANE, props: { ...PANE.props, placement: 'widget', anchoredEdges: [] }, surface: 'desktop' })
  const lines = (await ui.findAll({ type: 'Text' })).map(line => line.text)

  expect(lines).toEqual(['Puppeteer board: "Phi i...', "Requests of ezexe's to ...", 'Ledger: Phi integration'])
  expect(lines.every(line => line.length <= PANE.props.bodyColumns)).toBe(true)
  expect(await ui.findAll({ type: 'Markdown' })).toEqual([])
  await ui.unmount()
})

test('while the pane is open each look reads the pages anew, and the open drawing shows what changed', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...PUPPETEER } })

  await $.session.start(START)
  await clock.settle()
  await $.command.run(TYPED)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Markdown', text: /Ledger/ }))?.text).toBe(LEDGER.trim())

  // A worker's turn ended: the timer's look rewrote the ledger, and the same drawing holds the new page.
  const moved = LEDGER.replace('working; 2 turns', 'idle; 3 turns, shown done')
  seen.files[`${FOLDER}/ledger.md`] = moved
  const wrote = seen.wrote.length
  await clock.advance(5_000)
  expect((await ui.find({ type: 'Markdown', text: /Ledger/ }))?.text).toBe(moved.trim())
  // A drawing writes no file, and the pages are read by the module itself.
  expect(seen.wrote.length).toBe(wrote)
  expect(seen.read.filter(path => path.endsWith('/ledger.md')).length).toBeGreaterThan(1)

  // Once the person closed the pane a look reads no page.
  seen.panes.length = 0
  await clock.advance(5_000)
  const read = seen.read.length
  await clock.advance(60_000)
  expect(seen.read.length).toBe(read)
  await ui.unmount()
})

test('a session with no board and no ledger is told so in the pane, and a long page is cut with its path', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => WORKER })

  await $.session.start(START)
  await clock.settle()
  await $.command.run(TYPED)
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ ...PANE, surface })

    expect((await ui.findAll({ type: 'Text' })).map(line => line.text)).toEqual([
      'This session keeps no board and no ledger: it is no puppeteer and no orchestrator, or no look has run yet.',
    ])
    await ui.unmount()
  }

  // The session came to start others, and its ledger grew past what one page draws.
  seen.files[`${FOLDER}/ledger.md`] = `# Ledger: Phi integration\n\n${'- a row of the ledger\n'.repeat(2_000)}`
  await $.command.run(TYPED)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const page = (await ui.find({ type: 'Markdown' }))?.text ?? ''

  expect(page.length).toBeLessThan(24_200)
  expect(page.endsWith(`... the rest is in ${FOLDER}/ledger.md`)).toBe(true)
  await ui.unmount()
})

test('where no surface draws a pane the command says why, and a pane nobody opened draws with nothing stored', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const reason = 'no-surface: no surface is attached'
  machine(on, { files: { ...PUPPETEER }, unplaced: reason })

  // A surface asks for the pane before any command ran, as after a reload of the module.
  const ui = await $.ui.mount({ ...PANE, surface: 'mobile' })
  expect((await ui.findAll({ type: 'Markdown' })).length).toBe(0)
  await ui.unmount()

  await $.session.start(START)
  await clock.settle()
  expect((await $.command.run(TYPED)).text).toBe(`p4-phi's pane is open and not drawn: ${reason}`)
})

// A look where the store's phi.json turns `app_tools` on, and what the desktop app's two tools for sessions answer:
// one JSON text, as the model reads it. The field names are the tools' own.
const APP_ON: Answer = { ...ORCHESTRATOR, app_tools: true }
const APP_SELF = { sessionId: 'local_top00001', title: 'port the flush', cwd: '/work/project', group: null }
const APP_LINKED = [{ sessionId: 'local_kid00001', title: 'the flush', startedBy: 'local_top00001', name: 'flush' }]
const APP_KEPT = `{"at":0,"self":${JSON.stringify(APP_SELF)},"sessions":${JSON.stringify(APP_LINKED)}}\n`

// The calls of the app's tools the module made, each with its input, and the app's answers beneath them.
function app(on: On, answers?: (tool: string) => unknown): Record<string, unknown>[] {
  const calls: Record<string, unknown>[] = []
  on('tool.call', (_, e) => {
    const { tool_use_id: _id, ...input } = e as Record<string, unknown>
    calls.push(input)
    const given = answers?.(String(e.tool))
    if (given !== undefined) return given as never
    const said = JSON.stringify(String(e.tool).endsWith('get_session') ? APP_SELF : APP_LINKED)

    return { result: [{ type: 'text', text: said }], text: said } as never
  })

  return calls
}

function kept(seen: Seen): { path: string; text: string }[] {
  return seen.wrote.filter(write => write.path.endsWith('/app.json'))
}

test("where a look answers app_tools the app's tools are asked for the session and its linked ones, and python is left the answers", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_ON })
  const calls = app(on)

  await $.session.start(START)
  await clock.settle()

  expect(calls).toEqual([
    { tool: 'mcp__ccd_session_mgmt__get_session', session_id: 'self' },
    { tool: 'mcp__ccd_session_mgmt__list_sessions', linked: true, include_archived: true, limit: 100 },
  ])
  expect(kept(seen)).toEqual([{ path: `${BOUND_IN}/app.json`, text: APP_KEPT }])
})

test('a project with no store keeps the answers in the session folder, and with the setting off no tool is called', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isOn = false
  const seen = machine(on, { look: () => (isOn ? APP_ON : ORCHESTRATOR) })
  const calls = app(on)

  await $.session.start(START)
  await clock.advance(600_000)
  expect(calls).toEqual([])
  expect(kept(seen)).toEqual([])

  isOn = true
  await clock.advance(5_000)
  expect(calls.length).toBe(2)
  expect(kept(seen).map(write => write.path)).toEqual([`${FOLDER}/app.json`])
})

test("the app's tools are asked once a minute at most, and never while a turn of the session runs", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let moves = ''
  const seen = machine(on, { files: { ...STORE }, look: () => (moves ? { ...APP_ON, move: moves } : APP_ON) })
  const calls = app(on)

  // The first look starts a turn for work a wait left unmoved, so nothing is asked of the app beside it.
  moves = MOVE
  await $.session.start(START)
  await clock.settle()
  expect(seen.submitted).toEqual([MOVE])
  expect(calls).toEqual([])

  // While a turn runs the looks go on and ask nothing, and the look at its end asks.
  moves = ''
  await $.turn.start({ text: 'port the flush', turnId: 't1' })
  await clock.advance(120_000)
  expect(calls).toEqual([])
  await $.turn.complete(TURN)
  await clock.advance(5_000)
  expect(calls.length).toBe(2)

  // The looks of the next 50 seconds ask nothing more, and one past the minute asks again.
  await clock.advance(50_000)
  expect(calls.length).toBe(2)
  await clock.advance(15_000)
  expect(calls.length).toBe(4)
  expect(kept(seen).length).toBe(2)
})

test('a session with no such tool is asked once, the debug log says so, and nothing is written', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_ON })
  const calls: string[] = []
  on('tool.call', (_, e) => {
    calls.push(String(e.tool))
    throw new Error('No such tool available: mcp__ccd_session_mgmt__get_session')
  })

  await $.session.start(START)
  await clock.advance(600_000)

  expect(calls).toEqual(['mcp__ccd_session_mgmt__get_session'])
  expect(kept(seen)).toEqual([])
  expect(seen.logged.filter(line => line.includes('is no tool of this session')).length).toBe(1)
  expect(seen.looks.length).toBeGreaterThan(2)
})

test("where p4-native's map reads a terminal with no tool of the app, none is called, and the debug log says so once", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const entry = { host: 'terminal', run: 'scripted', platform: 'linux', tools: { app: [], native: ['Bash'], servers: {} } }
  const seen = machine(on, { files: { ...STORE, [MAP_FILE]: mapOf(entry) }, look: () => ({ ...APP_ON, app_sections: true }) })
  const calls = app(on)

  await $.session.start(START)
  await clock.advance(600_000)

  expect(calls).toEqual([])
  expect(kept(seen)).toEqual([])
  expect(seen.logged.filter(line => line.includes("p4-native's map reads no tool of the desktop app")).length).toBe(1)
  expect(seen.logged.filter(line => line.includes('is no tool of this session'))).toEqual([])
  expect(seen.read.filter(path => path === MAP_FILE).length).toBe(1)
})

test("where the map reads the desktop app, with its tools listed or not yet connected, the app's tools are asked as before", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  // An entry read before the app's tool server connected lists no tool of the app, and decides nothing.
  const entry = { host: 'desktop', run: 'interactive', platform: 'windows', tools: { app: [], native: [], servers: {} } }
  const seen = machine(on, { files: { ...STORE, [MAP_FILE]: mapOf(entry) }, look: () => APP_ON })
  const calls = app(on)

  await $.session.start(START)
  await clock.settle()

  expect(calls.map(call => call.tool)).toEqual(['mcp__ccd_session_mgmt__get_session', 'mcp__ccd_session_mgmt__list_sessions'])
  expect(kept(seen).length).toBe(1)
  expect(seen.logged).toEqual([])
})

test("with no map for the session the first call's own answer tells, as before p4-native", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const other = JSON.stringify({ sessions: { 'another-session': { host: 'terminal', tools: { app: [] } } } })
  const seen = machine(on, { files: { ...STORE, [MAP_FILE]: other }, look: () => APP_ON })
  const calls = app(on)

  await $.session.start(START)
  await clock.settle()

  expect(calls.length).toBe(2)
  expect(kept(seen).length).toBe(1)
})

test("a refusal ends the asking too, and an answer that is an error or no JSON is not kept", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_ON })
  let round = 0
  const calls = app(on, tool => {
    if (tool.endsWith('get_session')) round += 1
    if (round === 1) return tool.endsWith('get_session') ? { result: 'gone', text: 'gone', isError: true } : { result: 'Sessions: none', text: 'Sessions: none' }

    return { deny: 'a session off this machine does not reach the desktop app' }
  })

  await $.session.start(START)
  await clock.settle()
  expect(calls.length).toBe(2)
  expect(kept(seen)).toEqual([])

  await clock.advance(600_000)
  expect(calls.length).toBe(3)
  expect(kept(seen)).toEqual([])
  expect(seen.logged.filter(line => line.includes('was refused')).length).toBe(1)
})

test('a call that does not answer is given up on after a short wait, and no second round starts while it runs', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_ON })
  let answer: (() => void) | undefined
  const held = new Promise<void>(resolve => {
    answer = resolve
  })
  const calls: string[] = []
  on('tool.call', async (_, e) => {
    calls.push(String(e.tool))
    if (String(e.tool).endsWith('get_session')) await held
    const said = JSON.stringify(String(e.tool).endsWith('get_session') ? APP_SELF : APP_LINKED)

    return { result: said, text: said } as never
  })

  await $.session.start(START)
  await clock.advance(4_000)
  expect(calls).toEqual(['mcp__ccd_session_mgmt__get_session'])
  expect(seen.looks.length).toBe(1)

  // The wait runs out: the linked sessions are asked and kept without the session's own answer.
  await clock.advance(2_000)
  expect(calls.length).toBe(2)
  expect(kept(seen).map(write => write.text)).toEqual([`{"at":0,"sessions":${JSON.stringify(APP_LINKED)}}\n`])
  expect(seen.logged.filter(line => line.includes('did not answer')).length).toBe(1)

  // The looks go on meanwhile, and no round starts while the first call has not settled.
  await clock.advance(300_000)
  expect(calls.length).toBe(2)
  expect(seen.looks.length).toBeGreaterThan(10)
  answer?.()
  await clock.advance(50_000)
  expect(calls.length).toBe(4)
})

// A puppeteer's look where `app_tools` is on, and what the app's two tools for the sidebar answer.
const APP_PUPPETEER: Answer = { ...APP_ON, app_sections: true }
const SECTIONS = [
  { id: 'sessions', kind: 'builtin', name: '', order: 1 },
  { id: 'cg-9', kind: 'manual', name: 'importers', order: 2 },
]
const GROUPS = [{ id: 'cg-9', name: 'importers', session_count: 1, order: 0 }]

function text(value: unknown): unknown {
  return { result: [{ type: 'text', text: JSON.stringify(value) }], text: JSON.stringify(value) }
}

test("a puppeteer's look has the sidebar's sections asked for too, and they are kept with the sessions", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_PUPPETEER })
  const calls = app(on, tool => (tool.endsWith('list_sections') ? text(SECTIONS) : undefined))

  await $.session.start(START)
  await clock.settle()

  expect(calls.map(call => call.tool)).toEqual([
    'mcp__ccd_session_mgmt__get_session',
    'mcp__ccd_session_mgmt__list_sessions',
    'mcp__ccd_sidebar__list_sections',
  ])
  expect(calls[2]).toEqual({ tool: 'mcp__ccd_sidebar__list_sections' })
  expect(kept(seen)).toEqual([
    { path: `${BOUND_IN}/app.json`, text: `${APP_KEPT.slice(0, -2)},"sections":${JSON.stringify(SECTIONS)}}\n` },
  ])
})

test('where the sections are not answered the groups are asked, as while no window of the app is open', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_PUPPETEER })
  const calls = app(on, tool => {
    if (tool.endsWith('list_sections')) return { result: 'No app window is open.', text: 'No app window is open.', isError: true }

    return tool.endsWith('list_groups') ? text(GROUPS) : undefined
  })

  await $.session.start(START)
  await clock.settle()

  expect(calls.map(call => call.tool).slice(2)).toEqual(['mcp__ccd_sidebar__list_sections', 'mcp__ccd_sidebar__list_groups'])
  expect(kept(seen)[0]?.text.endsWith(`,"sections":${JSON.stringify(GROUPS)}}\n`)).toBe(true)
})

test("a session with no tool of the sidebar asks for one once, and its sessions are asked for as before", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { ...STORE }, look: () => APP_PUPPETEER })
  const calls: string[] = []
  on('tool.call', (_, e) => {
    calls.push(String(e.tool))
    if (String(e.tool).startsWith('mcp__ccd_sidebar__')) throw new Error(`No such tool available: ${String(e.tool)}`)

    return text(String(e.tool).endsWith('get_session') ? APP_SELF : APP_LINKED) as never
  })

  await $.session.start(START)
  await clock.advance(130_000)

  expect(calls.filter(tool => tool.startsWith('mcp__ccd_sidebar__'))).toEqual(['mcp__ccd_sidebar__list_sections'])
  expect(calls.filter(tool => tool.endsWith('get_session')).length).toBe(3)
  expect(kept(seen).map(write => write.text.includes('"sections"'))).toEqual([false, false, false])
})
