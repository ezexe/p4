#!/usr/bin/env python3
"""test_model_fallback.py — a model that fails in a session falls back and asks for a retrain, once, and never loops.

The sessions of a store's repository only use its models; building and fixing them is the p4-model skill's, in the
model repository (ezexe/phi). So every model failure a session meets ends the same way: the session falls back (the
JSON ranker, the children, the operator), one row lands in models/retrain-needed.tsv, and the session carries on.
These tests break each model path and check exactly that: the notice and its quiet window; picks on a broken JSON
model (exit 3, the children road); the .pt ranker's server down (the JSON ranker alone, no notice), answering wrongly
(the JSON ranker alone, a notice) and answering well (its score one of the JSON ranker's features); a broken dispatch model at the prompt hook (the barrier as it
was, a notice); and the SessionStart line that tells a session the notices are open and not its to fix.

Run from anywhere:  python scripts/test_model_fallback.py
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pick_model  # noqa: E402
import test_dispatch_model as td  # noqa: E402
import test_hooks as th  # noqa: E402
import test_pick_model as tp  # noqa: E402

PICK = os.path.join(HERE, "pick_model.py")
TASK = "the audio ring buffer drain order"


def run(*args):
    r = subprocess.run([sys.executable, *args], capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def fake_server(p4, answer, names=None, seen=None):
    """A stand-in for phi_serve: answer(texts) → (status, body), every reply naming its store (names, p4 by
    default) as the real server does; its port in models/ranker.server.json. `seen` collects each request body."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if seen is not None:
                seen.append(req)
            code, body = answer(req["texts"])
            data = json.dumps({**body, "p4": os.path.realpath(names or p4)}).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.makedirs(os.path.join(p4, "models"), exist_ok=True)
    with open(os.path.join(p4, "models", "ranker.server.json"), "w") as f:
        json.dump({"port": srv.server_address[1], "pid": os.getpid(), "round": 7}, f)
    return srv


def enable_pt(p4, weight=2.0, effort=""):
    """A JSON model whose training found the .pt feature helps: `pt` set and a weight on it, fitted on the source
    `effort` names (the tree at medium or high, the single ranker when empty)."""
    path = os.path.join(p4, "models", "pick-model.json")
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    m["pt"] = True
    m.pop("pt_effort", None)
    if effort:
        m["pt_effort"] = effort
    m["w"][str(pick_model.h("pt-z"))] = weight
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f)


def test_notice_and_quiet_window():
    root, p4, stores = tp.seed()
    try:
        store = stores["aaaa1111"]
        assert pick_model.notify_retrain(store, "ranker server", ValueError("bad scores"), "s1")
        assert not pick_model.notify_retrain(store, "ranker server", ValueError("again"), "s2"), "not quiet"
        assert pick_model.notify_retrain(store, "ranker server", KeyError("scores"), "s2"), "another kind is news"
        rows = pick_model.open_notices(store)
        assert [(r["component"], r["kind"]) for r in rows] == [("ranker server", "ValueError"), ("ranker server", "KeyError")]
        with open(os.path.join(p4, "models", pick_model.NOTICES), encoding="utf-8") as f:
            assert f.readline().startswith("# p4 model retrain notices")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("notice and quiet window: green")


def test_picks_fallbacks():
    root, p4, stores = tp.seed()
    try:
        store = stores["aaaa1111"]
        run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        args = (PICK, "--store", store, "picks", "--session", "eeee5555", "--task", TASK, "--now", "2026-09-08 10:00")
        answer_well = lambda texts: (200, {"scores": [0.9 if "ring buffer" in t else -0.5 for t in texts],  # noqa: E731
                                           "threshold": 0.5, "round": 7, "per_file": 6})
        # a JSON model trained without the feature never asks the server, even one that answers
        srv = fake_server(p4, answer_well)
        code, out = run(*args)
        assert code == 0 and "(json r0)" in out and "+pt" not in out, out
        srv.shutdown()
        enable_pt(p4)
        # no server: the JSON ranker alone, nothing to report
        os.remove(os.path.join(p4, "models", "ranker.server.json"))
        code, out = run(*args)
        assert code == 0 and "(json r0)" in out and not pick_model.open_notices(store), out
        # a server that answers well: its score joins the JSON ranker's features
        srv = fake_server(p4, answer_well)
        code, out = run(*args)
        assert code == 0 and "(json r0+pt r7)" in out, out
        srv.shutdown()
        # a server that answers wrongly: the JSON ranker alone, and a notice
        srv = fake_server(p4, lambda texts: (500, {"error": "boom"}))
        code, out = run(*args)
        assert code == 0 and "(json r0)" in out, out
        assert [r["component"] for r in pick_model.open_notices(store)] == ["ranker server"]
        srv.shutdown()
        # a server gone, its port file left behind: the JSON ranker, no new notice
        code, out = run(*args)
        assert code == 0 and "json r0" in out and len(pick_model.open_notices(store)) == 1, out
        # a broken JSON model: exit 3 (the children road), a notice, no traceback
        with open(os.path.join(p4, "models", "pick-model.json"), "w") as f:
            f.write("{ not json")
        code, out = run(*args)
        assert code == 3 and "take the children road" in out and "Traceback" not in out, out
        assert "pick_model picks" in [r["component"] for r in pick_model.open_notices(store)]
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("picks fallbacks: green")


