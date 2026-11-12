#!/usr/bin/env python3
"""issues.py: the one loop a child session that changes a repository runs (#28).

  issue    at its first hook, a child whose brief or plan names files in a repository with a GitHub `origin` gets an
           issue for its purpose: the brief, the plan and the parent's id in its body. An issue its brief already
           names, open on that repository, is taken as its own instead of filing a second. The number is kept in
           session.json as `issue`, and a line tells the child. A read-only child (a check, an audit, a question, a
           relay) gets none, and neither does a repository with no GitHub remote.
  commits  at each step boundary, a commit made since the issue was taken that does not say `Closes #N` gets one line.
  proof    before the child counts as finished, its plan names the test that proves the issue fixed: a backticked
           command or a test file in a step that speaks of a test, or `phi.py proof "<command>"`. phi runs it again at
           Stop on the final head and comments the result on the issue; a failing test keeps the child open.
  push     the proven work is pushed at once and its p4 stores synced with `p4.py sync --push`; the push of the
           `Closes #N` commit closes the issue. Force-pushes and history rewrites still ask.
  archive  only with the issue closed and the test passed does archive-when-done retire the child, its outcome note on
           the parent carrying the issue link, the commit and the test.

`gh` is P4_PHI_GH when set (a .py file is run with this python), else `gh` on PATH. P4_PHI_ISSUES=0 or p4.json's
phi.issues false turns the loop off. phi.py calls these from the hooks every open session already has.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import relay  # noqa: E402

GH_S = 15                       # one gh call inside a hook
PROOF_S = 15.0                  # the proving test inside the Stop hook; a longer one finishes in the background
BODY_CHARS = 6000
TAIL_CHARS = 1500

WRITES = re.compile(r"\b(?:build|fix|add|implement|chang|edit|writ|refactor|renam|remov|delet|mov|creat|updat|port|"
                    r"migrat|commit|patch|rewrit|wire|seed|ship|land)\w*\b", re.I)
READS = re.compile(r"^\W*(?:check|audit|verify|review|question|relay|ask|answer|report|investigate|look|read|find|"
                   r"explain|measure|compare|list|show|summari[sz]e|confirm|survey)\b", re.I)
READ_ONLY = re.compile(r"\bread[- ]only\b|\b(?:do not|don't|never|no)\s+(?:edit|chang|commit|writ)\w*", re.I)
FILE_RE = re.compile(r"(?<![\w/\\.-])[\w-]+\.(?:py|js|ts|tsx|jsx|mjs|cjs|json|md|sh|ps1|toml|ya?ml|go|rs|c|h|cpp|"
                     r"hpp|cs|java|kt|rb|php|swift|sql|html|css|txt|cfg|ini)\b")
GITHUB = re.compile(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/*$", re.I)
NAMED = re.compile(r"(?:github\.com/([\w.-]+/[\w.-]+)/issues/|\b([\w.-]+/[\w.-]+)\s*(?:issue\s*)?#|\bissues?\s+#?|"
                   r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#)(\d+)", re.I)
URL_NUM = re.compile(r"/issues/(\d+)")
TEST_WORD = re.compile(r"\btest|\bsuite|\bpytest\b|\bunittest\b", re.I)
TEST_CMD = re.compile(r"`([^`\n]{3,})`")
TEST_FILE = re.compile(r"((?:[A-Za-z]:)?[\w./\\-]*?\btest_[\w-]+\.py|[\w./\\-]*?[\w-]+_test\.py)\b")


def on(home=""):
    if os.environ.get("P4_PHI_ISSUES") == "0":
        return False
    try:
        import p4conf
        store = home or ""
        return p4conf.section(store, "phi", write=False).get("issues", True) is not False if store else True
    except Exception:  # noqa: BLE001
        return True


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def gh(args, cwd=None, timeout=GH_S):
    """gh's CompletedProcess, None when there is no gh or it failed to start."""
    cmd = os.environ.get("P4_PHI_GH") or shutil.which("gh")
    if not cmd:
        return None
    argv = [sys.executable, "-I", "-X", "utf8", cmd] if cmd.endswith(".py") else [cmd]
    try:
        return subprocess.run(argv + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, cwd=cwd or None)
    except (OSError, subprocess.SubprocessError):
        return None


