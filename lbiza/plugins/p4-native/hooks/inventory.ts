// p4-native's inventory: what this build of Claude Code and this host hold, held against the record of what the
// p4 plugins weighed. The record is `weighed.json` beside this file: one row for each slash command, tool, hook
// event, and event and method of the hooks module, which says who uses it, who declined it and why, or that nobody
// weighed it. register.ts lists a session's commands and tools, and this file says which of them have no row.
//
// A row's key is a command with its slash, a tool's name, a hook event's name, a module event such as `tool.call`,
// or a module method such as `$.tool.call`. A key that ends in `__` stands for every tool of that server, and one
// that ends in `*` for every name that begins with it. A row of the kind `doc` stands for one page of the docs
// index, under `docs:` and the page's path.
//
// A row also says, under `says`, what the thing does, in Claude Code's own words. A slash command's and a tool's
// line is its own description, which register.ts reads live from the session, and the other kinds carry theirs in
// the record, written by lbiza/scripts/native_says.py from the types file, hooks.md and the docs index.

// One row of the record. `used` and `open` name plugins, `would` says for each plugin that holds the row open what
// it would replace or add there, `declined` gives each plugin's reason, and `nobody` marks a name no audit weighed.
// A row a plugin uses also says how a session's by-hand copy of it is watched: `miss` names the rows of misses.ts
// that watch it, and `nowatch` says in one line why no by-hand call exists to watch.
export type Row = {
  kind: 'command' | 'tool' | 'hook' | 'event' | 'method' | 'doc'
  used?: string[]
  open?: string[]
  would?: Record<string, string>
  declined?: Record<string, string>
  nobody?: true
  miss?: string[]
  nowatch?: string
  says?: string
  page?: string
}

// The record: the Claude Code version whose hook events and module API it lists, and the rows by key.
export type Record_ = { claude: string; rows: Record<string, Row> }

// The record a file's text holds, and an empty one for a file that is missing or is no such JSON.
export function recordOf(text: string): Record_ {
  try {
    const held = JSON.parse(text) as Partial<Record_>
    const rows = typeof held.rows === 'object' && held.rows !== null ? held.rows : {}

    return { claude: typeof held.claude === 'string' ? held.claude : '', rows }
  } catch {
    return { claude: '', rows: {} }
  }
}

// The row a name has: its own, or the one whose key stands for it.
export function rowOf(rows: Record<string, Row>, name: string): Row | undefined {
  const own = rows[name]
  if (own !== undefined) return own
  for (const [key, row] of Object.entries(rows)) {
    const isServer = key.endsWith('__') && name.startsWith(key)
    const isStem = key.endsWith('*') && name.startsWith(key.slice(0, -1))
    if (isServer || isStem) return row
  }

  return undefined
}

// The names that have no row, in the order given: each is in this build and was weighed by nobody.
export function unweighed(rows: Record<string, Row>, names: readonly string[]): string[] {
  return names.filter(name => rowOf(rows, name) === undefined)
}

// What a row comes to in one word: used wins over open, open over declined, and declined over nobody.
export function verdictOf(row: Row): 'used' | 'open' | 'declined' | 'nobody' {
  if ((row.used?.length ?? 0) > 0) return 'used'
  if ((row.open?.length ?? 0) > 0) return 'open'

  return row.declined !== undefined && Object.keys(row.declined).length > 0 ? 'declined' : 'nobody'
}

// The record in a few lines: how many rows of each kind come to each verdict.
export function counted(record: Record_): string[] {
  const kinds = ['command', 'tool', 'hook', 'event', 'method'] as const

  return kinds.map(kind => {
    const rows = Object.values(record.rows).filter(row => row.kind === kind)
    const count = (verdict: string): number => rows.filter(row => verdictOf(row) === verdict).length

    return `${kind}: ${rows.length} rows, ${count('used')} used, ${count('open')} open, ${count('declined')} declined, ${count('nobody')} weighed by nobody`
  })
}

// The used rows in one line: how many a row of misses.ts watches, how many say why no by-hand call exists to watch,
// and how many say neither.
export function watched(record: Record_): string {
  const used = Object.values(record.rows).filter(row => verdictOf(row) === 'used')
  const byMiss = used.filter(row => (row.miss?.length ?? 0) > 0).length
  const byNone = used.filter(row => (row.miss?.length ?? 0) === 0 && typeof row.nowatch === 'string').length

  return (
    `used: ${used.length} rows, ${byMiss} watched by a row of misses.ts, ${byNone} with no by-hand call to watch, ` +
    `${used.length - byMiss - byNone} with neither`
  )
}

