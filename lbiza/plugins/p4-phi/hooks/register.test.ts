// p4-phi's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On, SessionUsage } from 'claude-code'

const DATA = '/home/u/.claude/plugins/data/p4-phi-inline'
const KEPT = '/opt/python/bin/python3'
const FOLDER = '/work/project/.claude/p4/phi/sessions/local_top00001'
const START = { cwd: '/', surface: 'desktop', isInteractive: true } as const
const TURN = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const
const WORD = { origin: { kind: 'peer' }, text: 'the flush is ported' } as const

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
  usage?: SessionUsage
  // Why a message to an address is not delivered there, where it is not.
  refuses?: (to: string) => string | undefined
}

// What the module read, the pythons it tried, each phi.py command it ran with its whole call, what it wrote and
// the messages it sent to other sessions.
type Seen = {
  files: Record<string, string>
  read: string[]
  tried: string[][]
  looks: string[][]
  calls: { argv: readonly string[]; env: Readonly<Record<string, string>> | undefined }[]
  wrote: { path: string; text: string }[]
  logged: string[]
  sent: { to: string; text: string }[]
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
    calls: [],
    wrote: [],
    logged: [],
    sent: [],
  }
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.measure', (_, e) => ({ changed: e.changed }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('session.usage', () => ({ value: has.usage ?? USAGE }))
  on('fs.write', (_, e) => {
    seen.wrote.push({ path: plain(e.path), text: e.text })
    files[plain(e.path)] = e.text

    return { value: undefined }
  })
  on('session.id', () => ({ value: 'cli-0001' }))
  on('session.root', () => ({ value: '/work/project' }))
  on('turn.complete', () => ({ text: '' }))
  on('session.receive', (_, e) => ({ text: e.text }))
  on('session.send', (_, e) => {
    seen.sent.push({ to: e.to, text: e.text })
    const reason = has.refuses?.(e.to)

    return reason === undefined ? { isDelivered: true } : { isDelivered: false, reason }
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
