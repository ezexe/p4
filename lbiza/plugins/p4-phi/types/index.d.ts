// p4-phi's contract: the values its hooks module keeps in `$.state`, which `claude plugin validate` holds every
// `$.state` key of the module to. plugin.json names this file as `types`.

// One page of a session's folder in the store as the pane shows it: a puppeteer's board, the ledger of ezexe's
// requests, an orchestrator's ledger of its sessions or the `-p` workers a session started. `text` is the page's markdown as python wrote it, cut where
// it is long, and `path` is the file that holds it whole.
export type PhiPage = { name: 'workers' | 'board' | 'asks' | 'ledger'; title: string; path: string; text: string }

// One session of the tree as scripts/progress.py writes it into progress.json: its goal as `asked`, `set`, `met`,
// `failed` or `cleared`, its steps, and the plan it works with that plan's sections and its loop.
export type PhiGoal = { state: string; condition: string; reason?: string }
export type PhiStep = { addr: string; content: string; status: string; agents: number }
export type PhiLoop = { round: number; of: number; held: number; last: string; state: string; ended: boolean }
export type PhiPlan = {
  path: string
  title: string
  sections: { head: string; lands: boolean; done: boolean }[]
  loop: PhiLoop | null
}
export type PhiNode = {
  sessionId: string
  depth: number
  title: string
  working: boolean
  done: boolean
  goal: PhiGoal | null
  current: string
  steps: PhiStep[]
  plan: PhiPlan | null
  // The teammates of the team the session leads, and whether the session
  // stands apart from the tree, as a team's lead that no session of the tree started does.
  team?: { name: string; task: string; state: string; doing: string }[]
  apart?: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'p4-phi': { pages: Shaped<PhiPage[]>; tree: Shaped<PhiNode[]> }
  }
}