def git(repo, *args):
    r = relay._git(repo, *args)
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


def github_of(repo):
    """'owner/name' of a repository's `origin` on GitHub, '' for none."""
    m = GITHUB.search(git(repo, "remote", "get-url", "origin")) if repo else None
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def writing(text):
    """True when a brief or plan asks for changes, not a check, an audit, a question or a relay."""
    text = str(text or "")
    if READ_ONLY.search(text):
        return False
    lead = re.sub(r"^[\s#*>`-]+", "", text)
    if READS.match(lead) and not WRITES.search(lead.split("\n", 1)[0]):
        return False
    return bool(WRITES.search(text))


def repos_named(text, base):
    """[(repo path, 'owner/name')] of the GitHub repositories whose files the text names, in the order named."""
    out, seen = [], set()
    cands = [relay.repo_of(p) for p in relay.paths_in(text, base)]
    if base and FILE_RE.search(text):
        cands.append(relay.repo_of(base))
    for repo in cands:
        if not repo or repo in seen:
            continue
        seen.add(repo)
        slug = github_of(repo)
        if slug:
            out.append((repo, slug))
    return out


def named_issues(text, slug):
    """The numbers of the issues on `slug` the text already names, in order."""
    out = []
    for m in NAMED.finditer(str(text or "")):
        other = m.group(1) or m.group(2)
        if other and other.lower() != slug.lower():
            continue
        if int(m.group(3)) not in out:
            out.append(int(m.group(3)))
    return out


def named_issue(text, slug):
    """The number of the first issue on `slug` the text already names, 0 for none."""
    return (named_issues(text, slug) or [0])[0]


def issue_state(slug, n):
    """'OPEN', 'CLOSED', or '' when gh cannot say."""
    r = gh(["issue", "view", str(n), "-R", slug, "--json", "state", "-q", ".state"])
    out = (r.stdout or "").strip().upper() if r is not None and r.returncode == 0 else ""
    return out if out in ("OPEN", "CLOSED") else ""


def comment(slug, n, body):
    r = gh(["issue", "comment", str(n), "-R", slug, "--body", body])
    return r is not None and r.returncode == 0


def plan_lines(home, sid):
    import plans
    return "\n".join(f"- [{x.get('status') or 'pending'}] {x.get('addr')} {relay._short(x.get('content'), 200)}"
                     for x in plans.load(home, sid).get("steps") or [])


def link_of(rec):
    for k in ("url", "webUrl", "sessionUrl", "link"):
        v = (rec or {}).get(k)
        if isinstance(v, str) and v.startswith(("http", "claude:")):
            return v
    return ""


def ensure(home, s, text, base, where, rec=None):
    """At a child's first message (`where` "brief") or its first plan ("plan"): its issue, filed or taken from its
    brief, kept in s["issue"] (s is changed, the caller saves it). Returns the line for the child, '' for none."""
    parent = relay._parent(s)
    if not parent or not on(home):
        return ""
    if s.get("issue"):
        return ""
    looked = list(s.get("issueLooked") or [])
    if where in looked:
        return ""
    s["issueLooked"] = looked + [where]
    task, text = str(s.get("task") or ""), str(text or "")
    whole = text if task[:200] in text else "\n".join(p for p in (task, text) if p)
    if not writing(whole):
        return ""
    repos = repos_named(whole, base)
    if not repos:
        return ""
    repo, slug = repos[0]
    named = named_issues(whole, slug)
    n = next((k for k in named if issue_state(slug, k) == "OPEN"), 0)
    url, adopted = (f"https://github.com/{slug}/issues/{n}", True) if n else ("", False)
    if named and not n:
        return ""                                  # its purpose is filed already, in issues now closed: none again
    if not n:
        plan = plan_lines(home, s["sessionId"])
        title = relay._short(re.sub(r"^[\s#*>]+", "", (s.get("title") or whole).strip().split("\n", 1)[0]), 100)
        link = link_of(rec)
        body = (f"Filed by p4-phi for the child session `{s['sessionId']}`, started by `{parent}`."
                + (f" Session: {link}" if link else "") + "\n\n### Brief\n\n" + whole[:BODY_CHARS]
                + "\n\n### Plan\n\n" + (plan or "(none yet)")
                + "\n\nThe child's commits say `Closes #N`; phi re-runs the test that proves it at Stop, comments the "
                  "result here, and archives the child once this closes.")
        r = gh(["issue", "create", "-R", slug, "--title", title, "--body", body])
        m = URL_NUM.search((r.stdout or "") if r is not None and r.returncode == 0 else "")
        if not m:
            return ""
        n, url = int(m.group(1)), r.stdout.strip().splitlines()[-1].strip()
    s["issue"] = {"repo": slug, "path": repo, "number": n, "url": url, "time": now(), "adopted": adopted,
                  "base": git(repo, "rev-parse", "HEAD"), "planPosted": bool(plan_lines(home, s["sessionId"]))}
    return (f"phi (p4-phi): this session's purpose is {slug}#{n} ({url}), "
            + ("named in its brief" if adopted else "filed now") + ". Its loop: each commit says `Closes #" + str(n)
            + "`; a plan step names the test that proves it fixed (a backticked command or a test file, or "
              "`phi.py proof \"<command>\"`); phi re-runs that test at Stop on the final head and comments the "
              "result on the issue; green work is pushed at once, without asking, and each p4 store it touched synced "
              "with `p4.py sync --push`; then, with the issue closed, this session is archived.")


