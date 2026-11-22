// p4-temportal's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On, SessionCompactResult, SessionMessage, SessionUsage } from 'claude-code'

const DATA = '/home/u/.claude/plugins/data/p4-temportal-inline'
const KEPT = '/opt/python/bin/python3'
const START = { cwd: '/', surface: 'desktop', isInteractive: true } as const
const EXIT = { reason: 'prompt_input_exit', sessionId: 'cli-0001', resume: { id: 'cli-0001' } } as const
// What the engine stamps on a command a person types: Enter at the prompt, on the main screen at 80 columns.
const TYPED = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } } as const
// The module's tool as a call names it.
const TOOL = 'mcp__p4-temportal__lifetime'
// A turn of the main conversation, as the engine starts one and ends it.
const BEGUN = { text: 'go on', turnId: 't1' } as const
const TURN = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const

// The keep list, word for word as the module adds it to what a summary is told.
const KEEP =
  'Keep each of these verbatim in the summary, one to a line: every session id, every file path, every branch, ' +
  'every commit hash, every decision with its source, every open item, and the path of every state page and ' +
  'hand-over note.'
// The two lines a ledger opens with, and the line that counts what it left out.
const LEDGER =
  'p4-temportal kept this list across a compaction. Nobody typed it: the plugin built it from the tool calls of ' +
  'the session.\nFiles this session wrote or edited, the latest last:'
const LEFT_OUT = 'Older paths left out of this list: '
// The line of the transcript that says why the session compacts.
const WHY = (percent: number, line: number): string =>
  `The context is at ${percent} percent, at or past temportal.compact_at ${line}, so the session compacts.`

// What Claude Code 2.1.330 answers a call of the plugin's tool that came to its run and found no hook there, as a
// scripted session on that build printed it.
const UNSERVED =
  'p4-temportal registered the tool lifetime but no hook answered this call: add on("tool.run", { tool: ' +
  '"mcp__p4-temportal__lifetime" }, ($, e) => ({ result: ... })) to the plugin.'

// The words a call of the tool was refused with. A call enters at `tool.call`, and its error comes back to the
// caller in one of two shapes: `{ deny }` where the module answered at `tool.call`, as on Claude Code 2.1.330,
// and the error Claude Code makes of a `{ deny }` given at `tool.run`, with the words as its `text`, as on 2.1.326
// to 2.1.328. Nothing for a call that was served.
function refusal(out: unknown): string | undefined {
  const answer = out as { deny?: unknown; text?: unknown; isError?: unknown }
  if (typeof answer.deny === 'string') return answer.deny

  return answer.isError === true && typeof answer.text === 'string' ? answer.text : undefined
}

// Whether the module answered a call at `tool.run`, which it does where a glob reaches that event, as on Claude
// Code 2.1.326 to 2.1.328. What is beneath `tool.call` was never asked then: on those builds the engine's own
// permission check stands before `tool.run`, which the live sessions showed and no test of this file can.
function ranAbove(seen: Seen): boolean {
  return seen.ran.length > 0
}

// What Claude Code answers a plugin's own `$.session.compact` in a session a program started, as seen in the
// desktop app on Claude Code 2.1.326 and in a scripted session on 2.1.328.
const REFUSED =
  '$.session.compact: not available in a headless (-p / SDK) session yet: compaction here runs inside a turn ' +
  '(a /compact prompt); catch it and carry on'
// How the line of the debug log opens that says why the slash command ran, and the debug log apart from it.
const FELL_BACK = '$.session.compact was refused, so /compact runs: '
function apart(lines: readonly string[]): string[] {
  return lines.filter(text => !text.startsWith(FELL_BACK))
}

// What Claude Code's own compaction leaves: the summary as a message of the user's, the engine's own.
const SUMMARY: SessionMessage = {
  role: 'user',
  text: 'This session is being continued from a previous conversation that ran out of context.',
  toolUses: [],
  handle: 'h-summary',
}

// What a person asked, as a message of the transcript: a compaction runs over one message at least.
const ASKED: SessionMessage = { role: 'user', text: 'Port the flush.', toolUses: [], handle: 'h-asked' }

// A message of the transcript in which the model called one tool.
function called(tool: string, input: Record<string, unknown>, isError?: true): SessionMessage {
  const use = { tool_use_id: `u-${tool}-${JSON.stringify(input)}`, tool, input, ...(isError ? { isError } : {}) }

  return { role: 'assistant', text: '', toolUses: [use], handle: `h-${use.tool_use_id}` }
}

// A ledger as the module writes one: its two opening lines, a line for each path, and the count of those left out.
function ledger(paths: readonly string[], left = 0): SessionMessage {
  const lines = [LEDGER, ...paths.map(path => `- ${path}`), ...(left > 0 ? [`${LEFT_OUT}${left}.`] : [])]

  return { role: 'user', text: lines.join('\n'), toolUses: [] }
}

// What `$.session.usage` answers with the context at `percent` of a window of a million tokens. A live probe in the
// desktop app on Claude Code 2.1.326 read auto-compaction on, at 967000 tokens. No percent is a context not measured
// since a compaction.
function usageAt(percent: number | undefined, more: { isOn?: boolean; threshold?: number | null } = {}): SessionUsage {
  const breakdown = {
    isAutoCompactEnabled: more.isOn ?? true,
    ...(more.threshold === null ? {} : { autoCompactThreshold: more.threshold ?? 967_000 }),
  }
  const measured = percent === undefined ? {} : { tokens: percent * 10_000, percent }

  return {
    startedAt: 0,
    context: { ...measured, window: 1_000_000, breakdown },
    rateLimits: [],
    cost: { usd: 0 },
  } as unknown as SessionUsage
}

// What `lifetime.py tick` prints.
type Answer = Record<string, unknown>

// A sweep with nothing to say whose next one is an hour away, as lifetime.py answers in a store with no cookie.
const QUIET: Answer = { said: [], wait_s: 3600 }

// How a command of lifetime.py other than tick ends: its exit status and what it printed.
type Said = { code?: number; out?: string; err?: string }

// The files of a machine by path, the commands on its PATH that prove themselves as a python, what a tick prints
// there and how each other command of lifetime.py ends, and whether the name /lifetime is taken.
type Machine = {
  files?: Record<string, string>
  pythons?: Record<string, string>
  tick?: (args: readonly string[]) => Answer | string | Promise<Answer | string>
  says?: (args: readonly string[]) => Said
  isTaken?: boolean
  // Whether the name of the tool lifetime is taken.
  isToolTaken?: boolean
  // What comes back up to the module's `tool.call` hook from beneath it. With none given the call was allowed,
  // came to its run and found no hook there, and it is what Claude Code 2.1.330 answers then. A refusal of the
  // permission check comes back as a `{ deny }`.
  comes?: () => unknown
  // What the session's state holds of the last turn's end as this copy of the module starts: what the copy before
  // a reload wrote. With none given the state is the kit's own, empty at the start.
  ended?: () => number
  // The version of Claude Code and the release it is built from, or none where the read is refused.
  version?: () => { version: string; base?: string } | undefined
  // What the session's context reads at this moment.
  usage?: () => SessionUsage
  // What the engine's own compaction answers, where it is not the summary alone.
  compacted?: SessionCompactResult
  // What a slash command the module runs waits on before it answers, or why the engine rejects it.
  command?: () => Promise<void>
  // The main checkout of the repository, for a session in a git worktree of it, as `$.session.repo` answers it.
  // With none given the session is in no repository.
  main?: string
  // What the SessionStart command hooks beneath the module hand as additional context.
  context?: readonly string[]
  // The conversation as the model is sent it, which `$.session.messages({ as: 'api' })` answers. With none given
  // the read is refused.
  sent?: readonly { role: 'user' | 'assistant'; content: readonly { type: 'text'; text: string }[] }[]
  // Whether Claude Code lets a plugin compact by `$.session.compact` here, as at a terminal's prompt. With none
  // given the session is one a program started, as the desktop app's is, and the call is refused.
  isOpen?: boolean
  // What Claude Code does inside a compaction before its result comes up: it raises the SessionStart of the source
  // `compact`, whose additional context it keeps behind the summary.
  inside?: () => Promise<void>
  // What each source of the settings holds, as Claude Code loaded it. With none given, every read is refused.
  settings?: Readonly<Record<string, Record<string, unknown>>>
}

