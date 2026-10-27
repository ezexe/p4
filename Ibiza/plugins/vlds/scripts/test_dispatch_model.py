#!/usr/bin/env python3
"""test_dispatch_model.py — acceptance tests for the dispatch model and the turn close's retrain: the labelled rows,
training with its threshold under every repeat, the prompt hook writing FRESH only under `dispatch-model: on` and
only when the model is sure, the shadow log and its report, `off` leaving the barrier as it was, and the turn
close starting a retrain in the background when a model road or the dispatch model is behind the store.

Run from anywhere:  python scripts/test_dispatch_model.py
Each test seeds a throwaway project under a temp dir and runs the hook and the scripts as subprocesses. Exit 0 =
every test green. Nothing here touches a real store.
"""

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_hooks as th  # noqa: E402 — seed_project, run_hook
import test_pick_model as tp  # noqa: E402 — a p4 layout with labelled pools

DM = os.path.join(HERE, "dispatch_model.py")
TOPICS = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]


def row(fp, time_, state, addressed=None):
    out = f'\n- fingerprint: "{fp}"\n  time: {time_}\n  arrival: turn (stamped by the prompt hook, session t)\n'
    out += f"  state: {state}\n"
    if addressed:
        out += f"  addressed: {addressed}\n"
    return out


def history(day):
    """One session's rows: fresh asks that read like an addressed earlier one, and echoes of an open one."""
    out = ""
    for i, t in enumerate(TOPICS):
        out += row(f"run the {t} build and report the {t} timings for the plugin host", f"{day} 0{i}:00", "FRESH", "done")
        out += row(f"run the {t} build again and report the {t} timings for the editor host?", f"{day} 0{i}:30",
                   "FRESH", "done")
    for i, t in enumerate(TOPICS[:4]):
        out += row(f"check the {t} log for errors in the {t} session", f"{day} 1{i}:00", "FRESH")
        out += row(f"check the {t} log for errors in the {t} session", f"{day} 1{i}:02", "ECHO")
    return out


