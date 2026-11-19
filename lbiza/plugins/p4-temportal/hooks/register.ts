// p4-temportal's hooks module: the part of the plugin that runs inside Claude Code, where a command hook runs once
// at its event and is gone. It runs the retention sweep, `lifetime.py tick`, at a session's start, on a timer while
// the session runs, and in a process let go of at the session's end. It finds the python that find-python.sh proved
// for the plugin's runner, as p4-phi's module does, and it starts no `sh`.

import type { EngineInterface, Register, Timer } from 'claude-code'

// What find-python.sh runs to prove an interpreter: the interpreter prints its own path.
const PROOF = "import sys; print(sys.executable.replace(chr(92), '/'))"

// How long a sweep may run before Claude Code ends it.
const SWEEP_MS = 120_000

// The timer's wait after a sweep that answered none, and the least and the most an answer sets it to, which are
// lifetime.py's LEAST_WAIT_S and MOST_WAIT_S.
const WAIT_MS = 600_000
const LEAST_WAIT_MS = 60_000
const MOST_WAIT_MS = 3_600_000

// The wait before the sweep that was asked for while one ran.
const ASKED_MS = 1_000

// How long the start of the last sweep may take where nothing meters a session's end.
const END_MS = 10_000

// What `lifetime.py tick` prints: the lines of what it moved and cleared, and the seconds until the next sweep.
type Answer = { said?: unknown; wait_s?: unknown; let_go?: unknown }

// The python that runs the plugin's scripts, searched for once. A reload of the module starts all of this over.
let finding: Promise<string | undefined> | undefined

// A sweep is in flight: there is never a second one from this module.
let isSweeping = false
// A sweep was asked for while one ran.
let isAsked = false
let timer: Timer | undefined

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

// The folders that hold each plugin's data folder. The manifest reference puts `${CLAUDE_PLUGIN_DATA}` at
// `~/.claude/plugins/data/<id>/`, and the loading reference puts an installed plugin at
// `cache/<marketplace>/<plugin>/<version>/` under the same plugins root, which `CLAUDE_CODE_PLUGIN_CACHE_DIR` moves.
async function dataRoots($: EngineInterface): Promise<string[]> {
  const roots: string[] = []
  const installed = /^(.+)\/cache\/[^/]+\/[^/]+\/[^/]+$/.exec(slashed($.plugin.root))
  if (installed?.[1]) roots.push(`${installed[1]}/data`)
  const moved = await $.env.get('CLAUDE_CODE_PLUGIN_CACHE_DIR')
  if (moved) roots.push(`${slashed(moved)}/data`)
  const config = await $.env.get('CLAUDE_CONFIG_DIR')
  if (config) roots.push(`${slashed(config)}/plugins/data`)
  const home = (await $.env.get('USERPROFILE')) ?? (await $.env.get('HOME'))
  if (home) roots.push(`${slashed(home)}/.claude/plugins/data`)
  return [...new Set(roots)]
}

// Where find-python.sh keeps the interpreter it proved: `.python` in the plugin's data folder, and in the plugin's
// own folder where a runner had no data folder. A data folder is named after the plugin's id, `<name>@<origin>`
// with `@` as `-`, and the module is told only the name, so each folder that starts with the name is read.
async function keptFiles($: EngineInterface): Promise<string[]> {
  const files: string[] = []
  const data = await $.env.get('CLAUDE_PLUGIN_DATA')
  if (data) files.push(`${slashed(data)}/.python`)
  for (const root of await dataRoots($)) {
    const entries = await $.fs.list(root).catch(() => [])
    for (const entry of entries) {
      const isOwn = entry.kind === 'dir' && entry.name.startsWith(`${$.plugin.name}-`)
      if (isOwn) files.push(`${root}/${entry.name}/.python`)
    }
  }
  files.push(`${slashed($.plugin.root)}/.python`)
  return files
}

// The interpreter a runner proved and kept, as find-python.sh reads it back: an absolute path that still exists.
async function keptPython($: EngineInterface): Promise<string | undefined> {
  for (const file of await keptFiles($)) {
    const text = await $.fs.read(file).catch(() => '')
    const path = (text.split('\n')[0] ?? '').trim()
    const isKept = path.includes('/') && (await $.fs.exists(path).catch(() => false))
    if (isKept) return path
  }
  return undefined
}