// What the module read, the pythons it tried, the commands it registered, each lifetime.py command it ran with its
// whole call, and what it logged, the transcript's lines apart from the debug log's.
type Seen = {
  read: string[]
  tried: string[][]
  offered: { name: string; description: string; argumentHint?: string }[]
  tools: { name: string; description: string; inputSchema: unknown; isDeferred: unknown }[]
  ran: string[][]
  calls: { argv: readonly string[]; env: Readonly<Record<string, string>> | undefined; timeoutMs: number | undefined }[]
  shown: string[]
  debugged: string[]
  // What each compaction told the summarizer, the slash commands run beneath the plugin, and what each reading of
  // the context asked for.
  summarized: { trigger: string; instructions: string | undefined; agentId: string | undefined }[]
  commands: { command: string; args: string }[]
  measured: unknown[]
  // What the module wrote into the session's state of the last turn's end, in order.
  ends: unknown[]
  // The sources of the settings the module read, and the input each SessionStart command hook would get on stdin.
  sources: (string | undefined)[]
  starts: Record<string, unknown>[]
}

// A path as the test wrote it: the engine hands a hook the path resolved on the machine the test runs on.
function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const files = has.files ?? { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '' }
  const seen: Seen = {
    read: [],
    tried: [],
    offered: [],
    tools: [],
    ran: [],
    calls: [],
    shown: [],
    debugged: [],
    summarized: [],
    commands: [],
    measured: [],
    ends: [],
    sources: [],
    starts: [],
  }
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  // The SessionStart command hooks, which run beneath every hooks module and read this input on stdin.
  on('classic.SessionStart', (_, e) => {
    seen.starts.push({ ...e })

    return has.context === undefined ? {} : { additionalContext: [...has.context] }
  })
  // The PostToolUse command hooks, beneath every hooks module.
  on('classic.PostToolUse', () => ({}))
  on('settings.read', (_, e) => {
    seen.sources.push(e.source)
    if (has.settings === undefined) return { deny: 'the settings are closed to this plugin' }

    return { value: has.settings[e.source ?? ''] ?? {} }
  })
  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('session.usage', (_, e) => {
    seen.measured.push(e)

    return { value: (has.usage ?? (() => usageAt(10)))() }
  })
  on('session.compact', async (_, e) => {
    // The plugin's own call comes with no trigger here, where the engine stamps one on it. A stub that throws is
    // skipped, and with no stub left to answer the call rejects in the plugin, as the engine's refusal does.
    const isOwn = (e.trigger as string | undefined) === undefined || e.trigger === 'plugin'
    if (isOwn && has.isOpen !== true) throw new Error(REFUSED)
    seen.summarized.push({ trigger: e.trigger, instructions: e.instructions, agentId: e.agentId })
    await has.inside?.()

    return has.compacted ?? { messages: [SUMMARY], tokensBefore: 194_336, tokensAfter: 30_108 }
  })
  on('session.messages', () => (has.sent === undefined ? { deny: 'no transcript here' } : { value: has.sent }) as never)
  // A slash command the module runs. Its own `command.run` hook answers /lifetime above this one.
  on('command.run', async (_, e) => {
    seen.commands.push({ command: e.command, args: e.args })
    await has.command?.()

    return { text: 'Compacted' }
  })
  on('command.register', (_, e) => {
    if (has.isTaken === true) return { deny: '"/lifetime" refused: it is the built-in /lifetime' }
    seen.offered.push({ name: e.name, description: e.description, argumentHint: e.argumentHint })

    return { value: { command: e.name } }
  })
  // What is beneath the module at `tool.call`: the permission check and the run. This stands for Claude Code
  // 2.1.330, where no glob selects `tool.run`, so an allowed call finds no hook at its run and the engine's answer
  // comes back up. It names no `tool.run`, which an older Claude Code's test kit refuses a file for.
  on('tool.call', () => (has.comes?.() ?? { result: `Error: ${UNSERVED}`, text: UNSERVED, isError: true }) as never)
  // A tool the module registers, named as the engine names a plugin's tool.
  on('tool.register', (_, e) => {
    if (has.isToolTaken === true) return { deny: '"lifetime" refused: the name is taken' }
    seen.tools.push({ name: e.name, description: e.description, inputSchema: e.inputSchema, isDeferred: e.isDeferred })

    return { value: { tool: `mcp__p4-temportal__${e.name}` } }
  })
  on('session.version', () => {
    const version = has.version === undefined ? { version: '2.1.328', base: '2.1.328' } : has.version()

    return version === undefined ? { deny: 'the version is closed to this plugin' } : { value: version }
  })
  // The session's state beneath the plugin: what was written is noted, and a reading is what the copy of the
  // module before a reload left, where the test gives one.
  on('state.set', (_, e, next) => {
    seen.ends.push(e.value)

    return next(e)
  })
  if (has.ended !== undefined) {
    const ended = has.ended
    on('state.get', () => ({ value: { value: ended(), version: 1 } }))
  }
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('session.root', () => ({ value: '/work/project' }))
  on('session.repo', () => ({
    value: has.main === undefined ? null : { root: has.main, remote: null, internal: false, name: null },
  }))
  on('session.id', () => ({ value: 'cli-0001' }))
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
      const all = e.argv.slice(at + 1)
      seen.ran.push([...all])
      seen.calls.push({ argv: e.argv, env: e.init?.env, timeoutMs: e.init?.timeoutMs })
      // The command's own words: what the module hands of Claude Code's retention period comes ahead of its name.
      const args = all[0] === '--cleanup-days' ? all.slice(2) : all
      if (args[0] !== 'tick') {
        const said = has.says?.(args) ?? {}
        const value = { exitCode: said.code ?? 0, stdout: said.out ?? '', stderr: said.err ?? '' }

        return { value: { ...value, isStdoutTruncated: false, isStderrTruncated: false } }
      }
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

test('the start registers /lifetime with its four commands as the hint, and the session waits for it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)

  expect(seen.offered.map(command => command.name)).toEqual(['lifetime'])
  expect(seen.offered[0]?.argumentHint).toBe('list | set <path> <lifetime> | clear <path> | now')
  expect(seen.offered[0]?.description.length).toBeGreaterThan(20)
})