def post_plan(home, s):
    """The plan, commented on the issue once, when the issue was filed before the child had one."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or iss.get("planPosted") or iss.get("adopted"):
        return False
    plan = plan_lines(home, s["sessionId"])
    if not plan:
        return False
    iss["planPosted"] = True
    return comment(iss["repo"], iss["number"], "The child's plan:\n\n" + plan)


def _commits(repo, rng, limit=40):
    out = git(repo, "log", f"-{limit}", "--reverse", "--format=%h%x1f%s%x1f%B%x1e", *([rng] if rng else []))
    rows = []
    for rec in out.split("\x1e"):
        parts = rec.strip().split("\x1f")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def closes(body, slug, n):
    for ref in relay.CLOSES.findall(body or ""):
        other, _, num = ref.rpartition("#")
        if num == str(n) and (not other or other.lower() == slug.lower()):
            return True
    return False


def own_commits(s, cwd=""):
    """[(repo, sha, subject, body)] of the commits made since the issue was taken, in its repository and in the
    session's own checkout when that is a clone of the same one."""
    iss = s.get("issue") or {}
    out, seen = [], set()
    repos = [iss.get("path") or ""]
    here = relay.repo_of(cwd) if cwd else ""
    if here and here != repos[0] and github_of(here) == iss.get("repo"):
        repos.append(here)
    for repo in repos:
        if not repo:
            continue
        base = iss.get("base") if repo == iss.get("path") else ""
        rng = f"{base}..HEAD" if base else ""
        rows = _commits(repo, rng) if base else []
        if not base:
            made = str(s.get("createdAt") or "")
            out_ = git(repo, "log", "-40", "--reverse", f"--since={made}", "--format=%h%x1f%s%x1f%B%x1e") if made else ""
            rows = [tuple(r.strip().split("\x1f")[:3]) for r in out_.split("\x1e") if r.strip().count("\x1f") >= 2]
        for sha, subj, body in rows:
            if sha not in seen:
                seen.add(sha)
                out.append((repo, sha, subj, body))
    return out