// With nothing kept, the search of find-python.sh: the launcher first on Windows, where `python3` can be the Store's
// stub, and `python3` first elsewhere. Each candidate is proven by one run, since a module has no `command -v`.
async function provenPython($: EngineInterface): Promise<string | undefined> {
  const isWindows = /^[A-Za-z]:[\\/]/.test($.plugin.root)
  const order = isWindows ? [['py', '-3'], ['python'], ['python3']] : [['python3'], ['python'], ['py', '-3']]
  for (const head of order) {
    try {
      const ran = await $.process.run([...head, '-I', '-c', PROOF], { timeoutMs: 10_000 })
      const path = ran.stdout.trim()
      if (ran.exitCode === 0 && path) return path
    } catch {
      // not on PATH: the next name
    }
  }
  return undefined
}

async function searchPython($: EngineInterface): Promise<string | undefined> {
  try {
    return (await keptPython($)) ?? (await provenPython($))
  } catch {
    return undefined
  }
}

// The python, searched for once while it is found. With none found, the next call searches again.
async function findPython($: EngineInterface): Promise<string | undefined> {
  finding ??= searchPython($)
  const python = await finding
  if (python === undefined) {
    finding = undefined
    note($, 'no working python found, so no retention sweep runs')
  }
  return python
}

// Runs one command of lifetime.py for this session's project, as the plugin's runner runs it, and reads the one
// JSON line it prints. The project is told to lifetime.py as a command hook's environment tells it.
async function ask($: EngineInterface, args: readonly string[], timeoutMs: number): Promise<Answer | undefined> {
  const python = await findPython($)
  if (python === undefined) return undefined
  const script = `${slashed($.plugin.root)}/hooks/lifetime.py`
  const env = { CLAUDE_PROJECT_DIR: await $.session.root() }
  let printed = ''
  try {
    const ran = await $.process.run([python, '-I', '-X', 'utf8', script, ...args], { env, timeoutMs })
    printed = ran.stdout.trim().split('\n').at(-1) ?? ''
  } catch (error) {
    finding = undefined
    note($, `lifetime.py ${args.join(' ')} did not run: ${reason(error)}`)
    return undefined
  }
  try {
    const answer: unknown = JSON.parse(printed)
    return typeof answer === 'object' && answer !== null ? (answer as Answer) : undefined
  } catch {
    return undefined
  }
}

// How long the timer waits after a sweep: what the sweep answered, within lifetime.py's own bounds.
function waitOf(answer: Answer | undefined): number {
  const seconds = answer?.wait_s
  if (typeof seconds !== 'number' || !(seconds > 0)) return WAIT_MS
  return Math.min(Math.max(Math.round(seconds * 1000), LEAST_WAIT_MS), MOST_WAIT_MS)
}

// The timer, set anew to fire `wait` milliseconds from this moment. No timer runs while a sweep does.
function arm($: EngineInterface, wait: number): void {
  timer?.cancel()
  timer = $.clock.every(Math.max(1, Math.round(wait)), () => {
    void sweep($)
  })
}

// One retention sweep, and then the timer for the next. What the sweep moved or cleared is a line of the transcript,
// which ezexe reads and the model does not.
async function sweep($: EngineInterface): Promise<void> {
  if (isSweeping) {
    isAsked = true
    return
  }
  isSweeping = true
  isAsked = false
  timer?.cancel()
  timer = undefined
  let wait = WAIT_MS
  try {
    const answer = await ask($, ['tick'], SWEEP_MS)
    const lines = Array.isArray(answer?.said) ? answer.said : []
    for (const line of lines) if (typeof line === 'string' && line) $.ui.log(line)
    wait = waitOf(answer)
  } catch (error) {
    note($, `the retention sweep failed: ${reason(error)}`)
  } finally {
    isSweeping = false
  }
  arm($, isAsked ? ASKED_MS : wait)
}

// The last sweep of a session, started in a process that lifetime.py lets go of, since every `session.end` hook
// shares one short bound and a sweep cut at it would leave files half cleared. `left` is what the bound has left.
async function lastSweep($: EngineInterface, left: number): Promise<void> {
  try {
    const within = Number.isFinite(left) ? Math.min(left, END_MS) : END_MS
    if (within < 1) return
    await ask($, ['tick', '--let-go'], Math.round(within))
  } catch (error) {
    note($, `the last retention sweep did not start: ${reason(error)}`)
  }
}

export const register: Register = on => {
  // The session does not wait for its first sweep.
  on('session.start', ($, e, next) => {
    void sweep($)

    return next(e)
  })

  // After a /clear or a resume the process goes on, and the timer with it. Every other reason ends the process.
  on('session.end', async ($, e, next) => {
    const isOver = e.reason !== 'clear' && e.reason !== 'resume'
    if (isOver) await lastSweep($, next.budget.remainingMs)

    return next(e)
  })
}