def seed():
    root, store = th.seed_project("dddd0000-test")
    p4 = os.path.dirname(os.path.dirname(os.path.dirname(store)))
    for sid, day in (("aaaa0001", "2026-09-01"), ("bbbb0002", "2026-09-02")):
        s = os.path.join(p4, "sessions", sid, "vlds")
        os.makedirs(s)
        shutil.copy(th.SEED, os.path.join(s, "dispatch.md"))
        with open(os.path.join(s, "dispatch.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write(history(day))
    with open(os.path.join(store, "dispatch.md"), "a", encoding="utf-8", newline="\n") as f:
        f.write(row("run the gamma build and report the gamma timings for the plugin host", "2026-09-03 08:00",
                    "FRESH", "done"))
        f.write(row("check the delta log for errors in the delta session", "2026-09-03 09:00", "FRESH"))
    return root, store, p4


def set_recall(p4, text):
    os.makedirs(os.path.join(p4, "vindex"), exist_ok=True)
    with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# idx\n\nregister: 0\n\n## recall\n\n{text}\n")


def run(*args):
    r = subprocess.run([sys.executable, *args], capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def last_state(store):
    with open(os.path.join(store, "dispatch.md"), encoding="utf-8") as f:
        block = f.read().replace("\r\n", "\n").rsplit("\n- fingerprint:", 1)[1]
    for l in block.split("\n"):
        if l.startswith("  state:"):
            return l.split(":", 1)[1].strip()
    return None


def complete_last(store):
    """The operator's part, done by hand: the open row judged FRESH and addressed."""
    with open(os.path.join(store, "dispatch.md"), "a", encoding="utf-8", newline="\n") as f:
        f.write("  state: FRESH\n  addressed: answered\n")


def test_train_and_hook():
    root, store, p4 = seed()
    try:
        code, out = run(DM, "--store", store, "rows")
        assert code == 0 and "8 ECHO or SUPERSEDED" in out, out
        code, out = run(DM, "--store", store, "train", "--now", "2026-09-04 10:00")
        path = os.path.join(p4, "models", "dispatch-model.json")
        assert code == 0 and os.path.exists(path), out
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        assert m["repeats"] == 8 and m["threshold"] > 0, m
        code, out = run(DM, "--store", store, "eval")
        assert code == 0 and "repeats wrongly written FRESH" in out, out

        asks = [f"run the gamma build again and report the gamma timings for the {h} host?"
                for h in ("editor", "mixer", "render", "export")]
        echo = "check the delta log for errors in the delta session"
        # off, named: the barrier as it was, no model named, though a model is trained
        set_recall(p4, "dispatch-model: off")
        out = th.run_hook("prompt-open", {"session_id": "dddd0000-test", "prompt": asks[0]}, root)
        assert "dispatch model" not in out and "state: left open" in out and last_state(store) is None, out
        complete_last(store)
        # shadow: named and logged, never the state
        set_recall(p4, "dispatch-model: shadow")
        out = th.run_hook("prompt-open", {"session_id": "dddd0000-test", "prompt": asks[1]}, root)
        assert "dispatch model (shadow): would write FRESH" in out and last_state(store) is None, out
        complete_last(store)
        # on: FRESH written for the plain fresh ask, nothing for the operator
        set_recall(p4, "dispatch-model: on")
        out = th.run_hook("prompt-open", {"session_id": "dddd0000-test", "prompt": asks[2]}, root)
        assert "scores it plainly fresh" in out and last_state(store) == "FRESH", out
        with open(os.path.join(store, "dispatch.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("  addressed: answered (the record's, at the turn's close)\n")
        # on: an echo of an open row stays the operator's
        out = th.run_hook("prompt-open", {"session_id": "dddd0000-test", "prompt": echo}, root)
        assert "dispatch model (on): asks" in out and "state: left open" in out and last_state(store) is None, out
        complete_last(store)
        # unnamed: a trained model is on by default
        set_recall(p4, "pool-road: children")
        out = th.run_hook("prompt-open", {"session_id": "dddd0000-test", "prompt": asks[3]}, root)
        assert "scores it plainly fresh" in out and last_state(store) == "FRESH", out
        with open(os.path.join(p4, "models", "dispatch-shadow.tsv"), encoding="utf-8") as f:
            log = [l.split("\t") for l in f.read().strip().split("\n")[1:]]
        assert [l[2] for l in log] == ["shadow", "on", "on", "on"] and \
            [l[3] for l in log] == ["FRESH", "FRESH", "ask", "FRESH"], log
        # the row the model wrote FRESH is never a label for it; the rows the operator judged are
        sys.path.insert(0, HERE)
        import dispatch_model as dm  # noqa: E402
        fps = [r[1] for r in dm.labelled(store)]
        assert asks[2] not in fps and asks[3] not in fps and asks[0] in fps and asks[1] in fps, fps
        code, out = run(DM, "--store", store, "report")
        assert "proposed FRESH: 3 the operator's FRESH too" in out and "1 left to the operator" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("dispatch model and the prompt hook: green")


def wait_for(path, seconds=60):
    end = time.time() + seconds
    while time.time() < end:
        if os.path.exists(path):
            time.sleep(0.5)
            return True
        time.sleep(0.5)
    return False


def test_turn_close_retrain():
    root, p4, stores = tp.seed()
    try:
        payload = {"session_id": "aaaa1111", "cwd": root, "_keep_sid": True}
        model = os.path.join(p4, "models", "pick-model.json")
        # four labelled pools: under the bootstrap's five, nothing trains, whatever the road
        set_recall(p4, "pool-road: model-shadow")
        out = th.run_hook("turn-close", dict(payload), root)
        assert "retraining" not in out and not os.path.exists(model), out
        # an audit's children labels make the fifth: the first model trains, with no road named
        store = stores["aaaa1111"]
        picks = os.path.join(root, "audit.md")
        rows = [r for r in tp.phi.barrier_rows(store, "eeee5555")[0] if r["file"] == "local-storage.md"]
        with open(picks, "w", encoding="utf-8") as f:
            f.write("picks — local-storage.md, 1 of 10 entries bear on the task\n"
                    f"local-storage.md:{rows[8]['line']} || bears: the crash dump\n")
        code, out = run(tp.PICK, "--store", store, "label", "--session", "eeee5555", "--task",
                        "read the crash dump", "--now", "2026-09-08 10:00", "--picks", picks)
        assert code == 0 and "1 of 1 children picks" in out, out
        set_recall(p4, "")
        assert tp.phi.index_road(store) == "children"
        out = th.run_hook("turn-close", dict(payload), root)
        assert "retraining the pool ranker: 5 labelled pool(s) it has not seen" in out, out
        assert wait_for(model), "the background training wrote no model"
        with open(model, encoding="utf-8") as f:
            assert "eeee5555/audit" in json.load(f)["seen"]
        # trained: the road unnamed is the model's now
        assert tp.phi.index_road(store) == "model"
        # the lock holds a second turn close, and a model that has seen every pool owes nothing
        out = th.run_hook("turn-close", dict(payload), root)
        assert "retraining" not in out, out
        os.remove(os.path.join(p4, "models", ".retrain"))
        out = th.run_hook("turn-close", dict(payload), root)
        assert "retraining" not in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("turn close retrain: green")


if __name__ == "__main__":
    test_train_and_hook()
    test_turn_close_retrain()
    print("test_dispatch_model.py: all green")
