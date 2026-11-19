// p4-native's misses: the situations in which a session does by hand what a tool of this host does, each with the
// tool to name. A row is here only with a miss seen live behind it. register.ts checks the rows where a tool call
// has run and where a turn ends, and hands one line of context that names the tool, once for each situation in a
// session. Nothing here refuses a call, starts a process or asks a model: a row is a pattern over a call's own
// input or a turn's own answer.

// One situation. `seen` is the miss as it was seen, `names` the tools the line names, each of which must answer in
// the session for the line to be handed, and `at` where it is checked: after a tool call or at a turn's end.
export type Miss = {
  id: string
  seen: string
  names: readonly string[]
  line: string
  at: 'call' | 'end'
}

// The tools a row is read off or names.
export const TERMINAL = 'mcp__terminal__run_in_terminal'
export const OWN_TOOL = 'mcp__p4-native__native'
const EVENTS = 'mcp__ccd_session_mgmt__list_events'
const SEARCH = 'mcp__ccd_session_mgmt__search_session_transcripts'
const EXPORT = 'mcp__ccd_session_mgmt__export_transcript'
// The tools that read another session, of which a line names those that answer here.
export const READERS = [EVENTS, SEARCH, EXPORT] as const
// The tools whose call can show a miss.
export const WATCHED = new Set(['Bash', 'PowerShell', 'Read', 'Grep', 'Glob', TERMINAL, 'SendMessage', 'CronCreate', 'ScheduleWakeup'])

export const MISSES: readonly Miss[] = [
  {
    id: 'worker-with-no-exit-notice',
    seen: 'A `claude -p` worker was started in a Terminal tab with no notice asked for its exit, seen on 2026-11-19.',
    names: ['SendMessage'],
    line:
      'p4-native: a `claude -p` worker was started in a Terminal tab and no notice was asked for its exit. ' +
      '`SendMessage` with `notify_when_idle` set to true, to that session, gives one notice when it goes idle or exits.',
    at: 'end',
  },
  {
    id: 'turn-ended-with-a-worker-out',
    seen: 'A session with workers out ended its turn with nothing set to wake it, seen on 2026-11-19.',
    names: ['CronCreate'],
    line:
      'p4-native: this turn ended with a worker out and nothing set to wake the session. `CronCreate` schedules a ' +
      'prompt that looks in on the worker.',
    at: 'end',
  },
  {
    id: 'gh-run-polled-in-a-loop',
    seen: 'A shell loop polled `gh run list` and slept between the polls, seen on 2026-11-19.',
    names: [],
    line:
      'p4-native: this command polls `gh run` and sleeps. `gh run watch <run id> --exit-status` ends by itself when ' +
      'the run does, so run it once with `run_in_background` and wait for its notice.',
    at: 'call',
  },
  {
    id: 'gh-run-list-short-commit',
    seen: '`gh run list --commit` was given a short commit hash and listed nothing, seen on 2026-11-19.',
    names: [],
    line:
      'p4-native: `gh run list --commit` takes the full 40 characters of a commit hash, and a short one matches no ' +
      'run. `git rev-parse <short hash>` prints the full one.',
    at: 'call',
  },
  {
    id: 'transcript-read-from-disk',
    seen: "A session read another session's transcript file from disk, seen on 2026-11-19.",
    names: READERS,
    line:
      "p4-native: this reads another session's transcript file from disk. The desktop app's own tools read a " +
      'session: {names}. `list_events` can answer a session at work with almost nothing, which the probe ' +
      '`list-events-of-a-session-at-work` watches.',
    at: 'call',
  },
  {
    id: 'host-limit-from-memory',
    seen: 'A limit of the host was stated from memory, seen on 2026-11-19.',
    names: [OWN_TOOL],
    line:
      "p4-native: the turn's answer states a limit of this host. What was measured here is in the capability map " +
      'and the probes, so call `mcp__p4-native__native` with `map` or `probes` before stating one.',
    at: 'end',
  },
]

