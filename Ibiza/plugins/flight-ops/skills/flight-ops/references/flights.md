# The flights, one checklist each

Each section is one operator as its contract runs it: where its rules come from, then takeoff, landing, go-around and lost communications. When the source changes, this file changes with it.

## vlds-operator

**Source:** the vlds plugin's SessionStart contract (the operator rows), `hooks/operator-prompt.md`, `hooks/pool-prompt.md`; the recall config's `## recall` section.

**Takeoff**
- [ ] The message is the operator line: `Read <vlds>/hooks/operator-prompt.md and do what it says. store: <store> | session: <s8> | now: <the latest now:> | moment: open|sweep|… | <facts>`.
- [ ] `now:` copied from the latest hook `now:`.
- [ ] `subagent_type` general-purpose; `model` the moment's (`operator-model:`, `pool-model:` on open with a pool, `sweep-model:` on sweep).
- [ ] Foreground, except on the children road, where the session launches it in the background and its progress arrives as its messages.
- [ ] From the session: once per session; later moments by `SendMessage` to its agent id, at most `operator-moments:` continuations, then fresh. When `operator-via:` names a conductor, the launch goes to the conductor instead (flight `roboto-conductor`).

**Landing**
- [ ] The return opens `derivation — <moment>, session …`.
- [ ] It quotes its scripts' verdicts; the check line reads `0 corruption`.
- [ ] Its writes are inside this session's store, the pool's picks file and `vindex/`; nothing committed or staged in either repo.

**Go-around:** under a conductor, relaunch once, fresh, with a `conductor fact:` line; from the session, launch fresh and say so.
**Lost communications:** a continuation that fails is never assumed landed — launch fresh.

## roboto-conductor

**Source:** roboto's agent definition (Between the session and its operator) and its `derivation` skill.

**Takeoff**
- [ ] `subagent_type` mister:roboto, foreground.
- [ ] The operator line as above, then last `conductor: launch the operator with this message on <the moment's model>, and return a derived understanding`.

**Landing**
- [ ] The return opens `derived understanding — <moment>, session …, conducted by roboto`.
- [ ] Its `operator:` line reports every operator launch it made, a go-around included.
- [ ] It is no response to the owner: the response stays the session's.

**Go-around:** relaunch the hand-off once, saying so; read the hand-back for what the operator left.
**Lost communications:** roboto launches the operator fresh per moment and never continues it, so a silent operator is relaunched by roboto, not waited on.

## vlds-pick-reader

**Source:** `hooks/pool-prompt.md` (the children road) and `hooks/pool-child-prompt.md`.

**Takeoff**
- [ ] One per file under `inject:` and `digest:`, all in ONE message.
- [ ] `subagent_type` vlds:pick-reader (no tool that writes), general-purpose only where that type is absent; `model` the `pool-child-model:`.
- [ ] `run_in_background` true.
- [ ] The message: read `hooks/pool-child-prompt.md`, then `store`, `session`, `now`, `task`, `file`, `barrier` (that file's lines, pasted).

**Landing**
- [ ] The return opens `picks — <file>, <n> of <total> entries bear on the task`, then one `<file>:<line> || bears: …` per pick, or none.
- [ ] Appended to the picks file as it lands; the operator stays in its turn until every child has landed.

**Go-around:** none — a child that never lands leaves its file to the operator's own pass under pass heads, named in the pool's `read:` line.
**Lost communications:** at spawn depth 3 a child has no Agent tool and launches nothing.

## vlds-inspector-perspective

**Source:** the vlds `inspector` skill.

**Takeoff**
- [ ] The brief carries the line `flight: vlds-inspector-perspective`.
- [ ] Blind to the original reasoning; re-grounded in sources; framed to one angle — refute, re-derive, or stress one failure mode.
- [ ] A read-only agent type where one fits the angle.

**Landing**
- [ ] A for / against reading with the sources it re-grounded in.
- [ ] The tree unchanged after it, or the perspective is void.

**Go-around:** a void perspective is not counted in the distribution; another may be launched in its place.

## orchestration-branch

**Source:** roboto's `orchestration` skill (PLAY).

**Takeoff**
- [ ] The brief carries the line `flight: orchestration-branch`, and is a fresh prompter-prompt for one reading.

**Landing**
- [ ] The branch's compiled takes for the merge — never an action.

**Go-around:** a branch that acted is void; the act goes to `activation`.