test('/lifetime list and now run lifetime.py with that command and answer what it printed', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const listed = 'cookie  notebook/page.html  expires 2026-11-26T07:30+00:00\ncache   notebook/.out/  max_age_days=14'
  const seen = machine(on, { says: args => ({ out: args[0] === 'list' ? `${listed}\n` : 'nothing has expired\n' }) })

  const list = await $.command.run({ command: 'lifetime', args: 'list', ...TYPED })
  const now = await $.command.run({ command: 'lifetime', args: '  now ', ...TYPED })
  await clock.settle()

  expect(list.text).toBe(listed)
  expect(now.text).toBe('nothing has expired')
  expect(seen.ran).toEqual([['list'], ['now']])
  const call = seen.calls[0]
  expect(call?.argv.slice(0, 4)).toEqual([KEPT, '-I', '-X', 'utf8'])
  expect(call?.argv[4]?.endsWith('/hooks/lifetime.py')).toBe(true)
  expect(call?.env).toEqual({ CLAUDE_PROJECT_DIR: '/work/project' })
})

test('/lifetime set takes a quoted path as one word, and the sweep after it sets the timer by the new cookie', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  // Before the set no cookie is due within the hour, and after it one is due in five minutes.
  let hasCookie = false
  const seen = machine(on, {
    tick: () => ({ said: [], wait_s: hasCookie ? 300 : 3600 }),
    says: () => {
      hasCookie = true

      return { out: 'notebook/a page.html: expires 2026-11-19T08:05\n' }
    },
  })

  await $.session.start(START)
  await clock.settle()
  expect(seen.ran).toEqual([['tick']])

  const set = await $.command.run({ command: 'lifetime', args: 'set "notebook/a page.html" 5m', ...TYPED })
  await clock.settle()
  expect(set.text).toBe('notebook/a page.html: expires 2026-11-19T08:05')
  expect(seen.ran).toEqual([['tick'], ['set', 'notebook/a page.html', '5m'], ['tick']])

  await clock.advance(299_999)
  expect(seen.ran.length).toBe(3)
  await clock.advance(1)
  expect(seen.ran.length).toBe(4)
  expect(seen.ran.at(-1)).toEqual(['tick'])
})

test('/lifetime clear takes one path, in single quotes too', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { says: () => ({ out: 'cleared\n' }) })

  const bare = await $.command.run({ command: 'lifetime', args: 'clear notebook/page.html', ...TYPED })
  const quoted = await $.command.run({ command: 'lifetime', args: "clear 'notebook/a page.html'", ...TYPED })
  await clock.settle()

  expect([bare.text, quoted.text]).toEqual(['cleared', 'cleared'])
  expect(seen.ran).toEqual([['clear', 'notebook/page.html'], ['clear', 'notebook/a page.html']])
})

test('an ask that fits none of the four commands is answered with the usage, and nothing runs', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})
  const asks = ['', 'help', 'tick', 'tick --let-go', 'sweep', 'list all', 'set notebook/page.html', 'clear', 'now now']
  const asked: (string | undefined)[] = []

  for (const args of asks) asked.push((await $.command.run({ command: 'lifetime', args, ...TYPED })).text)
  await clock.settle()

  const usage = '/lifetime list | set <path> <lifetime> | clear <path> | now\n'
  expect(asked.map(text => text?.startsWith(usage))).toEqual(asks.map(() => true))
  expect(seen.ran).toEqual([])
  expect(seen.tried).toEqual([])
})

test('a refusal of lifetime.py is the answer, and no sweep follows a set that was refused', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const refused = 'lifetime.py: memory/MEMORY.md is in memory/, which is never cleared'
  const seen = machine(on, { says: () => ({ code: 2, err: `${refused}\n` }) })

  const set = await $.command.run({ command: 'lifetime', args: 'set memory/MEMORY.md 7d', ...TYPED })
  await clock.settle()

  expect(set.text).toBe(refused)
  expect(seen.ran).toEqual([['set', 'memory/MEMORY.md', '7d']])
})

test('with no python /lifetime says that lifetime.py did not run', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: {} })

  const list = await $.command.run({ command: 'lifetime', args: 'list', ...TYPED })
  await clock.settle()

  expect(list.text).toBe('lifetime.py list did not run, and the debug log says why.')
  expect(seen.debugged).toEqual(['no working python found, so no retention sweep runs'])
})

test('where the name /lifetime is taken the debug log says so, and the session starts and is swept', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { isTaken: true })

  const started = await $.session.start(START)
  await clock.settle()

  expect(started).toEqual({ cwd: '/' })
  expect(seen.ran).toEqual([['tick']])
  expect(seen.debugged.length).toBe(1)
  expect(seen.debugged[0]?.startsWith('/lifetime was not registered: ')).toBe(true)
})

test('every compaction tells the summary the keep list, after what it was told already and once', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, {})

  await $.session.compact({ trigger: 'manual', instructions: 'Stress the flush.', messages: [ASKED] })
  await $.session.compact({ trigger: 'auto', messages: [ASKED] })
  await $.session.compact({ trigger: 'manual', instructions: KEEP, messages: [ASKED] })
  await $.session.compact({ trigger: 'auto', agentId: 'a1', messages: [ASKED] })
  await $.session.compact({ trigger: 'precompute', messages: [ASKED] })

  expect(seen.summarized).toEqual([
    { trigger: 'manual', instructions: `Stress the flush.\n\n${KEEP}`, agentId: undefined },
    { trigger: 'auto', instructions: KEEP, agentId: undefined },
    { trigger: 'manual', instructions: KEEP, agentId: undefined },
    { trigger: 'auto', instructions: KEEP, agentId: 'a1' },
    { trigger: 'precompute', instructions: KEEP, agentId: undefined },
  ])
  for (const kept of ['session id', 'file path', 'branch', 'commit hash', 'decision with its source', 'open item']) {
    expect(KEEP.includes(`every ${kept}`)).toBe(true)
  }
  expect(KEEP.includes('the path of every state page and hand-over note')).toBe(true)
})

test('after a compaction the ledger lists the files the session wrote or edited, each once, the latest last', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  machine(on, {})
  const messages = [
    ASKED,
    called('Read', { file_path: '/work/project/README.md' }),
    called('Write', { file_path: '/work/project/src/flush.ts', content: 'x' }),
    called('Edit', { file_path: 'C:\\work\\notes\\state.md', old_string: 'a', new_string: 'b' }),
    called('Bash', { command: 'git status' }),
    called('NotebookEdit', { notebook_path: '/work/project/run.ipynb', new_source: '1' }),
    called('Edit', { file_path: '/work/project/refused.ts', old_string: 'a', new_string: 'b' }, true),
    called('Write', { file_path: '/work/project/src/flush.ts', content: 'y' }),
    called('Edit', { file_path: 'C:/work/notes/state.md', old_string: 'b', new_string: 'c' }),
  ] satisfies SessionMessage[]

  const out = await $.session.compact({ trigger: 'manual', messages })

  expect(out.messages).toEqual([
    SUMMARY,
    ledger(['/work/project/run.ipynb', '/work/project/src/flush.ts', 'C:/work/notes/state.md']),
  ])
  expect(out.skip === undefined ? out.tokensAfter : undefined).toBe(30_108)
})

