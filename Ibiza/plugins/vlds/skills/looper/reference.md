# VLDS Looper — Reference

The model behind the looper defined in [SKILL.md](SKILL.md). Load this for the shared-logger schema, how the looper composes the direct-invoke instruments and the always-on gc, and when to fork a subagent.

## Why One Skill Runs the Loop

Claude Code skills are single-purpose, selected one at a time, and cannot invoke or hand off to one another; a subagent runs in an isolated context and returns a result rather than sitting over the live conversation. So the four instruments cannot co-fire on a request, and none can call the others. The looper resolves this: it is the skill set to surface on its own to run the loop (the gate, guide, and inspector carry `disable-model-invocation: true`; the gc is always on, its cycle running in the hooks and the operator, and its skill loads only when a phase reaches a judgment), and it runs in the main conversation where it can see and discipline the live claims. It carries a request through the whole loop by **applying** each instrument's procedure in turn — reading their `SKILL.md` for the mechanism — owning only the order and the record.

## When Each Instrument Fires

The looper runs the instruments in a fixed order — **message before need before recall before claim before verdict** — skipping any step with nothing to act on (not every request has all five). Each fires on its own trigger:

1. **GC, dispatch barrier** — on the _message itself_, before the loop opens, read from the row the always-on gc's prompt hook stamped: is this one already addressed? An `ECHO` gets the delta, a `SUPERSEDED` message gets its free surfaced, and neither enters the loop — every step below would be redundant work on a settled question. Skip when the message is plainly new.
2. **Guide** — on the _need_ behind the request, at intake: when the intent is inferred rather than stated, a clarifying question is in order, the request matches something handled before, or a durable preference surfaces. Skip when intent is explicit and no standing preference is in play.
3. **GC** — on the _stored state_ the work is about to lean on: a recalled memory, configured rule (a guide `hit` included), plan-doc ruling, or training-data assumption whose grounding may have lapsed — read first from the marks the always-on cycle already made, and from any `gc:` line its write barrier raised — and, immediately, on a user retraction/correction that frees standing state, whose pre-finalizers run in this turn. Skip when the turn recalls nothing, retracts nothing, and no `gc:` line is owed.
4. **Gate** — on each _load-bearing claim_ the work rests on: a checkable fact still unverified this session (a version, date, statistic, API behavior, a "latest/best/standard", a security or correctness claim feeding an edit or recommendation), or a position kept because it "sounds right." Skip trivial, conversational, or already-hedged statements.
5. **Inspector** — on a _high-stakes verdict_: when a `CONFIRMED` claim's correctness carries real cost, a guide `match` is about to be reused on consequential ground, a consequential sweep is contested, or self-rationalization is the risk. Skip low-stakes verdicts the inside floor already covers.

These triggers once lived in each instrument's `when_to_use`. With the gate, guide, and inspector set to direct-invoke-only — out of the model's context — that field is inert, so the looper carries their triggers: it is the one that decides which of them applies, and when. The gc's own triggers are no longer the looper's to carry: the collector is always on, and its phases fire on the hooks whether or not the loop opens. The looper's `when_to_use` is the union of the three and of the moments where the gc's marks bear on the request.

## The Shared Logger

`logger.md` — in the **VLDS store**, the working directory's `.claude/p4/sessions/<s8>/vlds/` directory resolved by the plugin's memory override ([../../hooks/memory-override.md](../../hooks/memory-override.md)) — is the looper's own: the dashboard's single, append-only, user-editable activity log. Every instrument's decision is logged there as the looper runs, tagged by instrument.
The operative shape lives in the file's own header — one tagged bullet per decision, the canonical form — and on divergence the file wins, because a user's edit to it is a ruling; the yaml blocks below are the teaching decomposition of what each instrument's entry carries, not a literal serialization.
Each entry carries a `time` — local `YYYY-MM-DD HH:MM` read from the system clock at write time, never invented; if the real time isn't available, stamp the date alone rather than fabricate minutes (fake precision is the gate's own failure mode):

```yaml
# gate — a claim routed
- instrument: gate
  time: [YYYY-MM-DD HH:MM]   # local wall-clock at write time
  claim: [the claim]
  status: CONFIRMED | PENDING | HEDGED
  provenance: [source_type + what verified it, if anything]

# guide — a need handled
- instrument: guide
  time: [YYYY-MM-DD HH:MM]
  key: [need-shape + claim-kind]
  event: surfaced | reused
  outcome: [what was asked or applied]   # plus the match, on a reuse; see guide/reference.md

# gc — stored state collected
- instrument: gc
  time: [YYYY-MM-DD HH:MM]
  item: [the stored rule/memory/assumption traced]
  mark: LIVE | STALE | FREED-RESIDUE | UNOWNED | EXPIRED
  action: [applied | rewritten | swept + tombstoned | surfaced as OPEN | expired]   # a sweep also appends to tombstones.md in the VLDS store
  # `expired` is for virtual/session-storage entries whose scope closed — no tombstone.
  # A data-store entry DROPPED on failed re-verification is not expiry: log it `swept + tombstoned`, cause world-drift.

# gc — a message dispatched (the dispatch barrier)
- instrument: gc
  time: [YYYY-MM-DD HH:MM]
  message: [fingerprint — the opening clause plus the ask]
  state: FRESH | ECHO | SUPERSEDED
  match: [what justified an ECHO or SUPERSEDED call]   # the inference, on the record

# inspector — a verdict checked
- instrument: inspector
  time: [YYYY-MM-DD HH:MM]
  verdict: [the verdict re-examined]
  state: CORROBORATED | REJECTED | CONTESTED
  spread: [how the independent eyes landed]
```

The logger is the looper's own; the guide's `index.md` and `ledger.md` are the guide's (see [../guide/reference.md](../guide/reference.md)), and the gc's `tombstones.md` is the gc's (see [../gc/reference.md](../gc/reference.md)). Reach an instrument directly and you get the raw primitive; the logged trail is what the looper produces.

## Composing Direct-Invoke Instruments and the Always-On GC

The gate, guide, and inspector carry `disable-model-invocation: true`, so they never auto-fire and never compete with the looper. The gc is always on: its cycle runs without any skill being selected, and its skill is model-invocable only so that a phase reaching a judgment can load the doctrine. The looper does not _invoke_ them (skills cannot call skills); it **applies their procedures**, reading [../gate](../gate/SKILL.md), [../guide](../guide/SKILL.md), [../gc](../gc/SKILL.md), and [../inspector](../inspector/SKILL.md) as the authoritative mechanism for each step and executing it inline, in the main conversation, so it can discipline the live claims as they arise. The user can still reach any instrument alone through its `/vlds:<name>` command.

## Delegating a Heavy Check

The inspector's independent eyes are the one step that benefits from isolation — re-deriving a verdict from sources, blind to the originating reasoning. For a consequential check, the looper may **delegate to an isolated subagent** to run those eyes in a fresh context and return only the verdict, keeping the main conversation clean. Routine checks run inline; reserve isolation for genuinely high-stakes or expensive verifications.
