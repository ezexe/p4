#!/usr/bin/env python3
"""test_idb.py — acceptance tests for the keyspace engine (scripts/idb.py) and the hooks' keyspace paths: the key
lines and their order, the hot tier's versions and the stale index lines a sync sweeps, the two-phase pour and the
recovery of a crash at each of its steps, the light classes, the dispatch pour as an external object, the freed marks,
compaction, the gentle migration from a real φ store (normalize.py's own segments) with the register of active context
unchanged across it, the rollback, the check's scans, the rollout stages through the Stop hook, the pool's snapshot,
the sync's rounds, a wrapped entry, and a CRLF hot file.

Run from anywhere:  python scripts/test_idb.py
Each test seeds a throwaway project under a temp dir, as test_hooks.py does (its helpers are imported), and runs the
engine, phi.py, normalize.py or the hooks as the harness would. Exit 0 = every test green; the first failing assertion
names the test. Nothing here touches a real store.
"""

import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import idb as engine  # noqa: E402
import phi  # noqa: E402
import test_hooks as th  # noqa: E402 — seed_project, run_hook, the headers

IDB = os.path.join(HERE, "idb.py")
PHI = os.path.join(HERE, "phi.py")
NORM = os.path.join(HERE, "normalize.py")
NOW = "2026-09-29 10:00"

DATA_STORE = """# VLDS Partition — DataStore

Claims verified against a source.

```yaml
- claim: [the claim]
  time: [YYYY-MM-DD HH:MM]
  verified: [what was read]
  source: [where]
```

---
"""

TOMBSTONES = """# VLDS GC — Tombstones

```yaml
- freed: [the decision/rule/claim that was disposed]
  time: [YYYY-MM-DD HH:MM]
  cause: retraction | superseded | fixed-cause | world-drift
  owner-words: "[verbatim]"
  swept: [every store touched]
  lesson: [what survived]
```

---
"""


def run(cmd, root=None):
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=th.PLUGIN)
    if root:
        env["CLAUDE_PROJECT_DIR"] = root
    r = subprocess.run(cmd, capture_output=True, env=env, timeout=180)
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r\n", "\n")


def idb(store, *args):
    return run([sys.executable, IDB, "--store", store, *args])


def phi_cmd(store, *args):
    return run([sys.executable, PHI, "--store", store, *args])


def keys(store):
    with open(os.path.join(store, "idb", "keys.tsv"), encoding="utf-8") as f:
        return f.read()


def key_lines(store):
    return [l.split("\t") for l in keys(store).split("\n") if l and not l.startswith("#")]


def records(store, os_=None):
    return {(p[0], p[2]): dict(kv.split("=", 1) for kv in p[3:]) for p in key_lines(store)
            if p[1] == "01" and (os_ is None or p[0] == os_)}


def meta(store, scope, name):
    return next((p[3] for p in key_lines(store) if p[:3] == [scope, "00", name]), None)


