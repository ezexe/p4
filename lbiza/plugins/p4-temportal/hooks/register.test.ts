// p4-temportal's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const DATA = '/home/u/.claude/plugins/data/p4-temportal-inline'
const KEPT = '/opt/python/bin/python3'
const START = { cwd: '/', surface: 'desktop', isInteractive: true } as const
const EXIT = { reason: 'prompt_input_exit', sessionId: 'cli-0001', resume: { id: 'cli-0001' } } as const

// What `lifetime.py tick` prints.
type Answer = Record<string, unknown>

// A sweep with nothing to say whose next one is an hour away, as lifetime.py answers in a store with no cookie.
const QUIET: Answer = { said: [], wait_s: 3600 }

// The files of a machine by path, the commands on its PATH that prove themselves as a python, and what a command of
// lifetime.py prints there.
type Machine = {
  files?: Record<string, string>
  pythons?: Record<string, string>
  tick?: (args: readonly string[]) => Answer | string | Promise<Answer | string>
}

// What the module read, the pythons it tried, each lifetime.py command it ran with its whole call, and what it
// logged, the transcript's lines apart from the debug log's.
type Seen = {
  read: string[]
  tried: string[][]
  ran: string[][]
  calls: { argv: readonly string[]; env: Readonly<Record<string, string>> | undefined; timeoutMs: number | undefined }[]
  shown: string[]
  debugged: string[]
}

// A path as the test wrote it: the engine hands a hook the path resolved on the machine the test runs on.
function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const files = has.files ?? { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '' }
  const seen: Seen = { read: [], tried: [], ran: [], calls: [], shown: [], debugged: [] }
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('session.root', () => ({ value: '/work/project' }))
  on('ui.log', (_, e) => {
    const lines = e.to === 'debug' ? seen.debugged : seen.shown
    lines.push(e.text)

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
    const at = e.argv.findIndex(arg => arg.endsWith('/hooks/lifetime.py'))
    let stdout = ''
    if (at >= 0) {
      const args = e.argv.slice(at + 1)
      seen.ran.push([...args])
      seen.calls.push({ argv: e.argv, env: e.init?.env, timeoutMs: e.init?.timeoutMs })
      const printed = has.tick === undefined ? QUIET : await has.tick(args)
      stdout = typeof printed === 'string' ? printed : `${JSON.stringify(printed)}\n`
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

test('a session starts with one sweep, lifetime.py tick run as the runner runs it and with no sh', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.ran).toEqual([['tick']])
  const call = seen.calls[0]
  expect(call?.argv.slice(0, 4)).toEqual([KEPT, '-I', '-X', 'utf8'])
  expect(call?.argv[4]?.endsWith('/hooks/lifetime.py')).toBe(true)
  expect(call?.env).toEqual({ CLAUDE_PROJECT_DIR: '/work/project' })
  expect(seen.read).toEqual([`${DATA}/.python`])
  expect(seen.tried).toEqual([])
})

test('the session does not wait for its first sweep', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let isDone = false
  const seen = machine(on, {
    tick: async () => {
      await clock.sleep(30_000)
      isDone = true

      return QUIET
    },
  })

  await $.session.start(START)
  await clock.settle()
  expect(seen.ran).toEqual([['tick']])
  expect(isDone).toBe(false)

  await clock.advance(30_000)
  expect(isDone).toBe(true)
})

test('a long session is swept while it runs, each time after the wait the sweep before it answered', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  // A cookie is due in a quarter of an hour, and after it no other.
  const seen = machine(on, { tick: () => ({ said: [], wait_s: seen.ran.length > 1 ? 3600 : 900 }) })

  await $.session.start(START)
  await clock.settle()
  expect(seen.ran.length).toBe(1)

  await clock.advance(899_999)
  expect(seen.ran.length).toBe(1)
  await clock.advance(1)
  expect(seen.ran.length).toBe(2)

  await clock.advance(3_599_999)
  expect(seen.ran.length).toBe(2)
  await clock.advance(1)
  expect(seen.ran.length).toBe(3)

  // Eight hours on, a sweep an hour.
  await clock.advance(8 * 3_600_000)
  expect(seen.ran.length).toBe(11)
  expect(seen.ran.every(args => args.length === 1 && args[0] === 'tick')).toBe(true)
})

