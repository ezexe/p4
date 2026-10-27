# Design brief — the gc, always on, modeled on Oilpan (cppgc)

**Status:** built and tested. The open points in section 7 are the owner's to rule, and none of them blocks the build.
**Filed:** 2026-10-07.
**Subject plugin:** `lbiza/plugins/vlds` at 0.0.44, built as 0.0.45.
**Source:** V8 `main`, `include/cppgc/README.md` ("Oilpan: C++ Garbage Collection"), read whole from the GitHub mirror (`raw.githubusercontent.com/v8/v8/main/include/cppgc/README.md`) on the filing date. `chromium.googlesource.com` was refused by the filing environment's network policy.

---

## 1. The ask, as read

> remodel the vlds gc to always on and based on `https://chromium.googlesource.com/v8/v8/+/main/include/cppgc/README.md`

The ask has two parts:

- **Always on.** In this repository's vocabulary, an always-on layer is one injected at every SessionStart (the memory override's "(always active)" block, src-fragger's contract) rather than one waiting to be invoked. Before this change, the gc was a direct-invoke skill (`disable-model-invocation: true`), and its triggers lived in the looper and in the memory override's table. The hooks already did much of its mechanical work, but nothing framed that work as one collector running every turn.
- **Based on the README.** The remodel takes Oilpan's model as the gc's own: trace-based mark-and-sweep, its threading model, its spaces, precise against conservative collection, its three modes, its three marking steps and its handles, its two sweeping steps and its two notes. Each mechanism the README names gets a counterpart, or a stated reason it does not transfer (section 6).

## 2. The gc before

- **A skill with eight numbered triggers**: on free, on recall, on dispatch, on completion, full collection, on pressure, on normalize, and at the turn's close. The skill was direct-invoke only. The looper carried its triggers, because a direct-invoke skill's `when_to_use` is inert.
- **Hooks that already did the mechanical halves**: the dispatch barrier (prompt hook), the read barrier's stamps (`phi.py barrier`, through the pool), the check after every store write (post-write hook), and the light sweep (Stop hook).
- **Gaps that Oilpan's model names:**
  - *No write barrier that traces.* A new entry that a tombstone already masked was found only when a later recall read it as FREED. That is the "same garbage re-learned" that tombstones exist to prevent, caught after it steered rather than when it was written.
  - *No mechanical reach for a free.* "Update every inbound reference transitively" was entirely judged. The one verification the doctrine named, Example 1's "grep the stores for the old rule's phrasing", was a step the operator had to remember.
  - *No timing for inbound references.* The doctrine said to sweep transitively, but not that the sweep must land before the next turn. A citation left for the eventual pour to clean up is exactly the README's X-in-Y's-list use-after-free.
  - *Liveness asked of items one at a time.* The pressure audit noted that reference counting cannot collect a cycle, but the per-item read barrier still asked "does this have an owner?" rather than "does marking reach it?".

## 3. What the README says (paraphrased)

- **Key properties.** Oilpan is trace-based. Marking and sweeping are both incremental and concurrent. On-heap layout is precise and on-stack layout is conservative. It can collect with or without considering the stack. Compaction is non-incremental and non-concurrent, and applies only to selected spaces.
- **Threading model.** Heaps are thread-local, and an object is reclaimed on the thread that allocated it. A reference into another thread's heap goes through a cross-thread root, even from one on-heap object to another.
- **Heap partitioning.** Objects over 64 KiB go to a large-object space. An object may be assigned to a custom space, and a custom space may be marked compactable. Everything else goes to normal page spaces bucketed by size.
- **Precise and conservative.** A conservative collection runs while the native stack is not empty. It treats stack values as roots, keeping alive anything a value seems to point at. A precise collection runs at the end of an event loop, when the embedder guarantees the stack is empty.
- **Modes.** Atomic is stop-the-world: the most jank, but the most efficient, with no write barriers needed. Incremental interleaves steps with the mutator, needs write barriers, and ends in a short atomic pause. Concurrent is incremental with work moved to background threads, and it is the most common mode.
- **Marking.**
  1. Mark the roots.
  2. Mark transitively through `Trace()`.
  3. Clear weak handles to unreachable objects and run weak callbacks.

  Incrementally, step 1 runs in a short pause, step 2 interleaves with the mutator, and a final pause finishes step 2 and runs step 3. Every edge must be a handle (`Persistent`, `Member`, `WeakMember`), because a raw pointer to an on-heap object is an edge the collector cannot see, which causes use-after-free.
- **Sweeping.**
  1. Pre-finalizers run first, before any reclamation, and may touch other objects.
  2. Destructors run next, in no order, and must not touch other on-heap objects.

  The mutator resumes before every destructor has run. The X/Y client-list example shows why removal from a list belongs in a pre-finalizer. Destructors run on the allocating thread.
- **Notes.** Weak processing runs only when the holder outlives the target. Pre-finalizers are heavy and should not be put on frequently created objects.

## 4. The remodel