test('a ledger of the compaction before gives its paths to the next, and the result never holds two', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const before = { ...ledger(['/p/a.md', '/p/b.md']), handle: 'h-ledger' }
  machine(on, { compacted: { messages: [SUMMARY, before] } })
  const messages = [SUMMARY, before, called('Edit', { file_path: '/p/a.md' }), called('Write', { file_path: '/p/c.md' })]

  const out = await $.session.compact({ trigger: 'auto', messages })

  expect(out.messages).toEqual([SUMMARY, ledger(['/p/b.md', '/p/a.md', '/p/c.md'])])
})

test('a ledger lists the last sixty paths and counts the ones left out, across compactions', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  machine(on, {})
  const paths = Array.from({ length: 65 }, (_, at) => `/p/${at}.md`)

  const first = await $.session.compact({
    trigger: 'manual',
    messages: paths.map(path => called('Write', { file_path: path })),
  })
  const kept = first.messages?.at(-1)
  const second = await $.session.compact({
    trigger: 'manual',
    messages: [SUMMARY, { ...ledger(paths.slice(5), 5), handle: 'h-ledger' }, called('Write', { file_path: '/p/new.md' })],
  })

  expect(kept).toEqual(ledger(paths.slice(5), 5))
  expect(second.messages?.at(-1)).toEqual(ledger([...paths.slice(6), '/p/new.md'], 6))
})

test('a compaction that wrote no file adds no message, and neither does a skip or a precompute', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  machine(on, {})
  const wrote = [called('Write', { file_path: '/p/a.md' })]

  const read = await $.session.compact({ trigger: 'manual', messages: [called('Read', { file_path: '/p/a.md' })] })
  const ahead = await $.session.compact({ trigger: 'precompute', messages: wrote })
  const after = await $.session.compact({ trigger: 'auto', messages: wrote })

  expect(read.messages).toEqual([SUMMARY])
  expect(ahead.messages).toEqual([SUMMARY])
  expect(after.messages).toEqual([SUMMARY, ledger(['/p/a.md'])])
})

test('a compaction that was skipped stays skipped', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  machine(on, { compacted: { skip: 'a PreCompact hook blocked it' } })

  const out = await $.session.compact({ trigger: 'manual', messages: [called('Write', { file_path: '/p/a.md' })] })

  expect(out).toEqual({ skip: 'a PreCompact hook blocked it' })
})

test('in a session a program started, a quiet minute after a turn compacts by /compact with no words after it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { usage: () => usageAt(72) })
  await $.session.start(START)
  await clock.settle()

  await $.turn.complete(TURN)
  await clock.advance(59_999)
  const early = [...seen.commands]
  await clock.advance(1)
  await clock.settle()

  expect(early).toEqual([])
  expect(seen.commands).toEqual([{ command: 'compact', args: '' }])
  expect(seen.measured).toEqual([{ breakdown: 'summary' }])
  expect(seen.shown).toEqual([WHY(72, 70)])
  // Claude Code refused the plugin's own call, which the debug log says once, and no compaction came of that call.
  expect(seen.debugged.length).toBe(1)
  expect(seen.debugged[0]?.startsWith(FELL_BACK)).toBe(true)
  expect(seen.summarized).toEqual([])
})

test("at a terminal's prompt the quiet minute compacts by $.session.compact with the keep list, and no command runs", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { usage: () => usageAt(72), isOpen: true })
  await $.session.start(START)
  await clock.settle()

  await $.turn.complete(TURN)
  await clock.advance(60_000)
  await clock.settle()

  expect(seen.commands).toEqual([])
  expect(seen.summarized.map(told => told.instructions)).toEqual([KEEP])
  expect(seen.shown).toEqual([WHY(72, 70)])
  expect(seen.debugged).toEqual([])
})

test('the ledger of the main conversation is handed at the SessionStart Claude Code raises inside a compaction, and is no message', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const handed: unknown[] = []
  const seen = machine(on, {
    inside: async () => {
      handed.push(await $.classic.SessionStart({ source: 'compact' }))
    },
  })
  const wrote = [ASKED, called('Write', { file_path: '/p/a.md' }), called('Edit', { file_path: '/p/b.md' })]

  const out = await $.session.compact({ trigger: 'auto', messages: wrote })
  // A start that is no compaction's, and a second one of a compaction, take nothing.
  handed.push(await $.classic.SessionStart({ source: 'resume' }))
  handed.push(await $.classic.SessionStart({ source: 'compact' }))

  expect(out.messages).toEqual([SUMMARY])
  expect(handed).toEqual([{ additionalContext: [ledger(['/p/a.md', '/p/b.md']).text] }, {}, {}])
  expect(seen.starts.map(start => start.source)).toEqual(['compact', 'resume', 'compact'])
  expect(seen.debugged.filter(text => text.includes('list of written files'))).toEqual([])
})

test('the context the hooks beneath hand at that SessionStart comes first, and the ledger after it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const handed: unknown[] = []
  // A SessionStart command hook of another plugin, beneath this module, hands its own.
  machine(on, {
    context: ['the address book'],
    inside: async () => {
      handed.push(await $.classic.SessionStart({ source: 'compact' }))
    },
  })

  await $.session.compact({ trigger: 'manual', messages: [called('Write', { file_path: '/p/a.md' })] })

  expect(handed).toEqual([{ additionalContext: ['the address book', ledger(['/p/a.md']).text] }])
})

test('the ledger of the compaction before is read from the conversation as the model is sent it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const handed: unknown[] = []
  // What Claude Code kept of the SessionStart hook's additional context, as the model reads it, with another
  // hook's words around it.
  const before = `<system-reminder>\nSessionStart hook additional context: ${ledger(['/p/old.md', '/p/b.md'], 3).text}\n</system-reminder>`
  machine(on, {
    sent: [
      { role: 'user', content: [{ type: 'text', text: 'This session is being continued.' }] },
      { role: 'user', content: [{ type: 'text', text: 'the address book' }, { type: 'text', text: before }] },
      { role: 'assistant', content: [{ type: 'text', text: 'On it.' }] },
    ],
    inside: async () => {
      handed.push(await $.classic.SessionStart({ source: 'compact' }))
    },
  })

  await $.session.compact({ trigger: 'auto', messages: [ASKED, called('Edit', { file_path: '/p/b.md' }), called('Write', { file_path: '/p/new.md' })] })

  expect(handed).toEqual([{ additionalContext: [ledger(['/p/old.md', '/p/b.md', '/p/new.md'], 3).text] }])
})

test('a compaction that was skipped owes no ledger to a later SessionStart', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  machine(on, { compacted: { skip: 'a PreCompact hook blocked it' } })

  await $.session.compact({ trigger: 'manual', messages: [called('Write', { file_path: '/p/a.md' })] })

  expect(await $.classic.SessionStart({ source: 'compact' })).toEqual({})
})

