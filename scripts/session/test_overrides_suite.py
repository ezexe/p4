#!/usr/bin/env python3
"""test_overrides_suite.py — the overrides suite, the store miner and the notebook, offline: nothing here calls the API.

  1. every grader passes its task's reference and fails each bad answer (the instrument, before the pathways)
  2. the units are found from the plugins' own hooks.json, seed files left out
  3. the pathways are the ones the docstring names; an edits directory adds ~unit, a context directory =name
  4. a --fake run answers every pathway on every task, writes the JSON and resumes from its cache; a context that
     carries FAKE-FIX:<category> measurably helps, and a task's earlier turns reach the request
  5. the store miner finds corrections, retractions and repeats, and skips the files' own schema headers
  6. the notebook's code cells parse, and its audit cell turns measured gains and costs into the right readings
  7. the whole notebook runs with FAKE on a local repo on the old flat layout: the lessons are mined, the rebuild
     starts from the empty frame and keeps exactly the pieces that help, validation says to apply it, and the
     upgrade moves the repo onto the partitioned layout
  8. the jargon scan catches the contracts' vocabulary and leaves ordinary words alone

Run from the repository root:  python scripts/session/test_overrides_suite.py
"""

import ast
import json
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import overrides_suite as os_  # noqa: E402
import store_lessons as sl  # noqa: E402

TASKS = HERE / "overrides_tasks.jsonl"
NOTEBOOK = REPO / ".docs" / "p4" / "overrides_colab.ipynb"
FRESH_NOTEBOOK = REPO / ".docs" / "p4" / "fresh_validation.ipynb"
# The old contracts live in git history since the fresh marketplace emptied lbiza/ (1750fa2): the tests of the units,
# the pathways and the old Colab notebook read the marketplace as it was at f2323b2, beside this checkout's scripts.
OLD_REF = "f2323b2"
_OLD = []


def old_market():
    """A directory holding the old marketplace's lbiza/ (git archive of OLD_REF) and this checkout's scripts/ and
    .docs/: what the old notebook and the units read."""
    if _OLD:
        return _OLD[0]
    d = Path(tempfile.mkdtemp(prefix="p4-old-market-"))
    arch = subprocess.run(["git", "-C", str(REPO), "archive", OLD_REF, "lbiza"], capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(d)], input=arch.stdout, check=True)
    shutil.copytree(REPO / "scripts", d / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / ".docs", d / ".docs")
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
    assert {t["category"] for t in ts} <= set(os_.GENERAL) | {"protocol"}
    assert all(t.get("protocol_of") in CONTRACTS for t in ts if t["category"] == "protocol")


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


def cells():
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def cell(marker):
    found = [c for c in cells() if marker in c]
    assert len(found) == 1, (marker, len(found))
    return found[0]


def stub_colab_modules():
    """matplotlib and IPython are Colab's (and VS Code's kernel's); stubs stand in for them here."""
    ax = types.SimpleNamespace(bar=lambda *a, **k: None, set_xticks=lambda *a, **k: None, set=lambda **k: None,
                               legend=lambda **k: None)
    fig = types.SimpleNamespace(savefig=lambda *a, **k: None, tight_layout=lambda: None)
    plt = types.SimpleNamespace(subplots=lambda **k: (fig, ax))
    sys.modules["matplotlib"] = types.SimpleNamespace(use=lambda *_: None, pyplot=plt)
    sys.modules["matplotlib.pyplot"] = plt
    sys.modules.setdefault("IPython", types.ModuleType("IPython"))
    disp = types.ModuleType("IPython.display")
    disp.Markdown, disp.Image, disp.display = str, str, lambda *_: None
    sys.modules["IPython.display"] = disp


def settings(d, **over):
    g = {}
    exec(cell('RUN = "overrides-1"'), g)
    runs = over.pop("RUNS", {"claude-opus-5-5": [0, 1], "claude-sonnet-5-5": [0, 1]})
    g.update({"DRIVE_DIR": str(d), "P4_PATH": str(old_market()), "FAKE": True, "AUDIT_RUNS": runs, "VALIDATE_RUNS": runs,
              "MODELS": list(runs), "SEEDS": sorted({s for v in runs.values() for s in v}),
              "REBUILD_SEEDS": sorted({s for v in runs.values() for s in v}),
              "SCREEN_MODELS": ["claude-haiku-5-5"], "STORE_REPOS": [], "RUN_PLUGIN_TESTS": False}
             | over)
    exec(cell("def save_json"), g)
    return g


