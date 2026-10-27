#!/usr/bin/env python3
"""test_model_fallback.py — a model that fails in a session falls back and asks for a retrain, once, and never loops.

The sessions of a store's repository only use its models; building and fixing them is the p4-model skill's, in the
model repository (ezexe/phi). So every model failure a session meets ends the same way: the session falls back (the
JSON ranker, the children, the operator), one row lands in models/retrain-needed.tsv, and the session carries on.
These tests break each model path and check exactly that: the notice and its quiet window; picks on a broken JSON
model (exit 3, the children road); the .pt ranker's server down (the JSON ranker, no notice), answering wrongly (the
JSON ranker, a notice) and answering well (its picks); a broken dispatch model at the prompt hook (the barrier as it
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


def fake_server(p4, answer):
    """A stand-in for phi_prune.p4serve: answer(texts) → (status, body); its port in models/ranker.server.json."""
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            code, body = answer(req["texts"])
            data = json.dumps(body).encode()
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
        # no server: the JSON ranker, nothing to report
        code, out = run(*args)
        assert code == 0 and "json r0" in out and not pick_model.open_notices(store), out
        # a server that answers well: its scores pick
        srv = fake_server(p4, lambda texts: (200, {"scores": [0.9 if "ring buffer" in t else -0.5 for t in texts],
                                                   "threshold": 0.5, "round": 7, "per_file": 6}))
        code, out = run(*args)
        assert code == 0 and "ranker r7" in out and "(ranker r7)" in out and "ring buffer" not in out, out
        srv.shutdown()
        # a server that answers wrongly: the JSON ranker, and a notice
        srv = fake_server(p4, lambda texts: (500, {"error": "boom"}))
        code, out = run(*args)
        assert code == 0 and "json r0" in out, out
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
    test_fresh_store_ranker_train()
    test_dispatch_and_session_open()
    print("test_model_fallback.py: all green")
