// p4-phi's hooks module: the part of the plugin that runs inside Claude Code, where a command hook can only print.
// It finds the python that find-python.sh proved for the plugin's runners, and it is an orchestrator's watcher: it
// runs `phi.py look`, one pass over the session's subtree that writes its ledger, at a turn's end, at a message's
// arrival and on a timer.

import type { EngineInterface, Register, Timer } from 'claude-code'

// What find-python.sh runs to prove an interpreter: the interpreter prints its own path.
const PROOF = "import sys; print(sys.executable.replace(chr(92), '/'))"

// How long a look may run before Claude Code ends it. A slow look reads GitHub once for each issue of the subtree.
const LOOK_MS = 60_000
const SLOW_LOOK_MS = 300_000

// A session with nothing to watch is checked again after a wait that doubles, to this at most.
const MOST_WAIT_MS = 600_000

// What `phi.py look` prints, as puppeteer.look answers it: the times are seconds.
type Answer = {
  dir?: string
  watching?: boolean
  off?: boolean
  changed?: boolean
  net?: boolean
  watch_s?: number
  wait_s?: number
  net_s?: number
}

// The python that runs the plugin's scripts, searched for once. A reload of the module starts all of this over.
let finding: Promise<string | undefined> | undefined

// The watcher. P4_PHI=0 or P4_PHI_WATCH=0 turns it off, which is read once, ahead of the first look.
let switches: Promise<boolean> | undefined
let isOff = false
// A look is in flight: there is never a second one.
let isLooking = false
// An event asked for a look that has not started.
let isAsked = false
// The last look went over a subtree, so this session is an orchestrator.
let isWatching = false
// When the last look started, and the last slow one, in the milliseconds of `$.clock.now()`: never, at first.
let lookedAt = Number.NEGATIVE_INFINITY
let slowAt = Number.NEGATIVE_INFINITY
// The least time between two looks, which is `phi.watch_s`, how long the timer waits after a look, and how often a
// look is a slow one, each as the last look answered it.
let tickMs = 5_000
let waitMs = 5_000
let slowMs = 120_000
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
    note($, 'no working python found, so no look runs')
  }
  return python
}

// Runs one command of phi.py for this session, as a hook's runner runs it, and reads the one JSON line it prints.
// The session is told to phi.py as a command hook's environment tells it.
async function ask($: EngineInterface, args: readonly string[], timeoutMs: number): Promise<Answer | undefined> {
  const python = await findPython($)
  if (python === undefined) return undefined
  const script = `${slashed($.plugin.root)}/scripts/phi.py`
  const env = { CLAUDE_CODE_SESSION_ID: await $.session.id(), CLAUDE_PROJECT_DIR: await $.session.root() }
  let printed = ''
  try {
    const ran = await $.process.run([python, '-I', '-X', 'utf8', script, ...args], { env, timeoutMs })
    printed = ran.stdout.trim().split('\n').at(-1) ?? ''
  } catch (error) {
    finding = undefined
    note($, `phi.py ${args.join(' ')} did not run: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
    return undefined
  }
  try {
    const answer: unknown = JSON.parse(printed)
    return typeof answer === 'object' && answer !== null ? (answer as Answer) : undefined
  } catch {
    return undefined
  }
}

function milliseconds(seconds: number | undefined, otherwise: number): number {
  return typeof seconds === 'number' && seconds > 0 ? Math.max(50, Math.round(seconds * 1000)) : otherwise
}

// What a look answered, kept for the pace of the next ones. An orchestrator's timer waits as the look says, and
// one tick after an event's look, which can start before the command hooks of that event have written. A session
// with nothing to watch backs off: its wait doubles at each such answer.
function paceBy(answer: Answer | undefined, startedAt: number, wasSlow: boolean, wasAsked: boolean): void {
  if (answer?.off === true) {
    isOff = true
    isWatching = false
    return
  }
  const wasWatching = isWatching
  isWatching = answer?.watching === true
  tickMs = milliseconds(answer?.watch_s, tickMs)
  slowMs = milliseconds(answer?.net_s, slowMs)
  const told = milliseconds(answer?.wait_s, tickMs)
  if (isWatching) {
    if (wasSlow) slowAt = startedAt
    waitMs = wasAsked ? tickMs : told
  } else {
    waitMs = wasWatching ? told : Math.min(Math.max(waitMs * 2, told), Math.max(MOST_WAIT_MS, told))
  }
}

// The watcher's timer, set anew to fire `wait` milliseconds from this moment. No timer runs while a look does.
function arm($: EngineInterface, wait: number): void {
  timer?.cancel()
  timer = isOff
    ? undefined
    : $.clock.every(Math.max(1, Math.round(wait)), () => {
        void look($, false)
      })
}

// How long after a look's start the next one is due: one tick when an event asked for it, else the timer's wait.
function dueAfter(): number {
  return isAsked ? tickMs : Math.max(tickMs, waitMs)
}

async function isSwitchedOff($: EngineInterface): Promise<boolean> {
  try {
    return (await $.env.get('P4_PHI')) === '0' || (await $.env.get('P4_PHI_WATCH')) === '0'
  } catch {
    return false
  }
}

// One look, when one is due: never two in flight, and never two within the watcher's tick. A look asked for too
// early is taken by the timer when it is due.
async function look($: EngineInterface, isEvent: boolean): Promise<void> {
  try {
    switches ??= isSwitchedOff($)
    if (await switches) isOff = true
    if (isOff) return
    if (isEvent) isAsked = true
    const now = await $.clock.now()
    // The look in flight arms the timer at its end for what was asked meanwhile.
    if (isLooking) return
    const since = now - lookedAt
    if (since < dueAfter()) {
      arm($, dueAfter() - since)
      return
    }
    const wasAsked = isAsked
    const isSlow = now - slowAt >= slowMs
    isLooking = true
    isAsked = false
    lookedAt = now
    timer?.cancel()
    timer = undefined
    let answer: Answer | undefined
    try {
      answer = await ask($, isSlow ? ['look', '--net'] : ['look'], isSlow ? SLOW_LOOK_MS : LOOK_MS)
    } catch (error) {
      note($, `the watcher's look failed: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
    } finally {
      isLooking = false
    }
    paceBy(answer, now, isSlow, wasAsked)
    arm($, dueAfter() - ((await $.clock.now()) - now))
  } catch (error) {
    note($, `the watcher's timer failed: ${String((error as Error)?.message ?? error).slice(0, 200)}`)
  }
}

export const register: Register = on => {
  // At a session's start, and at each reload of the module: the first look, which arms the timer. The session
  // does not wait for it.
  on('session.start', ($, e, next) => {
    void look($, true)

    return next(e)
  })

  // A turn's end changes what the ledger shows: the main conversation's for every session, since it is where a
  // session comes to have a task or a child, and a subagent's for an orchestrator, whose ledger names what it wrote.
  on('turn.complete', ($, e, next) => {
    if (e.agentId === undefined || isWatching) void look($, true)

    return next(e)
  })

  // A message's arrival is a child's report or another session's word, which an orchestrator's ledger shows.
  on('session.receive', ($, e, next) => {
    if (isWatching) void look($, true)

    return next(e)
  })
}