def test_notebook_audit_readings():
    for c in cells():
        ast.parse(c)
    stub_colab_modules()
    with tempfile.TemporaryDirectory() as d:
        g = settings(d)
        exec(cell("def checkout"), g)
        exec(cell("import overrides_suite as osu"), g)
        exec(cell("def survey"), g)
        assert os_.main(["--p4", str(old_market()), "--tasks", str(TASKS), "--model", "claude-opus-5-5", "--fake",
                         "--cache", f"{d}/c", "--out", f"{d}/base.json"]) == 0
        base = json.loads(Path(f"{d}/base.json").read_text())
        accs = {"builtin": .70, "all": .80, "pad": .68,
                "-emission-discipline/emission-gate": .75, "+emission-discipline/emission-gate": .74,
                "-src-fragger/src-fragger": .78, "+src-fragger/src-fragger": .70,
                "-vlds/memory-override": .80, "+vlds/memory-override": .70,
                "-vlds/gc-contract": .82, "+vlds/gc-contract": .69}
        for m in g["MODELS"]:
            for s in g["SEEDS"]:
                r = json.loads(json.dumps(base))
                r.update(model=m, seed=s)
                for pw, p in r["pathways"].items():
                    p["accuracy"] = accs[pw]
                    p["by_category"] = {c: accs[pw] for c in os_.GENERAL} | {"protocol": 1.0}
                    p["jargon_rate"] = 0.0
                    for t in p["tasks"].values():
                        t["passed"] = True
                r["pathways"]["all"]["by_category"]["simple"] = .6
                for k in CONTRACTS:
                    r["pathways"][f"-{k}"]["by_category"]["simple"] = .9 if k == "src-fragger/src-fragger" else .6
                (Path(d) / g["RUN"] / "results" / f"overrides-{m}-s{s}.json").write_text(json.dumps(r))
        exec(cell("per_unit, decisions"), g)
        assert g["decisions"] == {"emission-discipline/emission-gate": "keep", "src-fragger/src-fragger": "edit",
                                  "vlds/memory-override": "drop", "vlds/gc-contract": "drop"}, g["decisions"]
        claims = g["claims"]
        assert claims["the old contracts together beat the built-in stand-in (all > builtin, every seed, every model)"] \
            == "holds"
        assert "simple" in g["per_unit"]["src-fragger/src-fragger"]["categories it costs"]


def test_notebook_end_to_end():
    """Every section with FAKE, on a local project still on the old flat layout."""
    stub_colab_modules()
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "proj"
        flat_store(proj)
        g = settings(Path(d) / "drive", STORE_REPOS=[{"path": str(proj)}], MIGRATE_DRY=False,
                     RUNS={"claude-haiku-5-5": [0]}, RUN_AUDIT=False, SHORTLIST=6, MIGRATE_PUSH=False,
                     PUSH_RESULTS=False)
        exec(cell("def checkout"), g)
        exec(cell("import overrides_suite as osu"), g)
        exec(cell("def survey"), g)
        assert g["stores_report"]["proj"]["before"]["layout"] == "flat"
        assert g["stores_report"]["proj"]["lessons"]["correction"] == 1
        # the lesson items a real run's SPLITTER_MODEL would write: the fake answers only these measurably help
        g["LESSON_ITEMS"] += [
            {"unit": "emission-discipline/emission-gate", "text": "FAKE-FIX:honesty Say what you cannot know.",
             "from": "fixture", "store": "proj"},
            {"unit": "vlds/memory-override", "text": "FAKE-FIX:memory Keep the earlier turns in mind.",
             "from": "fixture", "store": "proj"},
            {"unit": "vlds/memory-override", "text": "FAKE-FIX:judgment Check before acting on a request.",
             "from": "fixture", "store": "proj"},
            {"unit": "src-fragger/src-fragger", "text": "A line that changes nothing.", "from": "fixture",
             "store": "proj"}]
        for marker in ('plan = ([(m, s)', "per_unit, decisions", "SPLIT_SYSTEM", "screen = {}", "def assemble",
                       "vclaims = {", "REPORT_SYSTEM", "p4-push", "upgrades = load_state()"):
            exec(cell(marker), g)
        kept = {g["candidates"][c]["text"].split()[0] for c in g["chosen"]}
        assert kept == {"FAKE-FIX:honesty", "FAKE-FIX:memory", "FAKE-FIX:judgment"}, g["chosen"]
        rb = g["summary"]["rebuild"]
        assert rb["claims"]["the rebuilt contracts beat the built-in stand-in (test split, every seed, every model)"] \
            == "holds", rb["claims"]
        assert rb["apply"] is True, rb["claims"]
        assert rb["chars"]["rebuilt"] < rb["chars"]["old"]
        for u, f in rb["files"].items():   # the hooks and the plugin tests key on each contract's first line
            assert f["text"].splitlines()[0] == g["HEADS"][u]
        up = g["upgrades"]["proj"]
        assert up["before"] == "flat" and up["after"] == "partitioned", up
        assert (proj / ".claude" / "p4" / "vlds").is_dir(), "the local tree itself must stay untouched"


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


