# VLDS GC — Reference

The model behind the collector defined in [SKILL.md](SKILL.md).
Load this for Oilpan's model and what transfers from it, the generational model, the tombstone schema, the provenance-tracing procedure, and how the gc composes with the other instruments.

## Oilpan — the Model the Always-On Collector Follows

The source is V8's `include/cppgc/README.md`, "Oilpan: C++ Garbage Collection". Oilpan is a trace-based mark-and-sweep collector with limited compaction, built to run beside a mutator that never stops for long.
Its key properties land as follows.

| Oilpan | The gc |
| --- | --- |
| trace-based collection | liveness is reachability from the roots through handles, so an island that only its own members cite is unreachable, whatever its reference count |
| incremental and concurrent marking | the hooks' barriers mark in small steps beside the turn, and the operator's pool traces the store in the background |
| incremental and concurrent sweeping | the light sweep reclaims at every turn's close, and the judged sweep's placements finish over later closes |
| precise on-heap layout | every hot file declares its entry shape in its own header, so a script knows where each head and field lies. That is what lets the write barrier's trace follow handles without a model |
| conservative on-stack layout | the live turn's reasoning, which no script can read, so anything the conversation names counts as a root |
| collection with and without the stack | mid-turn the collector reclaims nothing the turn names; at the turn's close, with the stack empty, it collects precisely |
| non-incremental, non-concurrent compaction for selected spaces | the cold tier's merges only, under the sweep lock within one turn close; a hot file is never compacted by a script |

**Threading model, read as sessions.** Oilpan heaps are thread-local: an object is allocated, accessed, and reclaimed on one thread, which lets collection run in parallel with mutators on other threads. A reference into another thread's heap, even from one on-heap object to another, goes through a cross-thread root.
A session is the gc's thread. Its dispatch rows, inferences, and tasks are its heap, and another session reaches them only through a cross-session root: an entry promoted into a shared tier (`local-storage.md`, `data-store.md`, `index.md`). The shared tiers are not anyone's thread-local heap, which is why every write to them passes the write barrier and every read passes the read barrier. The one departure, the pour of another session's unpromoted inferences, is in [SKILL.md](SKILL.md).

**Heap partitioning, read as spaces.** Oilpan puts each object in a space: a large-object space for anything over 64 KiB, custom spaces (some marked compactable), and normal page spaces bucketed by size.
- The **normal spaces** are the hot files, bucketed by kind rather than size, one per tier, each budgeted in entries.
- The **large-object space** is the keyspace's `blobs/`, at the same 64 KiB threshold: an entry past it, a poured dispatch record, a legacy attachment.
- The **compactable custom space** is the cold tier, the keyspace's runs or the φ-register's segments. It is the only space any script compacts.

**Precise and conservative.** Oilpan's conservative collection runs while the native stack may hold references, and anything a stack value seems to point at stays alive. That over-retention is the price of not knowing which words are pointers. The precise collection runs at the end of an event loop, when the embedder guarantees the stack is empty.
The gc's event loop is the turn, and its embedder is the plugin's hooks. Mid-turn it reclaims nothing the conversation names. At the Stop hook it collects precisely. An owner's retraction is not the collector's free but an explicit one, and it takes effect at once, so only its reclamation waits for the close.

**Atomic, incremental, concurrent.** Atomic is `/vlds:gc full`: every phase in one stop-the-world pass, the most jank and the least overhead, needing no write barrier because nothing else runs.
Incremental is the hooks' steps between the turn's acts. Concurrent, the default and Oilpan's most common mode, moves the heavy tracing (the pool) and the heavy sweeping (the judged sweep) to the operator, off the session's context, so the mutator spends its context on the work rather than on the collector.

**Marking and handles.** Oilpan marks the root set, then everything transitively reachable through each object's `Trace()`, then clears the weak handles to unreachable objects and runs their callbacks.
To prevent use-after-free it must know every edge in the graph, so every pointer except one on the native stack is a handle (`Persistent<>`, `Member<>`, `WeakMember<>`), and a raw pointer to an on-heap object is an edge it cannot observe.
The gc's handle is textual: the cited entry's head quoted from its opening (at least its first 32 characters, verbatim, anywhere in a field), its fact id, or the owner's words verbatim. A field whose whole value is a verbatim quote of at least 24 characters from within the head also counts. A paraphrase is the raw pointer.
`phi.py trace` follows the head quotes in the hot tier. A fact id is followed by the keyspace, which marks a cold record freed when a tombstone names its id. The owner's words are followed by the barrier's mask.

**Sweeping, pre-finalizers first.** Oilpan invokes pre-finalizers first, while nothing has been reclaimed, and each may touch any other object. Destructors run afterwards, in no order, touching nothing else, and the mutator resumes before all of them have run.
Its README gives the example of X, a client in Y's list, whose destructor is the only thing removing it. Y can walk the list after the mutator resumes and call into a dead X, so X must leave in a pre-finalizer.
In the gc, a free's pre-finalizers are the rewrites and sweeps of every live holder of a handle to what was freed, and they run in the turn of the free. The reclamation, the pour that moves the dead entry's bytes to the cold tier, is the destructor. It runs at a later close, reads only the entry it moves, and is never what detaches a reference.