test('the wait is a minute at least and an hour at most, and ten minutes when a sweep answers none', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const answers: (Answer | string)[] = [{ said: [], wait_s: 0.5 }, { said: [], wait_s: 86_400 }, 'Traceback\n', {}]
  const seen = machine(on, { tick: () => answers[seen.ran.length - 1] ?? QUIET })

  await $.session.start(START)
  await clock.settle()
  expect(seen.ran.length).toBe(1)

  await clock.advance(59_999)
  expect(seen.ran.length).toBe(1)
  await clock.advance(1)
  expect(seen.ran.length).toBe(2)

  await clock.advance(3_599_999)
  expect(seen.ran.length).toBe(2)
  await clock.advance(1)
  expect(seen.ran.length).toBe(3)

  // A line that is no JSON, and then JSON with no wait.
  await clock.advance(599_999)
  expect(seen.ran.length).toBe(3)
  await clock.advance(1)
  expect(seen.ran.length).toBe(4)
  await clock.advance(600_000)
  expect(seen.ran.length).toBe(5)
})

test('what a sweep moved or cleared is a line of the transcript, and a quiet sweep shows none', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const moved = 'moved memory/ to temportal/memory/.'
  const cleared = 'cleared expired files: 1, notebook/page.html.'
  const seen = machine(on, { tick: () => (seen.ran.length === 1 ? { said: [moved, cleared], wait_s: 60 } : QUIET) })

  await $.session.start(START)
  await clock.settle()
  expect(seen.shown).toEqual([moved, cleared])

  await clock.advance(60_000)
  expect(seen.ran.length).toBe(2)
  expect(seen.shown).toEqual([moved, cleared])
  expect(seen.debugged).toEqual([])
})

test('there is never a second sweep in flight', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let inFlight = 0
  let most = 0
  const seen = machine(on, {
    tick: async () => {
      inFlight += 1
      most = Math.max(most, inFlight)
      await clock.sleep(90_000)
      inFlight -= 1

      return { said: [], wait_s: 60 }
    },
  })

  await $.session.start(START)
  // The module loads again while its first sweep runs, as at a reload of another plugin.
  await $.session.start(START)
  await clock.advance(90_000)
  expect(seen.ran.length).toBe(1)

  // The start that found a sweep running is given its own a second after that one ends.
  await clock.advance(999)
  expect(seen.ran.length).toBe(1)
  await clock.advance(1)
  expect(seen.ran.length).toBe(2)

  await clock.advance(600_000)
  expect(most).toBe(1)
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

test('with no python at all no sweep runs, the debug log says so once, and the search is made again', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const pythons: Record<string, string> = {}
  const seen = machine(on, { files: {}, pythons })

  await $.session.start(START)
  await clock.advance(3_600_000)
  expect(seen.ran).toEqual([])
  expect(seen.debugged).toEqual(['no working python found, so no retention sweep runs'])
  expect(seen.shown).toEqual([])

  // A python is installed while the session runs: the timer's next search finds it.
  pythons.python = KEPT
  await clock.advance(600_000)
  expect(seen.ran).toEqual([['tick']])
})

test('a session that ends starts its last sweep in a process let go of, inside what the end has left', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { tick: args => (args.includes('--let-go') ? { let_go: true } : QUIET) })

  await $.session.start(START)
  await clock.settle()
  const ended = await $.session.end(EXIT)

  expect(ended).toEqual({ sessionId: 'cli-0001' })
  expect(seen.ran).toEqual([['tick'], ['tick', '--let-go']])
  const timeoutMs = seen.calls[1]?.timeoutMs ?? 0
  expect(timeoutMs).toBeGreaterThan(0)
  expect(timeoutMs).toBeLessThanOrEqual(10_000)
  expect(seen.calls[1]?.env).toEqual({ CLAUDE_PROJECT_DIR: '/work/project' })
})

test('every reason that ends the process starts the last sweep, and a clear or a resume starts none', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})
  const lastSweeps = () => seen.ran.filter(args => args.includes('--let-go')).length

  await $.session.start(START)
  await clock.settle()
  await $.session.end({ ...EXIT, reason: 'clear' })
  await $.session.end({ ...EXIT, reason: 'resume' })
  expect(lastSweeps()).toBe(0)

  // The timer runs on after a clear.
  await clock.advance(3_600_000)
  expect(seen.ran).toEqual([['tick'], ['tick']])

  await $.session.end({ ...EXIT, reason: 'other' })
  await $.session.end({ ...EXIT, reason: 'logout' })
  await $.session.end(EXIT)
  expect(lastSweeps()).toBe(3)
})

test('a last sweep that cannot start ends the session all the same', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: {} })

  const ended = await $.session.end(EXIT)
  await clock.settle()

  expect(ended).toEqual({ sessionId: 'cli-0001' })
  expect(seen.ran).toEqual([])
})
