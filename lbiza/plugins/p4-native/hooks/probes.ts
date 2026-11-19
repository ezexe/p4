// p4-native's watched conditions: one probe for each decision the platform blocked and each known fault of the
// host. A probe names the decision it belongs to, the answer that decision was made on, and how the answer is read
// again. register.ts runs the probes when the Claude Code version of a host changes and on request, never at every
// start, and tells the session once when an answer changed.
//
// A probe is one of three kinds. `asked` is run by the module: it reads the capability map or makes one call that
// changes nothing, and this file reads the answer off what came back. The module makes each call itself, since the
// engine has `$` spelled at the call site and passed to no function a value holds. `seen` is read off a call the
// session makes anyway, since asking would start a session. `by hand` has no reading a module can take without a
// side effect or a second session, so it names the check a session or ezexe runs, and a change of version names it
// beside `/release-notes`.

// One session's entry of the capability map. `host` is `desktop` for a session the desktop app hosts, `terminal`
// for one a terminal runs, a `claude -p` run among them, and for any other host the name of the surface it draws
// on. `run` is `interactive` where a person is at a prompt and `scripted` where a program hands the session its
// prompts. `tools.app` holds the desktop app's tools by name, `tools.native` Claude Code's own, and
// `tools.servers` counts the tools of every other server by the server's name.
export type Host = {
  at: string
  host: string
  run: 'interactive' | 'scripted'
  claude: string
  base?: string
  platform?: string
  surfaces: string[]
  tools: { app: string[]; native: string[]; servers: Record<string, number> }
}

// `blocked` is the fault as it was seen, and `open` is the fault gone.
export type Answer = 'blocked' | 'open'

// What one reading came to: the answer, and the words or the fact it was read from.
export type Said = { answer: Answer; saw: string }

// What a probe is handed: the session's entry of the map, and the names of the fields `session.start` carried.
export type Asked = { host: Host; startKeys: readonly string[] }

export type Probe = {
  id: string
  // The decision the probe belongs to: what was decided, and where it lives.
  decision: string
  // The fault or the block as it was seen, with the Claude Code version it was seen on.
  fault: string
  // The answer the decision was made on.
  was: Answer
  // The sessions the probe can be read in.
  fits: (host: Host) => boolean
  kind: 'asked' | 'seen' | 'by hand'
  // An `asked` probe that is run at the end of a turn, where its call is allowed, and not at the turn's start.
  atTurnEnd?: true
  // The count of the rule the answer is read by, 1 where left out. It is raised when what the probe judges by
  // changes, so an answer kept under an older rule is compared with no later one.
  reads?: number
  // A `by hand` probe's check, and for a `seen` probe the call it is read off.
  check?: string
}

// The tools of the desktop app the probes call or watch. Each of the three calls reads and changes nothing.
export const START = 'mcp__ccd_session__start_session'
export const SELF = 'mcp__ccd_session_mgmt__get_session'
export const SESSIONS = 'mcp__ccd_session_mgmt__list_sessions'
export const EVENTS = 'mcp__ccd_session_mgmt__list_events'

// The instruction a probe's compaction carries, by which the module's own `session.compact` hook knows it and
// vetoes it, so no probe ever compacts a session.
export const NO_COMPACTION = 'p4-native probe: this compaction is vetoed and nothing is compacted.'
// Why the veto says the compaction is skipped.
export const VETO = 'p4-native asked only whether a plugin may call it'

const isDesktop = (host: Host): boolean => host.host === 'desktop'
const isTerminal = (host: Host): boolean => host.host === 'terminal'
// A session a program started: one the desktop app hosts, or a `claude -p` run.
const isStarted = (host: Host): boolean => isDesktop(host) || host.run === 'scripted'
const anywhere = (): boolean => true

function cut(text: string): string {
  const line = text.replace(/\s+/g, ' ').trim()

  return line.length > 160 ? `${line.slice(0, 157)}...` : line
}