**Its two notes, transferred whole.**
- *Weak processing runs only when the holder outlives the target.* If both die together, nothing clears the weak edge, and code that assumes it was cleared is wrong. A ledger event citing a freed rule may still read as written, and the read barrier, not its clearing, is what keeps it from steering.
- *Pre-finalizers are heavy.* Every sweep scans all of them, so they stay off frequently allocated objects. The gc owes them only for entries that get cited (rulings, rules, claims, tombstones), never for dispatch rows, logger lines, or a turn's inferences.

**What does not transfer.**
- *Reclamation for reuse.* Oilpan frees memory so it can be allocated again. The gc frees steering: a dead entry stops shaping decisions, and its bytes move to the cold tier, where nothing freed is ever removed. What the gc reclaims for reuse is the next session's recall and context, not storage.
- *Reclamation on the allocating thread.* The pour of another session's unpromoted inferences is the deliberate exception, explained in [SKILL.md](SKILL.md).
- *A program-owned heap.* The owner edits the store by hand, outside every barrier, and a hand edit is a ruling. Oilpan has no mutator the collector cannot see. The gc's answer is the trace at the turn's close, which catches whatever no post-write saw.
- *Exact edges.* Oilpan's graph is exact; the gc's handle test is a text match. It finds every citation written as a handle and no citation written as a paraphrase, which is why the write barrier's allocation discipline forbids paraphrase rather than trying to detect it.

## The Generational Model

Source-code collectors treat object age as a signal; the epistemic heap has three generations with opposite collectability:

| Generation | Store                                                             | Collectability                                                                                              |
| ---------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Gen 0      | The live session context (claims made this conversation)          | Cheapest to re-verify; collected naturally by the conversation moving on — but see the tenuring hazard below |
| Gen 1      | Persisted stores: memory files, the VLDS store's `index.md` and partition files, plan docs, CLAUDE.md directives | The gc's main heap: collected on free, on recall, on completion, and by full audit             |
| Gen 2      | Training data                                                     | Permanently allocated — never collectable, only maskable: tombstones + verification discipline sit in front of it |

**The tenuring hazard**: context summarization is a copying collector for Gen 0 — and it copies garbage as faithfully as live objects.
A stale claim carried forward by a summary arrives in the next window looking fresh, its provenance stripped by the copy.
Treat summary-carried claims as Gen 1 objects with weakened provenance: re-traceable on recall, not pre-trusted.

**The Gen 2 mask**: a training-data assumption cannot be deleted, so collecting it means writing what masks it — a tombstone or verified current fact in Gen 1 that the read barrier finds first.
This is why sweeping without a tombstone fails against Gen 2 garbage: the same prior re-generates the same stale claim, and nothing stands in front of it the next time.

## The Tombstone Schema

`tombstones.md` — in the **VLDS store**, the working directory's `.claude/p4/vlds/` directory resolved by the plugin's memory override ([../../hooks/memory-override.md](../../hooks/memory-override.md)) — is the gc's own store: append-only, user-editable, one entry per free.
The operative shape lives in the file's own header (the canonical form); the block below is the teaching copy, and on divergence the file wins:

```yaml
- freed: [the decision/rule/claim that was disposed]
  time: [YYYY-MM-DD HH:MM]   # local wall-clock at write time; date alone if minutes aren't real
  cause: retraction | superseded | fixed-cause | world-drift
  owner-words: "[the user's actual words, when the free was a retraction or supersession]"
  swept: [the items removed or rewritten with it — every store touched]
  lesson: [what survived compaction — the durable fact worth keeping, if any]
```

Tombstones serve three jobs: they make a sweep **reversible** (a wrongly-collected item can be resurrected from its entry), they make the collector **auditable** (the user reviews what was killed and why), and they **mask Gen 2** (the recorded free outranks the training prior that would otherwise re-learn the same rule).

## The Provenance-Tracing Procedure

Liveness is decided by tracing, never by how plausible the item still sounds:

1. **Find the allocation site** — what created this item: a user ruling, an incident, an observation, an inference?
2. **Find the owner** — which USER decision anchors it. No owner → `UNOWNED`, whatever else is true.
3. **Re-verify the load-bearing cause against the present world** — grep the code, run the check, read the source. The store's own restatement of the cause is not evidence; that is verifying memory against memory.
4. **Check supersession** — scan later rulings for contradiction; the latest user word frees every older one it contradicts.
5. **Walk the references both ways** — what this item derives from (dead upstream → dead here) and what derives from it (a sweep here owes a sweep there).

Two structural biases to trace against:

- **Self-defense at collection time.** The same reasoning that allocated a rule will defend it when audited; provenance-tracing is mechanical precisely to route around that — the chain either reaches a root or it does not.
- **The avoidance-rule blind spot.** A rule that prevents an action is never falsified by use, because it prevents the very runs that would falsify it. The longer an avoidance rule has survived, the LESS that survival means; seniority is not liveness.

## Where Echoes Come From

The dispatch barrier ([SKILL.md](SKILL.md)) exists because an echo is rarely the user repeating themselves; it is the harness re-delivering something already handled:

| Vector | How the echo arrives |
| --- | --- |
| Mid-turn interleave | a user message surfaces alongside a tool result inside a running turn, then appears again as a conversation turn |
| Hook injection | SessionStart / resume hooks re-emit the same resident text every session; system-reminders repeat stored memory verbatim |
| Summary replay | context summarization carries a handled message forward with its handled-ness stripped |
| Task notification | a background result returns on a premise that has since moved |
| Re-paste | the user re-sends a document already diffed against issued fixes |

