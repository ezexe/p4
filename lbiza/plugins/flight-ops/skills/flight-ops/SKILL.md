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
| `vlds-operator` | the session; or roboto, conducting | `general-purpose` on the moment's model (an integrator: sonnet) | the brief says to read the vlds plugin's `hooks/operator-prompt.md` | foreground; in the background on the pool's children road | `derivation — <moment>, …` |
| `roboto-conductor` | the session, when the recall config's `operator-via:` names roboto | `mister:roboto` on sonnet (an integrator) | the operator brief plus `conductor: launch the operator …` | foreground | `derived understanding — <moment>, …` |
| `vlds-pick-reader` | the VLDS operator | `vlds:pick-reader` (general-purpose where absent) on the child model (an evidence finder: haiku) | the brief says to read `hooks/pool-child-prompt.md` | background, all in one message | `picks — <file>, …` |
| `vlds-inspector-perspective` | the inspector | a read-only type where one fits the angle, on sonnet (a cross-check) | the line `flight: vlds-inspector-perspective` | foreground | a for / against reading with its sources |
| `orchestration-branch` | roboto's orchestration | the agent a branch runs as, on its work's role | the line `flight: orchestration-branch` | foreground | the branch's compiled takes, never an action |

Spawn depth is part of the airspace: the session is depth 0, roboto 1, the operator under roboto 2, its pick-readers 3 — and at depth 3 the harness gives no Agent tool, so nothing below a pick-reader can fly, and an operator under a conductor that finds no Agent tool takes the skeleton road.

Each flight's full checklist is in `references/flights.md`.

## Models by role

Every flight flies on its role's model, decided from the claude-api skill's model reference (its model table cached 2026-10-06) on the owner's words of 2026-10-27 04:37 ("bump the plan docs writers to the most capable plan and code snippet writters model and the rest of the plan-docs tasks to sonnet or haiku whichever is able to follow the instructions laid out in the plans best without diverting to there own judgments calls") and of 05:01 ("update the agentic loop aka vlds operator,roboto,flight orchastration ... and the rest .. to also now flow through" it):

| Role | Model | The work | Why, from the reference |
|---|---|---|---|
| Writer | `fable` (Claude Fable 5.1) | writes a plan, a plan's code snippets, a decision that lays out its edits, or a consequential answer as the full reasoning treatment | "Anthropic's most capable widely released model, for the most demanding reasoning and long-horizon agentic work"; the guide notes it can widen a task's scope, so its brief carries the scope line: the brief sets the scope, and the scope is the deliverable — don't quietly narrow, widen, or swap it |
| Integrator | `sonnet` (Claude Sonnet 5.5) | follows a contract or a plan as written: the VLDS operator, the pool's compose, the sweep's scoring, roboto conducting, a landing pilot | "strongest on multistep agentic coding in a real repository", and its line "interprets prompts literally and explicitly" |
| Cross-check | `sonnet` (Claude Sonnet 5.5) | re-reads another flight's output from its sources: an inspector perspective, a landing's one cross-check | the same literal reading, held to the sources it re-grounds in |
| Evidence finder | `haiku` (Claude Haiku 5.5) | reads files for picks, lines, snippets, inventories, with no decision to make: a pick-reader | for "classification, routing, extraction, and sub-agent tasks"; the guide moves reading-heavy sub-tasks to it |

The recall config's `operator-model:`, `pool-model:`, `pool-child-model:` and `sweep-model:` are a store's own ruling and stand where they name another model; absent, each takes its role's model above, which is what the vlds plugin's defaults already are. Roboto's agent definition keeps `fable` for a consequential answer it writes; a session that launches it to conduct passes `model: sonnet`.

## Takeoff (the tower, before the launch)