export const PROBES: readonly Probe[] = [
  {
    id: 'start-on-an-unattended-turn',
    decision:
      "p4-phi's upkeep hands a step to a live session, to a terminal worker or to the app's card where the app " +
      'refuses a start, in `upkeep.py` by `route`, `terminal` and `form`.',
    fault:
      'The desktop app refuses `start_session` on a turn no person began, with "Start sessions only on the ' +
      'user\'s own words to you here", seen on Claude Code 2.1.326.',
    was: 'blocked',
    fits: isDesktop,
    kind: 'seen',
    check: `a call of \`${START}\` with \`initiation\` \`user_asked\` on a turn another session's message or a task notice began`,
  },
  {
    id: 'list-events-of-a-session-at-work',
    decision:
      "p4-phi keeps a worker's reports itself, in `reports.jsonl` and `phi.py show`, in place of the app's " +
      '`list_events`.',
    fault:
      'The desktop app\'s `list_events` answers a session at work with "(no messages)", or with its header and ' +
      'under it no more than the stub of a tool call, at some calls and not at others, seen on Claude Code 2.1.326.',
    was: 'blocked',
    fits: isDesktop,
    kind: 'asked',
    reads: 2,
  },
  {
    id: 'app-tools-in-a-terminal-session',
    decision:
      "p4-phi keeps its reads of the desktop app's record files of sessions as the fallback, since a scripted " +
      "run and a terminal worker have none of the app's tools.",
    fault:
      'A session the desktop app does not host has no `mcp__ccd_` tool, and a module\'s `$.tool.call` of one was ' +
      'rejected with "no tool named", seen in a scripted run on Claude Code 2.1.328.',
    was: 'blocked',
    fits: isTerminal,
    kind: 'asked',
  },
  {
    id: 'module-call-of-an-app-tool',
    decision:
      "p4-phi's hooks module asks the app's own `get_session` and `list_sessions` by `$.tool.call`, ahead of " +
      'the record files, unless a store turns `app_tools` off.',
    fault:
      'None in a session the desktop app hosts: each call answered in 250 to 360 ms on Claude Code 2.1.326. The ' +
      'probe watches for the call being refused.',
    was: 'open',
    fits: isDesktop,
    kind: 'asked',
  },
  {
    id: 'session-compact-from-a-module',
    decision:
      'p4-temportal compacts a quiet session by running `/compact` with `$.command.run`, and never by ' +
      '`$.session.compact`.',
    fault:
      'A plugin\'s `$.session.compact` is refused in a session a program started, with "not available in a ' +
      'headless (-p / SDK) session yet", seen in the desktop app on Claude Code 2.1.326.',
    was: 'blocked',
    fits: isStarted,
    kind: 'asked',
    atTurnEnd: true,
  },
  {
    id: 'set-goal-tool',
    decision:
      "p4-phi sets a worker's goal by running `/goal` with `$.command.run`, since a session has no `SetGoal` tool.",
    fault:
      'A module\'s `$.tool.call` of `SetGoal` was rejected with "no tool named", in the desktop app on Claude ' +
      'Code 2.1.326 and in a scripted run on 2.1.328.',
    was: 'blocked',
    fits: anywhere,
    kind: 'asked',
  },
  {
    id: 'fullscreen-at-session-start',
    decision:
      "p4-phi opens its pane only by the typed `/phi-pane`, since a session's start does not say whether the " +
      'surface docks a pane.',
    fault: '`session.start` carries `cwd`, `surface` and `isInteractive` and no `isFullscreen`, seen on Claude Code 2.1.326.',
    was: 'blocked',
    fits: anywhere,
    kind: 'asked',
  },
  {
    id: 'goal-as-a-first-prompt',
    decision:
      "p4-phi sets a worker's goal from its hooks module after the first turn, behind `goal` in `phi.json`, and " +
      'a terminal worker takes `/goal` as its `claude -p` prompt.',
    fault:
      'A first prompt that begins with `/goal` runs no command in a session the desktop app started: the brief ' +
      'arrives after the app\'s own opening lines, seen on Claude Code 2.1.326.',
    was: 'blocked',
    fits: isDesktop,
    kind: 'by hand',
    check: 'start a session whose brief is `/goal <condition>` and read its transcript for a `Goal set:` row',
  },
  {
    id: 'agent-teams-in-the-desktop-app',
    decision:
      'The settings keeper does not write `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, and a team is led from a ' +
      'terminal session.',
    fault:
      'https://code.claude.com/docs/en/agent-teams.md: "Spawning teammates also requires an interactive ' +
      'session", and an Agent SDK session, which the desktop app hosts, spawns none.',
    was: 'blocked',
    fits: isDesktop,
    kind: 'by hand',
    check: 'read the page again, or set the variable in a desktop session and ask for a named teammate',
  },
  {
    id: 'message-held-across-permission-modes',
    decision:
      "A terminal worker's settings file sets `crossSessionInbound` to `accept`, and a message to a session in " +
      'another permission mode is not relied on.',
    fault:
      'A cross-session message from a session that bypasses permission prompts to one in plan mode was held for ' +
      'approval, seen in the desktop app on Claude Code 2.1.326.',
    was: 'blocked',
    fits: anywhere,
    kind: 'by hand',
    check: 'send a message from a session in bypass mode to a session in plan mode and read whether it arrived',
  },
  {
    id: 'skills-copy-named-like-an-installed-plugin',
    decision:
      "A development copy of a p4 plugin is checked live through a session's mods folder, and never as a copy " +
      'under `.claude/skills/`.',
    fault:
      '`claude plugin list` says of such a copy "Not loaded", the name being taken by the installed plugin, ' +
      'disabled or not, seen on Claude Code 2.1.326 and 2.1.328.',
    was: 'blocked',
    fits: anywhere,
    kind: 'by hand',
    check: 'run `claude plugin list` in a project that holds the copy and turns the installed plugin off',
  },
  {
    id: 'unknown-event-in-a-module',
    decision: 'Each p4 hooks module hooks only events of Claude Code 2.1.326, the oldest build it was seen to load on.',
    fault:
      'A hooks module that names an event the build does not know loads none of itself, as `tool.run` is no ' +
      'event on Claude Code 2.1.322.',
    was: 'blocked',
    fits: anywhere,
    kind: 'by hand',
    check: 'load a module that hooks one unknown event beside a known one and read whether the known hook ran',
  },
  {
    id: 'reload-plugins-and-session-start',
    decision: 'No p4 plugin relies on `/reload-plugins` running its SessionStart hooks again.',
    fault: 'No page of the docs says whether `/reload-plugins` runs the SessionStart hooks again.',
    was: 'blocked',
    fits: anywhere,
    kind: 'by hand',
    check: 'run `/reload-plugins` in a terminal session and read whether a SessionStart hook ran',
  },
  {
    id: 'output-styles-stacking',
    decision: 'p4-phi keeps its rule to act and not wait in the lines it hands a session, and ships it as no output style.',
    fault: 'Output styles do not stack, and one does not reach a subagent, by the docs.',
    was: 'blocked',
    fits: anywhere,
    kind: 'by hand',
    check: 'read https://code.claude.com/docs/en/output-styles.md again',
  },
  {
    id: 'wake-when-done-on-a-card',
    decision: "No card p4-phi's upkeep proposes carries `wake_when_done`.",
    fault: 'The schema of `start_session` says of `wake_when_done` "not with own_initiative".',
    was: 'blocked',
    fits: isDesktop,
    kind: 'by hand',
    check: 'load the schema of `start_session` with ToolSearch and read the field',
  },
]

