---
name: looper
description: "The conductor of the VLDS dashboard — the skill that surfaces on its own to run the loop, because Claude Code skills neither co-fire nor hand off to one another. A backstop rather than a wrapper: it catches a load-bearing claim, intent, stored assumption, or verdict about to be acted on unchecked, and runs the instruments in order — discipline the need (guide), read what the always-on gc marked and act on what it hands back before stored state steers (gc), route each claim (gate), re-examine high-stakes verdicts (inspector) — logging every decision to a shared, user-editable logger."
when_to_use: "When a request carries something load-bearing at risk of going unchecked. Stay quiet on trivial or conversational turns and where the discipline is already being applied by reflex: this is a backstop for the slip, not a wrapper for every turn. The tell is subordination to an action — a consequential claim, intent, or verdict ridden in on a request to do something, where default handling would act on it without pausing, unlike the same point raised head-on, which already invites the check. It fires on a claim about to be acted on unverified, an inferred intent treated as settled, a stored rule or memory whose grounding may have lapsed, a retraction that frees standing state referenced elsewhere, or a high-stakes verdict about to pass as fact. To run one instrument alone, invoke it directly."
argument-hint: "[request to run through the loop]"
---

# VLDS Looper

> The looper is what **runs the loop** — the skill that surfaces on its own and carries a request through all four instruments in order. Since Claude Code skills neither co-fire nor hand off, the looper **applies** each instrument's procedure rather than _invoking_ it; the user reaches the gate, guide, and inspector directly via `/vlds:<name>`, and the gc needs no reaching: it is always on, and the looper reads what its cycle already marked. The looper is what makes the loop run **on its own**. One commitment: _it owns the order and the log, leaving the mechanisms to the instruments — each step is the instrument's own._

## The Loop

On a load-bearing request, run the four instruments in order behind one preflight — applying each one's own procedure (the looper only sequences — the mechanism stays the instrument's):

1. **Preflight: the dispatch barrier** — before the loop opens, read the state the always-on gc's prompt hook (or the operator, on a candidate row) gave the request's row in `dispatch.md`: `ECHO` → answer the delta, not the message; `SUPERSEDED` → surface the free instead of acting. Only a `FRESH` message enters the loop, because a message already addressed makes every step below redundant work on a settled question. Procedure: [../gc/SKILL.md](../gc/SKILL.md).
2. **Guide the need** — at intake, treat the intent as a claim: look it up in `index.md` in the VLDS store (`hit` → apply the rule; `miss` → ask, teach, or offer to configure). Procedure: [../guide/SKILL.md](../guide/SKILL.md).
3. **Read the collector's marks** — the gc is always on, so the store was already traced: every stored rule, memory, or assumption the work is about to lean on (a guide `hit` included) carries the read barrier's mark in the pool, and any `gc:` line the write barrier raised this turn is owed now. Trace what the marks leave in doubt to a live root; freed or stale → do not apply, surface instead. A retraction in the request runs its pre-finalizers, the transitive sweep, and the tombstone in this turn. Procedure: [../gc/SKILL.md](../gc/SKILL.md).
4. **Gate each claim** — for every load-bearing claim the work rests on, route it to `CONFIRMED` / `PENDING` / `HEDGED` and verify what is `PENDING`. Procedure: [../gate/SKILL.md](../gate/SKILL.md).
5. **Inspect the high-stakes verdicts** — escalate a consequential `CONFIRMED`, applied `match`, or contested sweep to independent eyes → `CORROBORATED` / `REJECTED` / `CONTESTED`. Procedure: [../inspector/SKILL.md](../inspector/SKILL.md).

The order is the loop the dashboard is built on — **have I answered this already? → does the need have a configured answer? → is what I recall still alive? → is each claim known? → would an outside eye agree?** Carry state forward: a `REJECTED` verdict re-gates the claim; a `CONTESTED` one is surfaced; a swept rule un-hits the guide lookup that recalled it.

## Log Every Decision

As it runs, the looper appends each instrument's decision to its own shared, user-editable **`logger.md`** in the **VLDS store** — the working directory's `.claude/p4/vlds/` directory, resolved by the plugin's memory override, which extends the built-in memory system the way a derived class extends its base (legacy pre-override source: repo-root `.vlds/`; contract: [../../hooks/memory-override.md](../../hooks/memory-override.md)).
This is the looper's store — the dashboard's single activity log.
The guide keeps its own `index.md` (rules) and `ledger.md` (its config audit), and the gc keeps `tombstones.md` (its record of freed decisions), each unique to its instrument; the logger is the looper's record of the whole flow as it conducts it.

## How to Apply

1. Run on any **load-bearing or consequential** request; skip trivial or conversational ones.
2. Run the preflight, then steps 2–5 in order, applying each instrument's procedure.
3. Append each decision to `logger.md` in the VLDS store.
4. For a heavy independent check, **delegate to an isolated subagent** to run the inspector's eyes apart from the main context and return only a verdict; otherwise run inline.

To use one instrument alone, invoke it directly: `/vlds:gate`, `/vlds:guide`, `/vlds:inspector`; `/vlds:gc` forces a collection of the always-on gc. If a request was passed with the command — `/vlds:looper <request>` — run **that** through the loop.

## Additional Resources

- [reference.md](reference.md) — the shared logger schema (tagged entries for all four instruments), how the looper composes the direct-invoke instruments and the always-on gc, and when to fork a subagent for heavy checks.
- The instrument procedures: [../gate/SKILL.md](../gate/SKILL.md), [../guide/SKILL.md](../guide/SKILL.md), [../gc/SKILL.md](../gc/SKILL.md), [../inspector/SKILL.md](../inspector/SKILL.md).
