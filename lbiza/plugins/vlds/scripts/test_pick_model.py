#!/usr/bin/env python3
"""test_pick_model.py — acceptance tests for the pool's model road: the labelled pairs drawn from the store's own
pools, training and the round's delta, the picks file in the children's shape folded by phi.py pool, the barrier
holding (no SPENT row picked), the shadow row, and the roads the index and the hooks accept.

Run from anywhere:  python scripts/test_pick_model.py
Each test seeds a throwaway p4 layout under a temp dir — three session stores, each with a recall pool — and runs
the scripts as subprocesses. Exit 0 = every test green. Nothing here touches a real store.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PICK = os.path.join(HERE, "pick_model.py")
PHI = os.path.join(HERE, "phi.py")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "hooks"))
import phi  # noqa: E402
import pick_model  # noqa: E402

LOCAL_HEAD = """# VLDS Partition — localStorage

```yaml
- ruling: [the ruling, distilled]
  time: [YYYY-MM-DD HH:MM]
  owner-words: "[verbatim]"
  scope: [what it governs]
  status: LIVE | SPENT | FREED
```

---
"""

# (topic words, time, status): each ruling's text names its topic, so a task naming the topic finds it
RULINGS = [
    ("the audio ring buffer drains before the page is heard", "2026-09-01 10:00", "LIVE"),
    ("the audio ring buffer keeps one block of lead", "2026-09-01 11:00", "LIVE"),
    ("midi transport events cross on the message thread only", "2026-09-02 10:00", "LIVE"),
    ("midi transport carries the play head position", "2026-09-02 11:00", "LIVE"),
    ("plan documents go under the plan-docs skill directory", "2026-09-03 10:00", "LIVE"),
    ("plan documents list every decision for the owner", "2026-09-03 11:00", "LIVE"),
    ("the toolbar card hides the start button until audio runs", "2026-09-04 10:00", "LIVE"),
    ("the toolbar card shows the latency readout", "2026-09-04 11:00", "LIVE"),
    ("the crash dump is read with the symbol server first", "2026-09-05 10:00", "LIVE"),
    ("the audio ring buffer was sized by guess once", "2026-09-05 11:00", "SPENT"),
]

POOLS = [  # (session, pooled, task, the ruling indices its steering picked)
    ("aaaa1111", "2026-09-06 09:00", "a plan for draining the audio ring buffer before the page is heard", [0, 1]),
    ("bbbb2222", "2026-09-06 10:00", "midi transport and play head position through the message thread", [2, 3]),
    ("cccc3333", "2026-09-06 11:00", "a toolbar card with a hidden start button and a latency readout", [6, 7]),
    ("dddd4444", "2026-09-06 12:00", "a plan document under the plan-docs skill listing every decision", [4, 5]),
]


def seed():
    root = tempfile.mkdtemp(prefix="vlds-pick-")
    p4 = os.path.join(root, ".claude", "p4")
    stores = {}
    for sid, *_ in POOLS:
        s = os.path.join(p4, "sessions", sid, "vlds")
        os.makedirs(s)
        stores[sid] = s
    first = stores[POOLS[0][0]]
    with open(os.path.join(first, "local-storage.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(LOCAL_HEAD)
        for text, time, status in RULINGS:
            f.write(f'\n- ruling: "{text}"\n  time: {time}\n  owner-words: "{text}"\n  scope: durable\n'
                    f"  status: {status}\n")
    rows = [r for r in phi.barrier_rows(first, "")[0] if r["file"] == "local-storage.md"]
    by_time = {r["time"]: r for r in rows}
    for sid, pooled, task, picked in POOLS:
        steer = "\n".join(f"- [local-storage.md {RULINGS[i][1]} LIVE] {phi.distilled(by_time[RULINGS[i][1]])}; "
                          f"bears: the task names it" for i in picked)
        with open(os.path.join(stores[sid], "recall-pool.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# VLDS Recall Pool\n\nsession: {sid} \"t\"\ntask: {task}\npooled: {pooled}\nread: x\n\n"
                    f"## steering — bears on the task\n\n{steer}\n\n## standing — applies whatever the task\n\n- none\n")
    return root, p4, stores


def run(*args):
    r = subprocess.run([sys.executable, *args], capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def test_pairs():
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        pools, data = pick_model.build_pairs(store)
        assert len(pools) == 4 and all(p["matched"] == p["steering"] == 2 for p in pools), \
            [(p["session"], p["matched"]) for p in pools]
        # a row timed after the pool is no candidate for it
        late = [i for i, r in enumerate(data[0]) if r["time"] > "2026-09-06 09:00"]
        assert not late or not set(late) & set(pools[0]["rows"])
        # a pool the model steered is never a label for it
        mpath = os.path.join(stores["dddd4444"], "recall-pool.md")
        with open(mpath, encoding="utf-8") as f:
            text = f.read()
        with open(mpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace("read: x", "read: local-storage.md (10, model), ledger.md (0, model)"))
        assert len(pick_model.build_pairs(store)[0]) == 3
        with open(mpath, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        code, out = run(PICK, "--store", store, "pairs", "--jsonl", os.path.join(root, "pairs.jsonl"))
        assert code == 0 and "8 of 8 steering lines matched" in out, out
        with open(os.path.join(root, "pairs.jsonl"), encoding="utf-8") as f:
            lines = [json.loads(l) for l in f]
        assert sum(l["label"] for l in lines) == 8 and {"task", "file", "text", "label"} <= set(lines[0])
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pairs: green")


def decode_round(header, payload):
    """Positions and values back from a .phid payload, as phi_prune.delta.decode_delta reads it."""
    def read(i):
        places, total, k, prev = [1, 2], 0, 0, "0"
        while True:
            bit = payload[i]
            i += 1
            if bit == "1" and prev == "1":
                return total, i
            if bit == "1":
                while len(places) <= k:
                    places.append(places[-1] + places[-2])
                total += places[k]
            k += 1
            prev = bit
    t = header["tensors"][0]
    i, pos, last = 0, [], -1
    for _ in range(t["n_kept"]):
        g, i = read(i)
        last += g
        pos.append(last)
    vals = []
    for _ in range(t["n_kept"]):
        sign = -1 if payload[i] == "1" else 1
        c, i = read(i + 1)
        vals.append(sign * (c - 1) * t["scale"])
    assert i == len(payload), (i, len(payload))
    return pos, vals


def test_train_and_round_delta():
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        code, out = run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        model = os.path.join(p4, "models", "pick-model.json")
        assert code == 0 and "round 0" in out and os.path.exists(model), out
        with open(model, encoding="utf-8") as f:
            m = json.load(f)
        assert m["round"] == 0 and 0.3 <= m["threshold"] <= 0.95 and m["w"], m.keys()
        # a second round writes the change in the phi_prune.delta format
        old = pick_model.load_model(model)["w"]
        code, out = run(PICK, "--store", store, "train", "--now", "2026-09-07 11:00", "--tokens")
        delta = os.path.join(p4, "models", "pick-model.r01.phid")
        assert code == 0 and "round 1" in out and os.path.exists(delta), out
        with open(delta, encoding="utf-8") as f:
            header = json.loads(f.readline())
            payload = f.read()
        new = pick_model.load_model(model)["w"]
        pos, vals = decode_round(header, payload)
        changed = sorted(k for k in set(old) | set(new) if abs(new.get(k, 0) - old.get(k, 0)) > 1e-6)
        assert set(changed) <= set(pos), "a changed weight is missing from the delta"
        scale = header["tensors"][0]["scale"]
        for k, v in zip(pos, vals):
            assert abs(old.get(k, 0) + v - new.get(k, 0)) <= scale / 2 + 2e-6, k
        assert [pick_model.fib_code(n) for n in (1, 2, 3, 4, 5)] == ["11", "011", "0011", "1011", "00011"]
        assert pick_model.levels_for(6) == 20 and pick_model.levels_for(12) == 376
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("train and round delta: green")


def test_picks_fold_and_barrier():
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        picks = os.path.join(p4, "scratchpad", "pool-picks-eeee5555.md")
        task = "the audio ring buffer sizing and drain order"
        code, out = run(PICK, "--store", store, "picks", "--session", "eeee5555", "--task", task,
                        "--now", "2026-09-08 10:00", "--out", picks)
        assert code == 3 and "no model" in out, out   # no model yet: the skeleton road
        run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        code, out = run(PICK, "--store", store, "picks", "--session", "eeee5555", "--task", task,
                        "--now", "2026-09-08 10:00", "--out", picks)
        assert code == 0, out
        got, ignored, sources = phi.read_picks(picks)
        assert ignored == 0 and sources.get("local-storage.md") == {"model"}, (ignored, sources)
        rows = {(r["file"], r["line"]): r for r in phi.barrier_rows(store, "eeee5555")[0]}
        assert got and all(rows[k]["state"] == "LIVE" for k in got), "a pick outside the LIVE rows"
        spent = [k for k, r in rows.items() if r["state"] == "SPENT"]
        assert spent and not set(spent) & set(got), "the SPENT ruling was picked"
        assert any("ring buffer" in rows[k]["value"] for k in got), got
        assert sum(1 for k in got if k[0] == "local-storage.md") <= pick_model.PER_FILE
        # phi.py pool folds the model's picks and credits the file to the model
        code, out = run(PHI, "--store", store, "pool", "--session", "eeee5555", "--task", task,
                        "--now", "2026-09-08 10:00", "--picks", picks)
        steering = out.split("## steering")[1].split("## standing")[0]
        assert code == 0 and "bears: model" in steering and "local-storage.md (" in out and ", model)" in out, out[:600]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("picks, fold and barrier: green")


def test_atomic_write():
    """A reader racing a writer sees the old model or the new one, never a partial file."""
    import threading
    root = tempfile.mkdtemp(prefix="vlds-atomic-")
    try:
        path = os.path.join(root, "models", "m.json")
        pick_model.write_atomic(path, json.dumps({"w": {}, "n": 0}))
        bad, stop = [], threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    with open(path, encoding="utf-8") as f:
                        json.load(f)
                except ValueError as e:
                    bad.append(e)
                except OSError:
                    pass
                # a hook reads the model once and exits; a reader that reopens with no gap at all would hold the
                # file open for ever, and Windows refuses a replace over an open file however long it retries
                time.sleep(0.001)
        t = threading.Thread(target=reader, daemon=True)
        t.start()
        try:
            for n in range(300):
                pick_model.write_atomic(path, json.dumps({"w": {str(i): i * 0.5 for i in range(2000)}, "n": n}))
        finally:
            stop.set()
            t.join()
        assert not bad, bad[:1]
        assert not [f for f in os.listdir(os.path.dirname(path)) if f.endswith(".tmp")]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("atomic write: green")


def test_review_and_audit():
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        review = os.path.join(root, "review.md")
        code, out = run(PICK, "--store", store, "picks", "--session", "eeee5555", "--task",
                        "the audio ring buffer drain order", "--now", "2026-09-08 10:00",
                        "--out", os.path.join(root, "m.md"), "--review", review)
        with open(review, encoding="utf-8") as f:
            sheet = f.read()
        assert code == 0 and "## local-storage.md" in sheet and "\npick local-storage.md:" in sheet, sheet
        assert "\nalt  local-storage.md:" in sheet and "ring buffer" in sheet, sheet
        # the audit: decided by the session id alone, one in N; pool-audit: 0 never
        due = [s for s in (f"{i:08x}" for i in range(200)) if pick_model.audit_due(store, s)]
        assert 20 <= len(due) <= 60, len(due)
        os.makedirs(os.path.join(p4, "vindex"), exist_ok=True)
        with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# idx\n\n## recall\n\npool-audit: 0\n")
        assert not any(pick_model.audit_due(store, s) for s in due)
        # the audit's reader: the children by default, the agent pool-audit-via names when set, recorded in the labels
        with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# idx\n\n## recall\n\npool-audit: 1\npool-audit-via: mister:roboto\n")
        assert pick_model.audit_via(store) == "mister:roboto"
        code, out = run(PICK, "--store", store, "picks", "--session", "eeee5555", "--task",
                        "the audio ring buffer drain order", "--now", "2026-09-08 10:00")
        assert "run mister:roboto (pool-audit-via) as the audit's reader" in out, out
        picks = os.path.join(root, "roboto-picks.md")
        with open(picks, "w", encoding="utf-8") as f:
            f.write(out)
        code, out = run(PICK, "--store", store, "label", "--session", "eeee5555", "--task", "the ring buffer",
                        "--now", "2026-09-08 10:00", "--picks", picks, "--reader", "mister:roboto")
        assert code == 0 and "by mister:roboto" in out, out
        lab = pick_model.parse_label_file(os.path.join(p4, "models", "labels", "eeee5555.tsv"))
        assert lab["reader"] == "mister:roboto", lab
        # an operator-reviewed pool (credited `pass`) is a label; a model-only one is not
        assert pick_model.labelled_pool({**pick_model.parse_pool(os.path.join(stores["bbbb2222"], "recall-pool.md"))})
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("review and audit: green")


def test_shadow():
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        children = os.path.join(root, "children.md")
        model = os.path.join(root, "model.md")
        with open(children, "w", encoding="utf-8") as f:
            f.write("picks — local-storage.md, 2 of 10 entries bear on the task\n"
                    "local-storage.md:12 || bears: a\nlocal-storage.md:18 || bears: b\n")
        with open(model, "w", encoding="utf-8") as f:
            f.write("picks (model) — local-storage.md, 2 of 10 entries bear on the task\n"
                    "local-storage.md:12 || bears: model 0.9; shares: x\nlocal-storage.md:30 || bears: model 0.7; shares: y\n")
        code, out = run(PICK, "--store", store, "shadow", "--session", "eeee5555", "--now", "2026-09-08 10:00",
                        "--children", children, "--model-picks", model)
        path = os.path.join(p4, "models", "shadow.tsv")
        with open(path, encoding="utf-8") as f:
            last = f.read().strip().split("\n")[-1].split("\t")
        assert code == 0 and "1 of the children's 2" in out and last[1:5] == ["eeee5555", "2", "2", "1"], (out, last)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("shadow: green")


def test_roads():
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        os.makedirs(os.path.join(p4, "vindex"), exist_ok=True)
        for road in ("model", "model-shadow", "children"):
            with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"# idx\n\nregister: 0\n\n## recall\n\npool-road: {road}\n")
            assert phi.index_road(store) == road, (road, phi.index_road(store))
        import vlds_hooks  # noqa: E402
        for road in ("model", "model-shadow"):
            assert vlds_hooks.recall_lists(f"## recall\n\npool-road: {road}\n")[4]["road"] == road
        assert vlds_hooks.recall_lists("## recall\n\npool-road: nonsense\n")[4]["road"] == "children"
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("roads: green")


def test_pt_feature_kept_only_when_it_helps():
    """phi_rank's out-of-fold scores reach the JSON ranker's training; the .pt feature is kept only when it raises
    the leave-one-out r-precision — on a tie (here both are perfect) it is left out, and the figures are recorded."""
    import argparse
    root, p4, stores = seed()
    try:
        store = stores["aaaa1111"]
        pools, data = pick_model.build_pairs(store)
        oof = {p["id"]: {pick_model.text_key(phi.distilled(data[0][i], 400)): float(y)
                         for i, y in zip(p["rows"], p["labels"])} for p in pools}
        os.makedirs(os.path.join(p4, "models"), exist_ok=True)
        with open(os.path.join(p4, "models", "ranker-oof.json"), "w", encoding="utf-8") as f:
            json.dump({"round": 0, "pools": oof}, f)
        pick_model.cmd_train(argparse.Namespace(now="2026-09-07 10:00", tokens=False, model=""), store)
        with open(os.path.join(p4, "models", "pick-model.json"), encoding="utf-8") as f:
            m = json.load(f)
        assert m["heldout"] == {"without_pt": 1.0, "with_pt": 1.0, "pt_from": "ranker"} and m["pt"] is False, m
        assert "pt_effort" not in m
        # pool-effort naming the tree: the weight is fitted on the tree's out-of-fold scores at that effort
        with open(os.path.join(p4, "models", "tree-oof.json"), "w", encoding="utf-8") as f:
            json.dump({"k": 4, "folds": 4, "efforts": {"medium": {}, "high": oof}}, f)
        os.makedirs(os.path.join(p4, "vindex"), exist_ok=True)
        with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write("# idx\n\n## recall\n\npool-effort: high\n")
        assert pick_model.load_oof(store, "high") == oof and pick_model.load_oof(store, "medium") == {}
        pick_model.cmd_train(argparse.Namespace(now="2026-09-07 11:00", tokens=False, model=""), store)
        with open(os.path.join(p4, "models", "pick-model.json"), encoding="utf-8") as f:
            m = json.load(f)
        assert m["heldout"]["pt_from"] == "tree:high", m.get("heldout")
        # a pool phi_rank never scored carries no feature: no out-of-fold score is made up for it
        assert pick_model.pool_pt({**pools[0], "id": "unscored"}, data, oof) is None
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(".pt feature kept only when it helps: green")


if __name__ == "__main__":
    test_pairs()
    test_train_and_round_delta()
    test_picks_fold_and_barrier()
    test_atomic_write()
    test_review_and_audit()
    test_shadow()
    test_roads()
    test_pt_feature_kept_only_when_it_helps()
    print("test_pick_model.py: all green")