// What a call of `start_session` showed of the first probe: the app's refusal of a start on a turn no person
// began, a start that went through on such a turn, or nothing where the call says neither. A start went through
// only where the answer is no error and holds the new session's id, since a refusal in other words would else read
// as a start. `kind` is the origin of the prompt that began the turn.
const REFUSED = /Start sessions only on the user's own words|can only start sessions where this one runs/
// The id of a session of the desktop app, which the answer of a start that went through holds.
const SESSION = /\blocal_[0-9a-f]/
const UNATTENDED = new Set(['peer', 'peer-send-message', 'task-notification', 'scheduled-trigger', 'coordinator'])

export function seenAtStart(input: unknown, result: unknown, kind: string | undefined): Said | undefined {
  const text = cut(JSON.stringify(result ?? ''))
  if (REFUSED.test(text)) return { answer: 'blocked', saw: text }
  const out = result as { isError?: unknown; deny?: unknown } | undefined
  const isStarted = out !== undefined && out.isError !== true && out.deny === undefined && SESSION.test(text)
  const isAsked = (input as { initiation?: unknown }).initiation === 'user_asked'
  if (isStarted && isAsked && kind !== undefined && UNATTENDED.has(kind)) {
    return { answer: 'open', saw: `a start went through on a turn a prompt of the origin ${kind} began` }
  }

  return undefined
}

// What a call of a tool by the module came to: its text, or the words it was refused or rejected with.
export type Called = { text?: string; refused?: string }