test('a module loaded anew one second after a turn ended still compacts when the minute is over', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on, { now: 1_700_000_000_000 })
  // The copy before the reload wrote the turn's end, and its timer ended with it: this copy has none.
  let ended = 0
  const seen = machine(on, { usage: () => usageAt(72), ended: () => ended })
  ended = clock.now() - 1_000

  await $.session.start(START)
  await clock.settle()
  await clock.advance(58_999)
  const early = [...seen.commands]
  await clock.advance(1)
  await clock.settle()

  expect(early).toEqual([])
  expect(seen.commands).toEqual([{ command: 'compact', args: '' }])
  expect(seen.shown).toEqual([WHY(72, 70)])
  expect(seen.ends).toEqual([0])
  expect(apart(seen.debugged)).toEqual([])
})

test('a module loaded anew after the minute was over looks at the context at once, and one loaded with no turn ended does not', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on, { now: 1_700_000_000_000 })
  let ended = 0
  const seen = machine(on, { usage: () => usageAt(72), ended: () => ended })

  await $.session.start(START)
  await clock.settle()
  await clock.advance(120_000)
  const none = [...seen.commands]

  ended = clock.now() - 300_000
  await $.session.start(START)
  await clock.settle()
  await clock.advance(1)
  await clock.settle()

  expect(none).toEqual([])
  expect(seen.commands).toEqual([{ command: 'compact', args: '' }])
})

test('the end of a turn is kept in the state of the session, and a turn that begins takes it out again', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on, { now: 1_700_000_000_000 })
  const seen = machine(on, { usage: () => usageAt(10) })
  await $.session.start(START)
  await clock.settle()

  const at = clock.now()
  await $.turn.complete(TURN)
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await $.turn.start({ text: 'next', turnId: 't2' })
  await $.turn.start({ text: 'next', turnId: 't3', agentId: 'a1' })

  expect(seen.ends).toEqual([at, 0])
})

test('a turn that begins inside the minute ends the quiet, and a turn of a subagent neither ends nor starts it', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { usage: () => usageAt(72) })
  await $.session.start(START)
  await clock.settle()

  await $.turn.complete(TURN)
  await clock.advance(30_000)
  await $.turn.start(BEGUN)
  await clock.advance(600_000)
  const whileBusy = seen.measured.length
  await $.turn.complete(TURN)
  await clock.advance(30_000)
  await $.turn.start({ ...BEGUN, agentId: 'a1' })
  await $.turn.complete({ ...TURN, agentId: 'a1' })
  await clock.advance(29_999)
  const early = [...seen.commands]
  await clock.advance(1)
  await clock.settle()

  expect(whileBusy).toBe(0)
  expect(early).toEqual([])
  expect(seen.commands).toEqual([{ command: 'compact', args: '' }])
})

test('the line is the one the sweep answered, 70 until then, and under it nothing compacts', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let now = usageAt(69)
  let line: number | undefined
  const seen = machine(on, {
    usage: () => now,
    tick: () => (line === undefined ? QUIET : { ...QUIET, compact_at: line }),
  })
  await $.session.start(START)
  await clock.settle()

  await $.turn.complete(TURN)
  await clock.advance(60_000)
  const underSeventy = [...seen.commands]
  line = 40
  await clock.advance(3_600_000)
  now = usageAt(39)
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  const underForty = [...seen.commands]
  now = usageAt(45)
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  await clock.settle()

  expect(underSeventy).toEqual([])
  expect(underForty).toEqual([])
  expect(seen.commands).toEqual([{ command: 'compact', args: '' }])
  expect(seen.shown).toEqual([WHY(45, 40)])
})

test('a line of 0 starts no compaction and reads no context, and a line the sweep cannot give is left as it was', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let line: unknown = 0
  const seen = machine(on, { usage: () => usageAt(90), tick: () => ({ ...QUIET, compact_at: line }) })
  await $.session.start(START)
  await clock.settle()

  await $.turn.complete(TURN)
  await clock.advance(60_000)
  const off = { commands: [...seen.commands], measured: seen.measured.length }
  line = 'soon'
  await clock.advance(3_600_000)
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  const unread = [...seen.commands]
  line = 100
  await clock.advance(3_600_000)
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  await clock.settle()

  expect(off).toEqual({ commands: [], measured: 0 })
  expect(unread).toEqual([])
  expect(seen.commands).toEqual([])
})

test("no compaction starts where Claude Code's own is off, at the point of its own, or with no context measured", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let now = usageAt(80, { isOn: false, threshold: null })
  const seen = machine(on, { usage: () => now })
  await $.session.start(START)
  await clock.settle()
  const quiet = async (): Promise<number> => {
    await $.turn.complete(TURN)
    await clock.advance(60_000)
    await clock.settle()

    return seen.commands.length
  }

  const whileOff = await quiet()
  now = usageAt(97)
  const atItsOwn = await quiet()
  now = usageAt(undefined)
  const unmeasured = await quiet()
  now = usageAt(80)
  const due = await quiet()

  expect([whileOff, atItsOwn, unmeasured, due]).toEqual([0, 0, 0, 1])
  expect(seen.shown).toEqual([WHY(80, 70)])
})

test('a context at or past the line right after a compaction starts none, until Claude Code compacts again', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let now = usageAt(75)
  const seen = machine(on, { usage: () => now })
  await $.session.start(START)
  await clock.settle()
  const quiet = async (): Promise<number> => {
    await $.turn.complete(TURN)
    await clock.advance(60_000)
    await clock.settle()

    return seen.commands.length
  }

  const first = await quiet()
  await $.session.compact({ trigger: 'manual', instructions: KEEP, messages: [ASKED] })
  const rightAfter = await quiet()
  now = usageAt(90)
  const later = await quiet()
  await $.session.compact({ trigger: 'auto', messages: [ASKED] })
  now = usageAt(20)
  const under = await quiet()
  now = usageAt(71)
  const again = await quiet()

  expect([first, rightAfter, later, under, again]).toEqual([1, 1, 1, 1, 2])
  expect(apart(seen.debugged)).toEqual([
    'the context is at 75 percent right after a compaction, so temportal.compact_at 70 starts none',
  ])
})

test('the compaction of a subagent gets its own ledger and does not hold the main conversation', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { usage: () => usageAt(75) })
  await $.session.start(START)
  await clock.settle()

  const out = await $.session.compact({
    trigger: 'auto',
    agentId: 'a1',
    messages: [called('Write', { file_path: '/p/child.md' })],
  })
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  await clock.settle()

  expect(out.messages).toEqual([SUMMARY, ledger(['/p/child.md'])])
  expect(seen.commands).toEqual([{ command: 'compact', args: '' }])
})

test('while a compaction the module started runs it starts no second', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { usage: () => usageAt(75), command: () => clock.sleep(130_000) })
  await $.session.start(START)
  await clock.settle()

  await $.turn.complete(TURN)
  await clock.advance(60_000)
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  const inFlight = seen.commands.length
  await clock.advance(70_000)
  await $.turn.complete(TURN)
  await clock.advance(60_000)
  await clock.advance(130_000)

  expect(inFlight).toBe(1)
  expect(seen.commands.length).toBe(2)
})