def write(path, text, crlf=False):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n") if crlf else text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def seed_keyspace(logger=0, virtual=(), recall="index-engine: idb-new-stores\n", data=(), tombs=(), sid="test-session"):
    """A project whose index names a keyspace stage and has no φ register — a new store as the keyspace meets it."""
    root, store = th.seed_project(sid)
    write(os.path.join(store, "phi-index.md"), f"# idx\n\n## recall\n\n{recall}")
    with open(os.path.join(store, "logger.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(th.LOGGER_HEADER)
        for i in range(logger):
            f.write(f"\n- `[gc]` 2026-09-03 {10 + i // 60:02d}:{i % 60:02d} — **Entry {i + 1}.** A logged decision, "
                    f"number {i + 1}.\n")
    with open(os.path.join(store, "virtual.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(th.VIRTUAL_HEADER)
        for sid, txt in virtual:
            f.write(f"\n- inference: {txt}\n  time: 2026-09-03 10:30\n  basis: a reading\n  minted: session {sid}, "
                    "turn 1\n  disposition: pending\n")
    with open(os.path.join(store, "data-store.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(DATA_STORE)
        for i, (claim, src) in enumerate(data):
            f.write(f"\n- claim: {claim}\n  time: 2026-09-1{i % 10} 10:00\n  verified: read it\n  source: {src}\n")
    with open(os.path.join(store, "tombstones.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(TOMBSTONES)
        for freed, words, swept in tombs:
            f.write(f"\n- freed: {freed}\n  time: 2026-09-20 09:00\n  cause: retraction\n  owner-words: \"{words}\"\n"
                    f"  swept: {swept}\n  lesson: none\n")
    return root, store


def set_stage(store, stage):
    """The index's `index-engine:` set, as the owner would rule it."""
    idx = os.path.join(store, "phi-index.md")
    write(idx, engine.set_recall_key(read(idx), "index-engine", stage))


def heads(store, fname):
    return [b.line1 for b in engine.hot_blocks(store, fname)]


def clean_check(store, label):
    rc, out = idb(store, "check")
    assert rc == 0 and ", 0 debt" in out and "0 corruption" in out, f"{label}: check not clean:\n{out}"
    return out


# ─── tests ──────────────────────────────────────────────────────────────────────────────────────────────

def test_keyspace_derivation():
    root, store = seed_keyspace(logger=3, data=[("the cap is 10,000 characters", "the hook stream")],
                                tombs=[("go", "go", "local-storage.md")])
    try:
        rc, out = idb(store, "sync", "--session", "derive-session", "--now", NOW)
        assert rc == 0 and "keyspace new" in out and "inserted" in out, out
        lines = [l for l in keys(store).split("\n") if l and not l.startswith("#")]
        assert lines == sorted(lines), "keys.tsv is not in byte order"
        # every row of the barrier — the register of active context — is a record at its own line
        rc, out = phi_cmd(store, "barrier", "--json", "--session", "derive-s")
        rows = json.loads(out)["entries"]
        recs = records(store)
        hot_at = {(os_, int(r["at"][4:])) for (os_, _pk), r in recs.items() if r["at"].startswith("hot:")}
        for row in rows:
            assert (row["file"][:-3], row["line"]) in hot_at, f"barrier row {row['file']}:{row['line']} has no record"
        assert len(hot_at) == len(rows), f"{len(hot_at)} records for {len(rows)} barrier rows"
        # the indexes: by-kind finds the form ruling, by-owner-words joins the SPENT ruling to its tombstone
        rc, out = idb(store, "find", "local-storage", "by-kind", "form")
        assert "find: 1 record(s)" in out and "the plan goes in the reply" in out, out
        words = engine.sha(phi.norm_text("go"), 8)
        rc, a = idb(store, "find", "local-storage", "by-owner-words", words)
        rc, b = idb(store, "find", "tombstones", "32:by-owner-words", words)
        assert "find: 1 record(s)" in a and "find: 1 record(s)" in b, a + b
        rc, out = idb(store, "find", "data-store", "by-source", "sourced")
        assert "find: 1 record(s)" in out, out
        # a primary key is <time>|<sha8 of the head line>, a repeat takes #2
        pk = next(pk for (os_, pk) in recs if os_ == "local-storage" and pk.startswith("2026-09-03 10:00"))
        assert re.fullmatch(r"2026-09-03 10:00\|[0-9a-f]{8}", pk), pk
        with open(os.path.join(store, "logger.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("\n- `[gc]` 2026-09-03 10:00 — **Entry 1.** A logged decision, number 1.\n")
        idb(store, "sync", "--session", "derive-session", "--now", NOW)
        assert any(pk.endswith("#2") for (os_, pk) in records(store, "logger")), "a repeated block has no #2 key"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("keyspace derivation: green")


def test_hand_edit_and_sweep():
    root, store = seed_keyspace()
    try:
        idb(store, "sync", "--session", "edit-session", "--now", NOW)
        ls = os.path.join(store, "local-storage.md")
        before = records(store, "local-storage")
        # the owner edits a status in an editor: no hook fires
        text = read(ls)
        write(ls, text.replace("  status: LIVE\n", "  status: SPENT\n", 1))
        pk = next(pk for (o, pk) in before if pk.startswith("2026-09-03 10:00"))
        rc, out = idb(store, "get", "local-storage", pk)
        assert "BEHIND" in out and "status: SPENT" in out, f"a read before the sync must say it is behind:\n{out}"
        rc, out = idb(store, "sync", "--session", "edit-session", "--now", NOW)
        assert "1 updated" in out and "1 stale index line swept" in out and "31:by-status LIVE|" in out, out
        after = records(store, "local-storage")
        assert int(after[("local-storage", pk)]["v"]) > int(before[("local-storage", pk)]["v"]), "the version did not move"
        assert f"local-storage\t31:by-status\tSPENT|{pk}" in keys(store), "the new index line is missing"
        assert f"local-storage\t31:by-status\tLIVE|{pk}" not in keys(store), "the stale index line was not swept"
        # a head rewrite is a delete and an insert; a removal drops the record
        write(ls, read(ls).replace('- ruling: "go"', '- ruling: "go now"'))
        rc, out = idb(store, "sync", "--session", "edit-session", "--now", NOW)
        assert "1 inserted" in out and "1 dropped" in out, out
        last = int(meta(store, "local-storage", "last-version"))
        assert all(int(r["v"]) <= last for r in records(store, "local-storage").values()), "a version past the counter"
        clean_check(store, "after the edits")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("hand edit + sweep: green")


def test_pour():
    root, store = seed_keyspace(logger=10)
    try:
        idb(store, "sync", "--session", "pour-session", "--now", NOW)
        h = heads(store, "logger.md")
        # (a) four entries — a count the φ-register refuses (Zeckendorf(4) opens two positions) — pour at once
        rc, out = idb(store, "pour", "--session", "pour-session", "--now", NOW, "--dry",
                      f"logger.md:{h[0]},{h[1]},{h[2]},{h[3]}")
        assert rc == 0 and "would pour 4 logger.md" in out, out
        assert not os.path.isdir(os.path.join(store, "idb", "runs")), "the dry run wrote"
        rc, out = idb(store, "pour", "--session", "pour-session", "--now", NOW, f"logger.md:{h[0]},{h[1]},{h[2]},{h[3]}")
        assert rc == 0 and "sweep: poured 4 (4 logger.md) into logger-000001.md" in out, out
        assert th.count_entries(os.path.join(store, "logger.md")) == 7, "6 left + the sweep's own entry"
        cold = {r["id"]: (pk, r) for (o, pk), r in records(store, "logger").items() if "id" in r}
        assert sorted(cold) == ["lg-0001", "lg-0002", "lg-0003", "lg-0004"], cold
        run_lines = read(os.path.join(store, "idb", "runs", "logger-000001.md")).split("\n")
        for rid, (pk, r) in cold.items():
            line = int(r["at"].rsplit(":", 1)[1])
            assert run_lines[line - 1] == f"id: {rid}" and run_lines[line] == f"key: {pk}", f"{rid}'s at= is off"
        rc, out = idb(store, "get", "logger", "lg-0002")
        assert "**Entry 2.**" in out and "state=live" in out, out
        # (b) a line that is not an entry head is refused, nothing written
        rc, out = idb(store, "pour", "--session", "pour-session", "--now", NOW, "logger.md:6")
        assert rc == 1 and "line 6 is not an entry head" in out, out
        # (c) the journal is empty again, the check clean, the index rewritten with the pour
        assert read(os.path.join(store, "idb", "journal.tsv")).strip() == "", "the journal kept a settled intent"
        clean_check(store, "after the pour")
        assert "updated: " + NOW in read(os.path.join(store, "phi-index.md")), "the index was not rewritten"
        assert "| logger.md | 7 | 7 |" in read(os.path.join(store, "phi-index.md")), "at-sweep did not move"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pour: green")


def _crash(name, exc="injected crash"):
    """Replace engine.<name> with a function that raises — a crash at exactly that step."""
    original = getattr(engine, name)

    def boom(*_a, **_k):
        raise RuntimeError(exc)
    setattr(engine, name, boom)
    return original


def test_pour_crash_recovery():
    claims = [("alpha holds", "a"), ("beta holds", "b"), ("gamma holds", "c")]
    # (a) a crash after the run is written, before the keyspace commit: the next pass discards the run
    root, store = seed_keyspace(data=claims)
    try:
        ks = engine.Keyspace.fresh()
        engine.sync(store, ks, NOW)
        engine.save_keys(store, ks)
        h = heads(store, "data-store.md")
        original = _crash("save_keys")
        try:
            engine.do_pour(store, ks, {"data-store.md": h[:2]}, NOW, "crash-se", "a test")
        except RuntimeError:
            pass
        finally:
            engine.save_keys = original
        assert os.path.exists(os.path.join(store, "idb", "runs", "data-store-000001.md")), "(a) the run was not written"
        assert "pending" in read(os.path.join(store, "idb", "journal.tsv")), "(a) no pending intent"
        rc, out = idb(store, "check")
        assert "journal: pour data-store-000001.md still pending" in out, f"(a) check does not see the torn pour:\n{out}"
        rc, out = idb(store, "light", "--session", "crash-session", "--now", NOW)
        assert "recovered a torn pour: data-store-000001.md discarded before its commit" in out, out
        assert not os.path.exists(os.path.join(store, "idb", "runs", "data-store-000001.md")), "(a) the run survived"
        assert th.count_entries(os.path.join(store, "data-store.md")) == 3, "(a) an entry left the hot file"
        clean_check(store, "(a)")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # (b) a crash after the commit, before the trim: the next pass finishes the trim
    # (c) the same, with the owner editing one poured block before that pass: the edit wins
    for edit in (False, True):
        root, store = seed_keyspace(data=claims)
        try:
            ks = engine.Keyspace.fresh()
            engine.sync(store, ks, NOW)
            engine.save_keys(store, ks)
            h = heads(store, "data-store.md")
            original = _crash("trim_blocks")
            try:
                engine.do_pour(store, ks, {"data-store.md": h[:2]}, NOW, "crash-se", "a test")
            except RuntimeError:
                pass
            finally:
                engine.trim_blocks = original
            assert "committed" in read(os.path.join(store, "idb", "journal.tsv")), "(b) no committed intent"
            assert th.count_entries(os.path.join(store, "data-store.md")) == 3, "(b) trimmed before the crash"
            if edit:
                ds = os.path.join(store, "data-store.md")
                write(ds, read(ds).replace("  source: b", "  source: b, re-read by the owner"))
            rc, out = idb(store, "light", "--session", "crash-session", "--now", NOW)
            assert "committed, its trim finished" in out, out
            left = th.count_entries(os.path.join(store, "data-store.md"))
            if not edit:
                assert "(2 trimmed)" in out and left == 1, f"(b) {left} left:\n{out}"
            else:
                assert "1 trimmed, 1 edited since and kept hot" in out and left == 2, f"(c) {left} left:\n{out}"
                assert "re-read by the owner" in read(os.path.join(store, "data-store.md")), "(c) the edit was lost"
                assert "source: b\n" in read(os.path.join(store, "idb", "runs", "data-store-000001.md")), \
                    "(c) the run lost the old text"
            clean_check(store, "(c)" if edit else "(b)")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print("pour crash recovery: green")


def test_light_through_the_hook():
    root, store = seed_keyspace(logger=40, virtual=[("other-session", "an inference another session minted"),
                                                    ("light-session", "an inference this session minted")],
                                sid="light-session")
    try:
        out = th.run_hook("turn-close", {"session_id": "light-session", "cwd": root}, root)
        assert out.startswith("turn-close: keyspace started"), f"(a) report:\n{out}"
        assert "poured 16 (15 logger.md, 1 virtual.md)" in out and "idb.py check: 0 corruption, 0 debt" in out, out
        assert th.count_entries(os.path.join(store, "logger.md")) == 26, "40 - 15 + the pass's own entry"
        assert th.count_entries(os.path.join(store, "virtual.md")) == 1, "this session's inference was poured"
        virt = next(n for n in os.listdir(os.path.join(store, "idb", "runs")) if n.startswith("virtual-"))
        assert "disposition: expired (turn close" in read(os.path.join(store, "idb", "runs", virt)), "no expiry reason"
        assert not os.path.isdir(os.path.join(store, "arc")), "the keyspace wrote into arc/"
        out = th.run_hook("prompt-open", {"session_id": "light-session", "prompt": "next"}, root)
        assert "- turn-close (" in out and "poured 16" in out, f"(b) the report at the next prompt:\n{out}"
        out = th.run_hook("turn-close", {"session_id": "light-session", "cwd": root}, root)
        assert out.strip() == "", f"(b) a pass with nothing to move printed:\n{out}"
        # (c) a fresh lock held by another session skips the pass and says so
        with open(os.path.join(store, "idb", ".sweep-lock"), "w", encoding="utf-8") as f:
            f.write("holder-session 2026-09-29 10:00:00\n")
        out = th.run_hook("turn-close", {"session_id": "light-session", "cwd": root}, root)
        assert "skipped" in out and "holder-session" in out, f"(c) the lock not honoured:\n{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("light through the hook: green")


def test_dispatch_blob():
    """Every session keeps its own dispatch record in its own store: a second session's first prompt seeds and stamps
    its own, the first session's record stays whole where it was, and no dated pour is written anywhere."""
    root, store = seed_keyspace(sid="first-session")
    try:
        th.run_hook("prompt-open", {"session_id": "first-session", "prompt": "commit"}, root)
        th.run_hook("prompt-open", {"session_id": "first-session", "prompt": "commit"}, root)
        th.run_hook("turn-close", {"session_id": "first-session", "cwd": root}, root)
        before = read(os.path.join(store, "dispatch.md"))
        assert before.count('- fingerprint: "commit"') == 2, before[-400:]
        out = th.run_hook("prompt-open", {"session_id": "second-session", "prompt": "hello there", "_keep_sid": True},
                          root)
        second = th.store_of(root, "second-session")
        assert "session store: .claude/p4/sessions/second-s/vlds/" in out, out
        assert '- fingerprint: "hello there"' in read(os.path.join(second, "dispatch.md")), "no row in the second store"
        assert read(os.path.join(store, "dispatch.md")) == before, "the first session's record changed"
        for d in (store, second):
            assert not os.path.isdir(os.path.join(d, "idb", "blobs", "dispatch")), f"a dated pour in {d}"
        # the owner voice and a known command read across both sessions' records
        out = th.run_hook("prompt-open", {"session_id": "second-session", "prompt": "commit", "_keep_sid": True}, root)
        assert "known" in out and "commit" in out, f"a known command not derived across sessions:{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("dispatch per session: green")


def test_freed_marks():
    root, store = seed_keyspace()
    try:
        idb(store, "sync", "--session", "free-session", "--now", NOW)
        h = heads(store, "local-storage.md")
        idb(store, "pour", "--session", "free-session", "--now", NOW, f"local-storage.md:{h[1]}")
        rec = next(r for r in records(store, "local-storage").values() if r.get("id") == "ls-0001")
        assert rec["state"] == "live", rec
        # a tombstone with the same owner-words frees the cold ruling at the next pass — a marker, nothing removed
        ts = os.path.join(store, "tombstones.md")
        write(ts, TOMBSTONES + '\n- freed: "go"\n  time: 2026-09-29 09:00\n  cause: retraction\n  owner-words: "go"\n'
                               "  swept: local-storage.md\n  lesson: none\n")
        idb(store, "sync", "--session", "free-session", "--now", NOW)
        rec = next(r for r in records(store, "local-storage").values() if r.get("id") == "ls-0001")
        tomb = next(pk for (o, pk) in records(store, "tombstones"))
        assert rec["state"] == "freed" and rec["ts"] == tomb, rec
        rc, out = idb(store, "get", "local-storage", "ls-0001")
        assert "FREED by" in out and "go" in out, out
        # the free is derived: the tombstone gone, the record is live again; named by id in swept:, freed again
        write(ts, TOMBSTONES)
        idb(store, "sync", "--session", "free-session", "--now", NOW)
        assert next(r for r in records(store, "local-storage").values() if r.get("id") == "ls-0001")["state"] == "live"
        write(ts, TOMBSTONES + "\n- freed: an older rule\n  time: 2026-09-29 09:05\n  cause: superseded\n"
                               "  owner-words: \"\"\n  swept: local-storage.md ls-0001\n  lesson: none\n")
        idb(store, "sync", "--session", "free-session", "--now", NOW)
        assert next(r for r in records(store, "local-storage").values() if r.get("id") == "ls-0001")["state"] == "freed"
        run = next(n for n in os.listdir(os.path.join(store, "idb", "runs")) if n.startswith("local-storage-"))
        assert 'owner-words: "go"' in read(os.path.join(store, "idb", "runs", run)), "a freed entry left its run"
        clean_check(store, "after the freed marks")
        # the marks read the tombstones as they stand: one added at the top, and a pour's commit — nothing else
        # synced, the process gone before its trim — already carries the free
        write(ts, TOMBSTONES)
        with open(os.path.join(store, "logger.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("\n- `[gc]` 2026-09-03 10:00 — **Entry.** A logged decision.\n")
        idb(store, "sync", "--session", "free-session", "--now", NOW)
        write(ts, TOMBSTONES.replace("---\n", "---\n\n- freed: \"go\"\n  time: 2026-09-29 09:10\n  cause: retraction\n"
                                     "  owner-words: \"go\"\n  swept: local-storage.md\n  lesson: none\n", 1))
        ks, _how = engine.load_keys(store)
        original = _crash("trim_blocks")
        try:
            engine.do_pour(store, ks, {"logger.md": heads(store, "logger.md")[:1]}, NOW, "free-ses", "a test")
        except RuntimeError:
            pass
        finally:
            engine.trim_blocks = original
        rec = next(r for r in records(store, "local-storage").values() if r.get("id") == "ls-0001")
        assert rec["state"] == "freed", f"the commit carried a stale mark: {rec}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("freed marks: green")


def test_compaction():
    root, store = seed_keyspace(logger=8)
    try:
        idb(store, "sync", "--session", "comp-session", "--now", NOW)
        for _ in range(4):
            idb(store, "pour", "--session", "comp-session", "--now", NOW, f"logger.md:{heads(store, 'logger.md')[0]}")
        runs = sorted(os.listdir(os.path.join(store, "idb", "runs")))
        assert runs == [f"logger-00000{i}.md" for i in range(1, 5)], runs
        rc, out = idb(store, "compact", "--session", "comp-session", "--now", NOW)
        assert "compacted logger: 4 runs → logger-000005.md" in out, out
        assert sorted(os.listdir(os.path.join(store, "idb", "runs"))) == ["logger-000005.md"], "the parents stayed"
        for rid in ("lg-0001", "lg-0002", "lg-0003", "lg-0004"):
            rc, out = idb(store, "get", "logger", rid)
            assert rc == 0 and "at=runs/logger-000005.md:" in out and "note:" not in out, out
        clean_check(store, "after the compaction")
        # a crash after the children are written, before the commit: the next pass discards them
        for _ in range(2):
            idb(store, "pour", "--session", "comp-session", "--now", NOW, f"logger.md:{heads(store, 'logger.md')[0]}")
        ks, _how = engine.load_keys(store)
        original = _crash("save_keys")
        try:
            engine.compact(store, ks, NOW, "comp-ses", force=True)
        except RuntimeError:
            pass
        finally:
            engine.save_keys = original
        rc, out = idb(store, "light", "--session", "comp-session", "--now", NOW)
        assert "recovered a torn compaction" in out and "discarded before its commit" in out, out
        clean_check(store, "after the torn compaction")
        # --force compacts two small runs at once; the next earliest time is set 1-3 days out
        rc, out = idb(store, "compact", "--session", "comp-session", "--now", NOW, "--force")
        assert "compacted logger: 3 runs" in out, out
        when = meta(store, "@", "earliest-compaction")
        delta = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M") - datetime.datetime.strptime(NOW, "%Y-%m-%d %H:%M")
        assert datetime.timedelta(days=1) <= delta <= datetime.timedelta(days=3), when
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("compaction: green")


def seed_phi_store():
    """A φ store as normalize.py leaves it: two segments, an attachment, a hook-poured record left unregistered."""
    root, store = th.seed_project()
    th.seed_register(store, logger_entries=40, virtual=[("other-session", "an inference another session minted")])
    arc = os.path.join(store, "arc")
    with open(os.path.join(arc, "dispatch-20260903-100000-other-se.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# VLDS Partition — Dispatch\n\n---\n\n- fingerprint: \"commit\"\n  time: 2026-09-03 10:00\n"
                "  arrival: turn\n  addressed: committed\n")
    out = th.run_hook("turn-close", {"session_id": "phi-session", "cwd": root}, root)
    assert "poured 13" in out and "attached" in out, f"the φ light sweep did not run:\n{out}"
    rc, out = run([sys.executable, NORM, "--store", store, "--session", "phi-session", "--now", "2026-09-03 11:00",
                   "--pour", f"logger.md:{heads(store, 'logger.md')[0]}"])
    assert "sweep: poured 1" in out, out
    with open(os.path.join(arc, "dispatch-20260904-090000-later-se.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# VLDS Partition — Dispatch\n\n---\n\n- fingerprint: \"push it\"\n  time: 2026-09-04 09:00\n"
                "  arrival: turn\n")
    assert "0 corruption" in th.run_check(store), th.run_check(store)
    return root, store


def pool_without_updated(store):
    rc, out = phi_cmd(store, "pool", "--session", "same-ses", "--task", "a task", "--now", NOW)
    # the updated: line is the index's own news, and the room the skeleton reports is counted with it
    return "\n".join(re.sub(r"about \d+ characters of room", "about N characters of room", l) for l in out.split("\n")
                     if "updated:" not in l and not l.startswith("pool-road:"))


def test_migration():
    root, store = seed_phi_store()
    try:
        arc = os.path.join(store, "arc")
        segs = sorted(f for f in os.listdir(arc) if f.startswith("arc-"))
        entries = {}
        for seg in segs:
            _h, es, _i = phi.parse_segment(os.path.join(arc, seg))
            for e in es:
                first, _nl, rest = e.partition("\n")
                entries[first.split()[1]] = rest.lstrip("\n")
        blobs = {f: engine.file_sha(os.path.join(arc, f)) for f in os.listdir(arc) if f.startswith("dispatch-")}
        logger = os.path.join(store, "logger.md")
        with open(logger, "rb") as f:
            logger_before = f.read()
        barrier_before = phi_cmd(store, "barrier", "--session", "same-ses")[1]
        standing_before = phi_cmd(store, "standing", "--session", "same-ses")[1]
        pool_before = pool_without_updated(store)
        # (a) the dry run imports and verifies in a temporary directory, writing nothing
        rc, out = idb(store, "migrate", "--session", "mig-session", "--now", NOW, "--dry")
        assert rc == 0 and "migration would pass" in out and f"{len(entries)} entries" in out, out
        assert not os.path.exists(os.path.join(store, "idb")) and os.path.isdir(arc), "(a) the dry run wrote"
        # (b) the stage names the migration; the Stop hook runs it, then the keyspace's pass
        idx = os.path.join(store, "phi-index.md")
        set_stage(store, "idb-migrate-gentle")
        recall_before = read(idx).split("## recall", 1)[1].split("## epochs")[0]
        out = th.run_hook("turn-close", {"session_id": "mig-session", "cwd": root}, root)
        assert "turn-close: migrated to the keyspace" in out and "arc/ moved to arc.phi-retired/" in out, out
        assert not os.path.exists(arc) and os.path.isdir(os.path.join(store, "arc.phi-retired")), "(b) arc/ not aside"
        assert os.path.exists(os.path.join(store, "arc.phi-retired", "phi-index.md")), "(b) the φ index not saved"
        # every entry verbatim under its old id; every record, blob and at= resolves
        cold = {r["id"]: (os_, pk) for (os_, pk), r in records(store).items() if "id" in r}
        for rid, body in entries.items():
            assert rid in cold, f"{rid} missing from the keyspace"
            rc, out = idb(store, "get", cold[rid][0], rid)
            assert body in out and "note:" not in out, f"{rid} not verbatim:\n{out}"
        for name, digest in blobs.items():
            line = next(l for l in keys(store).split("\n") if l.startswith(f"dispatch\t03\t{name}"))
            assert f"sha={digest}" in line and "from=arc" in line, line
        # the index in the keyspace's shape: the register retired, ## recall verbatim
        text = read(idx)
        assert "register:" not in text and "## positions" not in text and "## epochs" not in text, text
        assert recall_before.strip() in text, "the ## recall section changed"
        rc, out = phi_cmd(store, "check")
        assert rc == 0 and "idb.py check: 0 corruption, 0 debt" in out, f"(b) phi.py check did not delegate:\n{out}"
        # (c) the register of active context did not move: the migration's only hot write is its own logger line,
        # appended; with the logger held at its old bytes, the barrier, the standing rules and the pool read the same
        with open(logger, "rb") as f:
            logger_after = f.read()
        assert logger_after.startswith(logger_before) and b"Migrated to the keyspace" in logger_after[len(logger_before):] \
            and logger_after[len(logger_before):].count(b"\n- ") == 1, "the migration wrote more than its logger line"
        with open(logger, "wb") as f:
            f.write(logger_before)
        assert phi_cmd(store, "barrier", "--session", "same-ses")[1] == barrier_before, "the barrier changed"
        assert phi_cmd(store, "standing", "--session", "same-ses")[1] == standing_before, "the standing rules changed"
        assert pool_without_updated(store) == pool_before, "the pool changed beyond its updated: line"
        with open(logger, "wb") as f:
            f.write(logger_after)
        # a stray φ lock on the migrated store is refused, and a lock-only arc/ is cleared, never retired again
        rc, out = phi_cmd(store, "lock", "some-session")
        assert rc == 1 and "the store is on the keyspace" in out and not os.path.exists(arc), out
        os.makedirs(arc)
        write(os.path.join(arc, ".sweep-lock"), "old 2026-09-01 10:00:00\n")
        idb(store, "light", "--session", "mig-session", "--now", NOW)
        assert not os.path.exists(arc) and not os.path.exists(os.path.join(store, "arc.phi-retired.2")), \
            "a lock-only arc/ was retired"
        # (d) the session opens on the keyspace
        out = th.run_hook("session-open", {"source": "startup", "session_id": "mig-session"}, root)
        assert "### keyspace — digest" in out and "engine: idb (index-engine: idb-migrate-gentle)" in out, out
        assert "migrated: " in out and "### idb.py check" in out and "idb.py check: 0 corruption" in out, out
        assert "idb.py --store <store> pour" in out and "held when the last sweep" not in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("migration: green")


def test_migration_refused():
    root, store = seed_phi_store()
    try:
        seg = sorted(f for f in os.listdir(os.path.join(store, "arc")) if f.startswith("arc-"))[0]
        path = os.path.join(store, "arc", seg)
        write(path, re.sub(r"^verified: .*\n", "", read(path), flags=re.M))
        rc, out = idb(store, "migrate", "--session", "ref-session", "--now", NOW)
        assert rc == 1 and "refused — the φ check reports corruption" in out and "verified:" in out, out
        idx = os.path.join(store, "phi-index.md")
        set_stage(store, "idb-migrate-gentle")
        out = th.run_hook("turn-close", {"session_id": "ref-session", "cwd": root}, root)
        assert "the migration to the keyspace waits — refused" in out, f"the refusal not said:\n{out}"
        out = th.run_hook("turn-close", {"session_id": "ref-session", "cwd": root}, root)
        assert "waits" not in out, f"the same refusal said twice:\n{out}"
        assert not os.path.exists(os.path.join(store, "idb")) and os.path.isdir(os.path.join(store, "arc")), \
            "a refused migration moved something"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("migration refused: green")


def test_migration_legacy_shapes():
    """The φ era's odd corners: an id annotated `(tombstoned)`, a legacy per-session record attached to a segment."""
    root, store = seed_phi_store()
    try:
        arc = os.path.join(store, "arc")
        seg = sorted(f for f in os.listdir(arc) if f.startswith("arc-"))[-1]
        path = os.path.join(arc, seg)
        text = read(path)
        first_id = re.search(r"^id: ([a-z]{2}-\d{4})$", text, re.M).group(1)
        text = text.replace(f"id: {first_id}\n", f"id: {first_id} (tombstoned)\n", 1)
        text = re.sub(r"^(verified: .*)$", r"\1\nattached: dispatch-a1b2c3d4.md", text, count=1, flags=re.M) \
            if "attached:" not in text else text.replace("attached: ", "attached: dispatch-a1b2c3d4.md, ", 1)
        write(path, text)
        write(os.path.join(arc, "dispatch-a1b2c3d4.md"), "# legacy record\n\n---\n\n- fingerprint: \"old\"\n")
        assert "0 corruption" in th.run_check(store), th.run_check(store)
        rc, out = idb(store, "migrate", "--session", "leg-session", "--now", NOW)
        assert rc == 0 and "migrated to the keyspace" in out, out
        rec = next(r for r in records(store).values() if r.get("id") == first_id)
        assert rec["state"] == "freed" and rec["ts"] == "annotation", rec
        line = next(l for l in keys(store).split("\n") if l.startswith("legacy\t03\tdispatch-a1b2c3d4.md"))
        assert "from=arc" in line and "blob=blobs/legacy/dispatch-a1b2c3d4.md" in line, line
        clean_check(store, "after the legacy migration")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("migration legacy shapes: green")


def test_migration_crash_after_commit():
    """The commit point is the rename of idb.tmp/ to idb/: a crash after it leaves a keyspace, a φ index and an arc/ —
    the next pass is the keyspace's, which finishes the migration; the φ sweep never runs over the imported arc/."""
    root, store = seed_phi_store()
    try:
        idx = os.path.join(store, "phi-index.md")
        set_stage(store, "idb-migrate-gentle")
        original = _crash("finish_migration", "power cut")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    engine.cmd_migrate(store, "crash-session", NOW)
                except RuntimeError:
                    pass
        finally:
            engine.finish_migration = original
        assert os.path.exists(os.path.join(store, "idb", "keys.tsv")) and os.path.isdir(os.path.join(store, "arc")), \
            "the crash state is not a committed keyspace beside arc/"
        rc, out = run([sys.executable, NORM, "--store", store, "--session", "x", "--light"])
        assert rc == 1 and "refused — the store is on the keyspace" in out, out
        segs = sorted(os.listdir(os.path.join(store, "arc")))
        out = th.run_hook("turn-close", {"session_id": "crash-session", "cwd": root}, root)
        assert "arc/ moved to arc.phi-retired/" in out and "into arc-" not in out, f"the pass after the crash:\n{out}"
        assert sorted(os.listdir(os.path.join(store, "arc.phi-retired"))) == sorted(segs + ["phi-index.md"]), \
            "the retired arc is not the imported one"
        assert "register:" not in read(idx), "the index was not rewritten"
        clean_check(store, "after the finished migration")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("migration crash after commit: green")


def test_rollback():
    root, store = seed_phi_store()
    try:
        idx = os.path.join(store, "phi-index.md")
        set_stage(store, "idb-migrate-gentle")
        rc, out = idb(store, "migrate", "--session", "rb-session", "--now", NOW)
        assert rc == 0 and "migrated to the keyspace" in out, out
        # the owner edits the recall section after the migration; the rollback keeps the edit
        write(idx, read(idx).replace("digest: logger.md\n", "digest: logger.md, data-store.md\n"))
        rc, out = idb(store, "rollback", "--session", "rb-session", "--now", NOW)
        assert rc == 0 and "on the φ-register again" in out, out
        assert os.path.isdir(os.path.join(store, "arc")) and not os.path.exists(os.path.join(store, "idb")), out
        text = read(idx)
        assert "register: " in text and "index-engine: phi" in text and "digest: logger.md, data-store.md" in text, text
        assert "0 corruption" in th.run_check(store), th.run_check(store)
        # after pours: the entries poured since the migration return to their hot files, verbatim
        set_stage(store, "idb")
        th.run_hook("turn-close", {"session_id": "rb-session", "cwd": root}, root)
        first = engine.hot_blocks(store, "logger.md")[0]
        idb(store, "pour", "--session", "rb-session", "--now", NOW, f"logger.md:{first.line1}")
        assert first.text not in read(os.path.join(store, "logger.md")), "the pour did not trim"
        rc, out = idb(store, "rollback", "--session", "rb-session", "--now", NOW)
        assert rc == 0 and "1 entr(ies) poured since the migration back in their hot files (1 to logger.md)" in out, out
        assert first.text in read(os.path.join(store, "logger.md")), "the poured entry did not return"
        assert "0 corruption" in th.run_check(store), th.run_check(store)
        # history in the runs — the old text a trim recovery kept when the owner edited a poured entry — is kept in
        # arc/, never deleted with idb/
        set_stage(store, "idb")
        th.run_hook("turn-close", {"session_id": "rb-session", "cwd": root}, root)
        ks, _how = engine.load_keys(store)
        victim = engine.hot_blocks(store, "local-storage.md")[0]     # a continuation edit keeps its key
        original = _crash("trim_blocks")
        try:
            engine.do_pour(store, ks, {"local-storage.md": [victim.line1]}, NOW, "rb-ses", "a test")
        except RuntimeError:
            pass
        finally:
            engine.trim_blocks = original
        ls = os.path.join(store, "local-storage.md")
        write(ls, read(ls).replace(victim.text, victim.text.replace("scope: durable", "scope: durable, re-read")))
        rc, out = idb(store, "light", "--session", "rb-session", "--now", NOW)
        assert "1 edited since and kept hot" in out, out
        rc, out = idb(store, "rollback", "--session", "rb-session", "--now", NOW)
        assert rc == 0 and "1 history entr(ies) kept in arc/keyspace-history-" in out, out
        hist = next(n for n in os.listdir(os.path.join(store, "arc")) if n.startswith("keyspace-history-"))
        assert victim.text in read(os.path.join(store, "arc", hist)), "the history text was not kept"
        os.remove(os.path.join(store, "arc", hist))
        # a record the prompt hook poured and no sync has registered yet still moves; a crash after the returns, and
        # one after arc/ came back, are both resumed by running the rollback again — nothing returned twice
        set_stage(store, "idb")
        th.run_hook("turn-close", {"session_id": "rb-session", "cwd": root}, root)
        first = engine.hot_blocks(store, "logger.md")[0]
        idb(store, "pour", "--session", "rb-session", "--now", NOW, f"logger.md:{first.line1}")
        th.run_hook("prompt-open", {"session_id": "rb-session", "prompt": "a row for the record"}, root)
        # the prompt hook pours nothing since the p4 layout; a pre-partition store's unregistered pour stands in
        bdir = os.path.join(store, "idb", "blobs", "dispatch")
        os.makedirs(bdir, exist_ok=True)
        shutil.copy(os.path.join(store, "dispatch.md"), os.path.join(bdir, "dispatch-20260929-100000-rb-sessi.md"))
        poured = os.listdir(bdir)
        unregistered = [n for n in poured if f"dispatch\t03\t{n}" not in keys(store)]
        assert unregistered, "the fresh pour was already registered — the case is not under test"
        original = _crash("splice_section")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    engine.cmd_rollback(store, "rb-session", NOW)
                except RuntimeError:
                    pass
        finally:
            engine.splice_section = original
        assert os.path.exists(os.path.join(store, "idb", engine.ROLLBACK_MARK)), "the returns were not marked"
        rc, out = idb(store, "light", "--session", "rb-session", "--now", NOW)
        assert "a rollback is mid-way" in out, f"the keyspace's pass ran during a rollback:\n{out}"
        real_move = shutil.move
        engine.shutil.move = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("power cut"))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    engine.cmd_rollback(store, "rb-session", NOW)
                except RuntimeError:
                    pass
        finally:
            engine.shutil.move = real_move
        assert os.path.isdir(os.path.join(store, "arc")) and os.path.isdir(os.path.join(store, "idb")), \
            "the second crash is not between arc/'s return and the end"
        rc, out = idb(store, "rollback", "--session", "rb-session", "--now", NOW)
        assert rc == 0 and "returned before a crash" not in out and "on the φ-register again" in out, out
        assert read(os.path.join(store, "logger.md")).count(first.text) == 1, "an entry was returned twice"
        for n in unregistered:
            assert os.path.exists(os.path.join(store, "arc", n)), f"{n} was not moved into arc/"
        assert not os.path.exists(os.path.join(store, "idb")) and "index-engine: phi" in read(idx), "not finished"
        assert "0 corruption" in th.run_check(store), th.run_check(store)
        # an archived entry edited in the keyspace refuses the rollback: the returning arc would lose the edit
        set_stage(store, "idb")
        th.run_hook("turn-close", {"session_id": "rb-session", "cwd": root}, root)
        run = sorted(n for n in os.listdir(os.path.join(store, "idb", "runs")) if n.startswith("logger-"))[0]
        rp = os.path.join(store, "idb", "runs", run)
        write(rp, read(rp).replace("A logged decision, number 1.", "A logged decision, number one.", 1))
        rc, out = idb(store, "rollback", "--session", "rb-session", "--now", NOW)
        assert rc == 1 and "edited in the keyspace since the migration" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("rollback: green")


def test_check_scans():
    root, store = seed_keyspace(logger=6)
    try:
        idb(store, "sync", "--session", "chk-session", "--now", NOW)
        idb(store, "pour", "--session", "chk-session", "--now", NOW, f"logger.md:{heads(store, 'logger.md')[0]}")
        kp = os.path.join(store, "idb", "keys.tsv")
        good = read(kp)
        lines = good.split("\n")
        # out of order → corruption, and the next pass rebuilds from the files
        a, b = 1, len(lines) - 2
        lines[a], lines[b] = lines[b], lines[a]
        write(kp, "\n".join(lines))
        rc, out = idb(store, "check")
        assert rc == 1 and "out of order" in out, out
        rc, out = idb(store, "light", "--session", "chk-session", "--now", NOW)
        assert "keyspace rebuilt from the files" in out, out
        clean_check(store, "after the rebuild")
        # a stale index line → debt, swept by the next sync; a counter lowered → corruption
        good = read(kp)
        stale = good.split("\n")
        row = next(i for i, l in enumerate(stale) if "\t30:by-kind\t" in l)
        stale[row] = re.sub(r"v=\d+$", "v=999", stale[row])
        write(kp, "\n".join(stale))
        rc, out = idb(store, "check")
        assert "1 stale index line(s)" in out, out
        idb(store, "sync", "--session", "chk-session", "--now", NOW)
        clean_check(store, "after the sweep")
        good = read(kp)
        write(kp, re.sub(r"^(logger\t00\tlast-version\t)\d+", r"\g<1>1", good, flags=re.M))
        rc, out = idb(store, "check")
        assert rc == 1 and "past last-version 1" in out, out
        write(kp, good)
        # a blob gone → corruption; an unregistered blob → debt; an open intent → debt; a duplicate id → corruption
        bd = os.path.join(store, "idb", "blobs", "dispatch")
        os.makedirs(bd)
        write(os.path.join(bd, "dispatch-20260902-100000-extra-se.md"), "# d\n\n---\n\n- fingerprint: \"x\"\n")
        rc, out = idb(store, "check")
        assert "unregistered — the next sync registers it" in out, out
        idb(store, "sync", "--session", "chk-session", "--now", NOW)
        clean_check(store, "after the registration")
        os.remove(os.path.join(bd, "dispatch-20260902-100000-extra-se.md"))
        rc, out = idb(store, "check")
        assert rc == 1 and "missing from idb/blobs/dispatch/" in out, out
        write(kp, "\n".join(l for l in read(kp).split("\n") if not l.startswith("dispatch\t03\t")))
        with open(os.path.join(store, "idb", "journal.tsv"), "a", encoding="utf-8", newline="\n") as f:
            f.write("2026-09-29 10:00:00\tpour\tlogger-000077.md\tpending\twrapped=\n")
        rc, out = idb(store, "check")
        assert "journal: pour logger-000077.md still pending" in out, out
        write(os.path.join(store, "idb", "journal.tsv"), "")
        dup = next(l for l in read(kp).split("\n") if l.startswith("logger\t01\t") and "\tid=lg-0001" in l)
        hot = next(l for l in read(kp).split("\n") if l.startswith("logger\t01\t") and "\tat=hot:" in l)
        write(kp, read(kp).replace(hot, hot + "\tid=lg-0001"))
        rc, out = idb(store, "check")
        assert rc == 1 and "id lg-0001 held by 2 records" in out, out
        assert dup
        # a damaged run: the rebuild's counter steps past it, and the check names it
        idb(store, "pour", "--session", "chk-session", "--now", NOW, f"logger.md:{heads(store, 'logger.md')[0]}")
        top = sorted(n for n in os.listdir(os.path.join(store, "idb", "runs")) if n.startswith("logger-"))[-1]
        tp = os.path.join(store, "idb", "runs", top)
        good_run = read(tp)
        write(tp, good_run.replace("```yaml", "yaml", 1))
        write(kp, read(kp).replace("\t", " ", 1))
        rc, out = idb(store, "light", "--session", "chk-session", "--now", NOW)
        assert "keyspace rebuilt from the files" in out, out
        assert int(meta(store, "@", "next-run")) == int(top[len("logger-"):-3]) + 1, meta(store, "@", "next-run")
        rc, out = idb(store, "check")
        assert rc == 1 and f"runs/{top} does not parse" in out, out
        write(tp, good_run)
        idb(store, "sync", "--session", "chk-session", "--now", NOW, "--full")
        clean_check(store, "after the run was repaired")
        # keys.tsv gone: the store is still on the keyspace, and the next pass rebuilds it from the runs
        os.remove(kp)
        rc, out = idb(store, "engine")
        assert "engine: idb" in out, out
        rc, out = idb(store, "light", "--session", "chk-session", "--now", NOW)
        assert "rebuilt from the files (keys.tsv was missing)" in out, out
        rc, out = idb(store, "get", "logger", "lg-0001")
        assert rc == 0 and "**Entry 1.**" in out, out
        clean_check(store, "after the rebuild from the runs")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("check scans: green")


def test_stages():
    # idb-control: the φ sweep runs, the shadow's verdict is said once, and nothing lands in the store
    root, store = seed_phi_store()
    try:
        idx = os.path.join(store, "phi-index.md")
        set_stage(store, "idb-control")
        out = th.run_hook("turn-close", {"session_id": "stage-session", "cwd": root}, root)
        assert "turn-close: shadow: migration would pass" in out, out
        assert not os.path.exists(os.path.join(store, "idb")), "the shadow wrote into the store"
        out = th.run_hook("turn-close", {"session_id": "stage-session", "cwd": root}, root)
        assert "shadow" not in out, f"the same verdict said twice:\n{out}"
        out = th.run_hook("session-open", {"source": "startup", "session_id": "stage-session"}, root)
        assert "engine: phi (index-engine: idb-control)" in out and "### phi.py check" in out, out
        # idb-new-stores: a φ store stays φ
        set_stage(store, "idb-new-stores")
        with open(os.path.join(store, "logger.md"), "a", encoding="utf-8", newline="\n") as f:
            for i in range(20):
                f.write(f"\n- `[gc]` 2026-09-05 10:{i:02d} — **Late {i}.** More.\n")
        out = th.run_hook("turn-close", {"session_id": "stage-session", "cwd": root}, root)
        assert "into arc-" in out and not os.path.exists(os.path.join(store, "idb")), f"a φ store left φ:\n{out}"
        # phi: the stage a store names to stay on the φ-register, whatever the default
        set_stage(store, "phi")
        with open(os.path.join(store, "logger.md"), "a", encoding="utf-8", newline="\n") as f:
            for i in range(20):
                f.write(f"\n- `[gc]` 2026-09-06 10:{i:02d} — **Later {i}.** More.\n")
        out = th.run_hook("turn-close", {"session_id": "stage-session", "cwd": root}, root)
        assert "into arc-" in out and not os.path.exists(os.path.join(store, "idb")), f"a store naming phi left φ:\n{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # the default, idb-migrate-gentle: a φ store that names no stage is told at SessionStart, in either pool mode, that
    # it migrates at the next turn close, and it does — the stage left unnamed, so the store keeps following the default
    assert engine.DEFAULT_ENGINE == "idb-migrate-gentle", engine.DEFAULT_ENGINE
    root, store = seed_phi_store()
    try:
        idx = os.path.join(store, "phi-index.md")
        write(idx, read(idx).replace("index-engine: phi\n", ""))
        owed = ("engine: phi (index-engine: idb-migrate-gentle, the default) — migrates to the keyspace at the next turn "
                "close once the φ check is clean")
        out = th.run_hook("session-open", {"source": "startup", "session_id": "stage-session"}, root)
        assert owed in out, f"the migration the default owes was not announced:\n{out}"
        write(idx, engine.set_recall_key(read(idx), "pool", "inject"))
        out = th.run_hook("session-open", {"source": "startup", "session_id": "stage-session"}, root)
        assert owed in out and "### inject" in out, f"inject mode did not announce the migration:\n{out}"
        write(idx, read(idx).replace("pool: inject\n", ""))
        out = th.run_hook("turn-close", {"session_id": "stage-session", "cwd": root}, root)
        assert "turn-close: migrated to the keyspace" in out and os.path.isdir(os.path.join(store, "arc.phi-retired")), out
        assert "index-engine" not in read(idx), "the migration wrote the stage the default chose into the index"
        rc, out = idb(store, "engine")
        assert "engine: idb (index-engine: idb-migrate-gentle; the store: idb)" in out, out
        out = th.run_hook("session-open", {"source": "startup", "session_id": "stage-session"}, root)
        assert "engine: idb (index-engine: idb-migrate-gentle, the default)" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # ...and a new store starts on the keyspace: nothing is poured, its first turn close writes the keyspace and the
    # index, and no arc/ ever appears
    root, store = th.seed_project()
    try:
        out = th.run_hook("session-open", {"source": "startup", "session_id": "new-session"}, root)
        assert "the keyspace writes it at the first turn close" in out, out
        th.run_hook("prompt-open", {"session_id": "new-session", "prompt": "a first row"}, root)
        th.run_hook("prompt-open", {"session_id": "next-session", "prompt": "hello"}, root)
        assert not os.path.isdir(os.path.join(store, "idb", "blobs", "dispatch")), "a new store poured its record"
        th.run_hook("turn-close", {"session_id": "next-session", "cwd": root}, root)
        assert os.path.exists(os.path.join(store, "idb", "keys.tsv")), "a new store's first turn close wrote no keyspace"
        assert os.path.exists(os.path.join(store, "phi-index.md")), "a new store's first turn close wrote no index"
        assert not os.path.exists(os.path.join(store, "arc")), "a new store grew an arc/"
        clean_check(store, "a new store at the default")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # idb: every store on the keyspace — a φ store migrates at its next turn close
    root, store = seed_phi_store()
    try:
        idx = os.path.join(store, "phi-index.md")
        set_stage(store, "idb")
        out = th.run_hook("turn-close", {"session_id": "stage-session", "cwd": root}, root)
        assert "migrated to the keyspace" in out, out
        out = th.run_hook("post-write", th.write(os.path.join(store, "ledger.md"), "x", root), root)
        assert "idb.py check:" in out, f"the post-write verdict is not the keyspace's:\n{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("stages: green")


def test_pool_stamp():
    root, store = seed_keyspace(sid="pool-session")
    try:
        th.run_hook("turn-close", {"session_id": "pool-session", "cwd": root}, root)
        pool = os.path.join(store, "recall-pool.md")
        write(pool, "# VLDS Recall Pool\n\nsession: pool-ses \"A title\"\ntask: t\npooled: 2026-09-29 10:00\n")
        old = datetime.datetime(2026, 9, 1, 10, 0).timestamp()
        os.utime(pool, (old, old))
        th.run_hook("post-write", th.write(os.path.join(store, "ledger.md"), "x", root), root)
        assert not os.path.exists(os.path.join(store, "idb", "pool-stamp.tsv")), "a write elsewhere stamped the pool"
        th.run_hook("post-write", {"tool_name": "Write", "cwd": root, "session_id": "pool-session",
                                   "tool_input": {"file_path": pool, "content": "x"}}, root)
        assert os.path.exists(os.path.join(store, "idb", "pool-stamp.tsv")), "the post-write hook did not stamp"
        out = th.run_hook("session-open", {"source": "compact", "session_id": "pool-session"}, root)
        assert "re-injected after the compact" in out and "pool: current" in out, out
        with open(os.path.join(store, "ledger.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("\n- correction: the pool is older than this\n  time: 2026-09-29 10:05\n  match: a\n  meant: b\n"
                    "  delta: c\n")
        ls = os.path.join(store, "local-storage.md")
        write(ls, read(ls).replace("scope: durable", "scope: durable, confirmed"))
        out = th.run_hook("session-open", {"source": "compact", "session_id": "pool-session"}, root)
        assert "pool: predates 2 writes" in out and "ledger.md 1 new" in out and "local-storage.md 1 changed" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pool stamp: green")


def test_rounds():
    root, store = seed_keyspace(logger=2, data=[("a claim", "a source")])
    try:
        rc, out = idb(store, "sync", "--session", "round-session", "--now", NOW, "--budget-s", "0")
        assert "left for the next round" in out, out
        first = meta(store, "@", "sweep-cursor")
        assert first not in (None, "-"), first
        rc, out = idb(store, "sync", "--session", "round-session", "--now", NOW, "--budget-s", "0")
        assert meta(store, "@", "sweep-cursor") != first, "the cursor did not move"
        rc, out = idb(store, "sync", "--session", "round-session", "--now", NOW)
        assert meta(store, "@", "sweep-cursor") == "-" and "left for the next round" not in out, out
        clean_check(store, "after the rounds")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("rounds: green")


def test_wrap_and_crlf():
    root, store = seed_keyspace()
    try:
        big = "x" * (70 * 1024)
        ds = os.path.join(store, "data-store.md")
        write(ds, DATA_STORE + f"\n- claim: a very long claim\n  time: 2026-09-10 10:00\n  verified: {big}\n  source: s\n"
                               "\n- claim: a short one\n  time: 2026-09-11 10:00\n  verified: read\n  source: s\n",
              crlf=True)
        idb(store, "sync", "--session", "wrap-session", "--now", NOW)
        h = heads(store, "data-store.md")
        rc, out = idb(store, "pour", "--session", "wrap-session", "--now", NOW, f"data-store.md:{h[0]}")
        assert rc == 0 and "poured 1" in out, out
        run = read(os.path.join(store, "idb", "runs", "data-store-000001.md"))
        assert "(wrapped: blobs/data-store/ds-0001.md sha=" in run and big not in run, "the long entry was not wrapped"
        rc, out = idb(store, "get", "data-store", "ds-0001")
        assert big in out and "note:" not in out, "the wrapped entry did not read back whole"
        with open(ds, "rb") as f:
            raw = f.read()
        assert b"\r\n" in raw and b"\n- claim: a short one" not in raw.replace(b"\r\n", b"\r\r"), "CRLF was not kept"
        assert th.count_entries(ds) == 1, "the trim missed"
        clean_check(store, "after the wrap")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("wrap + crlf: green")



def test_edges():
    """A whitespace-only last line, a stale lock taken over once, and an engine that will not load."""
    root, store = seed_keyspace(logger=2)
    try:
        # (a) a block whose last line is two spaces reads back from its run with that line
        ds = os.path.join(store, "data-store.md")
        write(ds, DATA_STORE + "\n- claim: trailing space\n  time: 2026-09-10 10:00\n  verified: read\n  source: s\n  \n")
        idb(store, "sync", "--session", "edge-session", "--now", NOW)
        idb(store, "pour", "--session", "edge-session", "--now", NOW, f"data-store.md:{heads(store, 'data-store.md')[0]}")
        rc, out = idb(store, "get", "data-store", "ds-0001")
        assert rc == 0 and "note:" not in out, f"(a) the run lost the whitespace line:\n{out}"
        clean_check(store, "(a)")
        # (b) a stale lock is taken over by the first session; the second finds it fresh
        lock = os.path.join(store, "idb", ".sweep-lock")
        write(lock, "crashed-session 2026-09-01 10:00:00\n")
        old = datetime.datetime(2026, 9, 1, 10, 0).timestamp()
        os.utime(lock, (old, old))
        ok1, msg1 = engine.take_lock(lock, "session-one")
        ok2, msg2 = engine.take_lock(lock, "session-two")
        assert ok1 and "superseding stale lock" in msg1 and not ok2 and "session-one" in msg2, (msg1, msg2)
        engine.release_lock(lock, "session-one")
        assert not os.path.exists(lock) and not [f for f in os.listdir(os.path.dirname(lock)) if f.endswith(".aside")]
        # (b2) light keeps to its budget: past it, the pour waits for the next pass and the lock is released
        with open(os.path.join(store, "logger.md"), "a", encoding="utf-8", newline="\n") as f:
            for i in range(40):
                f.write(f"\n- `[gc]` 2026-09-04 10:{i:02d} — **More {i}.** Filler.\n")
        rc, out = idb(store, "light", "--session", "edge-session", "--now", NOW, "--budget-s", "0")
        assert "the light pour waits for the next turn close (out of time)" in out, out
        assert not os.path.exists(os.path.join(store, "idb", ".sweep-lock")), "(b2) the lock was left held"
        rc, out = idb(store, "light", "--session", "edge-session", "--now", NOW)
        assert "poured" in out, out
        # (c) the engine will not load: a keyspace store's first prompt keeps its rows hot, and no arc/ appears
        th.run_hook("turn-close", {"session_id": "edge-session", "cwd": root}, root)
        th.run_hook("prompt-open", {"session_id": "edge-session", "prompt": "hello"}, root)
        broken = os.path.join(root, "plugin-copy")
        shutil.copytree(th.PLUGIN, broken)
        write(os.path.join(broken, "scripts", "idb.py"), "this is not python (\n")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=root, CLAUDE_PLUGIN_ROOT=broken)
        r = subprocess.run([sys.executable, os.path.join(broken, "hooks", "vlds_hooks.py"), "prompt-open"],
                           input=json.dumps({"session_id": th.CURRENT_SID[0], "prompt": "hi"}).encode("utf-8"),
                           capture_output=True, env=env, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert 'stamped: dispatch.md row "hi"' in out, out
        assert not os.path.exists(os.path.join(store, "arc")), "(c) the φ road ran on a keyspace store"
        r = subprocess.run([sys.executable, os.path.join(broken, "hooks", "vlds_hooks.py"), "turn-close"],
                           input=json.dumps({"session_id": th.CURRENT_SID[0], "cwd": root}).encode("utf-8"),
                           capture_output=True, env=env, timeout=60)
        out = r.stdout.decode("utf-8", "replace")
        assert "idb.py failed" in out and not os.path.exists(os.path.join(store, "arc")), f"(c) not reported:\n{out}"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("edges: green")


def test_pour_refuses_a_root():
    """A sweep's naming never pours a LIVE ruling: pour refuses a root unless --archive is passed, writing nothing."""
    root, store = seed_keyspace()
    try:
        idb(store, "sync", "--session", "root-session", "--now", NOW)
        h = heads(store, "local-storage.md")
        rc, out = idb(store, "pour", "--session", "root-session", "--now", NOW, f"local-storage.md:{h[0]}")
        assert rc == 1 and f"local-storage.md:{h[0]} is a LIVE ruling, a root" in out, out
        assert not os.path.isdir(os.path.join(store, "idb", "runs")), "a refused pour wrote a run"
        assert heads(store, "local-storage.md") == h, "a refused pour trimmed the hot file"
        # the SPENT ruling beside it is no root, and pours as before
        rc, out = idb(store, "pour", "--session", "root-session", "--now", NOW, "--dry", f"local-storage.md:{h[1]}")
        assert rc == 0 and "would pour 1 local-storage.md" in out, out
        rc, out = idb(store, "pour", "--session", "root-session", "--now", NOW, "--archive", f"local-storage.md:{h[0]}")
        assert rc == 0 and "archive: poured 1 (1 local-storage.md)" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pour refuses a root: green")


def test_archive():
    """/vlds:gc archive: every hot object store poured whole, LIVE roots included and nothing exempt; the freed stay
    freed in the keyspace, the cold tombstones still mask the hot tier, and dispatch.md is untouched."""
    root, store = seed_keyspace(logger=3, data=[("the sky is blue", "a look")], tombs=[('"go"', "go", "local-storage.md")])
    try:
        idb(store, "sync", "--session", "arch-session", "--now", NOW)
        dispatch = read(os.path.join(store, "dispatch.md"))
        hot = {f: len(heads(store, f)) for f in engine.OBJECT_STORES if os.path.exists(os.path.join(store, f))}
        # (a) the dry run counts every hot object store and writes nothing
        rc, out = idb(store, "archive", "--session", "arch-session", "--now", NOW, "--dry")
        assert rc == 0 and "archive: dry run — would pour" in out, out
        for f, n in hot.items():
            if n:
                assert f"{n} {f}" in out, f"(a) the dry run did not count {f}: {out}"
        assert not os.path.isdir(os.path.join(store, "idb", "runs")), "(a) the dry run wrote"
        # (b) the archive empties the hot tier, the logger keeping only the archive's own line
        rc, out = idb(store, "archive", "--session", "arch-session", "--now", NOW)
        assert rc == 0 and "archive: poured" in out, out
        for f in hot:
            want = 1 if f == "logger.md" else 0
            assert th.count_entries(os.path.join(store, f)) == want, f"(b) {f} kept hot entries"
        assert "Archive — the hot tier poured whole" in read(os.path.join(store, "logger.md"))
        assert read(os.path.join(store, "dispatch.md")) == dispatch, "(b) the archive touched dispatch.md"
        # (c) every record of the poured object stores is cold; the masked ruling is still freed, the LIVE one live
        ls = records(store, "local-storage")
        assert ls and all(r["at"].startswith("runs/") for r in ls.values()), ls
        states = sorted(r["state"] for r in ls.values())
        assert states == ["freed", "live"], f"(c) the archive changed a free: {states}"
        live_id = next(r["id"] for r in ls.values() if r["state"] == "live")
        rc, out = idb(store, "get", "local-storage", live_id)
        assert rc == 0 and "the plan goes in the reply as one fenced block" in out and "status: LIVE" in out, out
        # (d) the cold tombstone still masks the hot tier: a ruling in the freed owner-words reads FREED
        masks = phi.tombstone_masks(store)
        assert any(str(m[0]).endswith("(cold)") for m in masks), f"(d) no cold mask: {masks}"
        state, why = phi.barrier_state("local-storage.md", "ruling", '"go"', {"owner-words": '"go"', "status": "LIVE"},
                                       "arch-session", masks)
        assert state == "FREED" and "(cold)" in why, (state, why)
        clean_check(store, "after the archive")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    # (e) a store on the φ-register is refused: the archive places through the keyspace
    root, store = seed_keyspace(recall="index-engine: phi\n")
    try:
        rc, out = idb(store, "archive", "--session", "arch-session", "--now", NOW)
        assert rc == 1 and "the store is on the φ-register" in out, out
        assert th.count_entries(os.path.join(store, "local-storage.md")) == 2, "(e) a refused archive poured"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("archive: green")


def test_blob_reads():
    """blob and blobs read a registered external object, validated against its recorded sha; an unregistered or
    changed blob is refused."""
    root, store = seed_keyspace()
    try:
        bdir = os.path.join(store, "idb", "blobs", "dispatch")
        os.makedirs(bdir)
        path = os.path.join(bdir, "dispatch-20260929-0900-abcd1234.md")
        write(path, read(os.path.join(store, "dispatch.md")) + '\n- fingerprint: "ship the fix"\n  time: 2026-09-29 09:00\n')
        rc, out = idb(store, "blob", "dispatch", "dispatch-20260929-0900-abcd1234.md")
        assert rc == 1 and "is not a registered external object" in out, out
        idb(store, "sync", "--session", "blob-session", "--now", NOW)
        rc, out = idb(store, "blobs", "dispatch")
        assert rc == 0 and "dispatch-20260929-0900-abcd1234.md" in out and "1 external object(s) under dispatch" in out, out
        rc, out = idb(store, "blob", "dispatch", "dispatch-20260929-0900-abcd1234.md")
        assert rc == 0 and '- fingerprint: "ship the fix"' in out, out
        write(path, read(path) + "  addressed: edited by hand\n")
        rc, out = idb(store, "blob", "dispatch", "dispatch-20260929-0900-abcd1234.md")
        assert rc == 1 and "no longer hashes to the sha the keyspace recorded" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("blob reads: green")


if __name__ == "__main__":
    test_keyspace_derivation()
    test_hand_edit_and_sweep()
    test_pour()
    test_pour_crash_recovery()
    test_light_through_the_hook()
    test_dispatch_blob()
    test_freed_marks()
    test_compaction()
    test_migration()
    test_migration_refused()
    test_migration_legacy_shapes()
    test_migration_crash_after_commit()
    test_rollback()
    test_check_scans()
    test_stages()
    test_pool_stamp()
    test_rounds()
    test_wrap_and_crlf()
    test_edges()
    test_pour_refuses_a_root()
    test_archive()
    test_blob_reads()
    print("test_idb.py: all green")
