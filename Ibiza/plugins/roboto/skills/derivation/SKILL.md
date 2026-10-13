---
name: derivation
description: Roboto as the conductor of a session's VLDS operator — the session hands roboto a store moment (open with its pool, or a sweep) instead of launching the operator itself; roboto launches the operator on the moment's model, the operator runs its haiku puppets, and the operator's derivation comes back through roboto's four lenses as a derived understanding — the barrier, the intent, what the store establishes for the task and how firmly — which the session acts on. Never a response to the owner; the response stays the session's. Use when a session hands roboto a VLDS store moment to conduct, never when the brief is the one roboto gives the operator.
when_to_use: "Trigger only on a session's hand-off to roboto — a brief that asks to read the vlds plugin's hooks/operator-prompt.md and whose `conductor:` line asks you to launch the operator (`conductor: launch the operator with this message on <model>, and return a derived understanding`), as a session sends when its index's `operator-via:` names roboto. Never when the `conductor:` line names roboto as the one to return to (`conductor: roboto — …`) — that brief is the operator's own, and whoever reads it is the operator, which conducts nothing."
metadata:
  p4:
    type: skill
    phases: [prompter, pioneer, puppeteer]
    depends_on: [vlds, bias-patterns]
    optional_depends_on: [persistence, vlds:gc]
    interface:
      domains: [operator_conducting, derived_understanding, store_moments]
      capabilities: [operator_launch, operator_continuation, derivation_lensing, derived_understanding, hand_back]
    hooks:
      on_prompty: []
      on_prompter: [read_handoff]
      on_pioneer: [launch_operator, lens_the_derivation]
      on_puppeteer: [emit_derived_understanding]
    tiers: [derivation]
---

# Derivation Skill — roboto between the session and its operator

> The session hands roboto a store moment; roboto conducts the vlds operator, and the operator's derivation comes back through roboto's lenses as a derived understanding.
> Roboto never answers the owner here: the response stays the session's.

## The Flow

```text
session ──hand-off──▶ roboto ──operator line──▶ operator (the moment's model: Sonnet by default for every moment)
                                                   └──▶ haiku puppets, one per store file (the pool's children road)
session ◀──derived understanding── roboto ◀──derivation── operator ◀──picks── puppets
```

Each link speaks only to its neighbours: the session never speaks to the operator, and nobody but the operator speaks to a puppet.
The vlds plugin owns the operator and its puppets — its `hooks/operator-prompt.md`, `hooks/pool-prompt.md` and `hooks/pool-child-prompt.md` are their briefs.
This skill owns the conductor's part: the launch, the lenses, and the understanding.
A session routes its store moments here when its index's `## recall` section names roboto's agent type in `operator-via:`; without that line the session launches the operator itself, and roboto never sees the moment.

## 1. Read the Hand-off

The session's message carries the operator line — `Read <vlds plugin root>/hooks/operator-prompt.md and do what it says. store: … | session: … | now: … | moment: … | <facts>` — and one more line: `conductor: launch the operator with this message on <model>, and return a derived understanding`.
Keep the operator line verbatim: it is the operator's brief, and the clock in it is the only time anyone may write.
The model is the moment's: the pool's model for a pool, the sweep model for a sweep, the operator model for the rest of open.
The session's task, in one line, rides in the facts; it is the object the lenses read the store against.

## 2. Launch the Operator, Fresh for Each Moment

Every moment launches it anew: the Agent tool, `subagent_type` general-purpose, `model` as the hand-off names, in the foreground, with one message — the operator line, then `conductor: roboto — you are the operator: return your derivation to me as your final message once every child has landed; launch no operator; send nothing to main`.
Never continue an operator with SendMessage: a subagent has no tool that waits on the reply, which lands only at some later tool round, so the conductor would spin on reads it does not need until it arrives.
An operator return that is not a derivation — a progress note on children still running, or a derived understanding of its own — is a failed moment: relaunch it once, fresh, with the same message and one `conductor fact:` line naming what the first launch reported and left behind, and report both launches in `operator:`.
The chain is as deep as the harness lets it launch: roboto runs at spawn depth 1, the operator at 2 and its puppets at 3, where an agent gets no Agent tool — so an operator that conducts another operator leaves the real one unable to launch a puppet.
The store carries the state between moments, so a fresh operator loses nothing but the reads it repeats.
Never launch or message a puppet: the operator's children are its own, and their picks reach roboto only through the derivation.
Never open a store file: the derivation, and the pool it carries, are the whole input.