test('the start registers one tool for the model, lifetime, which takes a command and its words', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  expect(seen.offered.map(command => command.name)).toEqual(['lifetime'])
  expect(seen.tools.map(tool => [tool.name, tool.isDeferred])).toEqual([['lifetime', undefined]])
  expect(seen.tools[0]?.inputSchema).toEqual({
    type: 'object',
    properties: {
      command: { type: 'string', enum: ['list', 'set', 'clear', 'now'] },
      path: { type: 'string' },
      lifetime: { type: 'string' },
    },
    required: ['command'],
  })
  for (const word of ['list', 'set', 'clear', 'now', '`path`', '`lifetime`', '.claude/p4/temportal/']) {
    expect(seen.tools[0]?.description.includes(word)).toBe(true)
  }
})

test('a call of the tool runs the command of lifetime.py it names, and what that printed is its result', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { says: args => ({ out: `ran ${args[0]}\n` }) })

  const list = await $.tool.call({ tool: TOOL, command: 'list' } as never)
  const now = await $.tool.call({ tool: TOOL, command: ' now ' } as never)
  const clear = await $.tool.call({ tool: TOOL, command: 'clear', path: '-old notes.md' } as never)
  await clock.settle()

  expect([list, now, clear]).toEqual([{ result: 'ran list' }, { result: 'ran now' }, { result: 'ran clear' }])
  expect(seen.ran).toEqual([['list'], ['now'], ['clear', '--', '-old notes.md']])
  expect(seen.calls[0]?.env).toEqual({ CLAUDE_PROJECT_DIR: '/work/project' })
})

test('a set by the tool takes a path and a lifetime, and the sweep after it sets the timer by the new cookie', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  let hasCookie = false
  const seen = machine(on, {
    tick: () => ({ said: [], wait_s: hasCookie ? 300 : 3600 }),
    says: () => {
      hasCookie = true

      return { out: 'notebook/a page.html: expires 2026-11-19T08:05\n' }
    },
  })
  await $.session.start(START)
  await clock.settle()

  const set = await $.tool.call({ tool: TOOL, command: 'set', path: 'notebook/a page.html', lifetime: '5m' } as never)
  await clock.settle()
  const after = seen.ran.map(args => [...args])
  await clock.advance(300_000)

  expect(set).toEqual({ result: 'notebook/a page.html: expires 2026-11-19T08:05' })
  expect(after).toEqual([['tick'], ['set', '--', 'notebook/a page.html', '5m'], ['tick']])
  expect(seen.ran.at(-1)).toEqual(['tick'])
  expect(seen.ran.length).toBe(4)
})

test('a call that fits none of the four commands is refused with what the tool takes, and nothing runs', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})
  const refused =
    'p4-temportal: `command` is list, set, clear or now. set takes `path` and `lifetime`, clear takes `path`, ' +
    'and list and now take neither.'

  const answers = [
    await $.tool.call({ tool: TOOL } as never),
    await $.tool.call({ tool: TOOL, command: 'sweep' } as never),
    await $.tool.call({ tool: TOOL, command: 'set', path: 'notebook/a.md' } as never),
    await $.tool.call({ tool: TOOL, command: 'set', path: '  ', lifetime: '7d' } as never),
    await $.tool.call({ tool: TOOL, command: 'clear' } as never),
    await $.tool.call({ tool: TOOL, command: 'clear', path: 'notebook/a.md', lifetime: '7d' } as never),
    await $.tool.call({ tool: TOOL, command: 'now', path: 'notebook/a.md' } as never),
    await $.tool.call({ tool: TOOL, command: 'list', path: 7 } as never),
  ]
  await clock.settle()

  expect(answers.slice(0, 7).map(refusal)).toEqual(Array.from({ length: 7 }, () => refused))
  expect(answers[7]).toEqual({ result: 'lifetime.py list printed nothing and exited 0.' })
  expect(seen.ran).toEqual([['list']])
})

test('a refusal of lifetime.py is the error of the call, and so is a call with no python', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const refused = 'lifetime.py: memory/MEMORY.md is in memory/, which is never cleared'
  const seen = machine(on, { says: () => ({ code: 2, err: `${refused}\n` }) })

  const set = await $.tool.call({ tool: TOOL, command: 'set', path: 'memory/MEMORY.md', lifetime: '7d' } as never)
  await clock.settle()

  expect(refusal(set)).toBe(refused)
  expect(seen.ran).toEqual([['set', '--', 'memory/MEMORY.md', '7d']])
})

test('with no python the tool says that lifetime.py did not run', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: {} })

  const list = await $.tool.call({ tool: TOOL, command: 'list' } as never)
  await clock.settle()

  expect(refusal(list)).toBe('lifetime.py list did not run, and the debug log says why.')
  expect(seen.debugged).toEqual(['no working python found, so no retention sweep runs'])
})

test('where the tool cannot be registered the debug log says so, and the command is registered all the same', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { isToolTaken: true })

  await $.session.start(START)
  await clock.settle()

  expect(seen.offered.map(command => command.name)).toEqual(['lifetime'])
  expect(seen.tools).toEqual([])
  expect(seen.debugged.length).toBe(1)
  expect(seen.debugged[0]?.startsWith('the tool lifetime was not registered: ')).toBe(true)
})

for (const version of ['2.1.311', '2.1.322', '2.1.325', '2.0.400', '1.9.999']) {
  test(`on Claude Code ${version}, which has no tool.run, no tool is registered and the command is`, async ($, on) => {
    mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
    const clock = mock.clock(on)
    const seen = machine(on, { version: () => ({ version, base: version }) })

    await $.session.start(START)
    await clock.settle()

    expect(seen.offered.map(command => command.name)).toEqual(['lifetime'])
    expect(seen.tools).toEqual([])
    expect(seen.debugged).toEqual([
      'the tool lifetime is not registered: this Claude Code has no `tool.run` event to serve it at',
    ])
  })
}

const RUNS: [string, { version: string; base?: string } | undefined][] = [
  ['2.1.326', { version: '2.1.326', base: '2.1.326' }],
  ['2.2.0', { version: '2.2.0', base: '2.2.0' }],
  ['3.0.1', { version: '3.0.1', base: '3.0.1' }],
  ['a development build of 2.1.328', { version: '2.1.328-dev.20261119.t101500.sha1a2b3c4', base: '2.1.328-dev' }],
  ['2.1.330 with no release named', { version: '2.1.330' }],
  ['a version spelled as no release', { version: 'from source' }],
  ['a version that cannot be read', undefined],
]
for (const [what, version] of RUNS) {
  test(`on Claude Code ${what} the tool is registered`, async ($, on) => {
    mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
    const clock = mock.clock(on)
    const seen = machine(on, { version: () => version })

    await $.session.start(START)
    await clock.settle()

    expect(seen.tools.map(tool => tool.name)).toEqual(['lifetime'])
    expect(seen.debugged).toEqual([])
  })
}

test('a call the permission check refused comes back with its refusal, and lifetime.py does not run', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, { comes: () => ({ deny: 'a deny rule names this tool' }) })

  const out = await $.tool.call({ tool: TOOL, command: 'now' } as never)
  if (ranAbove(seen)) return

  expect(refusal(out)).toBe('a deny rule names this tool')
  expect(seen.ran).toEqual([])
})

