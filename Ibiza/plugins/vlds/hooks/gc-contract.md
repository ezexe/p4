## VLDS gc (always on)

The collector is never invoked and never off. It collects belief state the way V8's Oilpan (cppgc) collects a C++ heap — trace-based mark-and-sweep, limited compaction, marking and sweeping interleaved with the work — and this session is its mutator: its cycle runs every turn, on the plugin's hooks and in the operator, whether anyone names it or not.
`/vlds:gc full` forces an atomic collection, `/vlds:gc archive` pours the whole hot tier into the cold tier, and `/vlds:gc <target>` collects that target first. The `vlds:gc` skill holds the full doctrine; load it when a phase below reaches a judgment this block does not settle.

**The heap.** Every entry in `store/*` (rulings, rules, claims, inferences, tasks, tombstones) and any base memory or plan doc the work leans on.
**Roots** (Persistent): the owner's LIVE rulings and standing rules, the world as it verifies now, and the live turn.
**Strong edges** (Member): a handle from one entry to another. A handle is the cited entry's head quoted from its opening (at least its first 32 characters, verbatim), its fact id, or the owner's words verbatim.
**Weak edges** (WeakMember): history that cites, such as ledger events, logger lines, and a dispatch row's `match:`. A weak edge never keeps its target alive.
**A paraphrase is a raw pointer.** The trace cannot see it, so a free never reaches it, which makes it a use-after-free by construction. Write handles, never paraphrases.

### The cycle runs. Act on what it hands you.

| Phase | Runs at | What it does | Owed by this context |
|---|---|---|---|
| root marking (the short pause) | SessionStart | prints the standing rules whole (the roots), the index digest, and the verdict | read them as roots |
| concurrent marking | the first prompt (in the background on the default pool road) | the operator and its pool children trace the store from the roots outside this context, the way Oilpan's marking runs on background threads; every entry passes the read barrier | launch the operator as the SessionStart directive says, then act on the pool |
| incremental marking | every prompt and every recall | the dispatch barrier marks the message FRESH, ECHO or SUPERSEDED; a recalled entry is traced to a root before it steers, and an unreachable one is surfaced, never applied | the operator's open moment when the prompt hook names a candidate |
| the write barrier | every store write (post-write hook) | runs the check, then `phi.py trace`: each new entry is traced against the tombstones, and a `gc:` line names freed garbage allocated again, or a new tombstone's reach and the live entries holding handles to it | a re-allocation: the operator judges it before anything leans on it. Holders: their pre-finalizers, this turn |
| finalization (the precise collection) | the turn's close (Stop hook) | the turn holds nothing now, so the collection is precise here and only here: the trace runs once more, then the light sweep reclaims what rule alone decides | nothing; the next prompt prints its report |
| lazy sweeping | the turn closes after | finishes pours, compactions and the judged sweep's placements over later turns; a crash leaves debt, never a lost entry | the sweep moment, when the check shows judged debt |

**Conservative mid-turn, precise at the close.** While the turn runs, its reasoning is the native stack, and anything the conversation names may be a reference. The collector reclaims nothing it names mid-turn, and an entry that only looks referenced stays alive a turn longer. Over-retention is the accepted cost; a collector's free mid-turn never is. An owner's retraction is an explicit free and takes effect at once; only the reclamation of its bytes waits.

**A free runs its pre-finalizers in its own turn.** On a retraction, a correction, or a superseding ruling, and on every `gc:` line that names holders, rewrite or sweep each live entry that holds a handle to what was freed, and write the tombstone with `swept:` naming them. Either order works, and tombstone-first lets the write barrier name the holders still left. All of it happens before the reply ends: the next turn is the mutator resuming, and it must find no handle into freed state. The pour that reclaims the freed entry's bytes can come turns later, in no promised order, so it must never be what detaches a reference. Pre-finalizers are heavy, so they are owed only for entries that get cited (rulings, rules, claims). Dispatch rows, logger lines and a turn's inferences die without one.

**Session-local heaps.** A session's dispatch rows, inferences and tasks are its own heap. Another session reaches them only through a cross-session root, meaning an inference promoted into `local-storage.md` or `data-store.md`, never by reading its virtual entry.

**Reachability, not reference.** An entry is live because marking reaches it from a root, not because something cites it. A cluster of rules that cite only each other is unreachable whatever each link says. Such an island is surfaced as UNOWNED and never swept on the collector's word.

**The archive opens on the owner's word.** What a pour moves into the cold tier stays there verbatim and is never removed, and nothing reads it unasked: the pool, the standing rules and every derivation read the hot files alone. `/vlds:recall <query>` is the one road in — the owner asks, the operator reads through `idb.py`, and each match returns as weakened provenance through the read barrier, written back into a hot file only when the owner rules it live again.

**Modes.** Concurrent is the default, and it is never switched off. `/vlds:gc full` is the atomic collection: every phase back to back over the whole store, with the session doing nothing else until it ends, so it needs no write barrier. `/vlds:gc archive`, on the owner's word alone, is no collection: it pours the whole hot tier into the cold tier, LIVE rulings included and nothing exempt, writing no tombstone — the next session starts empty and reaches the past only through `/vlds:recall`.