1. **The brief is the contract's, whole.** The operator line carries `store:`, `session:`, `now:` and `moment:`, then the facts only the tower holds; a conducted launch adds its `conductor:` line last; a pick-reader's carries `store`, `session`, `now`, `task`, `file` and that file's barrier lines.
2. **The clock is copied, never guessed.** `now:` is the latest `now:` in the hook stream; the template's `<the latest now:>` is a defect, not a value.
3. **The pilot is the contract's type, on its role's model.** The operator is `general-purpose`; the conductor `mister:roboto`; a pick-reader `vlds:pick-reader`. The model is the recall config's for the moment where it names one (`operator-model:`, `pool-model:`, `pool-child-model:`, `sweep-model:`), else the role's in **Models by role**: the operator, the pool and the sweep integrate (sonnet), a pick-reader finds evidence (haiku), the conductor integrates (sonnet), an inspector perspective cross-checks (sonnet), and an orchestration branch takes the role of the work it is given.
4. **Foreground or background as the road says.** Pick-readers fly in the background, launched in one message; the operator flies in the background only on the children road.
5. **Launch once, continue, then relaunch.** The session launches its operator once and continues it by `SendMessage` for at most `operator-moments:` moments, then launches fresh; a conductor launches the operator fresh for every moment and never continues it.

The plugin's PreToolUse hook (`hooks/flight_ops.py takeoff`) checks items 1 to 4 for each recognized flight and bounces a launch that fails them **once** — the same call re-issued passes, since the check can be wrong and a bounced operator must never stall a session.

## In flight

- **Following.** A background flight's progress arrives as its messages; the tower acts on nothing a pilot streams except its landing.
- **Sterile cockpit.** While the operator is airborne the tower opens no store file; it asks the operator for an entry, never the file.
- **Lost communications.** A continuation that fails — the operator gone after a compact or a restart — is never assumed landed: the tower launches fresh and says so. A conductor's operator that returns while its children still run has left them with no one to report to: that return is not a landing.

## Landing (the tower, at the return)

The return must open with the shape its brief promises (the table above); for the operator the derivation quotes its scripts' verdicts (`phi.py`/`idb.py check: 0 corruption`), and its writes stay inside its airspace — this session's store, the pool's picks file, the cumulative index.
The plugin's PostToolUse hook (`hooks/flight_ops.py landing`) checks the opening of every foreground return of the operator and of the conductor, and records each flight.
The harness may run any Agent call asynchronously and answer it with `{isAsync, status: async_launched, agentId}`: that acknowledgment is no return, so the flight is recorded airborne under its agent id, and it lands when its hand-back reaches the tower as an `<agent-message from=…>` prompt — the UserPromptSubmit hook (`hooks/flight_ops.py handback`) matches it by agent id and checks the report's opening there. A flight a subagent launched hands back to that subagent, where no prompt hook runs; it stays airborne in the record, and its tower lands it by hand.

## Go-around

- **vlds-operator under roboto:** a return that is not a derivation — a progress note, a derived understanding of its own — is relaunched once, fresh, with a `conductor fact:` line naming what the first launch reported and left behind; both launches are reported in `operator:`.
- **vlds-operator from the session:** a failed continuation is relaunched fresh, said in the reply.
- **roboto-conductor:** no derived understanding came back — read its hand-back for the operator's failure and relaunch the hand-off once, saying so.
- **vlds-pick-reader:** a child that never lands leaves its file to the operator's own pass, under the pass heads, and the pool's `read:` line names it.
- **inspector perspective:** a perspective that changed anything is void.
- **orchestration branch:** a branch that acted instead of returning material is void, and its act goes to `activation`.

## The recorder

Every recognized flight is one line per phase in `.claude/p4/sessions/<name>/flights.tsv` — time, flight, phase (`takeoff`, `bounced`, `airborne`, `landed`, `go-around`), pilot, a fingerprint of the launch, a note (an asynchronous flight's `agent <id>`) — written by the hooks, tracked by the p4 repo beside the session's `vlds/` and `src/`, never a ruling.

## The incident loop

A go-around, a bounce that was right, a lost flight, or a miss found after a landing is an incident.
It is handed to the VLDS operator (close) as a `correction` for `store/ledger.md` — `match` what was assumed, `meant` what was so, and the fix — in the turn it is caught; and the checklist that should have caught it is amended here and in `hooks/flight_ops.py`, with a test in `hooks/test_flight_ops.py` that reproduces the miss.
An incident with no amended check is not closed.