def fresh_fixture(d):
    """Two small new-layout stores (p4-recall's test fixture) and one lesson task bound to one of them."""
    sys.path.insert(0, str(REPO / "lbiza" / "plugins" / "p4-recall" / "scripts"))
    from test_store import make_store
    a = make_store(str(Path(d) / "a"))
    lessons = Path(d) / "lessons.jsonl"
    lessons.write_text(json.dumps({
        "id": "lesson-ap-p4_mac-branch", "category": "lessons", "split": "train", "from_store": "ap-p4_mac",
        "prompt": "Which branch does the Mac's work go on, 0.0.1-1.0.0_mac or the mac_mac one?",
        "grader": {"type": "judge", "rubric": "Passes if it names 0.0.1-apple&win&mac_mac."},
        "reference": "0.0.1-apple&win&mac_mac, cut under 0.0.1-apple&win&mac.",
        "bad": ["0.0.1-1.0.0_mac."]}) + "\n", encoding="utf-8")
    return {"p4-p4": a, "ap-p4_mac": a}, lessons


def test_fresh_validation_fake():
    """The fresh validation notebook, every cell with FAKE, on two fixture stores: tasks, contexts, the judge check,
    the three runs, the findings and the (empty) upgrades step, nothing spent; the short turns' own readings never
    reach their contexts."""
    import fresh_validation as fv
    import make_fresh_validation_notebook as mk
    nb = mk.notebook()
    codes = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    for c in codes:
        ast.parse(c)
    first = "".join(nb["cells"][0]["source"])
    assert mk.PAID_COMMAND in first and "$" in first and "TOTAL_MAX_USD" in first
    if FRESH_NOTEBOOK.exists():
        assert json.loads(FRESH_NOTEBOOK.read_text())["cells"] == nb["cells"], "regenerate the notebook"
    saved = fv.settings()
    with tempfile.TemporaryDirectory() as d:
        stores, lessons = fresh_fixture(d)
        g = {}
        exec(codes[0], g)                                       # the settings cell
        assert g["FAKE"] is True and g["TOTAL_MAX_USD"] == fv.TOTAL_MAX_USD == 42.0
        try:
            fv.configure(WORK=f"{d}/w", STORES=",".join(f"{k}={v}" for k, v in stores.items()),
                         LESSON_TASKS=str(lessons), TRAIN=False, N_SHORT=6, CACHE_FROM="",
                         UPGRADES_DIR=f"{d}/no-upgrades", NOW="2026-11-01 19:00")
            for c in codes[1:]:
                exec(c, g)
            s = g["summary"]
            assert s["fake"] and s["spent_usd"] == 0.0
            assert set(s["verdict"]) >= {"8.2 =recall never below the built-in", "8.3 short turns read right",
                                         "8.4 newer than the model"}
            assert {"=emission-plain", "=recall@ap-p4_mac", "=recall@p4-p4", "=recall+pinned@p4-p4"} <= \
                set(s["validate"])
            p = fv.paths()
            assert (p["results"] / "findings.md").exists() and (p["results"] / "summary.json").exists()
            short = [json.loads(l) for l in open(p["short"], encoding="utf-8")]
            assert short and all(t["category"] == "short" and t["held_cut"] for t in short)
            assert any(t["history"] for t in short), "the rows before a turn ride as its conversation"
            for t in short:
                said = t["reference"][len("I take it as: "):]
                for f in p["ctx"].glob(f"*.{t['id']}.md"):
                    assert said not in f.read_text(), (t["id"], "the held-out reading leaked into recall")
            newer = [json.loads(l) for l in open(p["newer"], encoding="utf-8")]
            assert len(newer) == 12 and all(t["category"] == "newer" and t["bad"] for t in newer)
            got = list(p["ctx"].glob("recall@ap-p4_mac.n11-mac-branch.md"))
            assert got and "0.0.1-apple&win&mac_mac" in got[0].read_text(), "the newer fact is recalled"
            assert g["upgrades"]["kept"] == []
        finally:
            fv.configure(**saved)


