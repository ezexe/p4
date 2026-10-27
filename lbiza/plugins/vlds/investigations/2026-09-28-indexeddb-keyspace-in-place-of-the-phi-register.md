# Design brief — an IndexedDB keyspace in place of the φ-register

**Status:** built, tested and ruled. The rulings of section 8 are applied, the rename declined at the final stage; the four final-stage rulings of section 10.5 are ruled as recommended and applied (section 10.6): the default stage is `idb-migrate-gentle`, and the φ code retires in a follow-up. How the branch lands on `main` stays the owner's word.
**Filed:** 2026-09-28; the build recorded 2026-09-29 (section 10), the final stage ruled the same day (section 10.6).
**Subject plugin:** `lbiza/plugins/vlds` at 0.0.42, built as 0.0.43, ruled as 0.0.44.
**Sources:** Chromium `main` at 156.0.8077.0, read file by file from the GitHub mirror (`raw.githubusercontent.com/chromium/chromium/main/…`) on the filing date. `chromium.googlesource.com` was refused by the filing environment's network policy. Appendix A names the file behind every Chromium fact; VLDS facts cite the plugin's own files.

---

## 1. The ask, as read

> keep the register of active context the same as it is but index through that system instead of the current phi register system

Two registers are in play, and this brief keeps them apart:

- **The register of active context** is what a session can have in context: the hot files, the read barrier's `<file>:<line>` rows and their states, and the pool built from them (`phi.py barrier | pool | standing`, `recall-pool.md`, the `## recall` settings). It is **kept byte-identical** (section 4).
- **The φ-register** is how everything that leaves the hot files is placed and found: `phi-index.md`'s digit string, positions and epochs, `arc/` segments at Fibonacci capacities, the Zeckendorf pour counter, BORROW → RESOLVE → CARRY, watermarks and attachments. It is **replaced** by the model Chromium's IndexedDB uses to index its data (section 5).

"Unready" is read as the φ-register not being ready to carry the archive for the long term. Section 2.2 lists the debt it produces by arithmetic alone.

## 2. The φ-register today

### 2.1 What it does

| Job | Mechanism | Where |
| --- | --- | --- |
| place | a pour lands at the one position that `Zeckendorf(total pours)` opens; capacities are `CACHE[p−1]` KB | `normalize.py` `plan_light`, `plan_pours` |
| find | `phi-index.md` positions table; a miss greps fact-ids across segment headers | `skills/gc/reference.md` "Recall" |
| compact | BORROW → RESOLVE → CARRY, merges gated by `verify-merge` | `skills/gc/reference.md` "Rules" |
| protect | the sweep lock, `verified:` commit marks, watermarks `mask=A:B sha=H`, `verify-pour` | `phi.py` |
| verify | eleven structural scans, among them register debt, the positions cross-check, Cassini epochs, owed borrows and voided watermarks | `phi.py check` |

### 2.2 Debt that exists only because of the arithmetic

Every line below is owed work that no judgment created. It exists because a Fibonacci placement rule refused a move:

- `register '2'` / `register '11'`: a RESOLVE or CARRY is owed (`phi.py check`, scan 1).
- "no pour count from this register opens exactly one position with the room — the judged sweep places it" (`normalize.py` `plan_light`).
- "`k` pours would open `n` positions — counts that open exactly one: […]; name that many entries" (`plan_pours`). This one bends judgment to arithmetic: the operator must change *which entries it calls cold* until the count fits.
- "no live segment has the room — attachment owed to a count that opens one" (`_attach`), plus `--move` and, since 0.0.38, `--detach`, which exist to clear a position's overflow after the attacher filled the only room.
- "does not read Zeckendorf(N) — counter drift" (`_register`), and the light sweep refusing to run on any register that is not clean.
- The operator's judged sweep is *held* "while the last sweep's `[gc]` line found no count opening one position" (`hooks/memory-override.md`). Entries the gc already judged cold stay hot because the numbers will not take them.

The reference is candid about what did not transfer from the codec: "no store quantity satisfies `F(k)+F(k+1)=F(k+2)` exactly (dedup shrinks bytes), so the rules transfer as procedures, not equations" (`skills/gc/reference.md`). So the exact capacities buy bounded merges and pay for them with the classes above.

## 3. How Chromium indexes IndexedDB (verified)

### 3.1 Topology