def test_pool_effort():
    """`pool-effort: low` never asks the server; otherwise the server is asked at the effort the model's pt weight was
    fitted on (its pt_effort), whatever the index names now, and a tree's answer is named in the tag."""
    root, p4, stores = tp.seed()
    try:
        store = stores["aaaa1111"]
        run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        enable_pt(p4)
        args = (PICK, "--store", store, "picks", "--session", "eeee5555", "--task", TASK, "--now", "2026-09-08 10:00")
        seen = []

        def answer(texts):
            effort = seen[-1].get("effort", "")
            return 200, {"scores": [0.9 if "ring buffer" in t else -0.5 for t in texts], "threshold": 0.0, "round": 7,
                         "per_file": 6, "source": f"tree:{effort}:101" if effort else "ranker"}
        srv = fake_server(p4, answer, seen=seen)
        os.makedirs(os.path.join(p4, "vindex"), exist_ok=True)

        def effort_is(v, fitted=""):
            enable_pt(p4, effort=fitted)
            with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
                f.write("# idx\n\n## recall\n\n" + (f"pool-effort: {v}\n" if v else ""))
            del seen[:]
            return run(*args)
        code, out = effort_is("")
        assert code == 0 and "(json r0+pt r7)" in out and "effort" not in seen[0], out
        code, out = effort_is("low", "high")                     # low skips the .pt whatever it was fitted on
        assert code == 0 and "(json r0)" in out and not seen, out
        code, out = effort_is("medium", "medium")
        assert code == 0 and "(json r0+pt r7 tree:medium:101)" in out and seen[0]["effort"] == "medium", out
        code, out = effort_is("high", "high")
        assert code == 0 and seen[0]["effort"] == "high" and "tree:high" in out, out
        code, out = effort_is("high")                            # named, but the weight was fitted on the ranker
        assert code == 0 and "effort" not in seen[0] and "(json r0+pt r7)" in out, out
        code, out = effort_is("extreme")                         # not an effort: as unnamed
        assert code == 0 and "effort" not in seen[0], out
        assert pick_model.pool_effort(store) == "" and not pick_model.open_notices(store)
        srv.shutdown()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("pool effort: green")


def test_fresh_store_ranker_train():
    """ranker-train on a store with no labelled pool: nothing to learn, exit 0, and no retrain notice."""
    root, store = th.seed_project("f1e5a7a0-fresh")
    try:
        env = dict(os.environ, VLDS_RANKER_PYTHON=sys.executable)
        r = subprocess.run([sys.executable, PICK, "--store", store, "ranker-train", "--now", "2026-10-27 10:00"],
                           capture_output=True, timeout=120, env=env)
        out = r.stdout.decode("utf-8", "replace")
        if "no interpreter with phi_prune" in out:
            print("fresh store ranker-train: skipped (no phi_prune here)")
            return
        assert r.returncode == 0 and "nothing to learn" in out, out
        assert not pick_model.open_notices(store)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("fresh store ranker-train: green")


def test_server_identity_and_transport():
    """Only this store's server is believed: another store's, or anything that is not a ranker on a reused port, is
    'down' — the JSON ranker, and no notice."""
    import socket
    root, p4, stores = tp.seed()
    try:
        store = stores["aaaa1111"]
        run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        enable_pt(p4)
        args = (PICK, "--store", store, "picks", "--session", "eeee5555", "--task", TASK, "--now", "2026-09-08 10:00")
        srv = fake_server(p4, lambda texts: (500, {"error": "boom"}), names=os.path.join(root, "elsewhere"))
        code, out = run(*args)
        assert code == 0 and "json r0" in out and not pick_model.open_notices(store), out
        srv.shutdown()
        # a non-HTTP process on the port the stale file names (BadStatusLine): down, quietly
        lst = socket.socket()
        lst.bind(("127.0.0.1", 0))
        lst.listen(5)
        port = lst.getsockname()[1]

        def answer_ssh():
            while True:
                try:
                    c, _ = lst.accept()
                except OSError:
                    return
                c.recv(65536)
                c.sendall(b"SSH-2.0-OpenSSH_9\r\n")
                c.close()
        threading.Thread(target=answer_ssh, daemon=True).start()
        with open(os.path.join(p4, "models", "ranker.server.json"), "w") as f:
            json.dump({"port": port, "pid": 1}, f)
        assert pick_model.ranker_health(store) is None
        code, out = run(*args)
        assert code == 0 and "json r0" in out and not pick_model.open_notices(store), out
        lst.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("server identity and transport: green")


