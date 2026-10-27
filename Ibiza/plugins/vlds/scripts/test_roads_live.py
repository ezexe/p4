#!/usr/bin/env python3
"""test_roads_live.py — the pool's road and the dispatch model switch live, inside one running store.

The road is read from the recall config at every hook call and every `phi.py pool` run, never cached, so an edit
to `.claude/p4/vindex/phi-index.md` — or a model appearing in, or leaving, `.claude/p4/models/` — takes effect at
the very next call, with no restart. One store, one session, and in order:

  1. nothing named, no model           → children
  2. `pool-road: model-shadow`          → model-shadow; the model's picks written beside, compared
  3. `pool-road: model`                 → model; the model's picks fold, credited to the reviewer
  4. `pool-road: children`              → children: the roll back, nothing else changed
  5. nothing named, the model trained   → model, by default
  6. nothing named, the model removed   → children again; on `model`, no model → exit 3, the children road
  7. `dispatch-model:` unnamed / off / on with a model trained → on / off / on, prompt to prompt

Each step asserts what every reader sees: the SessionStart recall line (`road …`), `phi.py pool`'s first line
(`pool-road: …`), `phi.index_road`, and for the dispatch model, the prompt hook's line.

Run from anywhere:  python scripts/test_roads_live.py
A throwaway p4 layout under a temp dir; nothing here touches a real store.
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phi  # noqa: E402
import test_dispatch_model as td  # noqa: E402 — dispatch rows with repeats
import test_hooks as th  # noqa: E402 — run_hook
import test_pick_model as tp  # noqa: E402 — a p4 layout with labelled pools

PICK = os.path.join(HERE, "pick_model.py")
DM = os.path.join(HERE, "dispatch_model.py")
TASK = "the audio ring buffer drain order"
SID = "aaaa1111"


def set_recall(p4, lines):
    os.makedirs(os.path.join(p4, "vindex"), exist_ok=True)
    with open(os.path.join(p4, "vindex", "phi-index.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("# idx\n\nregister: 0\n\n## recall\n\n" + "".join(l + "\n" for l in lines))


def run(*args):
    r = subprocess.run([sys.executable, *args], capture_output=True, timeout=120)
    return r.returncode, r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def readers_see(root, store):
    """(the SessionStart recall line's road, phi.py pool's road, phi.index_road) — every reader, asked now."""
    out = th.run_hook("session-open", {"session_id": SID, "source": "startup", "_keep_sid": True}, root)
    line = next((l for l in out.split("\n") if l.startswith("lists from")), "")
    hook_road = line.split("; road ", 1)[1].split(";", 1)[0] if "; road " in line else None
    _code, pool = run(phi.__file__, "--store", store, "pool", "--session", SID, "--task", TASK, "--now",
                      "2026-09-08 10:00")
    pool_road = pool.split("\n", 1)[0].split(";", 1)[0].replace("pool-road: ", "")
    return hook_road, pool_road, phi.index_road(store)


def test_roads_switch_live():
    root, p4, stores = tp.seed()
    store = stores[SID]
    model = os.path.join(p4, "models", "pick-model.json")
    try:
        # 1. nothing named, no model: the children gather the pools the first model trains on
        set_recall(p4, [])
        assert readers_see(root, store) == ("children", "children", "children")

        # a model trained by hand, so the model roads have one
        code, out = run(PICK, "--store", store, "train", "--now", "2026-09-07 10:00")
        assert code == 0 and os.path.exists(model), out

        # 2. model-shadow, named: every reader switches at its next call
        set_recall(p4, ["pool-road: model-shadow"])
        assert readers_see(root, store) == ("model-shadow", "model-shadow", "model-shadow")
        mpicks = os.path.join(root, "model.md")
        code, out = run(PICK, "--store", store, "picks", "--session", SID, "--task", TASK, "--now",
                        "2026-09-08 10:00", "--out", mpicks)
        assert code == 0, out
        children = os.path.join(root, "children.md")
        with open(children, "w", encoding="utf-8") as f:
            got, _i, _s = phi.read_picks(mpicks)
            first = sorted(got)[0]
            f.write(f"picks — {first[0]}, 1 of 1 entries bear on the task\n{first[0]}:{first[1]} || bears: a\n")
        code, out = run(PICK, "--store", store, "shadow", "--session", SID, "--now", "2026-09-08 10:00",
                        "--children", children, "--model-picks", mpicks)
        assert code == 0 and "1 of the children's 1" in out, out
        _c, pool = run(phi.__file__, "--store", store, "pool", "--session", SID, "--task", TASK, "--now",
                       "2026-09-08 10:00", "--picks", children)
        assert "child)" in pool.split("read:", 1)[1].split("\n", 1)[0], "model-shadow folds the children's picks"

        # 3. model, named: the model's picks fold
        set_recall(p4, ["pool-road: model"])
        assert readers_see(root, store) == ("model", "model", "model")
        _c, pool = run(phi.__file__, "--store", store, "pool", "--session", SID, "--task", TASK, "--now",
                       "2026-09-08 10:00", "--picks", mpicks)
        assert "bears: model" in pool and "model)" in pool.split("read:", 1)[1].split("\n", 1)[0], pool[:600]

        # 4. children, named: the roll back, while the model stays trained
        set_recall(p4, ["pool-road: children"])
        assert readers_see(root, store) == ("children", "children", "children")
        assert os.path.exists(model)

        # 5. nothing named, the model trained: model by default, at the next call
        set_recall(p4, [])
        assert readers_see(root, store) == ("model", "model", "model")

        # 6. the model removed: children again; a named model road with no model is exit 3, the children road
        os.remove(model)
        assert readers_see(root, store) == ("children", "children", "children")
        set_recall(p4, ["pool-road: model"])
        code, out = run(PICK, "--store", store, "picks", "--session", SID, "--task", TASK, "--now",
                        "2026-09-08 10:00")
        assert code == 3 and "no model" in out, out
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("roads switch live: green")


def test_dispatch_switches_live():
    root, store, p4 = td.seed()
    try:
        code, out = run(DM, "--store", store, "train", "--now", "2026-09-04 10:00")
        assert code == 0, out
        ask = "run the gamma build again and report the gamma timings for the {} host?"
        steps = [([], "on"), (["dispatch-model: off"], None), (["dispatch-model: shadow"], "shadow"),
                 (["dispatch-model: on"], "on")]
        for i, (lines, mode) in enumerate(steps):
            set_recall(p4, lines)
            out = th.run_hook("prompt-open", {"session_id": "dddd0000-test",
                                              "prompt": ask.format(f"host{i}")}, root)
            if mode is None:
                assert "dispatch model" not in out, (lines, out)
            elif mode == "shadow":
                assert "dispatch model (shadow)" in out and td.last_state(store) is None, (lines, out)
            else:
                assert "scores it plainly fresh" in out or "dispatch model (on)" in out, (lines, out)
            if td.last_state(store) is None:
                td.complete_last(store)
            else:
                with open(os.path.join(store, "dispatch.md"), "a", encoding="utf-8", newline="\n") as f:
                    f.write("  addressed: answered\n")
        with open(os.path.join(p4, "models", "dispatch-shadow.tsv"), encoding="utf-8") as f:
            modes = [l.split("\t")[2] for l in f.read().strip().split("\n")[1:]]
        assert modes == ["on", "shadow", "on"], modes
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("dispatch model switches live: green")


if __name__ == "__main__":
    test_roads_switch_live()
    test_dispatch_switches_live()
    print("test_roads_live.py: all green")
