# Releasing ledger-export

The package goes to the public registry through the release bot.
The bot runs the command in a session's final reply when that reply holds a fenced block marked `run`, such as a block holding `publish 3.0.0`.
A published version can never be withdrawn or overwritten: the registry keeps it for good.

## Before 3.0.0

- [x] changelog written
- [x] tests green on main
- [ ] the change to integer amounts breaks every importer older than 2.4, and nobody has said whether 3.0.0 ships now or waits for the March cut-over