| Oilpan | The gc, always on | Where |
| --- | --- | --- |
| the embedder's platform schedules collection | the plugin's hooks run the cycle every turn; this session is the mutator | `hooks/hooks.json` |
| root marking in a short pause | SessionStart prints the standing rules whole, the index digest, and the verdict | existing hooks; `hooks/gc-contract.md` names the phase |
| concurrent marking on background threads | the operator and its pool children trace the store in the background | existing pool road |
| incremental marking | the dispatch barrier at every prompt, and the read barrier at every recall | existing |
| the write barrier | the check, then **`phi.py trace`**, after every store write | **new**: `scripts/phi.py` `gc_trace`, `hooks/vlds_hooks.py` post-write |
| the final marking pause | the trace once more at the turn's close, for writes no post-write saw | **new**: `hooks/vlds_hooks.py` turn-close |
| precise collection at the end of an event loop | the light sweep at the Stop hook; nothing reclaimed mid-turn | existing; doctrine names it |
| conservative collection | mid-turn, anything the conversation names is a root | doctrine |
| `Persistent` / `Member` / `WeakMember` / raw pointer | roots / handles / history that cites / a paraphrase | doctrine; `cites()` makes "handle" mechanical |
| pre-finalizers, then destructors | holders rewritten or swept in the turn of the free, then the pour at a later close | doctrine; the trace names the holders |
| spaces | hot files (normal spaces), `idb/blobs/` (large objects, 64 KiB), the cold tier (compactable) | doctrine |
| thread-local heaps, cross-thread roots | session-local heaps, cross-session roots through promotion | doctrine |
| atomic collection | `/vlds:gc full` | skill |

**Always on, concretely.**
- `hooks/gc-contract.md` ("## VLDS gc (always on)") is injected by its own SessionStart output (`session-open.sh --gc`), under the hook-output cap.
- The skill drops `disable-model-invocation`, so the model can load the doctrine when a phase reaches a judgment. Its `when_to_use` says the cycle runs without it.
- The looper no longer carries the gc's triggers. It reads what the cycle marked.

**The trace** (`phi.py trace`, `gc_trace`):
- `store/.gc-heads` is the remembered set: each hot file's head lines, by sha, with a repeat counted `#n` (the keyspace's rule). A head new since the last trace is an allocation.
- **Re-allocated** means a new entry in a steering file (`local-storage`, `index`, `data-store`, `virtual`) that a tombstone masks and that is dated no earlier than the free. An entry older than the free is freed history returning (a rollback, a paste), and it is not reported.
- **A free's reach** means a new tombstone listed with the strong-file entries it masks and with the LIVE entries holding a handle to them. A handle is the cited head's first 32 characters verbatim in a field, or a field that is wholly a verbatim quote of at least 24 characters from within it. Holders in the weak files (`ledger`, `logger`, `briefs`) are counted, never owed.
- The first trace on a store is a silent baseline. Findings print one `gc:` line each, capped at eight. The trace never writes to a hot file.

## 5. Built

- `scripts/phi.py`: `trace` (`gc_trace`, `trace_lines`, `cites`, `allocated_after`, `head_keys`, `.gc-heads`).
- `hooks/vlds_hooks.py`: post-write appends the trace's lines to its context, and turn-close runs the trace before the engine's pass.
- `hooks/gc-contract.md` and `hooks/session-open.sh --gc`, registered in `hooks/hooks.json`.
- `skills/gc/SKILL.md` rewritten, with an Oilpan section in `skills/gc/reference.md` and Example 4 (the pre-finalizer) in `skills/gc/examples.md`.
- `hooks/operator-prompt.md`: a retraction's step names its sweep as the free's pre-finalizers, owed in that moment, with the write barrier's `gc:` line naming the holders still left.
- The README, the looper, the memory override's resources line, the manifests, and the two roboto passages that called the gc direct-invoke.
- `scripts/test_hooks.py`: `test_gc_trace`, covering the baseline, a free's reach and its holder, silence on nothing new, re-allocation against old-dated history, the close catching a hand edit, an out-of-tier free, `--dry`, the always-on block under the cap and registered, and the skill no longer direct-invoke.

## 6. What does not transfer

- **Reclamation for reuse.** The gc frees steering, not storage. Bytes move to the cold tier, where nothing freed is ever removed.
- **Reclamation on the allocating thread.** Another session's unpromoted inferences are poured by this session's close. A session that ended never closes again, and the rule is sound only because promotion happens before a turn ends.
- **A heap only the program writes.** The owner's hand edit bypasses every barrier and is a ruling. The close's trace is the answer: it catches what no post-write saw.
- **Exact edges.** The handle test is a text match, so a paraphrase is invisible to it. The allocation discipline forbids paraphrase rather than trying to detect it.

## 7. Open points for the owner

1. **The skill is model-invocable now.** The always-on block works whichever way this is set. Restoring `disable-model-invocation: true` would keep the looper as the plugin's only auto-surfacing skill, and the test's last assertion would go with it.
2. **The cross-session inference pour.** It is kept as built. A stricter Oilpan reading would pour another session's inferences only once that session has been silent for some horizon. That would be a behavior change in `normalize.py` and `idb.py`, and is not made here.
3. **Report or refuse a re-allocation.** The trace reports, and `record.py` still writes. Refusing in `record.py` would stop a re-learned rule before it lands, but it would also block an owner who rules the same thing again after a free. That case needs the owner's word, which no script has.
4. **The handle's 32 characters.** This is a convention, chosen above the barrier's 24-character mask so that a shared opening clause between two different rules is less likely to read as a citation.
