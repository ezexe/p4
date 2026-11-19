// p4-temportal's contract: the values its hooks module keeps in `$.state`, which `claude plugin validate` holds
// every `$.state` key of the module to. plugin.json names this file as `types`.

// When the main conversation's last turn ended, in milliseconds as `$.clock.now` gives them, and 0 while a turn
// runs, none has ended, or the quiet minute after it has been looked at.
export type TurnEnded = number

declare module 'claude-code' {
  interface PluginState {
    'p4-temportal': { turnEnded: TurnEnded }
  }
}