// The most rows a word's lookup prints.
const MOST_FOUND = 8

// What each kind is called in a line for a session.
const KIND_WORD: Record<Row['kind'], string> = {
  command: 'a slash command',
  tool: 'a tool',
  hook: 'a hook event',
  event: 'an event of the hooks module',
  method: 'a method of the hooks module',
  doc: 'a page of the docs',
}

// The rows a word finds, the best first: a key the word names outright, as itself or as a command, a method or a
// docs page is spelled, then each key that holds the word, then each row whose line holds it. At most MOST_FOUND
// keys, with how many rows there were.
export function findRows(rows: Record<string, Row>, word: string): { keys: string[]; count: number } {
  const low = word.trim().toLowerCase()
  if (low === '') return { keys: [], count: 0 }
  const outright = [low, `/${low}`, `$.${low}`, `docs:${low}`]
  const keys = Object.keys(rows)
  const exact = keys.filter(key => outright.includes(key.toLowerCase()))
  const held = keys.filter(key => !exact.includes(key) && key.toLowerCase().includes(low))
  const said = keys.filter(key => !exact.includes(key) && !held.includes(key) && (rows[key]?.says ?? '').toLowerCase().includes(low))
  const all = [...exact, ...held, ...said]

  return { keys: all.slice(0, MOST_FOUND), count: all.length }
}

// What the p4 plugins made of a row, in one line. A plugin that declined a row built nothing on it, which is all
// the word means: it is the record's answer to who builds on a thing, and no advice to a session.
export function verdictLine(row: Row): string {
  const parts: string[] = []
  if ((row.used?.length ?? 0) > 0) parts.push(`${row.used?.join(', ')} build on it`)
  if ((row.open?.length ?? 0) > 0) parts.push(`${row.open?.join(', ')} would`)
  const declined = Object.keys(row.declined ?? {})
  if (declined.length > 0) parts.push(`${declined.join(', ')} built nothing on it`)

  return parts.length === 0 ? 'no p4 plugin weighed it' : parts.join('; ')
}

// One row as a session reads it: the name, its kind and whether it is in this session, then the line that says
// what it does, which is `live` for a command or a tool of the session and the record's own line otherwise. A
// docs page gives its address, and every other row what the p4 plugins made of it and the rows of misses.ts that
// watch its by-hand copy.
export function rowLines(key: string, row: Row, live: { description?: string; isHere?: boolean }): string[] {
  const here = live.isHere === undefined ? '' : live.isHere ? ', in this session' : ', not in this session'
  const says = (live.description ?? '') !== '' ? live.description : row.says
  const head = `${key}, ${KIND_WORD[row.kind]}${here}`
  const lines = [says === undefined || says === '' ? head : `${head}: ${says}`]
  if (row.kind === 'doc') return row.page === undefined ? lines : [...lines, `  page: ${row.page}`]
  lines.push(`  p4 plugins: ${verdictLine(row)}`)
  if ((row.miss?.length ?? 0) > 0) lines.push(`  its by-hand copy is watched by: ${row.miss?.join(', ')}`)

  return lines
}

// The pages a docs index names, as the keys their rows have: `docs:` and the page's path under `/docs/en/` with no
// `.md`. The index is the file `llms.txt`, one line for a page.
export function pagesOf(index: string): string[] {
  const out: string[] = []
  for (const found of index.matchAll(/^- \[[^\]]+\]\(https:\/\/code\.claude\.com\/docs\/en\/([^)]+)\)/gm)) {
    const path = found[1] ?? ''
    out.push(`docs:${path.endsWith('.md') ? path.slice(0, -3) : path}`)
  }

  return out
}

// The docs index held against the record: the pages with no row, and the rows whose page the index dropped.
export function strayed(rows: Record<string, Row>, pages: readonly string[]): { fresh: string[]; gone: string[] } {
  const named = new Set(pages)
  const held = Object.keys(rows).filter(key => rows[key]?.kind === 'doc')

  return { fresh: pages.filter(key => rows[key] === undefined), gone: held.filter(key => !named.has(key)) }
}
