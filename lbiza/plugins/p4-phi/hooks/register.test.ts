// p4-phi's hooks module under `claude plugin test`: each hook here stands for the engine, beneath the plugin.

import { expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const DATA = '/home/u/.claude/plugins/data/p4-phi-inline'
const KEPT = '/opt/python/bin/python3'

// The files of a machine, by path, and the commands on its PATH that prove themselves as a python.
type Machine = { files: Record<string, string>; pythons: Record<string, string> }

// What the module reads and runs, in order.
type Seen = { read: string[]; ran: string[][] }

// A path as the test wrote it: the engine hands a hook the path resolved on the machine the test runs on.
function plain(path: string): string {
  return path.replaceAll('\\', '/').replace(/^[A-Za-z]:/, '')
}

function machine(on: On, has: Machine): Seen {
  const seen: Seen = { read: [], ran: [] }
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('fs.list', (_, e) => {
    const folder = plain(e.path)
    const below = Object.keys(has.files).filter(path => path.startsWith(`${folder}/`))
    const names = [...new Set(below.map(path => path.slice(folder.length + 1).split('/')[0] ?? ''))]

    return {
      value: names.map(name => ({
        name,
        kind: has.files[`${folder}/${name}`] === undefined ? ('dir' as const) : ('file' as const),
        size: 0,
        mtimeMs: 0,
        isLink: false,
      })),
    }
  })
  on('fs.read', (_, e) => {
    seen.read.push(plain(e.path))
    const text = has.files[plain(e.path)]

    return text === undefined ? { deny: 'ENOENT' } : { value: text }
  })
  on('fs.exists', (_, e) => ({ value: has.files[plain(e.path)] !== undefined }))
  on('process.run', (_, e) => {
    seen.ran.push([...e.argv])
    const path = has.pythons[e.argv[0] ?? '']
    if (path === undefined) return { deny: 'ENOENT' }

    return {
      value: { exitCode: 0, stdout: `${path}\n`, stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
    }
  })

  return seen
}

test('the python a runner kept in the data folder is found, and none is searched for', async ($, on) => {
  mock.env(on, { CLAUDE_PLUGIN_DATA: DATA })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '' }, pythons: {} })

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await clock.settle()

  expect(seen.read).toEqual([`${DATA}/.python`])
  expect(seen.ran).toEqual([])
})

test('the data folder is found under the plugins root by the plugin name', async ($, on) => {
  mock.env(on, { HOME: '/home/u' })
  const clock = mock.clock(on)
  const seen = machine(on, { files: { [`${DATA}/.python`]: `${KEPT}\n`, [KEPT]: '' }, pythons: {} })

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await clock.settle()

  expect(seen.read).toEqual([`${DATA}/.python`])
  expect(seen.ran).toEqual([])
})

test('with none kept, the search of find-python.sh proves the first python that runs', async ($, on) => {
  mock.env(on, {})
  const clock = mock.clock(on)
  const seen = machine(on, { files: {}, pythons: { python: KEPT } })

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await clock.settle()

  const names = seen.ran.map(argv => argv[0])
  expect(names.at(-1)).toBe('python')
  expect(names.slice(0, -1).every(name => name === 'py' || name === 'python3')).toBe(true)
  expect(seen.ran.at(-1)?.slice(-3, -1)).toEqual(['-I', '-c'])
})
