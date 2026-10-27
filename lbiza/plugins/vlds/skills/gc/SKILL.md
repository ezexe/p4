---
name: gc
description: "The epistemic garbage collector, always on. It is the liveness instrument for STORED state: memories, configured rules, plan-doc rulings, session-summary carryovers, and training-data assumptions. It is modeled on V8's Oilpan (cppgc): trace-based mark-and-sweep with limited compaction, marking and sweeping running concurrently with the work and incrementally beside it. Its cycle rides the plugin's hooks every turn and never waits to be invoked. Roots are marked at session start, the store is traced in the background, a write barrier traces every store write, and the precise collection runs at the turn's close, when the turn holds nothing. Where the gate asks whether a claim is known now, the gc asks whether a stored decision is still ALIVE, meaning reachable from a live root (a standing user ruling, or a currently-verifiable state of the world) through handles, never through a paraphrase. It catches the use-after-free (a retracted ruling still applied), the leak (a directive whose justifying causes were fixed long ago), the dangling pointer (a memory citing what no longer exists), the island (rules that cite only each other), and the stale oldest generation (training data asserting versioned facts as current). A free runs its pre-finalizers in its own turn. Sweeps compact rather than erase, so the durable lesson survives and the dead directive dies, and every free is tombstoned so the same garbage is not re-learned."
when_to_use: "The cycle runs without this skill: its contract is injected at every session start and its barriers ride the hooks. Load the skill when a phase reaches a judgment that block does not settle. That means a retraction or superseding ruling whose free must be swept transitively with its pre-finalizers, a `gc:` line from the write barrier naming re-allocated garbage or holders of a freed entry, a stored rule or memory about to steer work whose provenance is in doubt, a completed arc that obsoletes stored claims, a full (atomic) collection, an archive of the whole hot tier on the owner's word, or a pressure audit."
argument-hint: "[stored decision or store to collect | 'full' for an atomic whole-store collection | 'archive' to pour the whole hot tier into the cold tier]"
---

# VLDS GC

> The gc is **a garbage collector for belief state**, and it is **always on**. It applies the discipline that V8's Oilpan applies to a C++ heap to what a model stores and recalls: liveness is reachability from a live root through handles the trace can see, never plausibility.
> One question drives it: **"is this stored decision still alive, or am I dereferencing something the user already freed?"** It holds one commitment: _a disposed decision stops steering the work the moment it is freed, not whenever it happens to be noticed._

## Always on

Oilpan is not called by the code it serves. The embedder's platform schedules it, and it does its marking and sweeping on background threads and in small steps between the mutator's tasks.
The gc runs the same way. **This session is the mutator**, the plugin's hooks are the platform, and the operator subagent is the background thread.
The cycle runs every turn whether or not anyone names the gc. Its contract ([../../hooks/gc-contract.md](../../hooks/gc-contract.md)) is injected at every SessionStart beside the memory override, and its barriers are hooks and scripts.
This skill is the doctrine those phases cite. `/vlds:gc full` forces an atomic collection, `/vlds:gc archive` pours the whole hot tier into the cold tier, and `/vlds:gc <target>` collects that target first.

## The heap, the roots, the handles