def test_checkpoint_states_and_locks():
    """An LFS pointer is named, never served or respawned; one server start at a time; one training at a time."""
    root, p4, stores = tp.seed()
    try:
        store = stores["aaaa1111"]
        mdir = os.path.join(p4, "models")
        os.makedirs(mdir, exist_ok=True)
        with open(os.path.join(mdir, "ranker.pt"), "w") as f:
            f.write("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 34000000\n")
        assert pick_model.checkpoint_state(os.path.join(mdir, "ranker.pt")) == "lfs-pointer"
        line = pick_model.ensure_server(store)
        assert "git LFS pointer" in line and "git lfs pull" in line, line
        assert not os.path.exists(os.path.join(mdir, pick_model.SERVER_START_LOCK))
        lock = os.path.join(mdir, "x.lock")
        assert pick_model.take_lock(lock, 60) and not pick_model.take_lock(lock, 60)
        os.utime(lock, (1, 1))                     # a lock long past its staleness is taken over
        assert pick_model.take_lock(lock, 60)
        pick_model.release_lock(lock)
        # a training already running: a second one starts nothing and is no failure
        assert pick_model.take_lock(os.path.join(mdir, pick_model.RANKER_TRAIN_LOCK), 3600)
        code, out = run(PICK, "--store", store, "ranker-train", "--now", "2026-10-27 10:00")
        assert code == 0 and "another training holds" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("checkpoint states and locks: green")


def test_resolved_is_append_only_and_retrain_holds():
    """A notice is answered by a row in retrain-resolved.tsv; retrain-needed.tsv keeps every row. While a notice of
    a model is open, the turn close does not retrain that model (the p4-model skill does)."""
    root, p4, stores = tp.seed()
    try:
        store = stores["aaaa1111"]
        assert pick_model.notify_retrain(store, "pick_model picks", ValueError("x"), "s1")
        n = pick_model.open_notices(store)[0]
        assert pick_model.notice_open(store, "json") and not pick_model.notice_open(store, "ranker")
        th_set_recall = td.set_recall
        th_set_recall(p4, "pool-road: model-shadow")
        out = th.run_hook("turn-close", {"session_id": "aaaa1111", "cwd": root, "_keep_sid": True}, root)
        assert "retraining the pool ranker" not in out, out
        with open(os.path.join(p4, "models", pick_model.RESOLVED), "a") as f:
            f.write(f"{n['time']}\t{n['epoch']:.6f}\t{n['session']}\t{n['component']}\t{n['kind']}\t{n['error']}\t"
                    "retrained now\n")
        assert pick_model.open_notices(store) == []
        with open(os.path.join(p4, "models", pick_model.NOTICES)) as f:
            assert sum(1 for l in f if not l.startswith("#")) == 1
        # a pool with no session: line still has an id
        pools = {p["id"] for p in pick_model.label_pools(store)}
        assert "" not in pools
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("resolved append-only, retrain holds: green")


def test_dispatch_and_session_open():
    root, store, p4 = td.seed()
    try:
        td.run(td.DM, "--store", store, "train", "--now", "2026-09-04 10:00")
        with open(os.path.join(p4, "models", "dispatch-model.json"), "w") as f:
            f.write('{"w": "not weights", "threshold": 0.3}')
        out = th.run_hook("prompt-open", {"session_id": "dddd0000-test",
                                          "prompt": "run the gamma build again and report the gamma timings for x?"}, root)
        assert "state: left open" in out and "dispatch model" not in out, out
        assert [r["component"] for r in pick_model.open_notices(store)] == ["dispatch model"]
        out = th.run_hook("session-open", {"session_id": "dddd0000-test", "source": "startup"}, root)
        line = next(l for l in out.split("\n") if "retrain notice" in l)
        assert "1 retrain notice(s) open" in line and "nothing here to fix" in line and "ezexe/phi" in line, line
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("dispatch fallback and the session-open line: green")


if __name__ == "__main__":
    test_notice_and_quiet_window()
    test_picks_fallbacks()
    test_pool_effort()
    test_fresh_store_ranker_train()
    test_server_identity_and_transport()
    test_checkpoint_states_and_locks()
    test_resolved_is_append_only_and_retrain_holds()
    test_dispatch_and_session_open()
    print("test_model_fallback.py: all green")