## 3. Put the Derivation Through the Lenses

The four lenses run as always, on a narrower object: not how to answer the owner, but what the store establishes for this task, and how firmly.

- **Claude** reads the task with the derivation and its pool: what the store says bears on it.
- **Claudio** reads the task alone, with no store: what the message by itself supports — the control.
- **Claudius** names the delta: what the store adds or changes, marking anything neither grounds as `unexplained`.
- **Roboto** gates each load-bearing item and synthesizes the understanding:
  - an item the barrier passed `LIVE` and the pool carries is `CONFIRMED` as recall — what the store holds, cleared by the barrier, not a fresh fact about the world;
  - an item that steers the task but rests on a claim the store never verified, or on a state the world may have moved past, is `PENDING`, with the read that would settle it;
  - an `UNOWNED`, surfaced, or doubted item is `HEDGED` and never steers.

The bias scan then runs over the understanding: `context_pollution` when a store entry is steering a task it does not bear on, `context_starvation` when the task needs something the store does not hold.

## 4. Return the Derived Understanding

Return exactly this, nothing before it:

```text
derived understanding — <moment>, session <short id "title">, <now>, conducted by roboto
barrier: <FRESH | ECHO | SUPERSEDED — match, freed-by — as the operator found it>
intent: <one line — the operator's, or corrected, with the correction named>
act: <answer it | answer the delta: … | surface the free: …>
rules: <the owner's standing rules that bear on this task, by label — the pool's short line for each, with its file and time — or none>
understanding:
- <what the store establishes for this task, one line each: the item, its file and time, its status — CONFIRMED | PENDING (the read that settles it) | HEDGED>
delta: <what the store adds beyond the message alone; unexplained: what neither grounds, or none>
bias: <CLEAR, or the pattern and its correction>
surfaced: <what the barrier would not let steer, or nothing>
operator: <what it wrote — the pool at store/recall-pool.md with its time, size and road; a sweep's pours; or nothing — and its own could-not lines, verbatim>
hand-back: <pending acts, questions, store proposals, blocked — or none>
```

Rules of the understanding:

- At most 5,000 characters. The pool stays whole in `store/recall-pool.md`, where the operator wrote it and a compact re-injects it; the understanding carries what steers, not the pool again.
- `rules:` names the standing rules by label and never copies the pool's standing section. The session holds every form ruling and every-turn rule whole from the vlds start-up block that prints them, and the pool's grouped lines are lists of line numbers, not rules.
- Never a response to the owner: no Influence Disclosure block, no four named sections, no drafted answer, no plan for the task. The session writes the response.
- Report the operator's failures plainly — a gate's ask, a file absent, a lock held, a child relaunched — never smoothed over.
- Every `time` is the operator's or an entry's: roboto writes none.

## Relationship to the Lifecycle and Other Skills

- **identity** (always-on base). The lenses run in full; their output takes this skill's shape instead of the response contract — a deviation the `derivation` closure declares by being selected.
- **vlds** (required). Its gate supplies the statuses, and the read barrier's states come from the operator's pool.
- **bias-patterns** (required). The scan runs over the understanding before it is returned.
- **persistence** (optional). A finding the store should keep goes into the hand-back as a store proposal.
- **the vlds gc** (optional, `vlds:gc`). Its liveness classes are the barrier states the operator reports and this skill reads.
- **Configuration tiers:** ships in **Derivation** only — the closure the `rubric` selects when the brief is a store hand-off.
