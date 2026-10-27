# VLDS GC — Examples

Four collections walked end to end: a use-after-free swept on retraction, a read-barrier catch on recall, a write-barrier refusal at allocation, and a pre-finalizer the write barrier's trace called for.
The first two are drawn from a real incident pair on a real project, generalized.

## Example 1: the use-after-free — an incident laundered into doctrine

**The allocation.** During audio-plugin work, a test run once wedged inside the desktop app — a stuck process, recoverable only by restarting the app — and the same day's debugging had auto-previewed a sound-emitting page on every file save.
The agent stored a standing rule: _"audio tests are user gates — WARN before running anything that emits sound."_

**The frees, unnoticed.** Over the following days every cause was fixed in code: the page stopped auto-playing on bare loads (a URL flag gates the tone), the engine learned to mute its own OS output, an abandoned engine process learned to self-quit on a linger timer, and the test harnesses got bounded waits with force-kill cleanup.
Each fix freed part of the rule's justification.
The rule outlived all of them — nothing ever re-traced it, because it was an **avoidance rule**: it prevented the very runs that would have exposed it as dead.
For six days the agent deferred runnable verifications to the user, on a rule with no living cause and no owner.

**The retraction.** The user called it directly: the gating was _"also a halucination i didnt address yet"_ — an unaddressed hang hidden behind a gate instead of fixed, then stored as doctrine.

**The collection.**

1. **Mark**: the rule traces to an incident whose causes are all verifiably fixed, and to no user ruling — `FREED-RESIDUE`, and retroactively `UNOWNED` from the day it was written.
2. **Sweep transitively**: the memory file holding the rule is deleted and replaced by one recording the retraction and the causes' fixes; the memory index line is rewritten; an ops doc that framed the test matrix as "WARN/ask first" is re-framed; a changelog line repeating the gate — written hours earlier — is corrected; a sibling memory about hallucinated decisions gains this as its second instance.
3. **Verify the sweep**: grep the stores for the old rule's phrasing — zero inbound references remain.
4. **Run what the rule blocked**: both audio test harnesses, immediately, green — the first live proof the rule had been costing real verification.
5. **Tombstone**:

```yaml
- freed: "audio tests are user gates — warn before running anything that emits sound"
  time: 2026-07-21
  cause: retraction
  owner-words: "gating on sound was also a halucination i didnt address yet"
  swept: [the gating memory (replaced), the index line, the ops-doc framing, the changelog tail, second-instance note in the hallucinated-decisions memory]
  lesson: "attribute sound to a process by per-PID audio-session metering, never the device aggregate; fix an operational annoyance at its cause — a workaround stored as doctrine is an unowned allocation"
```

The compaction is the point: the durable lesson (how to attribute sound correctly) survives; the dead directive (don't run audio) dies; the tombstone's `owner-words` keep the same rule from being re-learned from the same prior.

## Example 2: the read-barrier catch — a stale ops claim about to drive work

**The recall.** Mid-task, a stored ops note surfaces: _"the audio test scripts hand-mirror the shared-memory byte layout — change the struct, update the script offsets in lockstep."_
A struct change just landed, so the note is about to allocate real work: a lockstep offset edit across the scripts.

**The trace.** Step 3 of the procedure — re-verify the cause against the present world, not against the store: grep the scripts for offsets, marshals, mappings.
Zero matches: the scripts were long since rewritten to drive a compiled client that includes the struct header, so the layout propagates by rebuild.

**The mark and sweep.** `STALE` — the world moved, the note did not.
The note is rewritten in place to the current fact with the verification date attached, and the planned lockstep edit is cancelled.
Cost of the barrier: one grep.
Cost of skipping it: a pointless edit pass, and a store that teaches the same wrong move again next session.

## Example 3: the write-barrier refusal — doctrine with no owner

**The temptation.** A flaky external service wastes an afternoon; the draft memory reads: _"never call service X directly — always stub it."_

**The barrier.** Before persisting a standing rule, name its owner.
No user ruled this; the flakiness is an incident, possibly transient, possibly fixable.
Stored as written it would be an `UNOWNED` allocation — and an avoidance rule, the kind that never self-corrects.

**What gets stored instead**: the incident as fact ("service X timed out N times on <date>, cost an afternoon"), plus an OPEN question for the user ("stub it by default, or fix the retry config?").
The decision stays where it belongs; the store carries evidence, not self-issued policy.

## Example 4: the pre-finalizer — Y still lists X after X died

**The graph.** A ruling in `local-storage.md` says _"the plan goes in the reply as one fenced block"_.
An index rule built on it quotes its opening as a handle: _"stub the suite — the plan goes in the reply as one fenced block, so nothing runs locally"_.
This is Oilpan's X and Y: X (the ruling) is a client in Y's list (the index rule).

**The free.** The owner retracts the fence ruling mid-task. The operator writes the tombstone.
The post-write hook's write barrier traces the new tombstone and hands back one line:

```text
gc: a free (tombstones.md:13) reaches local-storage.md:9 — held by index.md:11: each one's pre-finalizer is owed this turn, before the reply ends — rewrite it, or sweep it into the tombstone's swept:
```

**Why this turn, and not the close.** The ruling's bytes leave the hot tier at some later turn's close, when a sweep pours it. If the index rule were left to "go away when the ruling does", the next turn would resume with Y still listing a dead X.
The guide would hit the index rule, the rule would steer the plan's form, and the session would dereference a freed decision through a live entry. That is the use-after-free Oilpan's README warns of, met in the store.
The read barrier masks the ruling itself, because the tombstone names it. It does not mask the index rule, because nothing names that.

**The pre-finalizer.** Still in the turn of the free, the index rule is rewritten so that it no longer leans on the fence. Its own lesson stays, that the suite is stubbed in CI, while the fence citation goes.
The tombstone's `swept:` names the index line. Only then does the reply end.
The ruling's reclamation is left to the closes. It reads nothing but the entry it moves, and nothing waits on it.

**Cost of the barrier.** One line in the post-write output, and one rewrite.
**Cost of skipping it.** A rule that keeps re-imposing a form the owner disposed of, surviving because it never mentions the ruling by anything but a quote.
Had the index rule paraphrased the ruling instead (_"fence the plan, per the owner"_), the trace could not have seen the edge. That is why the allocation discipline forbids a paraphrase.

## The Shape to Notice

All four examples are one lesson at four phases of an object's life:
at allocation, name the owner or store a question, and cite by handle (Example 3);
at recall, trace before applying (Example 2);
at free, run the pre-finalizers in the turn of the free (Example 4), then sweep transitively and tombstone (Example 1).
Liveness is reachability — and the rules that most need collecting are precisely the ones whose nature keeps them from ever being tested.