Summary replay is the dangerous row, and for the same reason the tenuring hazard is: the copy is faithful to content and lossy about status.
A stale claim carried forward merely misleads; a handled message carried forward actively invites the work to be done a second time.

## Cycles and Pressure — Collecting What Grew Into Itself

Per-item tracing has a blind spot the literature already named: **reference counting cannot collect a cycle.**
A cluster whose every inbound reference comes from another member keeps all of them "referenced," so each one audited alone passes — and the procedure above audits them one at a time.
Only asking whether the _cluster_ reaches a live root, rather than whether an item has a referrer, sees the island float free.
That is marking's question, asked from the roots, and it is why the always-on collector traces rather than counts: Oilpan collects an unreachable cycle as a matter of course, because its trace never arrives there.
The gc marks such an island `UNOWNED` and surfaces it, because the sweep of doctrine nobody ruled on is the owner's call. The signals below count toward where to look.

Applied to stored doctrine, that island is a rule patching the previous rule's gap, patched in turn by the next: every link locally justified, the whole anchored to nothing anyone asked for.
It is the one failure the other marks structurally cannot catch, because each member really does have an owner — just a local one.

**Three counted signals**, counted rather than judged for the reason the tracing procedure is mechanical: the reasoning that allocated the complexity will defend it under audit, and that bias operates at structure scope too.

| Signal | Count | Reads as pressure when |
| --- | --- | --- |
| Growth ratio | insertions : deletions across the arc, or the last N changes | growth runs one way — a store that never deletes is accreting, whatever each change was worth |
| Repair fraction | changes repairing the previous changes, against changes serving a new need | a third or more: the collector running more and reclaiming less is thrashing |
| Root distance | hops from a new rule to a user ruling | more than two, and all of them through other doctrine — a cycle candidate |

**It previews. It never sweeps.**
Sorting essential complexity from accidental is `UNOWNED` by the write barrier's own rule — no user ruling covers it — so the output is a dry run: what would be collected, what it would cost, and what the collector is unsure of.

**A pressure signal names suspects, not garbage.**
Trace every candidate to a root before collecting it, and expect some to survive: a structure can be genuinely overgrown _and_ every branch of it still rooted in something the user asked for.
When that happens the collectible target is not the concepts but the **duplication they spawned** — the same fact restated across files, which compacts without losing anything.
Skipping the trace is how a collector eats live objects because a metric looked bad.

**It counts itself.**
The audit is an allocation like any other; if its own footprint grows across passes, that is pressure by its own first signal.

## The φ-Register — Compression and Recall

The store's compression and session-start recall are modeled on the fib/phi-binary machinery of `zeckendorf-prune`: the hot files are an unnormalized φ-register's pour cells, `store/arc/` is the normalized register, and the gc's compaction is the codec's normalization sweep.
The mechanical companion is `scripts/phi.py` (check / verify-merge / verify-pour / lock / rebuild / restore) — it computes and verifies; every judgment stays here, with the gc, in-session. The keyspace below replaces this machinery stage by stage.
The plugin's hooks (`hooks/vlds_hooks.py`) are its mechanical peers: the SessionStart hook hands the recall — and every store operation — to the operator subagent (or injects the recall, one index key away), the prompt hook stamps dispatch rows (naming the session by its short id and its chat title), writes `state: FRESH` when no earlier row resembles the message and names the candidate when one does, pours `dispatch.md` whole-file at a new session's first prompt, the copy named after the session whose rows it holds, and prints the last turn close's report, the pre-write hook asks before a store-named file is written outside a `.claude/p4/vlds/` directory or a persisted entry carries a placeholder `time:` or one later than the latest `now:` by more than a minute, the post-write hook runs `check` after any store write or store-named write, and the Stop hook runs the light sweep (`scripts/normalize.py --light`); the post-write and Stop hooks also run the write barrier's trace (`phi.py trace`); every hook output carries the clock (`now:`) the model copies its stamps from.
The machinery governs **structure only** — what is hot, where history lives, how it parses — never the content of entries; that boundary is the source project's own measured lesson, transferred whole.

**Conventions, pinned once.**
Positions are 1-based over the cache `[1, 2, 3, 5, 8, 13, 21, 34, ...]`: position p has weight `cache[p−1]` and byte capacity `cache[p−1]` KB.
Epoch pairs are `(cache[k], cache[k+1])`; Cassini `b²−ab−a² = (−1)^k` holds under cache indexing and flips sign under any odd shift, so the position-weight numbering is never reused for the epoch check.
Positions are budgeted in KB; hot files are counted in entries; the two are never interchanged.
The register digit string reads highest position first.
A watermark is recorded as `mask=A:B sha=H` — a 0-based, half-open physical line range naming the masked span, plus the span's content hash; both reader and writer share exactly this definition.

