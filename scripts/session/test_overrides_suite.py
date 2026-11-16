#!/usr/bin/env python3
"""test_overrides_suite.py — the overrides suite and the store miner, offline: nothing here calls the API.

  1. every grader passes its task's reference and fails each bad answer (the instrument, before the pathways)
  2. the units are found from the plugins' own hooks.json, seed files left out
  3. the pathways are the ones the docstring names; an edits directory adds ~unit, a context directory =name
  4. a --fake run answers every pathway on every task, writes the JSON and resumes from its cache; a context that
     carries FAKE-FIX:<category> measurably helps, and a task's earlier turns reach the request
  5. the store miner finds corrections, retractions and repeats, and skips the files' own schema headers
  6. the jargon scan catches the contracts' vocabulary and leaves ordinary words alone

Run from the repository root:  python scripts/session/test_overrides_suite.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import overrides_suite as os_  # noqa: E402
import store_lessons as sl  # noqa: E402

TASKS = HERE / "overrides_tasks.jsonl"
# The old contracts live in git history since the fresh marketplace emptied lbiza/ (1750fa2): the tests of the units
# and the pathways read the marketplace as it was at f2323b2.
OLD_REF = "f2323b2"
_OLD = []


def old_market():
    """A directory holding the old marketplace's lbiza/, a git archive of OLD_REF: what the units read."""
    if _OLD:
        return _OLD[0]
    d = Path(tempfile.mkdtemp(prefix="p4-old-market-"))
    arch = subprocess.run(["git", "-C", str(REPO), "archive", OLD_REF, "lbiza"], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(d)], input=arch.stdout, check=True)
    _OLD.append(d)
    return d
CONTRACTS = ["emission-discipline/emission-gate", "src-fragger/src-fragger", "vlds/memory-override", "vlds/gc-contract"]

LEDGER = """# VLDS Ledger

What the guide loop did.

```yaml
correction:
  key: [the mis-matched key]
  match: [what the loop assumed]
  meant: [what was actually wanted]
```

```yaml
correction:
  key: cmake-floor
  time: 2026-10-29 11:05
  match: keep the build working under CMake 3.x
  meant: require the latest CMake everywhere
```
"""
TOMBSTONES = "# Tombstones\n\n- freed: the sibling checkout\n  time: 2026-10-29 02:17\n  cause: superseded\n"
DISPATCH = ("# Dispatch\n\n  state: FRESH | ECHO | SUPERSEDED\n\n---\n\n- fingerprint: \"pull both repos\"\n"
            "  time: 2026-10-28 23:00\n  state: SUPERSEDED\n\n- fingerprint: \"start\"\n  time: 2026-10-28 23:01\n"
            "  state: FRESH\n")


def tasks():
    return [json.loads(l) for l in open(TASKS, encoding="utf-8") if l.strip()]


def flat_store(root):
    """A project on the old flat layout: .claude/p4/vlds/ holding a correction, a retraction and a repeat."""
    store = root / ".claude" / "p4" / "vlds"
    store.mkdir(parents=True)
    (store / "ledger.md").write_text(LEDGER, encoding="utf-8")
    (store / "tombstones.md").write_text(TOMBSTONES, encoding="utf-8")
    (store / "dispatch.md").write_text(DISPATCH, encoding="utf-8")
    return store


def test_graders():
    assert os_.check_graders(tasks()) == []
    ts = tasks()
    assert len({t["id"] for t in ts}) == len(ts)
    assert {t["category"] for t in ts} <= set(os_.GENERAL)


def test_units():
    assert os_.units(REPO) == {}, "the fresh marketplace injects no contract (gate 0.1)"
    us = os_.units(old_market())
    assert list(us) == CONTRACTS, list(us)
    assert all(not u["path"].endswith("-seed.md") for u in us.values())
    assert any(k.startswith("skill:") for k in os_.units(old_market(), skills=True))


def test_pathways():
    us = os_.units(old_market())
    p = os_.pathways(us, ["builtin", "all", "loo", "solo", "pad"])
    assert set(p) == {"builtin", "all", "pad"} | {f"-{k}" for k in CONTRACTS} | {f"+{k}" for k in CONTRACTS}
    assert p["builtin"] == "" and len(p["pad"]) == len(p["all"])
    with tempfile.TemporaryDirectory() as d:
        os_.edit_file(d, "vlds/gc-contract").write_text("# gc, shorter\n", encoding="utf-8")
        p = os_.pathways(us, ["all"], d)
        assert "# gc, shorter" in p["~vlds/gc-contract"] and us["vlds/gc-contract"]["text"] not in p["~vlds/gc-contract"]


