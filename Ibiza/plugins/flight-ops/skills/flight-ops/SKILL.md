---
name: flight-ops
description: Flight operations for the p4 plugins' own operators, as they run — the VLDS operator, roboto as its conductor, the operator's pick-readers, the inspector's perspectives, and an orchestration branch run as an agent. Each is a flight with its own takeoff checklist (the brief its contract prescribes, the agent type, foreground or background, the clock), its own landing (the return shape its brief promises), its own go-around and lost-communications rule, and a flight recorder line in the session's flights.tsv; a miss goes to the vlds ledger as a correction and amends the checklist. Use before launching or continuing any of these operators, when one returns, when one goes silent, and before amending a checklist after a miss. Launches that are not a p4 operator's are not flights here.
---

# flight-ops — the p4 operators fly under their own checklists

The p4 plugins launch agents at fixed moments, each under a contract that already says what the launch must carry and what must come back.
flight-ops holds every one of those contracts to one discipline: a **takeoff** checklist before the launch, a **landing** checklist at the return, a **go-around** when the landing fails, a **lost-communications** rule when the return never comes, and an **incident** loop that turns every miss into an amended check.
The launching context is the **tower**; the operator is the **pilot**; a pilot never clears or lands itself.

This is not a plan system: nothing is filed, and a launch that is not a p4 operator's is not a flight.
The checklists below are the operators' own rules, gathered — the vlds contract, the operator and pool briefs, roboto's `derivation` skill, the inspector — so a change to an operator changes its checklist here in the same change.

## The flights

| Flight | Tower | Pilot | Recognized by | Flies | Returns |
|---|---|---|---|---|---|
| `vlds-operator` | the session; or roboto, conducting | `general-purpose` on the moment's model | the brief says to read the vlds plugin's `hooks/operator-prompt.md` | foreground; in the background on the pool's children road | `derivation — <moment>, …` |
| `roboto-conductor` | the session, when the recall config's `operator-via:` names roboto | `mister:roboto` | the operator brief plus `conductor: launch the operator …` | foreground | `derived understanding — <moment>, …` |
| `vlds-pick-reader` | the VLDS operator | `vlds:pick-reader` (general-purpose where absent) on the child model | the brief says to read `hooks/pool-child-prompt.md` | background, all in one message | `picks — <file>, …` |
| `vlds-inspector-perspective` | the inspector | a read-only type where one fits the angle | the line `flight: vlds-inspector-perspective` | foreground | a for / against reading with its sources |
| `orchestration-branch` | roboto's orchestration | the agent a branch runs as | the line `flight: orchestration-branch` | foreground | the branch's compiled takes, never an action |

Spawn depth is part of the airspace: the session is depth 0, roboto 1, the operator under roboto 2, its pick-readers 3 — and at depth 3 the harness gives no Agent tool, so nothing below a pick-reader can fly, and an operator under a conductor that finds no Agent tool takes the skeleton road.

Each flight's full checklist is in `references/flights.md`.

## Takeoff (the tower, before the launch)

1. **The brief is the contract's, whole.** The operator line carries `store:`, `session:`, `now:` and `moment:`, then the facts only the tower holds; a conducted launch adds its `conductor:` line last; a pick-reader's carries `store`, `session`, `now`, `task`, `file` and that file's barrier lines.
2. **The clock is copied, never guessed.** `now:` is the latest `now:` in the hook stream; the template's `<the latest now:>` is a defect, not a value.
3. **The pilot is the contract's type and model.** The operator is `general-purpose`; the conductor `mister:roboto`; a pick-reader `vlds:pick-reader`. The model is the recall config's for the moment (`operator-model:`, `pool-model:`, `pool-child-model:`, `sweep-model:`).
4. **Foreground or background as the road says.** Pick-readers fly in the background, launched in one message; the operator flies in the background only on the children road.
5. **Launch once, continue, then relaunch.** The session launches its operator once and continues it by `SendMessage` for at most `operator-moments:` moments, then launches fresh; a conductor launches the operator fresh for every moment and never continues it.

The plugin's PreToolUse hook (`hooks/flight_ops.py takeoff`) checks items 1 to 4 for each recognized flight and bounces a launch that fails them **once** — the same call re-issued passes, since the check can be wrong and a bounced operator must never stall a session.

## In flight

- **Following.** A background flight's progress arrives as its messages; the tower acts on nothing a pilot streams except its landing.
- **Sterile cockpit.** While the operator is airborne the tower opens no store file; it asks the operator for an entry, never the file.
- **Lost communications.** A continuation that fails — the operator gone after a compact or a restart — is never assumed landed: the tower launches fresh and says so. A conductor's operator that returns while its children still run has left them with no one to report to: that return is not a landing.

## Landing (the tower, at the return)

The return must open with the shape its brief promises (the table above); for the operator the derivation quotes its scripts' verdicts (`phi.py`/`idb.py check: 0 corruption`), and its writes stay inside its airspace — this session's store, the pool's picks file, the cumulative index.
The plugin's PostToolUse hook (`hooks/flight_ops.py landing`) checks the opening of every foreground return of the operator and of the conductor, and records each flight; a background flight is recorded airborne, its landing being the completion that reaches its tower.

## Go-around

- **vlds-operator under roboto:** a return that is not a derivation — a progress note, a derived understanding of its own — is relaunched once, fresh, with a `conductor fact:` line naming what the first launch reported and left behind; both launches are reported in `operator:`.
- **vlds-operator from the session:** a failed continuation is relaunched fresh, said in the reply.
- **roboto-conductor:** no derived understanding came back — read its hand-back for the operator's failure and relaunch the hand-off once, saying so.
- **vlds-pick-reader:** a child that never lands leaves its file to the operator's own pass, under the pass heads, and the pool's `read:` line names it.
- **inspector perspective:** a perspective that changed anything is void.
- **orchestration branch:** a branch that acted instead of returning material is void, and its act goes to `activation`.

## The recorder

Every recognized flight is one line in `.claude/p4/sessions/<name>/flights.tsv` — time, flight, phase (`takeoff`, `bounced`, `airborne`, `landed`, `go-around`), pilot, a fingerprint of the launch, a note — written by the hooks, tracked by the p4 repo beside the session's `vlds/` and `src/`, never a ruling.

## The incident loop

A go-around, a bounce that was right, a lost flight, or a miss found after a landing is an incident.
It is handed to the VLDS operator (close) as a `correction` for `store/ledger.md` — `match` what was assumed, `meant` what was so, and the fix — in the turn it is caught; and the checklist that should have caught it is amended here and in `hooks/flight_ops.py`, with a test in `hooks/test_flight_ops.py` that reproduces the miss.
An incident with no amended check is not closed.