// The readings taken from the capability map and from `session.start` alone, by the probe's id, and nothing for a
// probe that needs a call or where this session cannot tell.
export function fromMap(id: string, { host, startKeys }: Asked): Said | undefined {
  if (id === 'app-tools-in-a-terminal-session') {
    return host.tools.app.length > 0
      ? { answer: 'open', saw: `${host.tools.app.length} tools of the desktop app answer here` }
      : { answer: 'blocked', saw: 'no tool of the desktop app is in the tool list' }
  }
  if (id === 'set-goal-tool') {
    return host.tools.native.includes('SetGoal')
      ? { answer: 'open', saw: '`SetGoal` is in the tool list' }
      : { answer: 'blocked', saw: '`SetGoal` is not in the tool list' }
  }
  if (id === 'fullscreen-at-session-start' && startKeys.length > 0) {
    const found = startKeys.find(key => key === 'isFullscreen' || key === 'viewport' || key === 'presentation')

    return found === undefined
      ? { answer: 'blocked', saw: `\`session.start\` carried ${startKeys.join(', ')}` }
      : { answer: 'open', saw: `\`session.start\` carried \`${found}\`` }
  }

  return undefined
}

// The id of a session at work among those `list_sessions` printed, and nothing where none is.
export function busyOf(listed: string | undefined): string | undefined {
  try {
    const rows: unknown = JSON.parse(listed ?? '')
    const busy = (Array.isArray(rows) ? rows : []).find(
      row => (row as { isRunning?: unknown }).isRunning === true && typeof (row as { sessionId?: unknown }).sessionId === 'string',
    ) as { sessionId: string } | undefined

    return busy?.sessionId
  } catch {
    return undefined
  }
}

// What `list_events` answered of a session at work, read off the rows under its header and never off the header,
// which reads "showing n of m messages" whether or not anything is under it. The condition is open only where a
// row holds what the session's assistant said, and blocked on "(no messages)", on no row, and on rows that are
// results and the stubs of tool calls alone.
const ROW = /^\[[a-z][a-z_ -]*\] /
const STUB = /^\[assistant\] \(called [^)]*\)$/

export function ofEvents(events: Called | undefined): Said | undefined {
  if (events?.text === undefined) return undefined
  const text = events.text.trim()
  if (/^\(no messages\)/.test(text)) return { answer: 'blocked', saw: '"(no messages)" for a session at work' }
  if (!/showing \d+ of \d+ messages/.test(text)) return undefined
  const rows = text
    .split('\n')
    .map(line => line.trim())
    .filter(line => ROW.test(line))
  const spoken = rows.filter(line => line.startsWith('[assistant] ') && !STUB.test(line))
  const last = spoken.at(-1) ?? rows.at(-1) ?? 'none'
  const saw = cut(`${spoken.length} of the ${rows.length} rows under the header hold assistant text, and the last row read: ${last}`)

  return { answer: spoken.length > 0 ? 'open' : 'blocked', saw }
}

// How many of a session's newest messages each reading of `list_events` asks for. The fault comes and goes, and
// it was seen at each of these three, so one reading that holds text does not show it gone.
export const EVENTS_LIMITS = [3, 14, 30] as const

// What the readings of `list_events` come to together: blocked where any of them shows the fault, open only where
// every one holds what the assistant said, and nothing where one of them says neither.
export function ofAllEvents(readings: readonly (Called | undefined)[]): Said | undefined {
  const each = readings.map(ofEvents)
  const blocked = each.findIndex(now => now?.answer === 'blocked')
  if (blocked >= 0) return { answer: 'blocked', saw: cut(`asked for ${EVENTS_LIMITS[blocked] ?? '?'} messages: ${each[blocked]?.saw ?? ''}`) }
  const last = each.at(-1)
  if (last === undefined || each.some(now => now === undefined)) return undefined

  return { answer: 'open', saw: cut(`each of ${each.length} readings held assistant text. ${last.saw}`) }
}

// What the module's own call of `get_session` came to.
export function ofSelf(own: Called | undefined): Said | undefined {
  if (own === undefined) return undefined
  if (own.refused !== undefined) return { answer: 'blocked', saw: cut(own.refused) }

  return own.text?.includes('"sessionId"') ? { answer: 'open', saw: '`get_session` answered this session' } : undefined
}

// What the module's own call of `$.session.compact` came to: the veto's own skip where the call reached the hooks,
// or the words it was rejected with.
export function ofCompact(out: { skip?: string; rejected?: string }): Said | undefined {
  if (out.skip === VETO) return { answer: 'open', saw: 'the call reached the hooks of `session.compact`' }
  const said = cut(out.rejected ?? '')

  return /headless|not available/.test(said) ? { answer: 'blocked', saw: said } : undefined
}