def test_upgrades_keep_fail_conflict():
    """The upgrades step on a dummy repo: one upgrade passes and is kept, one fails its own test, one conflicts with
    the kept one; the kept set is one commit with results.md, and nothing else in the worktree is committed."""
    import fresh_validation as fv
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "repo"
        repo.mkdir()
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def git(*a):
            return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True,
                                  env={**__import__("os").environ, **env})
        git("init", "-q")
        (repo / "gate.txt").write_text("threshold 0.50\nmargin 0.10\n")
        (repo / "notes.txt").write_text("unrelated\n")
        git("add", "-A")
        git("commit", "-q", "-m", "base")
        (repo / "notes.txt").write_text("an uncommitted change of the owner's\n")
        up = repo / ".docs" / "p4" / "upgrades"

        def upgrade(name, new_line, passes):
            u = up / name
            u.mkdir(parents=True)
            if new_line.startswith("threshold"):
                diff = "--- a/gate.txt\n+++ b/gate.txt\n@@ -1,2 +1,2 @@\n-threshold 0.50\n+" + new_line + \
                    "\n margin 0.10\n"
            else:                                  # a new file: applies over any other upgrade
                diff = "--- /dev/null\n+++ b/extra.txt\n@@ -0,0 +1 @@\n+" + new_line + "\n"
            (u / "patch.diff").write_text(diff)
            (u / "test.sh").write_text(f"echo '{{\"metric\": \"silent\", \"before\": 0.84, \"after\": 0.97, "
                                       f"\"pass\": {'true' if passes else 'false'}}}'\n")
            (u / "README.md").write_text(name + "\n")
        upgrade("a-threshold", "threshold 0.65", True)
        upgrade("b-worse", "margin 0.20", False)
        upgrade("c-other", "threshold 0.70", True)
        (up / "index.json").write_text(json.dumps({"upgrades": [{"id": "a-threshold"}, {"id": "b-worse"},
                                                                {"id": "c-other"}]}))
        git("add", ".docs")
        git("commit", "-q", "-m", "the upgrades")
        rec = fv.step_upgrades(repo=repo, upgrades_dir=up, tests=["test -f {root}/gate.txt"],
                               measures={"gate": "cat {root}/gate.txt"}, work=f"{d}/w", apply=True, paid=False)
        why = {r["id"]: r["why"] for r in rec["upgrades"]}
        assert rec["kept"] == ["a-threshold"], why
        assert "did not pass" in why["b-worse"]
        assert why["c-other"].startswith("conflicts with an upgrade already kept: a-threshold"), why
        assert rec["measures"]["gate"]["ok"] and "threshold 0.65" in " ".join(rec["measures"]["gate"]["tail"])
        assert rec["committed"], rec
        show = git("show", "--stat", "--format=%s", "HEAD").stdout
        assert "p4 upgrades: a-threshold" in show and "gate.txt" in show and "results.md" in show
        assert "notes.txt" not in show and git("status", "--short").stdout.strip() == "M notes.txt"
        res = (up / "results.md").read_text()
        assert "| a-threshold | yes |" in res and "| b-worse | no |" in res and "0.97" in res


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name, "ok")
    shutil.rmtree(HERE / "__pycache__", ignore_errors=True)
    print("test_overrides_suite.py: all green")
