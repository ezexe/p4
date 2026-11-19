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
  // What `hook.py lookup-check` prints for a call's input: a PreToolUse command hook's output, or nothing.
  check?: (payload: Record<string, unknown>) => unknown
  // What the goal command prints for a condition, where it is not `Goal set: <condition>`.
  goalSays?: (condition: string) => string
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
  // Each run of `hook.py lookup-check`: its command line past the script, its environment and its input.
  checks: { args: string[]; env: Readonly<Record<string, string>> | undefined; payload: Record<string, unknown> }[]
  // The slash commands it ran, each as a person would type it.
  ran: { command: string; args: string }[]
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
    checks: [],
    ran: [],
  }
  on('command.run', (_, e) => {
    seen.ran.push({ command: e.command, args: e.args })

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
  on('process.run', async (_, e) => {
    const at = e.argv.findIndex(arg => arg.endsWith('/scripts/phi.py'))
    const hook = e.argv.findIndex(arg => arg.endsWith('/scripts/hook.py'))
    let stdout = ''
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
      } else if (args[0] === 'goal') {
        seen.asked.push([...args])
        stdout = `${JSON.stringify({ set: true })}\n`
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

test('a goal the command did not set is said to the debug log, and python is not told', async ($, on) => {
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
  expect(seen.asked).toEqual([])
  expect(seen.logged.filter(line => line.includes('did not set the goal')).length).toBe(1)
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
  await $.tool.check(call('MultiEdit', { file_path: 'a.py', edits: [] }))
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
