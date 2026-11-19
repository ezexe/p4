// p4-native's inventory: what this build of Claude Code and this host hold, held against the record of what the
// p4 plugins weighed. The record is `weighed.json` beside this file: one row for each slash command, tool, hook
// event, and event and method of the hooks module, which says who uses it, who declined it and why, or that nobody
// weighed it. register.ts lists a session's commands and tools, and this file says which of them have no row.
//
// A row's key is a command with its slash, a tool's name, a hook event's name, a module event such as `tool.call`,
// or a module method such as `$.tool.call`. A key that ends in `__` stands for every tool of that server, and one
// that ends in `*` for every name that begins with it.

// One row of the record. `used` and `open` name plugins, `declined` gives each plugin's reason, and `nobody` marks
// a name no audit weighed.
export type Row = {
  kind: 'command' | 'tool' | 'hook' | 'event' | 'method'
  used?: string[]
  open?: string[]
  declined?: Record<string, string>
  nobody?: true
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
