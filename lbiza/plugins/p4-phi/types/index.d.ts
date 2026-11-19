// p4-phi's contract: the values its hooks module keeps in `$.state`, which `claude plugin validate` holds every
// `$.state` key of the module to. plugin.json names this file as `types`.

// One page of a session's folder in the store as the pane shows it: a puppeteer's board, the ledger of ezexe's
// requests or an orchestrator's ledger of its sessions. `text` is the page's markdown as python wrote it, cut where
// it is long, and `path` is the file that holds it whole.
export type PhiPage = { name: 'board' | 'asks' | 'ledger'; title: string; path: string; text: string }

declare module 'claude-code' {
  interface PluginState {
    'p4-phi': { pages: Shaped<PhiPage[]> }
  }
}