def test_fake_run():
    with tempfile.TemporaryDirectory() as d:
        Path(f"{d}/ctx").mkdir()
        Path(f"{d}/ctx/fix.md").write_text("FAKE-FIX:honesty FAKE-FIX:judgment FAKE-FIX:memory", encoding="utf-8")
        args = ["--p4", str(REPO), "--tasks", str(TASKS), "--model", "claude-haiku-5-5", "--fake",
                "--context-dir", f"{d}/ctx", "--cache", f"{d}/cache", "--out", f"{d}/out.json"]
        assert os_.main(args) == 0
        out = json.loads(Path(f"{d}/out.json").read_text())
        n = len(tasks())
        assert all(p["answered"] == n for p in out["pathways"].values())
        assert out["pathways"]["=fix"]["accuracy"] == 1.0 > out["pathways"]["builtin"]["accuracy"]
        assert out["pathways"]["=fix"]["tasks"]["m1-retraction"]["passed"]
        assert not out["pathways"]["all"]["tasks"]["m1-retraction"]["passed"]
        r = subprocess.run([sys.executable, str(HERE / "overrides_suite.py"), *args], capture_output=True, text=True)
        assert r.returncode == 0 and "0 answers to ask" in r.stdout, r.stdout
    req = os_.request("claude-haiku-5-5", "CTX", "now", "high",
                      [{"role": "user", "content": "first"}, {"role": "assistant", "content": "ok"}])
    first, last = req["messages"][0]["content"], req["messages"][-1]["content"]
    assert first[0]["text"].endswith("CTX") and first[1]["text"] == "first" and last[-1]["text"] == "now"


def test_store_lessons():
    with tempfile.TemporaryDirectory() as d:
        flat_store(Path(d))
        got = sl.lessons(Path(d) / ".claude" / "p4")
    assert got["counts"]["correction"] == 1 and got["counts"]["retraction"] == 1 and got["counts"]["repeat"] == 1, got
    assert "cmake-floor" in got["lessons"][0]["text"]


def test_jargon():
    assert os_.JARGON.search("I registered the frag and wrote the tombstone.")
    assert os_.JARGON.search("the operator's derivation says FRESH")
    assert not os_.JARGON.search("Here is a fragment of the file; the pour-over coffee is ready.")


def test_context_dir_per_task():
    """--context-dir: `<pathway>.<task id>.md` is that pathway's context for that task alone (8.2's small change); a
    task without one gets `<pathway>.md`, or nothing, and nothing is the built-in's request, answered from its cache."""
    with tempfile.TemporaryDirectory() as d:
        ctx = Path(d) / "ctx"
        ctx.mkdir()
        (ctx / "recall.h1-downloads.md").write_text("- FAKE-FIX:honesty\n", encoding="utf-8")
        (ctx / "recall.j3-force-push.md").write_text("- FAKE-FIX:judgment\n", encoding="utf-8")
        (ctx / "plain.md").write_text("FAKE-FIX:memory", encoding="utf-8")
        (ctx / "plain.m2-repeat.md").write_text("nothing here", encoding="utf-8")
        (ctx / "v1.2.md").write_text("a dotted name that is no task's", encoding="utf-8")
        base, per = os_.context_dir(ctx, {t["id"] for t in tasks()})
        assert set(base) == {"=recall", "=plain", "=v1.2"} and base["=recall"] == ""
        assert set(per["=recall"]) == {"h1-downloads", "j3-force-push"} and set(per["=plain"]) == {"m2-repeat"}
        args = ["--p4", str(REPO), "--tasks", str(TASKS), "--model", "claude-haiku-5-5", "--fake", "--pathways",
                "builtin", "--context-dir", str(ctx), "--cache", f"{d}/cache", "--out", f"{d}/out.json"]
        assert os_.main(args) == 0
        out = json.loads(Path(f"{d}/out.json").read_text())
        b, r, pl = (out["pathways"][n]["tasks"] for n in ("builtin", "=recall", "=plain"))
        assert r["h1-downloads"]["passed"] and r["j3-force-push"]["passed"]
        assert not b["h1-downloads"]["passed"] and not b["j3-force-push"]["passed"]
        assert [k for k in r if r[k]["passed"] != b[k]["passed"]] == ["h1-downloads", "j3-force-push"]
        assert pl["m1-retraction"]["passed"] and not pl["m2-repeat"]["passed"], "the per-task file replaces the base"
        assert out["pathways"]["=recall"]["per_task_contexts"] == 2
        assert out["pathways"]["=recall"]["silent_tasks"] == len(tasks()) - 2
        # the =recall tasks without a file are the built-in's requests: 2 new answers, the rest from the cache;
        # =plain and =v1.2 differ from the built-in on every task
        n = len(tasks())
        assert len(list(Path(f"{d}/cache").glob("*.json"))) == n + 2 + n + n


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name, "ok")
    shutil.rmtree(HERE / "__pycache__", ignore_errors=True)
    print("test_overrides_suite.py: all green")
