"""Drive the installed p4-recall plugin's real hooks, through its own run-hook.sh, on a copy of a store: session
start, a prompt that serves a rule, the statement command exactly as the block prints it, the end of the turn,
and what each left behind. The store is only read.

    python3 -I scripts/session/live_e2e.py <project>/.claude/p4 [--root <plugin root>] [--prompt "..."]

The prompt has to be one recall shows a rule line for; without --prompt the store's own tasks are tried, newest
first, until one does. Exit 0 when every check passes."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import argparse

HOME = os.path.expanduser("~")
ap = argparse.ArgumentParser()
ap.add_argument("store")
ap.add_argument("--root", default="", help="the plugin root; default: the newest installed p4-recall, else this checkout's")
ap.add_argument("--prompt", default="")
args = ap.parse_args()
cached = sorted((p for p in glob.glob(os.path.join(HOME, ".claude", "plugins", "cache", "p4-marketplace", "p4-recall", "*"))
                 if os.path.basename(p).replace(".", "").isdigit()), key=lambda p: [int(x) for x in os.path.basename(p).split(".")])
ROOT = args.root or (cached[-1] if cached else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lbiza", "plugins", "p4-recall"))
ROOT = os.path.abspath(ROOT)
S = os.path.join(ROOT, "scripts")
sys.path.insert(0, S)
LIVE = os.path.abspath(args.store)
git_bash = os.path.join("C:" + os.sep, "Program Files", "Git", "bin", "bash.exe")
BASH = git_bash if os.path.exists(git_bash) else "bash"
PROMPT = args.prompt
SID = "e2e0e2e0-1111-2222-3333-444455556666"

tmp = tempfile.mkdtemp(prefix="p4-live-")
proj = os.path.join(tmp, "proj")
p4 = os.path.join(proj, ".claude", "p4")
shutil.copytree(LIVE, p4, ignore=shutil.ignore_patterns(".git", "index-cache.tmp*", "scratchpad", "served", "flights", "view"))
subprocess.run(["git", "init", "-q", proj], capture_output=True)
env = {**os.environ, "CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj}
env.pop("P4_RECALL_INJECT", None)
ok = []


def hook(name, payload):
    t = time.time()
    r = subprocess.run([BASH, os.path.join(ROOT, "hooks", "run-hook.sh").replace("\\", "/"), name], input=json.dumps(payload),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    ms = round((time.time() - t) * 1000)
    try:
        out = json.loads(r.stdout) if r.stdout.strip() else {}
    except ValueError:
        out = {"raw": r.stdout[:200]}
    return out, ms, r.returncode


def check(name, cond, note=""):
    ok.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({note})" if note else ""))


try:
    import labels as lb, said, view  # noqa: E402,E401
    import p4 as cli  # noqa: E402
    import repo  # noqa: E402
    SLUG = view.slug_dir(repo.project_of(LIVE) or os.path.dirname(os.path.dirname(LIVE)))
    if not PROMPT:                               # the newest task recall shows a rule, correction or fact line for
        for t in sorted(lb.read_tasks(p4).values(), key=lambda t: t.get("time", ""), reverse=True)[:400]:
            text = t.get("text") or ""
            if text and not text.lstrip().startswith("<") and any(
                    i.startswith(("rules.md", "corrections.md", "retractions.md", "facts.md")) for i in cli.query(p4, text)["ids"]):
                PROMPT = text
                break
    with open(os.path.join(p4, "p4.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    was = (cfg["recall"].get("said") or {}).get("mode", "off")
    cfg["recall"]["said"] = {"mode": "on"}       # the copy runs with statements on, whatever the store has
    with open(os.path.join(p4, "p4.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    print("plugin", ROOT, "| the store's said mode:", was)
    out, ms, rc = hook("layout", {"hook_event_name": "SessionStart", "source": "startup", "cwd": proj, "session_id": SID})
    check("session start hook runs clean", rc == 0 and "systemMessage" not in out, f"{ms} ms")
    out, ms, rc = hook("recall", {"prompt": PROMPT, "session_id": SID, "cwd": proj})
    ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("a prompt serves a rule line with a handle", "[r1]" in ctx and " rule: " in ctx, f"{ms} ms")
    check("the block asks for a statement and prints the command once", ctx.count("where SAID is: ") == 1 and "SAID applied r1" in ctx)
    cmd = ctx.split("where SAID is: ")[1].strip() if "where SAID is: " in ctx else ""
    r = subprocess.run([BASH, "-c", cmd + " applied r1"], capture_output=True, text=True, cwd=tmp)
    check("the statement command as printed runs", r.returncode == 0 and "said: noted" in r.stdout, (r.stdout + r.stderr).strip()[:80])
    found = sorted(glob.glob(os.path.join(SLUG, "*.jsonl")), key=os.path.getsize)
    real = found[len(found) // 2] if found else ""
    check("a transcript of the project is on this machine", bool(real), SLUG)
    out, ms, rc = hook("close", {"session_id": SID, "cwd": proj, "transcript_path": real, "last_assistant_message": "Moved it to src/axiom/services/mojo as the rule says."})
    check("end-of-turn hook runs clean", rc == 0 and "systemMessage" not in out, f"{ms} ms")
    out, ms, rc = hook("recall", {"prompt": "ok", "session_id": SID, "cwd": proj})
    check("a short prompt gets no statement request", "SAID" not in json.dumps(out), f"{ms} ms")

    rows = [r for r in lb.read_tsv(said.path(p4)) if r["session"] == SID[:8]]
    check("said.tsv holds the asked row and the statement", [r["act"] for r in rows][:2] == ["asked", "applied"], str([r["act"] for r in rows]))
    lab = [r for r in lb.read_tsv(lb.mpath(p4, lb.TRAIN)) if r["source"] == "said"]
    check("the statement is a label on the rule", len(lab) == 1 and lab[0]["label"] == "1" and lab[0]["entry"].startswith("rules.md:"))
    check("training reads it (mode on)", any(r["source"] == "said" for r in lb.training_labels(p4)), said.mode(p4))
    v = view.load(p4, SID)
    check("the context record was written at the end of the turn", bool(v) and v["turns"] > 0 and v.get("size", {}).get("calls", 0) > 0,
          f"{v['turns']} turns, {len(v['files'])} files, {v['size']['last'] // 1000}k tokens" if v and v.get("size") else "none")
    check("the shown rule is in the session's record", bool(v) and lab and lab[0]["entry"] in v["entries"])
    r = subprocess.run([sys.executable, "-I", os.path.join(S, "p4.py"), "view", SID, "--p4", p4], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("p4.py view describes the session", "context:" in r.stdout and "what filled it:" in r.stdout)
    r = subprocess.run([sys.executable, "-I", os.path.join(S, "p4.py"), "check", "--p4", p4], capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((l.strip() for l in r.stdout.splitlines() if "said (" in l), "")
    check("check counts it", "asked on 1 turns, stated on 1; applied 1" in line, line)
    r = subprocess.run([sys.executable, "-I", os.path.join(S, "p4.py"), "train", "--p4", p4], capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("a training round runs with the statement in its labels", r.returncode == 0 and "train: round" in r.stdout, r.stdout.strip()[:70])
    check("no term dictionary was recreated", not os.path.exists(os.path.join(p4, "store", "vocabulary.md")))
    print(f"{sum(ok)} of {len(ok)} passed")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if ok and all(ok) else 1)