**The register.**
At most one live segment per position, `arc/arc-<p>-<seq>.md`; new material pours at position 1; higher positions exist only as merge products.
The index's digit string (`register: 10100100`) is the archived history as a phi-binary numeral — one glance shows '11' debt; a '2' state (two segments at one position) is visible only to the arc listing, which `phi.py check`'s register scan reads.
The capacities are the unique ones under which merges cannot overflow: `cap(j)+cap(j+1)=cap(j+2)` (CARRY, exact) and `2·cap(j)=cap(j+1)+cap(j−2)` (RESOLVE, exact — the worst-case excess equals the residue capacity, zero slack).
A segment is a ```yaml-fenced header (never `---` frontmatter) plus entry blocks delimited by column-0 `---`; each entry block is an `id: xx-NNNN` line, a blank line, then the verbatim body.
The delimiter cannot occur inside a valid entry (headers fenced, continuations indented, offenders poured whole-file), so one mangled entry corrupts only itself and the parse resynchronizes at the next delimiter.

**The normalize sweep** (`/vlds:gc normalize <file | 'register'>`) — gc-owned: the judgment is the collector's, and it runs whenever the check shows the work owed, never held for the user's word.
A sweep takes the session-stamped lock `arc/.sweep-lock` (stale after 60 minutes) before any arc write; without it a session only reports owed work — deterministic naming makes concurrent-sweep collisions certain, so the destructive tail is serialized.
**The light sweep** is the mechanical subset, run by the plugin's Stop hook after every reply (`scripts/normalize.py --light`): the classes decided by rule alone — a hook-poured dispatch record attached to the highest-position live segment with the room, its bytes counted as the check counts them; a virtual entry minted by another session, past its turn by definition, its disposition rewritten to expired and the entry poured; the logger's oldest entries poured when it holds more than its budget, down to three quarters of it so the sweep's own log line does not re-open the debt. Placement is the counter's: the pour total must read Zeckendorf on the register, so the light planner accepts a count only when exactly one position joins the register — one child, byte-checked with its attachments, its parents the positions that leave — trying the target count, then smaller, then larger; a count that would open two positions needs a judged split and is left owed, as is a record no segment can hold. It runs only on a clean register and refuses counter drift; every step goes through the gates below in the frag's own order, a failed gate stops it where it stands, and its one-line report reaches the model through the next prompt hook, a Stop hook's stdout never reaching the model. What needs a score — a spent ruling, a stale claim, a correction whose lesson is doctrine — stays this judged sweep's: the operator's sweep moment scores the cold entries and names them by head line, and the same script's `--pour` form places them with the same single-position rule and gates, naming the counts that would open exactly one position when the named count does not — judgment names, arithmetic places.
The sweep's standing occasion is **pressure and register debt** — `check`'s verdict, injected at session start and after every store write — and the dispatch pour is no longer its act: the prompt hook pours `dispatch.md` whole-file at a new session's first prompt, mechanically, because every entry there is dead by definition (each belongs to a prior conversation) and no judgment is needed on what to pour; the cold spans in the other hot files are scored, not counted, so they stay the sweep's.
The hook keys on the store's `.sessions` ledger (one line per session id that has submitted a prompt, or was recorded by the SessionStart index hook on a resume, fork, or compact): a RESUME's id is already there and pours nothing — a resumed conversation's dispatch entries are its own live barrier state — a FORK's new id is recorded before its first prompt (the forked conversation is live, and so are its rows), and a transient `SessionStart` firing never submits a prompt, so it never pours. The hook honours the sweep lock — a fresh lock held by another session skips that session's pour, and the rows stay hot until the next new session or an in-session sweep — and its copy is sha-verified before the reseed.
Concurrent sessions share the one dispatcher: the barrier matches on fingerprints, so interleaved entries are tolerated, and a simultaneous append can lose an entry — the accepted cost of one shared file; a session that predates the ledger pours once on its first prompt after the hook lands, and the barrier's FRESH default makes that recoverable.

_Pour._ Entry-level: cold spans (pre-session logger entries, SPENT/FREED ruling bodies whose tombstones exist, expired virtual entries) copy verbatim into position-1 segments, chunked at entry boundaries so no segment exceeds capacity, oldest first; a hook-poured dispatch record (`arc/dispatch-<stamp>-<session>.md`, byte-identical to the file it replaced) is registered by the sweep as a position attachment, or carved entry-level into segments when the sweep judges that worth doing.
A poured body that is ALREADY tombstoned gets its segment id line annotated — `id: xx-NNNN (tombstoned)` — so the owed-BORROW scan can tell archived history from a lurking free: the tombstone says freed, the annotation says archived-not-steering, and only the pair together retires the '-1' state (annotating an id changes the segment body, so the `verified:` sha restamps with it).
A SPENT ruling without a tombstone stays hot deliberately — an anti-citation warning until a gc pass tombstones it.
Grammar gate at pour time: an entry containing a column-0 `---` or a code fence is poured whole-file or escaped by a recorded one-level indent; partition entries are bare in both places — the header's shape fence is a file's only fence — and a segment's `fenced: yaml` flag remains only on legacy pours from the fenced-body era.
The gate fires on CARVE extraction too: when lifting entries out of a fenced-era hot file, region delimiters are not entry content — check region boundaries, not just entry starts, because a splitter that misses this over-captures the region's close fence into a segment body and leaves the hot file's region unclosed in the same stroke (two defects, one miss — caught live in a peer store's bootstrap).
Whole-file: a file that cannot pour entry-level — a legacy per-session dispatch record from the pre-0.0.18 design, a hook-poured dispatch record, or any grammar offender — moves whole into `arc/` under its own name as a position **attachment** (`attached:` in the index row; merges move attachments to the child's row mechanically); a legacy record byte-identical to its seed is deleted after verification, not poured.
A poured span is trimmed from the hot file only after `phi.py` verifies the verbatim arc copy — this and merge-parent deletion are the design's two script-verified deletions.
A span poured but not yet trimmed is masked by a **watermark**: the `mask=A:B sha=H` line range plus content hash, recorded at pour time (`phi.py verify-pour` is the trim gate).
**Masked-span content remains authoritative until trimmed**: a hash mismatch means the user ruled there — `check` reports "watermark voided", and the gc must re-read, re-pour, and tombstone what the edit freed before the arc copy may be cited again.

_Rules._ The codec's three violation classes are the complete set of rules a sweep may apply — they are what normalization can do, not when it runs (pressure, below, is the when — a separate, admittedly conventional signal):

| Rule | Fires on | Action |
| --- | --- | --- |
| BORROW | a retraction/free reaching archived content — an event, raised by judgment or by check #8, never visible to the register scan | the subtraction pipeline: locate the fact by id (canonical AND residue entries carry ids), carve in place, tombstone LAST, re-settle from that position; lineage is audit trail, never a reconstruction source |
| RESOLVE | two live segments at one position j | `2·w(j) = w(j+1) + w(j−2)`: child at j+1, byte-mandated residue at j−2 — if the deduped child exceeds capacity, at least the excess must displace, and worst-case it exactly fits; a double at position 1 promotes whole (1+1=2, zero residue); a double at position 2 resolves to child at 3 plus residue at position 1 (2×2 = 3+1) |
| CARRY | positions j and j+1 both occupied | merge into j+2 — byte-exact before dedup even begins |

Priority **BORROW → RESOLVE → CARRY** transfers verbatim from the codec's check sequence; in the codec it is outcome-neutral scheduling, here it is doctrine — retractions outrank compaction because store merges, unlike codec carries, are costly to invert.
Merge mechanics: concatenate parents, dedupe exact duplicates into `## canonical`, everything displaced verbatim into `## residue`, ids on every entry, header records `merged-from`, `pours` (pour-count conservation), per-source spans.

