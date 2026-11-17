// p4-phi's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const DATA = '/home/u/.claude/plugins/data/p4-phi-inline'
const KEPT = '/opt/python/bin/python3'
const START = { cwd: '/', surface: 'desktop', isInteractive: true } as const
const TURN = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const
const WORD = { origin: { kind: 'peer' }, text: 'the flush is ported' } as const

// What `phi.py look` prints.
type Answer = Record<string, string | number | boolean>

// An orchestrator whose sources change, and a session with nothing to watch, as puppeteer.look answers them.
const ORCHESTRATOR: Answer = { watching: true, changed: false, net: false, watch_s: 5, wait_s: 5, net_s: 120 }
const WORKER: Answer = { watching: false, why: 'no orchestrator', watch_s: 5, wait_s: 30, net_s: 120 }

// The files of a machine by path, the commands on its PATH that prove themselves as a python, and what a look
// answers there.
type Machine = {
  files?: Record<string, string>
  pythons?: Record<string, string>
  look?: (args: readonly string[]) => Answer | Promise<Answer>
}

// What the module read, the pythons it tried, and each phi.py command it ran with its whole call.
type Seen = {
  read: string[]
  tried: string[][]
  looks: string[][]
  calls: { argv: readonly string[]; env: Readonly<Record<string, string>> | undefined }[]
  logged: string[]
}

// A path as the test wrote it: the engine hands a hook the path resolved on the machine the test runs on.
function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const seen: Seen = { read: [], tried: [], looks: [], calls: [], logged: [] }
  const files = has.files ?? { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '' }
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'cli-0001' }))
  on('session.root', () => ({ value: '/work/project' }))
  on('turn.complete', () => ({ text: '' }))
  on('session.receive', (_, e) => ({ text: e.text }))
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
  on('fs.exists', (_, e) => ({ value: files[plain(e.path)] !== undefined }))
  on('process.run', async (_, e) => {
    const at = e.argv.findIndex(arg => arg.endsWith('/scripts/phi.py'))
    let stdout = ''
    if (at >= 0) {
      const args = e.argv.slice(at + 1)
      seen.looks.push([...args])
      seen.calls.push({ argv: e.argv, env: e.init?.env })
      stdout = `${JSON.stringify(has.look === undefined ? ORCHESTRATOR : await has.look(args))}\n`
    } else {
      seen.tried.push([...e.argv])
      const path = (has.pythons ?? {})[e.argv[0] ?? '']
      if (path === undefined) return { deny: 'ENOENT' }
      stdout = `${path}\n`
    }

    return { value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
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

test('P4_PHI_WATCH=0 runs no look and arms no timer', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA, P4_PHI_WATCH: '0' })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await $.turn.complete(TURN)
  await $.session.receive(WORD)
  await clock.advance(3_600_000)

  expect(seen.looks).toEqual([])
  expect(seen.read).toEqual([])
})

test('a look that answers off is the last one', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { look: () => ({ watching: false, off: true, why: 'off' }) })

  await $.session.start(START)
  await clock.settle()
  await $.turn.complete(TURN)
  await clock.advance(3_600_000)

  expect(seen.looks.length).toBe(1)
})