def unclosed_text(home, s, cwd=""):
    """At a step boundary: this child's commits that do not say `Closes #N`, each named once (s is changed)."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or not on(home):
        return ""
    told = list(iss.get("flagged") or [])
    new = [(sha, subj) for _, sha, subj, body in own_commits(s, cwd)
           if not closes(body, iss["repo"], iss["number"]) and sha not in told]
    if not new:
        return ""
    iss["flagged"] = (told + [sha for sha, _ in new])[-100:]
    n = iss["number"]
    named = ", ".join(f"{sha} \"{relay._short(subj, 60)}\"" for sha, subj in new[:5])
    return (f"phi (p4-phi): commit{'s' if len(new) > 1 else ''} {named} since this session took {iss['repo']}#{n} "
            f"{'do' if len(new) > 1 else 'does'} not say `Closes #{n}`. This session's commits close its issue: give "
            f"the next one `Closes #{n}`, or amend an unpushed one's message.")


# --- the proving test -------------------------------------------------------------------------------------------------

def proof_path(home, sid):
    return os.path.join(relay._dir(home, sid), "proof.json")


def find_file(repo, name):
    """A test file named in a step, as a path: as given when it exists, else the tracked file with that name."""
    for base in (repo, ""):
        p = os.path.join(base, name) if base else name
        if os.path.isfile(p):
            return p
    tail = name.replace("\\", "/").rsplit("/", 1)[-1]
    for f in git(repo, "ls-files").splitlines():
        if f.rsplit("/", 1)[-1] == tail and f.endswith(name.replace("\\", "/")):
            return os.path.join(repo, f)
    return ""


def proof_of(home, s):
    """{'cmd', 'cwd', 'step'} of the test that proves the issue fixed: named by `phi.py proof`, else by a plan step
    that speaks of a test and names a backticked command or a test file; None when none is named."""
    import plans
    iss = s.get("issue") or {}
    if isinstance(iss.get("test"), dict) and iss["test"].get("cmd"):
        return dict(iss["test"], step=iss["test"].get("step") or "phi.py proof")
    repo = iss.get("path") or s.get("cwd") or ""
    for x in plans.load(home, s["sessionId"]).get("steps") or []:
        text = str(x.get("content") or "")
        if not TEST_WORD.search(text):
            continue
        for c in TEST_CMD.findall(text):
            if TEST_WORD.search(c) or TEST_FILE.search(c):
                return {"cmd": c.strip(), "cwd": repo, "step": x.get("addr")}
        m = TEST_FILE.search(text)
        if m:
            path = find_file(repo, m.group(1))
            if path:
                return {"cmd": f"\"{sys.executable}\" -I -X utf8 \"{path}\"".replace("\\", "/"), "cwd": repo,
                        "step": x.get("addr")}
    return None


def _argv(cmd):
    sh = shutil.which("sh") or shutil.which("bash")
    return ([sh, "-c", cmd], False) if sh else (cmd, True)


def run_now(cmd, cwd, timeout):
    """(exit code, output tail), or (None, '') when it outlasted `timeout`."""
    argv, shell = _argv(cmd)
    try:
        r = subprocess.run(argv, shell=shell, cwd=cwd or None, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, ""
    except OSError as e:
        return 127, str(e)
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-TAIL_CHARS:]


def run_background(home, sid, cmd, cwd, head):
    """The test, run on in a process of its own that writes proof.json when it ends."""
    path = proof_path(home, sid)
    relay._write_json(path, {"cmd": cmd, "cwd": cwd, "head": head, "state": "running", "time": now()})
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.abspath(__file__), "proof-run", path],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, start_new_session=os.name != "nt", close_fds=True)
    except OSError:
        pass


def proof_run(path):
    d = relay._read_json(path)
    code, tail = run_now(d.get("cmd") or "", d.get("cwd") or "", 3600)
    d.update(state="passed" if code == 0 else "failed", code=code, tail=tail, time=now())
    relay._write_json(path, d)


def proven(home, s, proof):
    """proof.json for the test on the current head: run now when it has no result for that head, in the background
    when it outlasts PROOF_S."""
    cwd = proof.get("cwd") or (s.get("issue") or {}).get("path") or ""
    head = git(cwd, "rev-parse", "--short", "HEAD") if cwd else ""
    path = proof_path(home, s["sessionId"])
    d = relay._read_json(path)
    if d.get("cmd") == proof["cmd"] and d.get("head") == head and d.get("state") in ("passed", "failed", "running"):
        return d
    try:
        limit = float(os.environ.get("P4_PHI_PROOF_S") or PROOF_S)
    except ValueError:
        limit = PROOF_S
    code, tail = run_now(proof["cmd"], cwd, limit)
    if code is None:
        run_background(home, s["sessionId"], proof["cmd"], cwd, head)
        return relay._read_json(path)
    d = {"cmd": proof["cmd"], "cwd": cwd, "head": head, "state": "passed" if code == 0 else "failed", "code": code,
         "tail": tail, "time": now()}
    relay._write_json(path, d)
    return d


def _told(iss, key):
    if iss.get("gateTold") == key:
        return True
    iss["gateTold"] = key
    return False


def gate(home, s, cwd=""):
    """At the Stop of a finished child with an issue: (ok, reason, note). ok when the test passed on the final head
    and the issue is closed; the reason sends the turn back, said once for each state of the head; the note is what
    the retirement keeps. s is changed; the caller saves it. A child with no issue is always ok."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or not on(home):
        return True, "", ""
    slug, n = iss["repo"], iss["number"]
    ref = f"{slug}#{n}"
    proof = proof_of(home, s)
    if not proof:
        return False, ("" if _told(iss, "no-test") else
                       f"phi (p4-phi): this session's work looks finished, but its plan names no test that proves "
                       f"{ref} fixed. Add a plan step naming it, a backticked command or a test file, or run "
                       f"`phi.py proof \"<command>\"`; phi re-runs it at Stop before this session is archived."), ""
    d = proven(home, s, proof)
    head, state = d.get("head") or "?", d.get("state") or "running"
    if state in ("passed", "failed") and d.get("commented") != f"{head}:{state}":
        body = (f"p4-phi re-ran the proving test `{proof['cmd']}` on {head}: **{state}** (exit {d.get('code')})."
                + (f"\n\n```\n{str(d.get('tail') or '')[-1200:]}\n```" if d.get("tail") else ""))
        if comment(slug, n, body):
            d["commented"] = f"{head}:{state}"
            relay._write_json(proof_path(home, s["sessionId"]), d)
    if state == "running":
        return False, ("" if _told(iss, f"running:{head}") else
                       f"phi (p4-phi): the proving test `{proof['cmd']}` outlasted the Stop hook and runs on in the "
                       f"background on {head}. Run it yourself to see its result, then end the turn; phi reads its "
                       f"own run's result at the next Stop."), ""
    if state == "failed":
        tail = relay._short(" ".join(str(d.get("tail") or "").split()[-80:]), 600)
        return False, ("" if _told(iss, f"failed:{head}") else
                       f"phi (p4-phi): phi re-ran the proving test `{proof['cmd']}` on {head} and it failed (exit "
                       f"{d.get('code')}), so this session stays open and is not archived until it passes. Its last "
                       f"lines: {tail}"), ""
    mine = own_commits(s, cwd)
    closing = [(repo, sha, subj) for repo, sha, subj, body in mine if closes(body, slug, n)]
    st = issue_state(slug, n)
    pushed = bool(closing) and all(_pushed(repo, sha) for repo, sha, _ in closing)
    if st == "CLOSED" or (not st and pushed):
        sha, subj = (closing[-1][1], closing[-1][2]) if closing else ("", "")
        iss["closed"] = now()
        note = (f"Issue: {iss['url']} (closed). Closing commit: "
                + (f"{sha} \"{relay._short(subj, 80)}\"" if sha else "none found") + f". Proven by `{proof['cmd']}` "
                f"on {head}: passed.")
        return True, "", note
    if not closing:
        why = (f"phi (p4-phi): the proving test passed on {head}, but no commit of this session says `Closes #{n}`. "
               f"Commit the work with `Closes #{n}` in its message, then push it at once, without asking.")
        return False, ("" if _told(iss, f"no-close:{head}") else why), ""
    if not pushed:
        why = (f"phi (p4-phi): the proving test passed on {head}. ezexe's rule is that green issue work is pushed at "
               f"once: push the `Closes #{n}` commit {closing[-1][1]} now, without asking, and sync each p4 store it "
               f"touched with `p4.py sync --push`; the push closes {ref}. Force-pushes and history rewrites still ask.")
        return False, ("" if _told(iss, f"push:{head}") else why), ""
    why = (f"phi (p4-phi): the `Closes #{n}` commit {closing[-1][1]} is pushed, but {ref} is still open: GitHub closes "
           f"it when that commit reaches the default branch. Land it there, or close it with `gh issue close {n} -R "
           f"{slug} --comment \"<the commit and the test>\"`.")
    return False, ("" if _told(iss, f"open:{head}") else why), ""


def _pushed(repo, sha):
    """True when a commit is on a remote branch."""
    out = git(repo, "branch", "-r", "--contains", sha)
    return bool(out.strip())


if __name__ == "__main__":
    if sys.argv[1:2] == ["proof-run"] and len(sys.argv) > 2:
        proof_run(sys.argv[2])