_Commit protocol_ (the codec's steps are atomic; the store's are not): write child → `phi.py verify-merge` → mark the child `verified:` (**the commit point**) → delete parents → update index → watermark last.
Recall treats an unverified child as nonexistent and its parents as live; an arc file absent from the index is a torn pour — delete it and re-sweep; duplicate fact-ids resolve in favor of the file the index lists; an un-tombstoned carve is treated as never having happened.
Between-step crashes leave readable '2'/'11' debt — debt is not corruption, and recall never blocks on it.

_Selection._ What stays hot in a partition tail is judged, never scored on a grid: the operator's sweep moment names the cold entries by head line against the rules above — every `status: LIVE` ruling, every ledger `correction` of the last two days, and every claim a live ruling leans on stay; placing what it names is mechanical. The 0..54 score grid and `phi.py mask` are retired: a rule against adjacent keeps belongs to the codec, not to a store.
Every rule application is logged in the codec's own `{rule, sources, targets}` shape; sweep totals (n_in / n_kept / n_merged / bytes before→after) go to `logger.md` and count against its budget — loss measured, never silent.

_Pressure._ A hot row reads `pressure: owed` when live/at-sweep ≥ φ ≈ 1.618 or bytes exceed budget — the φ-register's **own** pressure signal, an addition beside (never a rewrite of) this file's commit-scoped growth-ratio signal above, which serves a different consumer (the doctrine-cycle test); φ here is a convention fitting the pair's natural growth rate, not a property inherited from the machinery.
Amortization, measured by simulation: position k merges roughly once per φ^(k+1) ≈ 1.4·F(k) pours; one pour cascades at most O(register width) = O(log_φ total pours) steps.

**Recall.**
A fresh session reads `phi-index.md` whole, then the hot files it lists — every item still through the read barrier: the register narrows WHAT is read, never HOW it is judged — and the reader is the operator subagent, not the session itself; the writer of every entry the session owes is the record script (`scripts/record.py`), which applies the turn's record the session composes — upsert by head, each block in its file's shape, the rows completed, the check run — and prints the close derivation, so no model is spent on a close.
The SessionStart index hook prints a digest of the index, the recall mode and read list, a one-line digest — entries, bytes, last headline — per hot file, the owner voice, `check`'s verdict, and the directive under which the model, at its first prompt, derives the prompt's task in one line and launches the operator — once per session, continued by message for every moment after, re-reading before it writes — (`hooks/operator-prompt.md` is its brief, `hooks/pool-prompt.md` the pool's; the prompt hook's first-prompt line repeats the ask). The operator reads the index and every file under `inject:` and `digest:` whole in its own disposable context, passes each entry through the read barrier, and returns one pooled response scoped to the derived task — what steers it, what stands whatever the task, what is open, what was surfaced and not applied, what to read on demand — at most 8,000 characters, which the session pulls into its context in place of the files; it also writes `store/recall-pool.md`, session-named, which the index hook re-injects on a compact. The hot files themselves cost the session nothing: when the pool's line on an entry is not enough to steer, the session asks the operator for the entry rather than opening the file. `pool: inject` in the index's `## recall` section restores the slot injection: the `inject:` files split at entry boundaries into chunks, one slot hook printing each under the harness's 10,000-character per-hook cap, a marker line for a single entry over the cap or a chunk beyond the registered slots (twelve); `operator-model:` names the operator's model. On `source` resume, fork, or compact the index hook records the session id in `.sessions` and prints only the digest lines and the verdict, since the conversation holds its own recall, and the slots print nothing. The section is a ruling like the rest of the index: edit it to change what arrives and how.
Never read at start, by session or subagent: `arc/` and masked (watermarked) spans.
Hot budgets (entries): logger 34, data-store 34, ledger 21, local-storage 21, tombstones 21, virtual 13, session-storage 13, index rows 21; `dispatch.md` is unbudgeted (the floor) — the prompt hook pours it whole-file at a new session's first prompt anyway, and the ratio scan skips it.
On a miss: fact-id grep across segment headers and canonical blocks (O(log_φ) files), or largest-first descent; spans are per-source in headers, so time-anchored queries resolve per (source, time) pair.
Fact-id uniqueness — one id in one live canonical block — is enforced by merge dedupe and verified by scan: the store's **analog of**, not an instance of, Zeckendorf uniqueness.
Archive-read entries arrive as weakened-provenance Gen 1 objects, re-traced before steering.
Pressure is recomputed at recall by `phi.py check` (the stored pair updates only at sweep) — no per-append write obligation exists; the post-write hook re-runs `check` after every store write and hands back its verdict — whole when it changed, one line when it did not, so a turn of writes does not re-paste the same debt list into the context — and the light sweep at the turn's close settles what rule alone can settle, so pressure and debt are seen as they arise and the mechanical share of them never waits.