test("an error of the call that is not Claude Code's own answer for an unserved tool goes up as it came", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, {
    comes: () => ({ result: 'Error: the server is gone', text: 'the server is gone', isError: true }),
  })

  const out = await $.tool.call({ tool: TOOL, command: 'now' } as never)
  if (ranAbove(seen)) return

  expect(refusal(out)).toBe('the server is gone')
  expect(seen.ran).toEqual([])
})

test('a result that only quotes the words of an unserved call is no error, and runs nothing', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, { comes: () => ({ result: UNSERVED, text: UNSERVED }) })

  const out = await $.tool.call({ tool: TOOL, command: 'list' } as never)
  if (ranAbove(seen)) return

  expect(out).toEqual({ result: UNSERVED, text: UNSERVED })
  expect(seen.ran).toEqual([])
})

test('where a glob reaches tool.run, as on Claude Code 2.1.326 to 2.1.328, the allowed call is served there', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, { says: args => ({ out: `ran ${args[0]}
` }) })
  let out: unknown
  try {
    out = await ($.tool as unknown as { run: (e: unknown) => Promise<unknown> }).run({ tool: TOOL, command: 'now' })
  } catch (error) {
    out = String(error)
  }

  // On a Claude Code whose glob does not select tool.run, and on one with no such event, nothing answers a run.
  if (seen.ran.length === 0) expect(String(out)).toMatch(/no implementation for tool\.run|not a function/)
  else expect(out).toEqual({ result: 'ran now' })
  expect(seen.ran.length).toBeLessThanOrEqual(1)
})

test('a call that came back up as allowed and unserved runs lifetime.py once, at tool.call', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, { says: args => ({ out: `ran ${args[0]}
` }) })

  const out = await $.tool.call({ tool: TOOL, command: 'now' } as never)

  expect(out).toEqual({ result: 'ran now' })
  expect(seen.ran).toEqual([['now']])
})

test('a start hands every SessionStart command hook the settings of each source, the keys p4 reads and no other', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, {
    settings: {
      user: {
        autoMemoryDirectory: '~/notes',
        model: 'opus',
        apiKeyHelper: '/bin/secret',
        env: { P4_PHI_MAX_CHILDREN: '6', ANTHROPIC_AUTH_TOKEN: 'secret' },
        enabledPlugins: { 'p4-phi@p4-marketplace': true, 'other@market': true },
        permissions: { allow: ['Bash(ls *)'], additionalDirectories: ['~/beside'] },
      },
      project: { plansDirectory: 'docs/plans', autoMemoryEnabled: false },
      policy: { permissions: { blockWritesOutsideWorkingDirectories: true }, hooks: {} },
    },
  })

  await $.classic.SessionStart({ source: 'startup' })

  expect(seen.sources).toEqual(['user', 'project', 'local', 'policy'])
  expect(seen.starts.length).toBe(1)
  expect(seen.starts[0]?.source).toBe('startup')
  expect(seen.starts[0]?.p4_settings).toEqual({
    user: {
      autoMemoryDirectory: '~/notes',
      enabledPlugins: { 'p4-phi@p4-marketplace': true },
      env: { P4_PHI_MAX_CHILDREN: '6' },
      permissions: { additionalDirectories: ['~/beside'] },
    },
    project: { plansDirectory: 'docs/plans', autoMemoryEnabled: false },
    local: {},
    policy: { permissions: { blockWritesOutsideWorkingDirectories: true } },
  })
})

test('a permissions that is no object is handed as null, and an env or enabledPlugins that is none is left out', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, { settings: { policy: { permissions: 'all', env: ['P4_X'], enabledPlugins: 7 } } })

  await $.classic.SessionStart({ source: 'resume' })

  expect(seen.starts[0]?.p4_settings).toEqual({ user: {}, project: {}, local: {}, policy: { permissions: null } })
})

test('where the settings cannot be read the input goes down as it came, and the debug log says so once', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const seen = machine(on, {})

  await $.classic.SessionStart({ source: 'startup' })
  await $.classic.SessionStart({ source: 'clear' })

  expect(seen.starts.map(start => start.source)).toEqual(['startup', 'clear'])
  expect(seen.starts.some(start => 'p4_settings' in start)).toBe(false)
  const said = seen.debugged.filter(text => text.startsWith('the settings were not read'))
  expect(said.length).toBe(1)
  expect(said[0]).toContain("so the plugin's python reads the settings files")
  expect(said[0]).toContain('the settings are closed to this plugin')
})

test("each run of lifetime.py is handed Claude Code's cleanupPeriodDays as it merged the settings, ahead of the command's name", async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  // The merge of every source is the read that names no source.
  const seen = machine(on, { settings: { '': { cleanupPeriodDays: 14, model: 'opus' } } })

  await $.session.start(START)
  await clock.settle()
  await $.command.run({ command: 'lifetime', args: 'now', ...TYPED })
  await $.session.end(EXIT)

  expect(seen.ran).toEqual([
    ['--cleanup-days', '14', 'tick'],
    ['--cleanup-days', '14', 'now'],
    ['--cleanup-days', '14', 'tick', '--let-go'],
  ])
  expect(seen.sources).toEqual([undefined, undefined, undefined])
})

test('where no settings source holds cleanupPeriodDays nothing is handed, and a value that is no number is handed as it is', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const merged: Record<string, unknown> = { model: 'opus' }
  const seen = machine(on, { settings: { '': merged } })

  await $.session.start(START)
  await clock.settle()
  expect(seen.ran).toEqual([['tick']])

  // lifetime.py judges the value, and clears no plan by an age it cannot read.
  merged.cleanupPeriodDays = 'a month'
  await $.command.run({ command: 'lifetime', args: 'list', ...TYPED })
  expect(seen.ran[1]).toEqual(['--cleanup-days', '"a month"', 'list'])
})

// p4-native's capability map in the store of the machine's project, with one entry for each session id given.
const MAP = '/work/project/.claude/p4/native/host.json'
function mapOf(sessions: Record<string, { platform?: string }>): string {
  const entry = { at: '2026-11-19T14:37:03.384Z', host: 'terminal', run: 'scripted', claude: '2.1.328' }
  const entries = Object.entries(sessions).map(([id, more]) => [id, { ...entry, ...more }])

  return JSON.stringify({ sessions: Object.fromEntries(entries) })
}

// The order in which the search of a python tries its names on Windows, and anywhere else.
const WINDOWS_FIRST = ['py', 'python', 'python3']
const ELSEWHERE_FIRST = ['python3', 'python', 'py']

test("with p4-native's map holding this session as windows, the search tries the launcher first", async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: { [MAP]: mapOf({ 'cli-0001': { platform: 'windows' } }) }, pythons: {} })

  await $.session.start(START)
  await clock.settle()

  expect(seen.tried.map(argv => argv[0])).toEqual(WINDOWS_FIRST)
  expect(seen.read).toContain(MAP)
})

test("in a git worktree the map is read from the main checkout's store, where p4-native keeps it", async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const kept = '/work/main/.claude/p4/native/host.json'
  const seen = machine(on, { main: '/work/main', files: { [kept]: mapOf({ 'cli-0001': { platform: 'windows' } }) }, pythons: {} })

  await $.session.start(START)
  await clock.settle()

  expect(seen.tried.map(argv => argv[0])).toEqual(WINDOWS_FIRST)
  expect(seen.read).toContain(kept)
})