// A command line that starts a scripted Claude Code run.
const WORKER = /\bclaude(?:\.exe)?\b[^|;&\n]*\s(?:-p|--print)(?:\s|$)/
// A command line that runs one script file, whose path is the first group.
const SCRIPT = /^\s*(?:[&.]|sh|bash|pwsh|powershell)\s+['"]?([^'"]+\.(?:ps1|sh))['"]?\s*$/
// A polled `gh run`, a wait between polls, and a short hash handed to `--commit`.
const GH_RUN = /\bgh\s+run\s+(?:list|view)\b/
const WAITS = /\b(?:sleep|Start-Sleep)\b/
const SHORT = /\bgh\s+run\s+list\b[^|;&\n]*--commit[=\s]+['"]?([0-9a-fA-F]{4,39})['"]?(?![0-9a-fA-F])/
// A transcript file of Claude Code, as its path is spelled on either system.
const TRANSCRIPT = /[\\/]\.claude[\\/]projects[\\/][^\s"'|;]*\.jsonl/
// A sentence that says the host cannot do a thing.
const HOST = '(?:desktop app|claude code|this host|this session|the harness|a headless (?:run|session)|a scripted run)'
const CANNOT = "(?:cannot|can't|can not|does not support|doesn't support|is not available|isn't available|has no way|has no tool|there is no way)"
const LIMIT = new RegExp(`\\b${HOST}\\b[^.\\n]{0,80}\\b${CANNOT}|${CANNOT}[^.\\n]{0,80}\\b${HOST}\\b`, 'i')

function text(input: Record<string, unknown>, key: string): string {
  const value = input[key]

  return typeof value === 'string' ? value : ''
}

// Whether a line or a script's text starts a scripted Claude Code run.
export function isWorker(source: string): boolean {
  return WORKER.test(source)
}

// The script file a Terminal command runs, and nothing for a line that runs none.
export function scriptOf(command: string): string | undefined {
  return SCRIPT.exec(command)?.[1]
}

// Whether a call asks for a notice of another session's exit, and whether it sets something that wakes this one.
export function isNotice(tool: string, input: Record<string, unknown>): boolean {
  return tool === 'SendMessage' && input.notify_when_idle === true
}

export function isWake(tool: string, input: Record<string, unknown>): boolean {
  return tool === 'CronCreate' || tool === 'ScheduleWakeup' || isNotice(tool, input)
}

// The misses one call shows, by id. `own` is this session's id, whose transcript file is its own to read.
export function atCall(tool: string, input: Record<string, unknown>, own: string): string[] {
  const out: string[] = []
  const command = tool === 'Bash' || tool === 'PowerShell' ? text(input, 'command') : ''
  if (GH_RUN.test(command) && WAITS.test(command)) out.push('gh-run-polled-in-a-loop')
  if (SHORT.test(command)) out.push('gh-run-list-short-commit')
  const read = [command, text(input, 'file_path'), text(input, 'path'), text(input, 'pattern')].join('\n')
  const file = TRANSCRIPT.exec(read)?.[0]
  if (file !== undefined && (own === '' || !file.includes(own))) out.push('transcript-read-from-disk')

  return out
}

// The misses a turn's end shows, by id: a worker out with no notice asked, that and nothing else set to wake the
// session, and an answer that states a limit of the host in a session that never asked the plugin what it is.
export function atEnd(state: { isWorkerOut: boolean; isNoticed: boolean; isWoken: boolean; hasAsked: boolean }, answer: string): string[] {
  const out: string[] = []
  if (state.isWorkerOut && !state.isNoticed) out.push('worker-with-no-exit-notice')
  if (state.isWorkerOut && !state.isNoticed && !state.isWoken) out.push('turn-ended-with-a-worker-out')
  if (!state.hasAsked && LIMIT.test(answer)) out.push('host-limit-from-memory')

  return out
}