**The index** (`phi-index.md`).
Derived — recomputable from segment headers and store grammar — but **an edit to it is a ruling**: `rebuild` is corruption recovery only, refuses to run over a voided watermark, and a user-removed watermark is an un-mask order the gc executes before any rebuild.
Sections: `register` (the digit string); `positions` (weight, bytes, pours, spans, attachments — one recurrence check against the filename's independent witness plus conservation checks, labeled as such); `hot` (live, at-sweep, bytes, budget, watermark, pressure); `epochs` (table columns `| file | k | a | b |`, one row per swept file with a=cache[k], b=cache[k+1] — checked by Cassini **plus row-to-row continuity**: corruption falls off the Fibonacci lattice, skips break the chain); `recall` (two bare lines, not a table: `inject: a.md, b.md` and `digest: c.md` — comma-separated file names; a missing section or key falls back to the hooks' defaults, and the index hook says which it used); `updated` (time, session, command).
Archive names derive from position and epoch — no timestamps, so the historical same-second archive collision is structurally absent.

**What deliberately does not transfer.**
The conserved value functional — the axiom itself: no store quantity satisfies `F(k)+F(k+1)=F(k+2)` exactly (dedup shrinks bytes), so the rules transfer as procedures, not equations, and confluence, unique normal form, and free self-correction do NOT follow — placement and uniqueness are enforced by the scans and this doctrine instead.
Codec self-correction (the store never auto-repairs — deliberately); negative-state scannability (check #8 compensates); bit-level coding of content (it would destroy user-editability); continuous quantization (only the 0..54 grid transfers); matrix algebra as computation (the pair is bookkeeping, and no consumer composes indices); the measured 32% detection rate (the honesty transfers, the number does not).
`phi.py check`'s coverage is structural only — placement, un-run carries, broken streams, counter drift, verbatim duplication, voided watermarks, owed borrows, store-shaped files outside the store (`[STRAY]`, to depth 2 under the project root — reported, never moved); paraphrase duplication, mis-scores, wrong deadness calls, and semantic staleness remain the read barrier's, this collector's, and the inspector's.

## The Keyspace — IndexedDB's Indexing, in Place of the φ-Register

The φ-register places what leaves the hot files by arithmetic, and the arithmetic owes debt no judgment created: a count that opens two positions is refused, an attachment waits for room, a sweep is held for a count.
The keyspace (`scripts/idb.py`) indexes the same tier the way Chromium's IndexedDB indexes its records — one sorted keyspace, versions validated at read, a sweeper for what goes stale, a journal around every multi-step write, compaction when due — in plain text, and it places any count.
The register of active context does not move: the hot files, `phi.py barrier`, `pool` and `standing`, `recall-pool.md` and the index's `## recall` section read exactly as before; what moves is everything that leaves the hot files.

**Stages.** `index-engine:` in the index's `## recall` section, a ruling like the rest of it: `phi` (the φ-register runs — the stage a store names to stay on it), `idb-control` (φ runs; each turn close adds a shadow migration's verdict and writes nothing), `idb-new-stores` (a store with no φ trace starts on the keyspace), `idb-migrate-gentle` (the default: a new store starts on the keyspace, and a φ store migrates at a turn close once its φ check is clean — announced at SessionStart, reported at the next prompt), `idb` (the same; the stage at which the φ code paths retire, once every store in use reads `engine: idb` at SessionStart — until then they stay, for a store whose migration waits and for a rollback to return to).
A store with `idb/keys.tsv` is on the keyspace whatever the setting says, and `idb.py rollback` is the one way back; it writes `index-engine: phi`, so the default does not migrate the store again.