- Each **storage bucket** (an origin's default bucket, or a named one) has one `BucketContext`, which owns one backing store (`instance/bucket_context.cc`).
- In the LevelDB era, one LevelDB database per bucket holds every IndexedDB database of the origin (`docs/README.md`). For a first-party default bucket it lives at `<origin>.indexeddb.leveldb/`, with its blobs in `<origin>.indexeddb.blob/`; for other buckets it is `<bucket>/IndexedDB/indexeddb.leveldb` (`file_path_util.cc`).
- In the SQLite era, each IndexedDB database gets its own SQLite file, named by a deterministic mapping from the database name (`DatabaseNameToFileName`).

### 3.2 One sorted keyspace, prefixed for locality (LevelDB)

- Every key begins with «database id, object store id, index id», and id 0 is reserved for metadata. The prefix is packed into one length byte (3 bits for the database-id length − 1, 3 bits for the object-store-id length − 1, 2 bits for the index-id length − 1), followed by the ids in little-endian order. The coding-scheme doc gives the reason: data for one database, object store or index sits together, so that "reading that metadata only requires one seek".
- Under an object store, index id `1` holds **records** (the value is a version followed by the serialized value), `2` holds **"exists" entries** (the value is the record's current version), and `3` holds **external-object entries** (blob references). User indexes start at `30` (`kMinimumIndexId`) and store «…, index key, 0, primary key» → version + primary key.
- Metadata is typed. Global «0,0,0,t»: 0 schema version (latest 5, oldest readable 3), 1 max database id, 2 data format, 3 recovery blob journal, 4 active blob journal, 5 earliest sweep, 6 earliest compaction, 50 scopes, 201 name → database id. Per database «db,0,0,t»: 1 name, 3 max object-store id, 4 version, 5 blob-number generator. Per object store «db,0,0,50,os,t»: 0 name, 1 key path, 2 auto-increment, 4 last version number, 5 max index id, 7 key generator. Per index «db,0,0,100,os,idx,t»: 0 name, 1 unique, 2 key path, 3 multi-entry. Obsolete keys are still decoded, "as the sort order must be maintained".
- User keys are typed (0 null, 1 string, 2 date, 3 number, 4 array, 5 min, 6 binary). Doubles are stored in host endianness and strings as UTF-16BE, so byte order is not key order. LevelDB therefore runs with a custom comparator, `idb_cmp1`, and must keep it for good.

### 3.3 Versions: how an index goes stale without being wrong

- Every put takes `last version number + 1` for its object store (`GetNewVersionNumber`), writes the record and its exists entry with that version, and writes the new index entries with it too. **The old index entries are left in place.**
- Every index read checks the entry's version against the exists entry's (`VersionExists`). A mismatch marks the entry stale: it is skipped, and it is removed only when the transaction is allowed to write. For a read-only cursor, `RemoveTombstoneOrIncrementCount` does nothing.
- The sweeper exists because stale entries "stay around if script doesn't do a cursor iteration of the database" (`tombstone_sweeper.h`).

### 3.4 Maintenance runs at close, in rounds, when due

- When a bucket's last connection closes, a 2-second grace period (`kBackingStoreGracePeriod`) gives a re-open the chance to cancel the close. After that the pre-close queue runs, capped at 60 seconds in total. A force-close skips it entirely.
- **Task 1, the tombstone sweeper.** It walks every index of every object store of every database, starting from random seeds so that repeated partial passes cover different ground. It does 1,000 entries per round and 10 million at most, and reads with `fill_cache = false` so the sweep does not evict the working set. Deletions are batched per round, and a later pass resumes from the saved key.
- **Task 2, compaction.** `CompactRange(nullptr, nullptr)`: LevelDB rewrites its files and drops deleted keys.
- Each task runs only when it is due. That takes two clocks: a per-bucket "earliest" time persisted in the bucket's own keyspace (next = now + a random 1–3 days) and a process-wide one kept in memory (next = now + a random 5–60 minutes). The jitter stops buckets from all maintaining at the same moment.

### 3.5 Big values leave the keyspace, through journals

- A serialized value of 64 KiB or more is compressed with Snappy, and the compressed copy is kept only if it is at most 90% of the original. A value still over 64 KiB after that is wrapped into a Blob. The threshold is `kIDBWrapThreshold = 65536`, and the mojom gives the reason: LevelDB "was not designed with large values in mind… large values will slow down compaction".
- A blob is a file under `<blob dir>/<database id>/`, named by its blob number in hex and spread across 256 subdirectories by the number's second byte. The number comes from a per-database generator. A record points at its blob through an external-object entry.
- Two journals keep the files and the keys consistent. The **recovery journal** lists blob files that must be deleted: ones that are unlinked and unused, or that were written by a commit that never finished. The **active journal** lists unlinked blobs that a client is still reading.
- A commit has two phases. In phase one, the new blob numbers go into the recovery journal and then the files are written, so a crash at this point leaves them marked for deletion. In phase two, one atomic write adds the blob entries, takes the new blobs off the recovery journal, and puts the removed blobs on it; the dead files are deleted afterwards. The recovery journal is processed from time to time, when no transaction is active.

### 3.6 What Chromium keeps warm

| Layer | Setting | Why |
| --- | --- | --- |
| block cache | a shared LRU of 8 MiB, with web databases given a cache separate from the browser's own. On low-end devices a single 1 MiB cache serves both | "so rogue pages can't mount a denial of service attack by hammering the block cache" |
| bloom filters | 10 bits per key | a point read skips files that cannot hold the key |
| files | Snappy blocks, paranoid checks, at most 80 open files, a write buffer scaled to the disk's size | — |
| maintenance reads | `fill_cache = false` | the sweep never pushes out the working set |
| open handles | the backing store stays open 2 s after the last close; a SQLite connection stays 2 s after release | "a chance to re-open the same database without the overhead" |
| cursors | after 2 plain `continue()` calls, prefetch 5, doubling up to 100; a keyed `continue()`, or a call on another cursor in the same transaction, resets it | a sequential scan stops paying one IPC per row |
| quota | bucket space is cached for 30 s | — |

Memory pressure prunes the block caches.

### 3.7 Where it is going: SQLite, with a staged migration

- The SQLite backend (schema version 1) has one table per concept: `object_stores`, `indexes`, `records` (unique on object store and key), `index_references`, and `blobs`, with `overflow_blob_chunks` and `blob_references` beside it.
- **Records are immutable.** An update deletes the row and inserts a new one: it is an `INSERT OR REPLACE` with `recursive_triggers` on, so the replaced row's delete trigger fires.
- **Index maintenance is eager.** When a record is deleted, a trigger deletes its index references and blob references, so no versions and no sweeper are needed. `index_references` repeats the object-store id and the record key so that cursors never need a JOIN.
- Keys are stored with `EncodeSortableIDBKey`, an encoding whose plain byte order *is* IndexedDB key order. Its type bytes run 0x10 number < 0x20 date < 0x30 string < 0x40 binary < 0x50 array, it uses 0x00 sentinels, doubles are big-endian with the sign flipped, and −0 folds into +0. SQLite compares the BLOBs natively, so the custom comparator is gone.
- Blobs move inside the database: up to 5 MiB in a row, with overflow chunks beyond that, reference-counted by triggers. A record of 450 bytes or more is compressed (zstd at level −4, or Snappy on Android and Fuchsia) and kept compressed only if the result is at most 80% of the original. The renderer stops compressing and wrapping once it knows the backend is SQLite.
- Upkeep: the database runs in WAL mode, checkpointed when idle and truncated past 10,000 pages. Except on Android, which vacuums automatically, it runs `VACUUM` on close or after a long idle when at least 33% of pages are free and the disk has twice the used size plus 1% to spare.
- The rollout has five stages: `UseLevelDbOnly` → `UseLevelDbAsControl` → `UseSqliteForNewStores` → `MigrateDataToSqliteGentle` → `UseSqliteOnly`. Both of its features are off by default in source, but incognito already runs on SQLite.
- The gentle migration runs when the backing store closes. It goes ahead only if the disk stays under 99% full after reserving max(72 KiB, 2.5 × the LevelDB size). If it fails, the partial SQLite output is deleted; if it succeeds, the LevelDB and blob directories are. The duration of every attempt is logged, and a successful one also logs the size ratio.

### 3.8 Three things called "tombstone"

- A **LevelDB tombstone** is a deletion marker in the log-structured tree. Its space comes back only at compaction.
- **Chromium's "index tombstone"** is a stale index entry whose version no longer matches. This is what the sweeper sweeps.
- **VLDS `tombstones.md`** is the gc's record of a free: a mask with owner-words and a lesson. Nothing in this brief sweeps it.

Below, the second is called a **stale index line**, and "tombstone" means only the third.

## 4. What stays the same: the register of active context

Unchanged, byte for byte:

- the hot files, their headers (which are the authority on their shapes), the entry grammar (a `- field:` head with two-space continuations), the budgets, and the rule that a user's edit is a ruling;
- `phi.py barrier`: the states (LIVE / SPENT / FREED / EXPIRED), the rules that stamp them, and the `<file>:<line>  STATE  time  head — reason` row;
- `phi.py pool`: the skeleton, the sections, the `- [<file> <time> <STATE>] …` lines, the 8,000-character cap with its 2,000 reserve, the folding of picks, and `recall-pool.md`;
- `phi.py standing` and its SessionStart block;
- the `## recall` settings (`inject:`, `digest:`, `pool:`, `pool-road:`, the models, `operator-via:`, `operator-moments:`), still a ruling as they are today;
- the prompt hook's stamp and dispatch barrier, the owner-voice digest, and the known-short-command derivation. The last two keep reading the archived dispatch records, but they find them through the keyspace instead of by listing a directory;
- `record.py`'s upsert-by-head close, the pre-write and pre-ask gates, and the operator and pool briefs' rule that recall never opens the cold tier.

Only two things move. The cold tier's path changes from `arc/` to `idb/runs/` and `idb/blobs/`, and the SessionStart index digest prints a keyspace summary where it used to print the register's digit string.

## 5. The proposal: the store as one IndexedDB backing store

| Chromium IndexedDB | VLDS today | VLDS proposed |
| --- | --- | --- |
| backing store (bucket) | the store, `.claude/vlds/` | the same |
| object store | a hot file | the same: the file is the object store (`data-store`, `ledger`, …) |
| record + exists entry | an entry (hot) or an `id:` block in a segment (cold) | a record line: primary key → version, sha, location |
| primary key | none while hot; `xx-NNNN` minted at the first sweep | `<time>\|<sha8 of the head line>`, derived, so nothing is written into hot entries |
| version, per object store | none; watermarks hash whole spans | `last-version + 1` whenever a block changes |
| user index (≥ 30) | none; every lookup scans | `30:by-kind`, `31:by-status`, `32:by-owner-words`, `33:by-source`, `34:by-session`, `35:by-fact-id` |
| memtable → SSTable | hot file → a segment at a Fibonacci position | hot file (a memtable with pins) → a run file |
| compaction | CARRY and RESOLVE merges | runs merged by count and size, gated by the same `verify-merge` |
| external objects | whole-file pours, attached to a segment that has room | external-object lines, with the files under `idb/blobs/` |
| recovery journal | sha-verify before the reseed; the watermark window | `idb/journal.tsv` |
| tombstone sweeper | — | stale index lines dropped at every sync |
| earliest sweep / compaction | pressure plus register debt | `@ ⇥ 00 ⇥ earliest-compaction`, with jitter |
| block cache | `recall-pool.md` | the same, now validated by a version vector |

### 5.1 Layout

```text
.claude/vlds/
  local-storage.md … dispatch.md   hot files — unchanged
  recall-pool.md                   the session's block cache — unchanged
  phi-index.md                     config (## recall); its register tables retire at stage 4 (section 7)
  idb/
    keys.tsv      the keyspace: sorted, derived, rebuildable, never a ruling
    journal.tsv   append-only: the recovery journal, plus intents from writers that hold no lock
    runs/         cold records, one immutable sorted file per pour or merge (the SSTables)
    blobs/        external objects: whole-file pours and grammar offenders
    .sweep-lock   the sweep lock, as arc/.sweep-lock is today
```

Moving the config out settles a knot in the current design. Today `phi-index.md` mixes derived tables with ruling-bearing settings, so `rebuild` has to refuse and the gc has to reconcile. Once the keyspace holds only what can be derived, a rebuild can never write over a ruling.

### 5.2 The keyspace

Each key is one tab-separated line: `<object store> ⇥ <type> ⇥ <key> ⇥ <field=value> ⇥ …`. The lines are sorted by plain byte order. That is the SQLite-era lesson: pick an encoding whose byte order *is* the intended order, so `LC_ALL=C sort -c` verifies it, a bisect finds a key, and no script ever has to carry a custom comparator. A tab sorts below every printable character, which keeps each object store's lines together, and `@` (the store itself) sorts before every object-store name.

The types mirror Chromium's reserved ids:

| type | holds | Chromium |
| --- | --- | --- |
| `00` | metadata. Per store: `schema`, `synced`, `earliest-compaction`, `sweep-cursor`, `pool`. Per object store: `last-version`, `key-generator`, and the index definitions (`key=`, `unique=`, `multi=`) | «0,0,0,t» and «db,0,0,50/100,…» |
| `01` | a record: primary key → `v=`, `sha=`, `at=hot:<line>` or `at=runs/<file>:<line>`, `id=`, `state=` | ids 1 and 2 merged: the line carries no value, so it *is* the exists entry |
| `03` | an external object: key → `blob=`, `bytes=`, `sha=` | id 3 |
| `30:<name>` and up | an index entry: `<index key>\|<primary key>` → `v=` | ids ≥ 30 |

- **Primary key.** `<time>|<first 8 hex of sha256(head line)>`. The time comes from the `time:` field, or from the stamp inside the line (logger bullets), or else it is `0000-00-00 00:00`. Because the key is derived, the hot files carry nothing new. A change to a continuation field is an update (same key, new version); a rewrite of the head is a delete plus an insert, because the key itself changed, which is also how SQLite's immutable rows treat it. Two identical blocks get `#2`.
- **Version.** Per object store, `last-version + 1` whenever a block's `sha` changes (as in `GetNewVersionNumber`).
- **`sha`.** The first 12 hex of the sha256 of the block, the same width `phi.py` uses.
- **`at=hot:<line>` is a hint.** The barrier's line number is a snapshot address, as it is today. A reader checks the hint by `sha` and rescans the (small, budgeted) hot file when the hint has moved.
- **Indexes serve real readers.** `by-kind` serves `standing` and the pool's form and every-turn set. `by-owner-words` (on local-storage and tombstones) turns the barrier's same-owner-words mask into a join. `by-source` supports the UNOWNED call on unsourced claims, `by-session` finds virtual entries minted elsewhere, and `by-fact-id` resolves the legacy handles that tombstones cite. A tombstone's head-containment mask stays a scan, because substring containment cannot be looked up by key.

### 5.3 Reading

- The barrier and the pool read the hot files, exactly as they do today.
- A **point read** follows keyspace line → location → block. This covers the operator fetching one entry for the session, and any miss into the cold tier. Before the block is used it is validated. The index line's `v` must equal the record's `v`; otherwise the index line is stale and is skipped. The block at the location must hash to `sha`; otherwise the record is behind a hand edit, and the reader re-reads the hot file, because the file is the authority.
- A **range read** is a bisect over the sorted keys, for example from `ledger ⇥ 01 ⇥ 2026-08` up to `ledger ⇥ 01 ⇥ 2026-09`. Today's "time-anchored queries resolve per (source, time) pair" is answered by the sort order itself.
- **Readers never write.** This is the read-only cursor rule: a stale line a reader meets is skipped and left for the next sync.

### 5.4 Writing: eager where a script writes, lazy where a person does

- The owner's hand edits are rulings, and they pass through no script. So the index has to stay correct while it is behind. LevelDB's versioned validation is the model VLDS needs, rather than SQLite's triggers, and VLDS needs it more than Chromium does, since Chromium never has a person editing its keyspace.
- **`idb.py sync`** runs at every turn close under the lock (`--full` rebuilds from scratch). It re-derives every hot block's key and `sha`. A block with the same `sha` is kept as it is. A new or changed block gets `last-version + 1` and fresh index lines. A hot record whose key has vanished is dropped. Any index line whose key no longer exists is dropped too, which folds the sweeper into the rewrite. `keys.tsv` is then replaced atomically (write, fsync, rename), and that replacement is the commit point.
- A writer that holds no lock (the prompt hook's dispatch pour, or `record.py` if it later wants the index current at once) appends an intent to `journal.tsv`, and the next sync folds it in. This is LevelDB's log in front of its sorted files, reduced to one line of text.

### 5.5 Pour: two-phase, and the watermark goes

Which entries are cold is decided exactly as it is today, by both the judged classes and the light ones. What changes is placement:

1. Take the lock and journal `pour <run> pending`.
2. Write the run: sorted by key, with a fenced header giving the object store, the key range, the entry count and the body's `sha`. Fsync it.
3. Run `verify-pour`: every poured block must appear verbatim in the run. This gate is kept.
4. Commit: rewrite `keys.tsv` so the poured records read `at=runs/<run>:<line>` with `v+1` and an `id=` minted from the object store's key generator, and journal `pour <run> committed, trim pending`.
5. Trim the hot file and journal `trim done`.

| If a crash comes after step | what is on disk | what the next sync does |
| --- | --- | --- |
| 1–3 | the run file and a pending journal line; the keys are untouched | deletes the run, since every block is still hot (Chromium's recovery journal) |
| 4 | records point at the run, the blocks are still hot, and the journal says "trim pending" | finishes the trim for every block whose hot `sha` equals the run's |
| 4, followed by a hand edit | the same, except one block's hot `sha` now differs | lets the edit win: that record goes back to `at=hot` with a new version, and the run keeps the old text as history |

No span is ever left "poured but not trimmed" under a line-range hash. The watermark `mask=A:B sha=H`, the trim window that `verify-pour` guards, and "watermark voided" are all covered by the per-entry `sha` and the journal.

### 5.6 External objects: no capacity, no placement

- **The dispatch pour** happens in the prompt hook, at a new session's first prompt. It journals `blob pending`, copies `dispatch.md` to `idb/blobs/dispatch/<stamp>-<owner>.md`, verifies the copy byte for byte, reseeds `dispatch.md`, and journals `blob committed`. The next sync then writes `dispatch ⇥ 03 ⇥ <time>|<owner> ⇥ blob=… ⇥ bytes=… ⇥ sha=… ⇥ rows=…`. The crash rule: a pending blob whose rows are all still in `dispatch.md` is an orphan and is deleted; any other pending blob is registered.
- **Wrapping.** A block that fails the grammar gate (a column-0 `---` or a fence), or that exceeds 64 KiB, is wrapped: its run entry holds `(wrapped: idb/blobs/<os>/<n>.md sha=…)`. This is Chromium's wrap marker.
- **What goes away.** Attach, `--move`, `--detach`, "no live segment has the room" and "registration owed" all disappear, because a blob needs no home with room.
- The owner-voice digest and the known-short-command lookup take their file list from the `dispatch ⇥ 03` lines instead of listing `arc/`.

### 5.7 A free that reaches the cold tier

Deletion works by marker, as it does in LevelDB. The moment the tombstone lands, the record line takes `state=freed ts=<tombstone key>`: one line, instant, and reversible. The run keeps the text. A cold read that meets `freed` surfaces the entry instead of applying it. Physically removing the text stays with the owner (section 8), because an archived ruling carries the owner's own words and disposing of what the owner authored needs the per-act word. This replaces the BORROW carve and check #8's owed-borrow state.

### 5.8 Maintenance at the turn's close

- **Sync at every turn close.** The Stop hook runs `idb.py sync` instead of `normalize.py --light`. The sync is bounded: it works in rounds under a wall-clock budget of a few seconds (the hook's timeout is 50 s) and saves its place in `@ ⇥ 00 ⇥ sweep-cursor`, so a pass that is cut off resumes where it stopped, as Chromium's rounds do. The light classes still pour (other sessions' virtual entries, and the logger past its budget, down to three quarters), but now any count is accepted, since there is no position for a count to open.
- **Compaction when it is due.** It runs for an object store that has at least 4 small runs (LevelDB's level-0 trigger), or whose `earliest-compaction` has passed and that has at least 2 small runs. It merges the store's runs under 64 KiB into sorted runs, splitting at entry boundaries once a run passes 64 KiB, and collapses exact duplicates. Full-size runs are left alone. The keyspace maps every key exactly, so runs never need non-overlapping key ranges, and the cost stays in proportion to new data. `verify-merge` gates each merge, the `keys.tsv` rewrite is the commit point, and the parents are deleted afterwards, which is the same script-verified deletion merges have today. The next `earliest-compaction` is now + a random 1–3 days.
- The lock is the φ-register's lock, moved: session-stamped, and stale after 60 minutes.

### 5.9 The caching model

| Chromium | VLDS |
| --- | --- |
| block cache | `recall-pool.md`, a bounded (8,000-character) derived cache of the hot tier, one per session |
| a separate web cache | the standing rules' own SessionStart block, so a flood of task entries cannot push out the owner's form and every-turn rules. It is the same no-noisy-neighbour rule |
| version-validated entries | the pool's version vector, `@ ⇥ 00 ⇥ pool ⇥ <session> ⇥ local-storage=<n>,ledger=<n>,…`, written when the pool is built. After a compact, the SessionStart hook compares it with the current versions and reports either "current" or which files have been written since, and how many times (for example "predates 3 writes: ledger +2, local-storage +1"). The pool file itself does not change |
| `fill_cache = false` | maintenance never writes the pool, never prints pool lines, and reports in one line |
| bloom filter | not needed at this scale: run headers carry their key range, and the keyspace maps every key to its run and line |
| grace period | compaction's `earliest` time and its run-count trigger. Sync is cheap enough to run at every close |
| cursor prefetch | optional: when the session asks the operator for two entries in key order, return the next five, doubling up to a cap, and reset on an out-of-order ask |
| process-lifetime caches | none can exist: every hook is a fresh process, so every cache has to be a file |

To be clear about the limits: the index does not make recall faster, because the hot tier is already small by budget. What it does is make the cold tier addressable by key, make every change detectable per entry, and make it possible to tell whether the pool is stale.

### 5.10 The check

These scans are **kept**: duplication, liveness, conformance, stray, the hot budgets, and the live/at-sweep ≥ φ pressure convention. That last one is a convention about hot files, so it outlives the register.

These scans are **new**. They replace the register, positions, epochs, weights, torn-pour, owed-borrow and watermark scans:

1. `keys.tsv` is sorted and parseable, and every type is known.
2. For each object store, `last-version` is at least every record's `v`, and it never goes down from one sync to the next. A counter now does the job the epoch pairs did.
3. For every `at=runs/…` record, the run exists and the block at that line hashes to `sha`. A mismatch means a hand edit in the cold tier: a ruling, with a re-sync owed. That is a note, not corruption.
4. Every index line's key names a record, and its `v` is at most the record's. The number of stale lines is reported, and a sync is owed.
5. Every `03` line's blob exists, and its bytes and `sha` match.
6. Nothing in the journal is still pending from before the last sync. Anything that is marks a torn commit, which the crash table in 5.5 settles.
7. A file in `idb/runs` or `idb/blobs` that no line names and no journal line claims is owed registration or collection, and the gc judges which. This is today's unregistered-mass scan.
8. Primary keys are unique within each object store, and `35:by-fact-id` is unique.

## 6. Every φ mechanism and its successor

| Today | Successor |
| --- | --- |
| `register:` digit string, `## positions`, Fibonacci capacities | `01` lines with `at=`, plus run headers (key range, count, sha) |
| the Zeckendorf pour counter; "a count that opens exactly one position" | any count pours; compaction runs by run count and size |
| `## epochs` and Cassini's identity | per-object-store `last-version`, monotone (scan 2) |
| BORROW | `state=freed ts=…` on the record line; physical removal only on the owner's ruling |
| RESOLVE, CARRY | compaction, still gated by `verify-merge` |
| watermarks, the `verify-pour` trim window | per-entry `sha` plus the two-phase journal; `verify-pour` stays as the containment gate |
| attach, `--move`, `--detach` | external-object `03` lines |
| `phi.py mask` (the Zeckendorf DP over 0..54) | retired (section 8); naming entries cold stays a judgment |
| `lock` / `unlock` | unchanged, moved to `idb/.sweep-lock` |
| `rebuild` | `idb.py sync --full`, always safe because the keyspace is derived |
| `restore` | `idb.py get <os> <key>` and `idb.py range <os> <from> <to>` |
| `check` scans 1–5 and 8, and the watermark half of 7 | section 5.10's scans 1–8 |
| `## hot` table | computed live from the hot files and the budgets, with no stored copy to drift |
| `normalize.py --pour <file>:<lines>` | `idb.py pour <file>:<lines>`, same arguments, no count to adjust |
| `barrier`, `pool`, `standing`, `lint` | **unchanged** |

## 7. Migration, staged the way Chromium stages SQLite

A new key in the `## recall` section, `index-engine:`, selects the stage:

| stage | `index-engine:` | Chromium's stage | what runs |
| --- | --- | --- | --- |
| 0 | `phi` | `UseLevelDbOnly` | today's system |
| 1 | `idb-control` | `UseLevelDbAsControl` | φ stays the authority. `idb.py sync` builds the keyspace in shadow at each close, and the check reports where the two disagree: counts per file, and whether every arc entry is found in the shadow |
| 2 | `idb-new-stores` | `UseSqliteForNewStores` | a store with no register in `phi-index.md` starts on the keyspace |
| 3 | `idb-migrate-gentle` (the default, as ruled in 10.6) | `MigrateDataToSqliteGentle` | a clean φ store migrates once, at a turn close |
| 4 | `idb` | `UseSqliteOnly` | the φ code paths retire |

The gentle migration (stage 3) runs at a turn close:

- **Preconditions.** The lock is held. `phi.py check` reports no CORRUPT and no voided watermark (a voided watermark is a ruling to reconcile first). There is room on disk for 2.5 × `arc/`, which is Chromium's margin.
- **Import.** Every segment entry goes into runs, keeping its `id:` and getting a computed key. Ids marked `(tombstoned)` become `state=freed`. Each attachment, and each unregistered `arc/dispatch-*.md`, becomes an external object.
- **Verify.** Every segment entry's body must appear verbatim in the runs (`verify-merge` across the whole of `arc/`), and every blob must be byte-identical.
- **Commit.** Write `keys.tsv`. Then move `arc/` aside to `arc.phi-retired/`. It is not deleted: disposing of it is the owner's act.
- **On failure.** Delete `idb/` (it is derived), stay on φ, and log the failure in one line.

What each stage touches:

- **Stage 1:** a new `scripts/idb.py`; the `turn-close` hook in `hooks/vlds_hooks.py` runs it in shadow after the light sweep; plus acceptance tests.
- **Stages 3–4:**
  - `hooks/vlds_hooks.py`: `pour_dispatch`, `lock_holder`, `known_short`, `voice_corpus`, `index_digest`, `cmd_session_open` and `cmd_turn_close`.
  - `phi.py`: check scans 1–5 and 8, the watermark half of scan 7, `mask`, `rebuild` and `restore` retire. `barrier`, `pool`, `standing` and `lint` stay.
  - `normalize.py` retires; its `--pour` interface moves to `idb.py pour`.
  - The briefs: in `operator-prompt.md`, the sweep moment loses "counts that open exactly one position"; in `pool-prompt.md` and `memory-override.md`, the cold tier's path changes.
  - The doctrine: the "The φ-Register" section of `skills/gc/reference.md`, plus `skills/gc/SKILL.md` and `README.md`.
  - `scripts/test_hooks.py`.

## 8. Rulings this needs

Rulings 1, 2, 3, 5 and 6 are applied as recommended (section 10.2); ruling 4 moved to the final stage (section 10.5), where the name was kept.

1. **The keyspace's form.** Sorted TSV (recommended: auditable, diffable, no dependency), or an SQLite file with the same four tables (Chromium's direction, but opaque to `cat`)? The schema above is laid out so that switching later is mechanical.
2. **Physically removing freed cold entries.** Never (recommended), or at compaction when the tombstone's `swept:` names the key?
3. **Handles.** Keep minting `xx-NNNN` at pour time (recommended: short, readable, and cited by tombstones)?
4. **The file name.** Rename `phi-index.md` at stage 4, to `store-index.md`, with the hooks reading either name for one release?
5. **Selection.** Retire `phi.py mask` and the 0..54 score grid (recommended: its rule against adjacent keeps belongs to the codec, not to the store)?
6. **Pressure.** Keep the φ ≈ 1.618 pressure ratio on hot files (recommended: it is a convention about budgets and does not depend on the register)?

## 9. What does not transfer

- Binary keys, the custom comparator, and Snappy or zstd compression. The store stays plain text that its owner edits.
- Compaction dropping overwritten values. VLDS archives verbatim; only exact duplicates collapse.
- Transactions with scopes and modes, versionchange upgrades, and structured clone. A VLDS store's schema is its file headers, and a header edit is a ruling.
- Quota eviction by LRU. Nothing leaves the hot tier except by the gc's judgment or a counted light class.
- The active journal. No process holds a handle to a cold file between hooks.
- The SQLite era's eager-only maintenance. The owner's hand edits need LevelDB's lazy validation.

## 10. What was built, and the rulings the final stage needed

### 10.1 Built

- `scripts/idb.py` — the engine, every subcommand of sections 5–7: `sync` (in rounds; `--full` rebuilds from the files), `light`, `pour`, `compact`, `migrate` (`--dry`, `--shadow`, `--budget-s`), `rollback`, `get` / `range` / `find`, `check`, `engine`, `pool-stamp` / `pool-diff`, `digest`.
- `hooks/vlds_hooks.py` — the Stop hook runs what the stage names under one 55-second deadline; the prompt hook pours `dispatch.md` into `idb/blobs/dispatch/` inside a marker file; SessionStart digests the keyspace and, after a compact, says whether the pool predates writes; post-write stamps the pool when the pool file itself was written. A keyspace store never takes the φ road, even when the engine will not load.
- `scripts/phi.py` — `check` hands a keyspace store to `idb.py check`; `barrier`, `pool`, `standing` and the store-level scans are unchanged; the tombstone rule is shared (`tombstone_hit`); `mask` is retired; `lock` and `rebuild` refuse on a keyspace store. `scripts/normalize.py` refuses there too; `scripts/record.py` reads either check's verdict.
- Doctrine: the contract, the operator's brief, the gc's skill and reference (a new section, "The Keyspace"), the gate's reference, the README; the plugin at 0.0.43.

### 10.2 The rulings of section 8, as applied

| # | Ruling | Applied |
| --- | --- | --- |
| 1 | sorted text | `idb/keys.tsv`, byte order = key order |
| 2 | never remove a freed cold entry | a derived `state=freed ts=` mark; compaction keeps the entry; no command removes it |
| 3 | keep the `xx-NNNN` handles | minted at pour time from each object store's key generator; the φ ids kept at migration |
| 5 | retire `phi.py mask` and the grid | the subcommand prints its retirement; the gc reference's Selection rewritten |
| 6 | keep the φ pressure ratio | the kept store-level scans run on a keyspace store |
| 4 | rename `phi-index.md` | declined at the final stage (10.5): the name is kept |

### 10.3 Where the build departs from sections 5–7

- The prompt hook's dispatch pour leaves its intent in a marker file (`idb/pending/<record>`), not the journal: it holds no lock, and a line appended while a locked pass rewrote the journal could be lost. A marker older than ten minutes is settled — its copy removed when `dispatch.md` still holds its rows — and a young one is never touched.
- The rollback works at any point, not only before the first pour: every entry poured since returns to its hot file verbatim, history the runs hold is kept in `arc/`, and a crash part-way is resumed, never redone.
- A migration and the keyspace's first pass run at consecutive turn closes, each inside the Stop hook's deadline; the migration takes a budget and stops cleanly, committing nothing, rather than run past it.
- The index's hot table is rewritten only when something moved, as the φ light sweep did, so a turn of appends does not churn the file.
- A run entry puts its `id:` line first and its `key:` line second — a segment's grammar with one line more — so `phi.py restore` reads a run as it reads a segment.

### 10.4 Tested

- `scripts/test_idb.py` — 19 tests, 192 assertions after the final stage's rulings (section 10.6): the key lines and their order against the barrier's rows; versions and the sweep across a hand edit; the two-phase pour and a crash at each step (before the commit, after it, and after it with an edit between); the light classes through the Stop hook; the dispatch pour as an external object, torn and in flight; the freed marks, including after a partial sync; compaction, and a torn one; the migration from a store built by normalize.py's own segments — every entry verbatim under its id, every blob byte-identical, the barrier and the standing rules byte-identical before and after, the pool the same but for its `updated:` line; a refused migration said once; the φ era's legacy shapes; a crash right after the commit point; the rollback after pours, with history, with a record no sync had registered, and across two crashes; the check's scans; the stages through the hooks; the pool's stamp; the rounds; a wrapped entry and a CRLF hot file; a whitespace-only last line, a stale lock, an engine that will not load.
- `scripts/test_hooks.py` — the 19 φ tests, green and unchanged except that their seeded index now names `index-engine: phi`.
- Two independent review passes over the diff found 20 defects; every one is fixed, and most are pinned by a test above.
- Not yet run: the owner's own stores, and Windows. The tests ran on Linux, so the Windows paths — CRLF files, directory renames, the lock — are exercised only by their Linux equivalents.

### 10.5 The final-stage rulings

The final stage, `idb`, is where the φ code paths retire. Four rulings decide it and the merge into `main`. All four were ruled as recommended; section 10.6 records what changed.

1. **The stage `main` ships at** (`DEFAULT_ENGINE` in `scripts/idb.py`; `phi` on this branch). Recommended: **`idb-migrate-gentle`**. A new store starts on the keyspace, and a clean φ store migrates at its next turn close — verified before its commit, its arc kept aside, a rollback away from undone. A store the φ check calls corrupt keeps the φ sweep and says once why it waits. The conservative alternative is `idb-control`, which prints each store's shadow verdict and writes nothing. Either way the change is one constant and the one test that asserts it, since the φ tests already name their stage. A single check on a real store first: `idb.py --store <store> migrate --session x --dry`.
2. **When the φ code retires** (`normalize.py`, the φ scans in `phi.py`, the φ doctrine). Recommended: **not in this merge**, but in a follow-up once every store in use reports `engine: idb` at SessionStart. A store that cannot migrate yet (a torn φ pour, a voided watermark) needs the φ sweep until its ruling is reconciled, and a rollback needs the φ code to return to.
3. **`phi-index.md`'s name.** Recommended: **keep it.** It carries rulings (`## recall`, the budgets) under a name every hook, gate, test and habit already addresses, and the φ pressure ratio still reads its hot table. A rename would move a ruling-bearing file in every store to gain a name. If one is wanted, it belongs with the φ retirement, read under both names for one release.
4. **`arc.phi-retired/`.** Recommended: **kept until the owner removes it by hand.** The rollback returns from it, and disposing of what the owner authored keeps the per-act word; no script deletes it.

### 10.6 As ruled

1. **The default is `idb-migrate-gentle`** (`DEFAULT_ENGINE` in `scripts/idb.py`). A store whose index names no stage now takes it:
   - a new store starts on the keyspace: its first dispatch pour lands in `idb/blobs/dispatch/`, its first turn close writes `idb/keys.tsv` and the index, and no `arc/` appears;
   - a clean φ store migrates at its next turn close, and one the φ check calls corrupt keeps the φ sweep and says once why it waits;
   - the migration writes no `index-engine:` line, so the store keeps following the default.

   `index-engine: phi` keeps a store on the φ-register, and the rollback writes it, so a rolled-back store is not migrated again.
2. **A migration the default owes is announced before it runs.** SessionStart prints `engine: phi (index-engine: idb-migrate-gentle, the default) — migrates to the keyspace at the next turn close once the φ check is clean`, and the turn close's report follows at the next prompt. Before the ruling this line was silent whenever the index named no stage, which was right only while the default moved nothing. The `pool: inject` road printed no engine line at all; it now prints the same line under the index.
3. **Tests.** `test_idb.py`'s stage test asserts the new default:
   - the announcement in both pool modes, the migration, and the stage still unnamed after it;
   - the keyspace's digest naming the default;
   - a new store starting on the keyspace;
   - `phi` as the stage that keeps a store on the φ-register.

   Undoing any one of the constant, the announcement or the inject line fails it. Section 10.5 said the change was "one constant and the one test that asserts it". That undercounted: `test_hooks.py`'s session-title test had also relied on the default, since its store had no index. It now seeds the φ register, and so names its stage like every other φ test.
4. **The φ code stays** (ruling 2): `normalize.py`, the φ scans in `phi.py` and the φ doctrine. The gc's reference now names when they retire: once every store in use reads `engine: idb` at SessionStart.
5. **`phi-index.md` keeps its name** (ruling 3). Nothing changed.
6. **`arc.phi-retired/` is kept until the owner removes it by hand** (ruling 4). No script deletes it: the migration moves `arc/` aside, and the rollback moves it back. The rollback refuses when the directory or its saved φ index is missing. The gc's reference and the README now say that removing it gives the rollback up, the contract says the rollback returns from it, and the descriptions say it is kept until the owner removes it by hand.
7. **Not run: the dry run on a real store.** There is no store in this repository; the owner's stores live in their own projects. Before a φ store in use meets the default, `idb.py --store <store> migrate --session x --dry` says whether it would pass, and writes nothing.
8. The plugin is at 0.0.44. The contract's parts measure 8928, 4098, 8875 and 4434 bytes, all under the 9,500-byte cap.

The branch `claude/sleepy-planck-cstt6m` carries the brief, the build, the review's fixes and these rulings as separate commits. How they land on `main` is the owner's version-control word.

## Appendix A: Chromium sources

All paths are under `chromium/chromium` `main` at 156.0.8077.0 (`chrome/VERSION`).

| File | Supports |
| --- | --- |
| `content/browser/indexed_db/docs/leveldb_coding_scheme.md` | the prefix and its packing, the metadata key types, records / exists / external objects / indexes, versions and lazy deletion, "sort order must be maintained" |
| `content/browser/indexed_db/docs/README.md` | one LevelDB per origin's backing store, blob states, the recovery and active journals |
| `content/browser/indexed_db/indexed_db_leveldb_coding.{h,cc}` | key type bytes, schema versions 3–5, `kMinimumIndexId = 30`, global type bytes 0–6 / 50 / 100 / 201, `EncodeSortableIDBKey` |
| `content/browser/indexed_db/instance/leveldb/indexed_db_leveldb_operations.{h,cc}` | `idb_cmp1`, `GetNewVersionNumber`, `VersionExists`, the sweep and compaction delays (1–3 days, 5–60 minutes) |
| `content/browser/indexed_db/instance/leveldb/backing_store.cc` | LevelDB options (block cache, bloom 10, Snappy, 80 files), stale-entry removal, `RemoveTombstoneOrIncrementCount`, the two-phase commit and journals, the pre-close tasks and their 60 s budget, skipped on force-close |
| `content/browser/indexed_db/instance/leveldb/tombstone_sweeper.{h,cc}` | the random seeds, rounds of 1,000, the 10-million cap, `fill_cache = false`, batched deletions, resume |
| `content/browser/indexed_db/instance/leveldb/compaction_task.cc` | `CompactRange(nullptr, nullptr)` |
| `content/browser/indexed_db/instance/backing_store_pre_close_task_queue.{h,cc}` | the queue, the metadata fetch, stop on timeout |
| `content/browser/indexed_db/instance/bucket_context.{h,cc}` | the 2 s grace, the 15 s idle, the 30 s quota cache, the SQLite rollout stages and their selection, the gentle migration and its disk rule |
| `content/browser/indexed_db/instance/sqlite/database_connection.cc` | the schema, immutable records, triggers, blobs at 5 MiB with overflow, zstd / Snappy, WAL checkpoints, the vacuum rule, the 2 s destruction grace |
| `content/browser/indexed_db/file_path_util.cc` | the LevelDB, blob and SQLite paths |
| `content/public/common/content_features.cc` | `kIdbSqliteBackingStore` and `kIdbSqliteOnDiskRollout`, both disabled by default |
| `third_party/blink/renderer/modules/indexeddb/idb_cursor.{h,cc}` | prefetch 2 / 5 / 100, and its reset rules |
| `third_party/blink/renderer/modules/indexeddb/idb_value_wrapping.{h,cc}` | Snappy at ≥ 64 KiB kept only at ≤ 90%, wrapping above 64 KiB, neither on SQLite |
| `third_party/blink/public/mojom/indexeddb/indexeddb.mojom` | `kIDBWrapThreshold = 65536` and its rationale |
| `third_party/blink/common/features.cc` | `kIndexedDBCompressValuesWithSnappy`, enabled by default |
| `third_party/leveldatabase/leveldb_chrome.cc` | the 8 MiB / 1 MiB block caches, the web / browser split and its reason, pruning under memory pressure |
| `third_party/leveldatabase/env_chromium.cc` | the write buffer scaled to the disk's size |

## Appendix B: a worked example

A three-file store was built to check the design, and the design sketch's derivation was run on it using `phi.py`'s own `hot_entries`, `entry_kind` and `norm_text`. The digits below are computed from that store, not invented; `⇥` stands for a tab. `local-storage.md` holds two rulings, at lines 15 and 21 after its header:

```text
- ruling: design briefs for a plugin land in its investigations/ directory
  owner-words: "put the write-up in the repo next to the plugin"
  time: 2026-09-20 16:04
  scope: this repo
  status: LIVE
  form: file
- ruling: never run the integration suite locally
  owner-words: "dont run integration locally it broke my env"
  time: 2026-08-11 09:12
  scope: this repo
  status: FREED
```

`data-store.md` holds two claims and `tombstones.md` holds the free of the second ruling. The derived keyspace (`LC_ALL=C sort -c` passes):

```text
@ ⇥ 00 ⇥ recovery-journal ⇥ -
@ ⇥ 00 ⇥ schema ⇥ 1
@ ⇥ 00 ⇥ synced ⇥ 2026-09-28 10:55
data-store ⇥ 00 ⇥ last-version ⇥ 2
data-store ⇥ 01 ⇥ 2026-09-12 10:31|1d72b078 ⇥ v=1 ⇥ sha=e3c539522513 ⇥ at=hot:13
data-store ⇥ 01 ⇥ 2026-09-28 10:52|03c8a072 ⇥ v=2 ⇥ sha=956cefff649c ⇥ at=hot:17
data-store ⇥ 30:by-kind ⇥ claim|2026-09-12 10:31|1d72b078 ⇥ v=1
data-store ⇥ 30:by-kind ⇥ claim|2026-09-28 10:52|03c8a072 ⇥ v=2
data-store ⇥ 33:by-source ⇥ sourced|2026-09-12 10:31|1d72b078 ⇥ v=1
data-store ⇥ 33:by-source ⇥ sourced|2026-09-28 10:52|03c8a072 ⇥ v=2
local-storage ⇥ 00 ⇥ last-version ⇥ 2
local-storage ⇥ 01 ⇥ 2026-08-11 09:12|0b8d85a3 ⇥ v=2 ⇥ sha=415d678ed5f2 ⇥ at=hot:21
local-storage ⇥ 01 ⇥ 2026-09-20 16:04|cb8b6dc9 ⇥ v=1 ⇥ sha=25b5ab3f1c99 ⇥ at=hot:15
local-storage ⇥ 30:by-kind ⇥ form|2026-09-20 16:04|cb8b6dc9 ⇥ v=1
local-storage ⇥ 30:by-kind ⇥ ruling|2026-08-11 09:12|0b8d85a3 ⇥ v=2
local-storage ⇥ 31:by-status ⇥ FREED|2026-08-11 09:12|0b8d85a3 ⇥ v=2
local-storage ⇥ 31:by-status ⇥ LIVE|2026-09-20 16:04|cb8b6dc9 ⇥ v=1
local-storage ⇥ 32:by-owner-words ⇥ 3ff8f33b|2026-09-20 16:04|cb8b6dc9 ⇥ v=1
local-storage ⇥ 32:by-owner-words ⇥ 4560c5c7|2026-08-11 09:12|0b8d85a3 ⇥ v=2
tombstones ⇥ 00 ⇥ last-version ⇥ 1
tombstones ⇥ 01 ⇥ 2026-09-02 18:40|7c049e64 ⇥ v=1 ⇥ sha=1f1f944ba521 ⇥ at=hot:13
tombstones ⇥ 30:by-kind ⇥ freed|2026-09-02 18:40|7c049e64 ⇥ v=1
tombstones ⇥ 32:by-owner-words ⇥ 4560c5c7|2026-09-02 18:40|7c049e64 ⇥ v=1
```

The `4560c5c7` pair is the barrier's same-owner-words mask, found as a join: the freed ruling and its tombstone share the key.

The register of active context does not read any of this. `phi.py barrier` on the same store prints what it printed before the keyspace existed:

```text
local-storage.md:15  LIVE    2026-09-20 16:04  - ruling: design briefs for a plugin land in its investigations/ directory — its own status field
local-storage.md:21  FREED   2026-08-11 09:12  - ruling: never run the integration suite locally — its own status field
tombstones.md:13  LIVE    2026-09-02 18:40  - freed: never run the integration suite locally — the mask itself
data-store.md:13  LIVE    2026-09-12 10:31  - claim: "the harness caps one hook output at 10,000 characters" — no status, no mask
data-store.md:17  LIVE    2026-09-28 10:52  - claim: "Chromium main is 156.0.8077.0" — no status, no mask
```

**A hand edit.** The owner changes line 19 from `status: LIVE` to `status: SPENT` in an editor, so no hook fires. A reader using the old keyspace finds every index line on that entry *behind*: each line's `v` still matches the record's, but the block at `hot:15` no longer hashes to `25b5ab3f1c99`. The reader therefore re-reads the file and does not trust the index:

```text
BEHIND local-storage 30:by-kind form|2026-09-20 16:04|cb8b6dc9 — record sha 25b5ab3f1c99 != hot block at line 15: hand edit since the last sync; re-read the hot file
BEHIND local-storage 31:by-status LIVE|2026-09-20 16:04|cb8b6dc9 — record sha 25b5ab3f1c99 != hot block at line 15: hand edit since the last sync; re-read the hot file
BEHIND local-storage 32:by-owner-words 3ff8f33b|2026-09-20 16:04|cb8b6dc9 — record sha 25b5ab3f1c99 != hot block at line 15: hand edit since the last sync; re-read the hot file
```

**The next sync** (the turn-close Stop hook):

```text
sync: 1 updated, 0 inserted, 0 dropped; 1 stale index line(s) swept: local-storage 31:by-status LIVE|2026-09-20 16:04|cb8b6dc9 v=1
local-storage ⇥ 00 ⇥ last-version ⇥ 3
local-storage ⇥ 01 ⇥ 2026-09-20 16:04|cb8b6dc9 ⇥ v=3 ⇥ sha=a6ffe508207c ⇥ at=hot:15
local-storage ⇥ 31:by-status ⇥ SPENT|2026-09-20 16:04|cb8b6dc9 ⇥ v=3
```

The key stayed the same because the head did not change. The version moved from 1 to 3 (the object store's counter was at 2), the `LIVE` line was swept, and the `SPENT` line was written. The other two index lines kept their keys and were rewritten at `v=3`.

Today nothing indexes a hot entry, so a hot edit has nothing to put out of date, and the watermark catches an edit only inside a span that has been poured but not yet trimmed. The keyspace indexes every entry, so it has to catch every edit, and it does so one entry at a time.