test("where the main checkout's store holds no entry of this session, the map of the session's own root is read", async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const files = {
    '/work/main/.claude/p4/native/host.json': mapOf({ 'cli-0002': { platform: 'linux' } }),
    [MAP]: mapOf({ 'cli-0001': { platform: 'windows' } }),
  }
  const seen = machine(on, { main: '/work/main', files, pythons: {} })

  await $.session.start(START)
  await clock.settle()

  expect(seen.tried.map(argv => argv[0])).toEqual(WINDOWS_FIRST)
})

test("with p4-native's map holding this session as wsl, as linux or macos, the search tries python3 first", async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: { [MAP]: mapOf({ 'cli-0001': { platform: 'wsl' } }) }, pythons: {} })

  await $.session.start(START)
  await clock.settle()

  expect(seen.tried.map(argv => argv[0])).toEqual(ELSEWHERE_FIRST)
})

test('with no map the search reads the shape of its own folder, as it did before', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: {} })

  await $.session.start(START)
  await clock.settle()

  expect(seen.read).toContain(MAP)
  expect([WINDOWS_FIRST, ELSEWHERE_FIRST]).toContainEqual(seen.tried.map(argv => argv[0]))
})

// A map that holds no platform for this session: each leaves the module's own reading, which the map of the test
// would turn round if it were read.
for (const [what, map] of [
  ['an entry of another session', (other: string) => mapOf({ 'cli-0002': { platform: other } })],
  ['an entry that says unknown', () => mapOf({ 'cli-0001': { platform: 'unknown' } })],
  ['an entry with no platform', () => mapOf({ 'cli-0001': {} })],
  ['a map that is no JSON', () => '{"sessions": '],
] as const) {
  test(`${what} leaves the search its own reading of the folder`, async ($, on) => {
    mock.env(on, {})
    const clock = mock.clock(on)
    const files: Record<string, string> = {}
    const seen = machine(on, { files, pythons: {} })
    await $.session.start(START)
    await clock.settle()
    const own = seen.tried.map(argv => argv[0])
    expect(own.length).toBe(3)

    // The timer's next search, with the map in place.
    files[MAP] = map(own[0] === 'py' ? 'linux' : 'windows')
    await clock.advance(600_000)

    expect(seen.tried.map(argv => argv[0]).slice(3, 6)).toEqual(own)
  })
}

// A tool call that wrote a file, as a PostToolUse hook is handed it: what the Write tool answers names the file and
// says whether it made it, and what Edit answers names the file.
function wrote(tool: 'Write' | 'Edit' | 'Read', filePath: string, type?: 'create' | 'update') {
  const tool_response = type === undefined ? { filePath } : { type, filePath }

  return { tool_name: tool, tool_input: { file_path: filePath }, tool_response, tool_use_id: `u-${tool}-${filePath}` }
}

test('the last sweep is handed the plan files the session created and the ones it wrote again', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { tick: args => (args.includes('--let-go') ? { let_go: true } : QUIET) })
  const own = 'C:\\Users\\u\\.claude\\plans'

  await $.session.start(START)
  await clock.settle()
  await $.classic.PostToolUse(wrote('Write', `${own}\\made-here.md`, 'create'))
  await $.classic.PostToolUse(wrote('Edit', `${own}\\made-here.md`))
  await $.classic.PostToolUse(wrote('Edit', '/home/u/.claude/plans/made-elsewhere.md'))
  await $.classic.PostToolUse(wrote('Write', '/home/u/.claude/plans/written-again.md', 'update'))
  await $.session.end(EXIT)

  expect(seen.ran.at(-1)).toEqual([
    'tick',
    '--let-go',
    '--plan',
    `${own}\\made-here.md`,
    '--plan-edited',
    '/home/u/.claude/plans/made-elsewhere.md',
    '--plan-edited',
    '/home/u/.claude/plans/written-again.md',
  ])
})

test('a file outside a folder named plans, one a folder deeper, one that is no markdown and one only read are not handed on', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { tick: args => (args.includes('--let-go') ? { let_go: true } : QUIET) })

  await $.session.start(START)
  await clock.settle()
  await $.classic.PostToolUse(wrote('Write', '/work/project/docs/plan.md', 'create'))
  await $.classic.PostToolUse(wrote('Write', '/home/u/.claude/plans/notes.txt', 'create'))
  await $.classic.PostToolUse(wrote('Write', '/home/u/.claude/plans/deep/er.md', 'create'))
  await $.classic.PostToolUse(wrote('Read', '/home/u/.claude/plans/read.md'))
  await $.classic.PostToolUse({ tool_name: 'Bash', tool_input: { command: 'ls' }, tool_response: 'x', tool_use_id: 'u-b' })
  await $.session.end(EXIT)

  expect(seen.ran.at(-1)).toEqual(['tick', '--let-go'])
})

// The data folder Claude Code names for the plugin, which no search of the plugins folders would find.
const TOLD = '/elsewhere/data/p4-temportal-p4-marketplace'
// What `$.process.hookEnv` answers: the variables a command hook of the plugin gets. In a session of the desktop
// app in a git worktree the project among them is the main checkout.
const HOOK_ENV = {
  CLAUDE_CODE_SESSION_ID: 'cli-0001',
  CLAUDE_PID: '4242',
  CLAUDE_PROJECT_DIR: '/main/checkout',
  CLAUDE_PLUGIN_ROOT: '/plugins/p4-temportal',
  CLAUDE_PLUGIN_DATA: TOLD,
}

test('the python child gets the environment of the plugin\'s command hooks, and the data folder is the one Claude Code names', async ($, on) => {
  const clock = mock.clock(on)
  // The call is answered through a glob, so that this file still loads on a Claude Code with no such event.
  let isAsked = false
  on('process.*', (_, e, next) => {
    if (next.event !== 'process.hookEnv') return next(e)
    isAsked = true

    return { value: HOOK_ENV } as never
  })
  const seen = machine(on, { files: { [`${TOLD}/.python`]: `${KEPT}\n`, [KEPT]: '' } })

  await $.session.start(START)
  await clock.settle()

  // A Claude Code with no such call never asks, and the test after this one holds what the module does there.
  if (!isAsked) return
  expect(seen.ran).toEqual([['tick']])
  // Every variable is the engine's but the project, which is the session's own root.
  expect(seen.calls[0]?.env).toEqual({ ...HOOK_ENV, CLAUDE_PROJECT_DIR: '/work/project' })
  // The kept interpreter is read from the folder that was named, and no folder is searched for it.
  expect(seen.read).toEqual([`${TOLD}/.python`])
  expect(seen.tried).toEqual([])
})

test('on a Claude Code with no $.process.hookEnv the module names the project and finds the data folder by hand', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, {})

  await $.session.start(START)
  await clock.settle()

  // Nothing answers the call here, so it rejects in the module, as a build that lacks it throws.
  expect(seen.calls[0]?.env).toEqual({ CLAUDE_PROJECT_DIR: '/work/project' })
  expect(seen.read).toEqual([`${DATA}/.python`])
})