**The layout.** `store/idb/keys.tsv` — one line per key, `<object store> TAB <type> TAB <key> TAB <field=value> …`, sorted by plain byte order so `LC_ALL=C sort -c` verifies it and no comparator is carried; derived, rebuildable (`idb.py sync --full`), never a ruling.
Each hot file is an object store; a record's key is `<time>|<sha8 of the head line>` (`#2` for a repeat), derived, so the hot files carry nothing new — a continuation edit is an update, a head rewrite a delete and an insert.
Types: `00` metadata (the store's schema, run counter, clocks, migration marker; an object store's `last-version` and `key-generator`); `01` a record (`v=`, `sha=`, `at=hot:<line>` or `at=runs/<run>:<line>`, and on a cold record `id=`, `state=live|freed`, `ts=`); `03` an external object; `30:by-kind` and up the user indexes — by-kind (the standing set), by-status, by-owner-words (the barrier's same-words mask as a join), by-source (the UNOWNED call on a claim), by-session, by-fact-id.
`runs/` holds the cold tier — immutable sorted files, one per pour or compaction, each entry an `id:` line, a `key:` line and the verbatim body (a segment's grammar with one line more); `blobs/` holds external objects — dispatch records poured whole, legacy attachments, and any entry past 64 KiB, its run entry a wrap marker; `journal.tsv` holds the intents still open.

**Versions and the sweep.** A sync re-derives the hot tier: an unchanged block keeps its version, a changed one takes its object store's `last-version + 1` and fresh index lines, a vanished one drops.
An index line is live only while its version equals the record's — LevelDB's lazy index deletion — and the sync's rewrite drops every line that is not: Chromium's tombstone sweeper, folded into the rewrite.
A reader never writes: a line it finds stale is skipped, a hot hint that moved is re-found by sha, and a block edited since the last sync is read from the hot file, which rules — the owner's hand edit is a ruling the index catches one entry at a time, where the φ-register's watermark caught it only inside a poured span.
The sync runs in rounds: past its budget the next object store waits for the next pass, at the sweep cursor.

**The pour.** Two-phase, journaled: the expiry rewrite first (so the run says why an entry left), journal `pending`, the run written, the verify-pour gate (every block verbatim in its run), the keyspace committed — the commit point, records pointing at the run, ids minted from the object store's key generator — journal `committed`, the hot file trimmed, journal `done`.
A crash before the commit leaves a run nothing names, which the next pass discards; a crash after it leaves the trim owed, which the next pass finishes — and a block the owner edited in between keeps the edit, its cold record dropped and the run keeping the old text as history.
The dispatch pour runs in the prompt hook, which holds no lock: its copy lands in `blobs/dispatch/` between a `pending` and a `committed` journal line, and a pending copy older than ten minutes whose rows `dispatch.md` still holds is removed, since the reseed never happened.
The light classes are the φ-register's — another session's virtual entries expired and poured, the logger past its budget poured down to three quarters — at any count; the judged pour is the sweep moment's naming, placed by `idb.py pour`.

**The free.** A cold record's state is derived at every pass from every tombstone, hot or cold — the barrier's own rule (the same owner-words, or a head within its `freed:`), an id a tombstone's `freed:` or `swept:` names, or the φ era's `(tombstoned)` annotation — and a freed record carries the tombstone's key in `ts=`.
Nothing freed is ever removed from a run: the marker is the whole of the free, a cold read surfaces a freed entry instead of applying it, and a tombstone removed un-frees what it masked. This replaces BORROW and the owed-borrow state.

**Compaction.** An object store's small runs (under 64 KiB) merge once four exist, or two once `earliest-compaction` has passed (the next set 1–3 days out, jittered per store): every entry kept verbatim — a key held twice as history stays twice, only exact duplicates collapse — sorted, split at entry boundaries past 64 KiB, verify-merge before the commit, the parents deleted after it. This replaces RESOLVE and CARRY.

**Migration.** Gentle, at a turn close: refused while an open watermark, a φ check that reports corruption, or too little disk (2.5× the archive) stands — said once, the φ sweep running meanwhile; otherwise every segment entry is imported verbatim under its own id, every attachment and unregistered file byte for byte, all verified before the commit (the rename of `idb.tmp/` to `idb/`), then the φ index saved into `arc/`, `arc/` moved aside to `arc.phi-retired/` (kept until the owner removes it by hand — no script deletes it, and the rollback returns from it, so its removal gives the rollback up), and the index rewritten — the register, positions and epochs retired, the hot table, its budget column and `## recall` kept. Each step after the commit is idempotent, and the keyspace's next pass finishes one a crash interrupted.
`idb.py rollback` undoes a migration at any point — every entry poured since back in its hot file verbatim (the φ sweep pours it again), `arc/` back, the φ index back with the current `## recall` section and budgets and `index-engine: phi`, every dispatch record poured since moved into `arc/`, any history the runs hold kept there too — planned under the lock, resumable after a crash (the keyspace's own passes wait while one is mid-way), and refused only when an archived entry was edited in the keyspace since, which the returning arc would lose, or a dispatch pour is in flight.

**The check.** `phi.py check` hands a keyspace store to `idb.py check`: the keyspace sorted and readable, every counter at least its records' versions, every cold record's run present and its text at its sha (a hand edit there a note — a ruling), stale index lines and open intents as debt, every blob present, unregistered files, one id to one record, a migration's leftovers — plus the store-level scans this check keeps, which run as they always did: duplication, liveness, conformance, strays, the hot budgets, and the φ pressure ratio (live/at-sweep ≥ φ), a convention on hot files that outlives the register.
Its coverage is structural, as the φ check's was: the keyspace makes the cold tier addressable by key and every change detectable per entry, and adds no judgment — what is cold, stale or spent stays the gc's.

## The Archive — the Hot Tier Poured Whole

The sweep pours what is cold and keeps the roots.
The archive (`/vlds:gc archive`) pours everything, roots included, so a new session starts on an empty hot tier and the store's past reaches it only through `/vlds:recall`.
Its exempt set is empty: every entry of every hot object store pours — rulings, index rules, claims, the ledger, the tombstones, inferences, tasks, briefs and the logger.

**What an archived LIVE ruling means for the roots.** A root is a LIVE ruling or standing rule the read barrier finds in a hot file. A poured ruling keeps `state=live` in the keyspace, but nothing marks from the cold tier, so it stops steering the moment the archive commits: the SessionStart standing block prints nothing, the pool reads nothing, and the next session's roots are the world as it verifies now and the live turn alone. Every entry that held a handle to it is archived with it, so no hot handle points into the cold tier, and the handles between cold entries stay valid by fact id. A recalled ruling is weakened provenance with no hot root to trace to: the owner ruling it live again — a new `local-storage.md` ruling citing its id — becomes its root, and until then it is shown, never followed.

**An archive is not a free.** A free masks what it freed for good: a tombstone, `state=freed` in the keyspace, the read barrier surfacing it at every recall, the write barrier catching it written again, and pre-finalizers owed for every live holder in the turn of the free. The archive takes no word back, so it writes no tombstone, owes no pre-finalizer and frees nothing: each poured record keeps the state the tombstones give it — `live`, or `freed` where a tombstone already masked it — and a recall returns a live cold entry as something the owner may rule live again and a freed one as surfaced, never applied. A free says the entry is dead; the archive says only that it is no longer in front of the session.

**The tombstones go cold too, and the masks survive it.** With nothing exempt, `tombstones.md` pours with the rest. The keyspace keeps every free, because `mark_freed` derives a cold record's state from every tombstone, hot or cold, so a recall still surfaces a freed entry as freed. The hot tier's barriers keep them as well: on a keyspace store `phi.py`'s `tombstone_masks` adds the keyspace's cold tombstones to the hot ones (`cold_tombstone_masks`, read through `idb.py`'s validated reader), so after an archive the read barrier still marks a hot entry a cold tombstone masks FREED, and the write-barrier trace still flags freed garbage written again, naming the tombstone by its id.

**When it runs, and what it leaves.** Only on the owner's explicit `/vlds:gc archive` — never on the collector's initiative and never inside a sweep, since it moves every entry the owner wrote. Only on the keyspace (`engine: idb`); a φ store is refused until it migrates. `dispatch.md` is not an object store and stays — it is the running session's dispatcher, poured at the next session's first prompt as always — and `phi-index.md`, `recall-pool.md` and the base memories (`MEMORY.md` and its files) are untouched. The one hot entry the archive leaves is its own `[gc]` line in the emptied logger. The running session still holds its pool and its standing rules in context, and `recall-pool.md` still names the entries the archive moved, so a compact before the next session re-injects a pool of cold entries: the archive frees steering for the next session, and a new session after it is what starts on the empty hot tier.

**The mechanism.** `idb.py archive --session <id> --now <now> [--dry]` names every entry head of every hot object store and places them through the judged pour's own path under the sweep lock — two-phase and journaled, the verify-pour gate, one run per object store, ids minted, the hot files trimmed to their headers — then logs the move and rewrites the index's hot table; `--dry` prints the count per object store and writes nothing. `idb.py pour` refuses a root — a `local-storage.md` or `index.md` entry the read barrier reads LIVE — unless `--archive` is passed, so a sweep's naming never pours a LIVE ruling by mistake, and the archive is the one caller that passes it.

## Composing With the Other Instruments

- **Gate** — the gate stamps a claim's status now; the gc governs how long a stamp stays good. A recalled `CONFIRMED` whose verification has aged re-enters as `PENDING`: verification decays, and the gc's read barrier is where the decay is noticed. The gate's `source_type: training` is the gc's Gen 2, met at claim scope.
- **Guide** — the guide's `hit` is a read from the rule heap, so every hit passes the gc's read barrier before it is applied: a hit on a freed rule is exactly a use-after-free with good intentions. The guide's ledger records the liveness call beside the reuse it justified.
- **Inspector** — a contested liveness call (the trace is ambiguous, or the sweep is consequential) escalates to the inspector's independent eyes before anything is deleted.
- **Looper** — the gc is always on, so the looper does not carry its triggers. Its cycle runs in the hooks and the operator whether or not the loop opens. The looper reads what the cycle already marked: the dispatch barrier's state before the loop opens, the read barrier's marks on whatever stored state the request leans on, and any `gc:` line the write barrier raised. It applies the gc's procedure inline only where a judgment is owed, such as the transitive sweep and its pre-finalizers the moment a turn contains a retraction.

## The Honest Limit

The collector runs on the same substrate that allocated the garbage, and a bias that planted a rule can defend it under audit.
Mechanical tracing narrows that gap; the tombstone record hands the user the final audit; and the inspector supplies the outside eye on contested sweeps.
The floor rises; the ceiling stays where it is — a gc pass raises the odds that stored state is live, and manufactures no certainty that it is.
