---
name: recall
description: "The archive's one door, opened only on the owner's word. The keyspace's cold tier — every entry the gc poured out of the hot files, kept verbatim in idb/runs/ (an entry past 64 KiB wrapped into idb/blobs/) and never removed — is read by no session on its own: the pool and the SessionStart injection read the hot files alone. /vlds:recall is the road in: the session hands the operator a recall moment carrying the owner's request, the operator reads the cold tier through scripts/idb.py range, find and get — never the files — and returns each match with its object store, key and run location, as weakened provenance that passes the read barrier before it steers. Nothing recalled is written back into a hot file unless the owner rules it live again."
when_to_use: "Only when the owner asks for archived memory in words: /vlds:recall, 'recall from the archive', 'what did we rule about X back then' about something the pool does not hold. Never on the session's own initiative, never to fill a pool, never for a derivation the hot tier already settles."
argument-hint: "<query> | <object store> <key or id> | <object store> by-<index> <key>"
---

# VLDS recall

> The archive reaches a session only when the owner asks for it.
> Everything the gc pours stays in the cold tier, verbatim, forever; what keeps it from steering is that nothing reads it unasked.

## Where the archive sits

A pour moves an entry's bytes out of its hot file into a run under `idb/runs/`: an immutable file, the entry verbatim with its id kept, and the keyspace's record pointing at it (`at=runs/<run>:<line>`).
An entry past 64 KiB sits in `idb/blobs/<object store>/`, and its run holds a wrap marker that `idb.py get` unwraps.
A freed entry is marked `state=freed` in the keyspace and never removed.
The pool, the SessionStart standing block and the open moment's derivation read the hot files alone, so a new session starts with none of this in its context.

The object stores are the hot files' names without `.md`: `local-storage`, `index`, `data-store`, `ledger`, `tombstones`, `virtual`, `session-storage`, `logger`, `briefs`.
Each session keeps its own store (`.claude/p4/sessions/<s8>/vlds/`) with its own keyspace, so a recall runs `idb.py --store <that store>` per session; `.claude/p4/vindex/keys.tsv` (every session's keyspace line, its session first) and `vindex/sessions.tsv` say which sessions to open. A past message is in that session's own `dispatch.md`. A pre-partition store's poured dispatch record (`idb/blobs/dispatch/`, now under `sessions/_legacy/vlds/`) is an external object, not a record, so a request about a past message reads it through `idb.py blobs dispatch` (the listing) and `idb.py blob dispatch <name>` (one record's text, refused unless the keyspace registers it and it still hashes to the sha recorded for it). A match there is a row whose `fingerprint:` or `addressed:` bears on the request, quoted with the record's name.

## The request

Three forms, told apart by their first word:

- `/vlds:recall <query>` — free text. The operator lists each object store's records with `idb.py range <object store> ""`, keeps the cold ones (`at=runs/…`) whose printed head matches the query, and reads each match whole with `idb.py get`. When the query names an object store (`rulings`, `claims`, `corrections`, …), only that one is listed.
- `/vlds:recall <object store> <key or id>` — a point read: `idb.py get <object store> <key>`, the key a primary key (`<time>|<sha8>`) or an id such as `ls-0012`.
- `/vlds:recall <object store> by-<index> <key>` — an index read: `idb.py find <object store> <index> <key>`, for instance `local-storage by-status FREED` or `data-store by-source unsourced`.

## The flow

1. The session reads nothing under `idb/`. It hands the operator — or the agent the index's `operator-via:` names — one message: the operator brief, `store`, `session`, `now`, `moment: recall`, and the owner's request verbatim.
2. The operator runs the reads its brief's `recall` section names and returns the derivation in that section's shape: every match with its object store, key, id, run location and state, and its text.
3. The session reports the matches to the owner as what they are: archived entries, each one cold because the gc judged it spent, superseded, stale or past its budget.
4. Every match passes the read barrier before it steers anything. A `state=freed` match, or one a tombstone masks, is surfaced and never applied. A live cold match is weakened provenance: it is traced to a live root, a LIVE ruling or the world as it verifies now, before it shapes a decision, and an entry that reaches no root is shown and not followed.

## Back into the hot tier

Nothing recalled is written back, by the operator or by the session.
When the owner rules a recalled entry live again, in words, the turn's close records a new ruling in `local-storage.md` in the owner's words, citing the archived entry by its id (a handle by fact id) so the trace can follow it.
The write barrier traces that ruling against the tombstones like any other allocation, and a re-allocation of freed garbage is the operator's call before anything leans on it.
The cold entry stays where it is: the archive is never edited, only read.

## What it never does

- It never opens `idb/runs/` or `idb/blobs/` as files. `idb.py` validates each read against the keyspace's version and sha — `get`, `range` and `find` for records, `blob` for a dispatch record — and names a hand edit, a moved hint or a missing entry; a file read checks nothing.
- It never feeds the pool, the SessionStart injection or an open moment's derivation. A derivation that would need an archived entry names the gap and that `/vlds:recall` reaches it; it does not fetch the entry.
- It never runs on the session's own initiative. The owner's request is the trigger, and the request's words are what the operator receives.
