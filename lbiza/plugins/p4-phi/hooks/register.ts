// p4-phi's hooks module: the part of the plugin that runs inside Claude Code, where a command hook can only print.
// It finds the python that find-python.sh proved for the plugin's runners, and keeps it while the module is loaded.

import type { EngineInterface, Register } from 'claude-code'

// What find-python.sh runs to prove an interpreter: the interpreter prints its own path.
const PROOF = "import sys; print(sys.executable.replace(chr(92), '/'))"

// The python that runs the plugin's scripts. A reload of the module starts it over.
let python: string | undefined
let isFinding = false

function slashed(path: string): string {
  return path.replaceAll('\\', '/').replace(/\/+$/, '')
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

async function findPython($: EngineInterface): Promise<string | undefined> {
  if (python !== undefined || isFinding) return python
  isFinding = true
  try {
    python = (await keptPython($)) ?? (await provenPython($))
  } catch {
    python = undefined
  } finally {
    isFinding = false
  }
  return python
}

export const register: Register = on => {
  on('session.start', ($, e, next) => {
    void findPython($)

    return next(e)
  })
}