| Oilpan (cppgc)                        | Epistemic counterpart                                                                                                                              |
| ------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| On-heap object                        | A stored decision or claim: a memory entry, a configured rule (the VLDS store's `index.md`), a logged verdict, a plan-doc ruling, a summary carryover, a training-data assumption |
| Root set, `Persistent<>`              | What is live NOW: the owner's standing rulings (latest wins), the currently-verifiable state of the world, and the live turn                        |
| `Member<>`, a strong edge             | A **handle** from one entry to another: the cited entry's head quoted from its opening (at least its first 32 characters, verbatim), its fact id, or the owner's words verbatim. The cited entry lives while the citing one does, and dies only by a free |
| `WeakMember<>`, a weak edge           | History that cites, such as a ledger event, a logger line, a dispatch row's `match:`, or a recall-pool line. It never keeps its target alive, and it is cleared, never swept, when the target dies |
| Raw pointer to an on-heap object      | A **paraphrase**: a reference the trace cannot see. A free never reaches it, so it is a use-after-free by construction. It is forbidden in the store, as raw pointers are on the heap |
| Conservative stack scan               | Mid-turn, the live turn's reasoning holds references the collector cannot read, so anything the conversation names is treated as a root           |
| Use-after-free                        | Applying a stored derivative of a freed decision                                                                                                    |
| Leak                                  | An item whose justification no longer exists, surviving only because nothing re-traces its provenance                                               |
| Dangling pointer                      | A stored item citing a file, flag, symbol, or behavior that no longer exists                                                                        |
| Pre-finalizer                         | Rewriting or sweeping every live holder of a dying entry's handle, run in the turn of the free, before anything is reclaimed                        |
| Destructor / reclamation              | The pour or trim that moves a dead entry's bytes out of the hot tier, which runs lazily, in no promised order, and touches nothing else            |
| (no Oilpan counterpart)               | The **tombstone**: the record of the free (what was retracted, when, in whose words), which keeps the same garbage from being re-learned from the same prior |

## Liveness classes

Mark every item under collection:

| Class           | Meaning                                                                                | Sweep action                                            |
| --------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `LIVE`          | marking reaches it from a live root through handles                                     | keep; apply freely                                      |
| `STALE`         | contradicted by the current world — re-verify against the world, never against the memory of it | rewrite to the current fact, or delete          |
| `FREED-RESIDUE` | derives from a decision the user disposed of                                            | pre-finalize its holders, sweep transitively, tombstone |
| `UNOWNED`       | no user ruling at its root: self-allocated doctrine, or an island that only its own members reach | surface as an OPEN point for the user; never apply as settled |
| `EXPIRED`       | lifetime bound reached — a tier-scoped entry whose scope (the turn, the task) has closed | free without a tombstone; promote first if it must outlive its scope |

`EXPIRED` is the ordinary rule, not a new one. The live turn is already a root, so a turn-scoped entry's root **is** the turn and vanishes with it. Nothing contradicted it, which is why it takes no tombstone.

`UNOWNED` is an allocation bug, not only a collection target: a workaround for an operational annoyance stored as a standing rule was never anyone's decision.
The write barrier's allocation discipline is its prevention: before persisting any standing rule, name its owner (the user ruling that decided it). With no owner, store an open question instead of doctrine.

## The cycle

Oilpan has three modes: atomic (the whole cycle in one stop-the-world pause), incremental (the work cut into small steps between the mutator's tasks, with write barriers keeping the graph consistent), and concurrent (incremental, with most of the work moved to background threads).
**Concurrent is the gc's default, and it is never switched off.** Its phases bind to the hooks:

| Phase | Oilpan | Runs at | What it does |
| --- | --- | --- | --- |
| Root marking | marking step 1, in a short pause | SessionStart | `phi.py standing` prints the owner's standing rules whole (under `pool: inject`, the inject files arrive whole instead), and the index digest and the check's verdict follow |
| Concurrent marking | marking step 2, on background threads | the first prompt (in the background on the default pool road) | the operator and its pool children trace the store from the roots in their own contexts, off the session's, and every entry passes the read barrier ([Marking](#marking)) |
| Incremental marking | marking step 2, interleaved | every prompt; every recall | the dispatch barrier marks the new message, and a recalled entry is traced to a root before it steers |
| The write barrier | the barrier that keeps incremental marking sound | every store write (post-write hook) | runs the check, then `phi.py trace` over every new entry ([The write barrier](#the-write-barrier)) |
| Finalization | marking's final pause: step 2 finished, step 3 run | the turn's close (Stop hook) | traces once more what no post-write saw, then hands off to the precise collection |
| Precise collection and sweeping | sweeping, at the end of an event loop | the turn's close, then the turn closes after | the light sweep reclaims what rule alone decides, and pours, compactions and the judged sweep's placements finish over later turns ([Sweeping](#sweeping)) |

**Conservative mid-turn, precise at the close.**
Oilpan collects conservatively while the native stack may hold references it cannot type, keeping alive anything a stack value seems to point at, and precisely at the end of an event loop, when the stack is guaranteed empty.
The gc's stack is the live turn. While the turn runs, anything the conversation names may be a reference, so the collector reclaims nothing it names mid-turn, and an entry that only looks referenced stays alive a turn longer. Over-retention is the accepted cost; a collector's free mid-turn never is.
An owner's retraction is different. It is an explicit free, and it takes effect at once, because a disposed decision stops steering the moment it is freed. Only the reclamation of its bytes waits.
At the turn's close the turn holds nothing, so the collection is precise there and only there: the mechanical sweep reclaims at the Stop hook, never in the prompt or post-write hooks.
The one reclamation at a turn's start, the dispatch pour at a new session's first prompt, also happens on an empty stack. It falls between two event loops, and every row it moves belongs to a conversation that is not this one.

**Atomic on demand.** `/vlds:gc full` is the stop-the-world collection: every phase back to back over the whole store, including the cold tier and the base memories, with the session doing nothing else until it ends. Because nothing else runs, it needs no write barrier.

**Archive on the owner's word.** `/vlds:gc archive` is not a collection: it frees nothing and writes no tombstone. It pours every entry of every hot object store into the keyspace's cold tier, LIVE rulings and standing rules included, nothing exempt, so the next session starts on an empty hot tier and the store's past reaches it only through `/vlds:recall`. It runs only when the owner invokes it, never on the collector's initiative and never inside a sweep, and only on the keyspace. Run `idb.py --store <store> archive --session <id> --now "<now>" --dry` first and report its counts, then the same without `--dry`, and tell the owner that the running session still holds its pool and that a new session is the one that starts empty. An archived LIVE ruling stops steering because nothing marks from the cold tier, not because it was retracted. It comes back as a root only when the owner rules it live again. The tombstones go cold with everything else, and their masks still reach the hot barriers, which read the keyspace's cold tombstones beside the hot ones. The design and its costs are in [reference.md](reference.md), the archive.

## Marking

Oilpan marks in three steps, and so does the gc.

1. **Mark the roots.** The owner's LIVE rulings and standing rules (printed whole at SessionStart), the world as it verifies now, and the live turn.
2. **Trace transitively.** Follow each handle from what is marked to what it cites, and re-verify a load-bearing cause against the present world rather than the store's restatement of it ([reference.md](reference.md), the tracing procedure).
3. **Clear the weak edges.** A weak edge whose target died is cleared. A ledger event that recalled a freed rule stops counting as a reuse, and the guide's lookup un-hits it. A weak edge is never swept.

Oilpan runs weak processing only when the holder outlives its target, so code that assumes it always ran is wrong. The same holds here: a weak edge into freed state may still read as written, and the read barrier, not its having been cleared, is what keeps it from steering.

**Reachability, not reference.**
An entry is live because marking reaches it from a root, not because something cites it. Reference counting cannot collect a cycle; a trace from the roots never reaches one.
A cluster of rules that cite only each other, each locally justified and the whole anchored to nothing anyone asked for, is unreachable however many links it has. Such an island is `UNOWNED`. Marking finds it, and sweeping does not touch it: it is surfaced for the owner's ruling, because sorting essential complexity from accidental is no one's call but theirs. The pressure audit that counts toward it is in [reference.md](reference.md).

**The read barrier** is marking at recall. Before a stored rule, memory, or assumption shapes an in-session decision, trace its provenance to a root. Unreachable means do not apply it; surface it instead.
Its mechanical half (`phi.py barrier`) stamps each entry LIVE, SPENT, FREED, or EXPIRED by rule alone: its own status field, a tombstone's mask, a virtual entry another session minted, or a cleared task. The pool's readers copy those stamps and never re-judge them.
A tier-scoped entry whose scope has closed is collected here, and what rule alone can expire is collected again at the turn's close.

## The dispatch barrier — a new message, or the same one twice?

The read barrier guards what you recall and the write barrier guards what you store; the **dispatch barrier** guards what you _answer_. It is incremental marking at the prompt, with the new message as an allocation.
It fires as the thought stream forms, before a response is committed to rather than after it is written, on one question: **is this message new, or am I addressing it a second time believing it new?**
A message, once addressed, is stored state like any other. Re-addressing it dereferences a handled message as if unhandled, and re-addressing one that a later message overrode is a use-after-free with a friendly face.

| State | Meaning | Do |
| --- | --- | --- |
| `FRESH` | no matching entry in the record before this message's own stamped row | address it. The stamp is the hook's, and so is `state: FRESH` when no earlier row resembles the message. A candidate row leaves the state to the operator subagent's judgment, and `addressed:` is the operator's at the turn's close |
| `ECHO` | already addressed, and nothing about it changed | answer the delta only — never re-answer the message whole |
| `SUPERSEDED` | addressed, then freed by a later message | surface the free; acting on it is a use-after-free |

**Timing is the whole mechanism.**
Caught while the thought stream forms, an echo costs nothing to drop. Caught at emission, the duplicate already exists and every remaining option is bad: ship it and contradict yourself, or retract it and spend the turn on noise.

**Matching is an inference, so log it.**
Messages carry no ids, so a match rests on a fingerprint (the opening clause plus the ask), and it is exactly the sameness judgment the guide's `hit` can get wrong.
**When the match is uncertain, default to `FRESH`.** The failure modes are not symmetric: a wrong `FRESH` wastes a turn, while a wrong `ECHO` silently drops the user's request, and only the first is recoverable without the user having to notice and ask twice.

The record is `dispatch.md`, **one shared file**, never promoted to a rule; where echoes come from is in [reference.md](reference.md).
On a NEW session's first prompt the prompt hook pours the whole file into `arc/` (`idb/blobs/dispatch/` on the keyspace, journaled) as a byte-identical, sha-verified copy with the header kept, and the dispatcher starts fresh. The poured entries stay verbatim and demand-pageable, registered by the next sweep. The hook keys on the store's `.sessions` ledger, written at a first prompt and by the SessionStart index hook on a resume, fork, or compact. A resumed conversation keeps its own entries, a fork (a new id over a live conversation) is recorded before its first prompt and keeps them too, and a transient `SessionStart` firing (which never submits a prompt) takes nothing.
That pour supersedes the model's first-turn pour, which superseded the per-session-files era (`dispatch-<session>.md` + `.dispatch-current`), which itself replaced two attempts to rotate a shared record at hook time. Both attempts took the record out from under a running conversation, because `SessionStart` also fires on resume and under transient ids, so no `SessionStart` signal ever proved a session had begun. A first prompt from an unrecorded id is that proof: every entry in the file then belongs to a conversation that is not this one, so no judgment is needed on what to pour, and nothing is destroyed at all.
Collection here is nothing special anymore. The pour IS the collection, and it runs every new session without a model turn spent on it.
Collection promotes nothing, and cannot: by the time a record is collectable its session is gone, and with it the only party who could judge what deserved keeping.
So a misreading that steered work is promoted to the guide's `ledger.md` as a `correction` **when it is caught**, not when the record is eventually collected. `virtual.md` follows the same discipline: an inference that must outlive its turn is promoted before the turn ends rather than rescued after.

## The write barrier

Incremental marking needs a write barrier. Without one, the mutator could change the graph between marking steps, and a live object could be swept because the collector never saw the edge that made it live.
The gc's write barrier has two halves.

**Allocation discipline (judged).** Before persisting a standing rule, name its owner. With no owner, store an open question instead of doctrine.
Write every reference to another entry as a handle, never a paraphrase. On the heap a raw pointer is an edge Oilpan cannot observe, and in the store a paraphrase is a citation no trace can follow, so a free never reaches the citing entry.

**The trace (mechanical).** `phi.py trace` runs after every store write (the post-write hook) and once more at the turn's close.
`store/.gc-heads` remembers each hot file's head lines as the last trace saw them. Every head that is new since then is an allocation, traced against the tombstone masks the read barrier applies:

- **Re-allocated.** A new ruling, rule, claim, or inference that a tombstone masks, dated no earlier than the free, is freed garbage allocated again, or the owner ruling it again after the free. Which one is the operator's call. Until that call is made, the read barrier keeps the entry FREED.
- **A free's reach.** A new tombstone is listed with the hot entries it masks (the dying) and every LIVE entry that holds a handle to one of them. Each holder is owed its pre-finalizer this turn.

The trace prints one `gc:` line per finding and nothing when nothing is found. The first trace on a store records a baseline and reports nothing.
It follows head quotes only: a handle by fact id is the keyspace's free to follow, and a handle by the owner's words is the barrier's mask. Its coverage is structural, and so is every other script's. A citation by paraphrase is invisible to it, which is why the allocation discipline forbids one.

## Sweeping

Oilpan sweeps in two steps. Pre-finalizers run first, while every object is still intact and each may touch any other. Destructors run after, in no promised order and touching nothing else, and the mutator resumes before all of them have run.
Oilpan's README gives one warning that is the gc's whole sweeping discipline. If X sits in Y's list of clients and only X's destructor removes it, Y can walk the list after the mutator resumes and reach into a dead X. X must leave the list in a pre-finalizer, before the mutator runs again.

1. **Pre-finalizers, in the turn of the free.** On a retraction, correction, or superseding ruling, or a fixed cause, and on every `gc:` line that names holders, rewrite or sweep each live entry that holds a handle to what is freed. Do it TRANSITIVELY along the handles in both directions: everything derived from the freed decision, and every store that cites the swept items. Write the tombstone too, with `swept:` naming every store touched. The order is free, and tombstone-first has an advantage: the write barrier's line after it names every holder still left. All of it happens before the reply ends, because the next turn is the mutator resuming and must find no handle into freed state. A holder that only the close's trace names, for a write no post-write saw, is owed first thing in the next turn. A sweep that leaves an inbound handle has manufactured a dangling pointer.
2. **Reclamation, lazily.** The pour or trim that moves the dead entry's bytes out of the hot tier runs at a later turn's close, in no promised order, and reads nothing but the entry it moves. It must never be what detaches a reference. The light classes reclaim at every close; the judged sweep scores what is cold and a script places it ([reference.md](reference.md), the keyspace and the φ-register). An interrupted pour leaves debt, never a lost entry, and the next pass finishes it before the next cycle's marking.

**Pre-finalizers are heavy.** Oilpan scans every registered pre-finalizer at every sweep, so they are kept off objects allocated often.
The gc owes them only for entries that get cited: rulings, rules, claims, and tombstones. Dispatch rows, logger lines, and a turn's inferences are allocated every turn and die without one, because nothing may hold a strong handle to them.

**Sweeps compact rather than erase.** The durable lesson survives, rewritten in place, and the dead directive dies. That is compaction of meaning. **Heap compaction**, which moves bytes, is the cold tier's alone, as Oilpan compacts only the spaces marked compactable: the keyspace merges its runs under the sweep lock at a turn's close. No script compacts a hot file, which stays exactly as the owner can read and edit it.

**Every free is tombstoned** in the VLDS store's `tombstones.md` with the retraction, its date, the user's words, and what was swept with it. The tombstone makes the sweep reversible and the same garbage un-relearnable.

## Session-local heaps

Oilpan heaps are thread-local. An object is allocated, used, and reclaimed on one thread, and a reference into another thread's heap goes through a cross-thread root, even between two on-heap objects.
A session is the gc's thread. Its dispatch rows, its inferences in `virtual.md`, and its tasks in `session-storage.md` are its own heap.
Another session reaches them only through a cross-session root, meaning an inference promoted into `local-storage.md` or `data-store.md`. Reading another session's virtual entry is the cross-thread raw pointer: the read barrier marks it EXPIRED here, and the turn close's light sweep pours it.
That pour is the one place the gc departs from Oilpan, which reclaims only on the allocating thread. A session that ended never runs its own close again, so another session's close collects the inferences it left unpromoted, by rule and whether or not it has ended. That is sound only because an inference that must outlive its turn is promoted before the turn ends.

## The hazard ranking

- **Avoidance rules are the highest-risk objects.** A rule that prevents an action evades every natural re-verification — you never collide with what you never touch — so it survives on inertia and must be traced proactively at every recall.
- **A directive justified by an incident dies with the incident's causes.** Re-check whether the causes still exist; fixed causes make it `FREED-RESIDUE` even when no explicit retraction ever arrived.
- **Training data is the oldest generation.** Every versioned or dated claim recalled from it is `STALE`-suspect by default — the gate's `source_type: training`, read at store scope.
- **Latest user word wins.** Rulings are ordered; a newer ruling silently frees every older one it contradicts, and its pre-finalizers are owed at the moment of contradiction.
- **A paraphrased citation is the quiet use-after-free.** It survives every free of what it cites, because no trace can see it.

## Invalidation — the GC's job, now yours

The web platform teaches this lesson the hard way: `sessionStorage` clears itself when the tab dies, but `localStorage` never expires — invalidation is the developer's job, and state nobody invalidates becomes doctrine by default.
In VLDS the gc is that developer.
The gate's storage tiers persist to partition files, and no partition invalidates itself — so running their expiries is the gc's job.
**Which file takes what is settled in one place: the fires-when table of the always-injected contract** ([../../hooks/memory-override.md](../../hooks/memory-override.md)), which is in context every session; this section owns why those policies are what they are, not a second copy of them.
Two of them are phases of the cycle met at tier scope. `session-storage.md` clearing at task completion is a completed arc's free, and `local-storage.md` freeing on retraction is a free with its pre-finalizers.

Persisting an ephemeral tier gives Gen 0 state a Gen 1 body, which is exactly why its expiry has to be checked rather than assumed: an un-expired `virtual.md` entry is the tenuring hazard on disk.
No expiry fires on a timer. Expiry is **lazy, enforced at recall**, so an entry past its scope never steers, whatever bytes remain on disk. For what rule alone decides, such as a virtual entry minted by a session that is not this one, the turn's close pours it mechanically, so the bytes leave too.

Which expiries take a tombstone is not uniform, and the split follows what was lost:

- **`virtual.md` and `session-storage.md` — no tombstone.** Turn- and task-scoped state re-derives next time it is needed, so re-minting it is correct behavior, and tombstoning every expired inference would bury the record that matters under the record that doesn't. Mark them `EXPIRED`.
- **`local-storage.md` — tombstone.** It never expires on its own, so anything leaving it left by a user's word — a retraction, a correction, a superseding ruling — which is a free like any other.
- **`data-store.md` — it depends on which way it goes.** An entry **rewritten in place** to the verified current fact is already its own mask and owes nothing further; an entry **dropped** because re-verification failed is a `world-drift` free and owes a tombstone, or the same training prior regenerates the same stale claim with nothing standing in front of it.

## How to Apply

The cycle runs without being asked. This procedure is what a phase hands you when it reaches a judgment.

1. **Identify** the item under collection: the stored decision about to be applied, the one just retracted, the one a `gc:` line names, or the store under an atomic collection.
2. **Trace from a root**: who decided it, from what cause, along which handles, re-verified against the world as it is now — not as the store remembers it.
3. **Mark** its liveness class from the table above.
4. **Pre-finalize, then sweep**: rewrite or sweep every live holder of its handle, transitively and in this turn; compact (keep the durable lesson, kill the dead directive); then **tombstone** the free in `tombstones.md` with the retraction, its date, the user's words, and what was swept. Leave the bytes' reclamation to the turn closes.
5. **Surface the result**: what was collected, what survived compaction, and what is now `UNOWNED` awaiting a ruling.

If a target was passed with the command (`/vlds:gc <target>`), collect **that** first. `/vlds:gc full` runs every phase, atomically, over the whole store. `/vlds:gc archive` runs no phase: it pours the whole hot tier, as **Archive on the owner's word** says.

## Additional Resources

These load on demand — read them when the moment calls for it:

- [reference.md](reference.md) — the layer behind the collector: Oilpan's model and what transfers from it, the generational model (session context / stored memory / training data), the spaces, the tombstone schema, the tracing procedure, the pressure audit, the keyspace and the φ-register, and how the gc composes with the gate, guide, inspector, and looper.
- [examples.md](examples.md) — a real use-after-free walked end to end, a read-barrier catch, a write-barrier refusal, and a pre-finalizer the write barrier's trace called for.
- [../../hooks/gc-contract.md](../../hooks/gc-contract.md) — the always-on block every session receives.
