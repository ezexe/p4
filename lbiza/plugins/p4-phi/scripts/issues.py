#!/usr/bin/env python3
"""issues.py: the one loop a child session that changes a repository runs.

  issue    at its first hook, a child whose brief or task list names files in a repository with a GitHub `origin`
           gets an issue for its purpose: the brief, the task list and the parent session's id in its body. An issue
           its brief already names, open on that repository, is taken as its own instead of filing a second. The
           number is kept in session.json as `issue`, and a line tells the child. A read-only child, such as a check,
           an audit, a question or a message to pass on, gets none, and neither does a repository with no GitHub
           remote.
  commits  at each step boundary, a commit made since the issue was taken that closes no issue gets one line.
  proof    before the child counts as finished, its task list names the regression test that proves the issue fixed:
           a backticked command or a test file in a step that speaks of a test, or `phi.py proof "<command>"`. p4-phi
           runs it again at Stop on the final head and comments the result on the issue; a failing test keeps the
           child open.
  push     the proven work is pushed at once and each store it touched synced with `p4.py sync --push`; the
           `Closes #N` commit closes the issue once it reaches the default branch. Anything that cannot be undone,
           such as a force-push, a history rewrite or a deletion, still asks.
  archive  a finished child, marked `disposable` or archiving itself, is counted as archived only with the issue
           closed and the test passed, its outcome note on the parent carrying the issue link, the commit and the test.
           A child that archives itself before it is finished is counted as archived at once, its open steps named.

`gh` is P4_PHI_GH when set, and a .py file named there is run with this Python; else `gh` on PATH. P4_PHI_ISSUES=0
or p4.json's phi.issues false turns the loop off. phi.py calls these from its hooks.
"""

import glob
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
PROOF_S = 15.0                  # the regression test inside the Stop hook; a longer one finishes in the background
BODY_CHARS = 6000
TAIL_CHARS = 1500

WRITES = re.compile(r"\b(?:build|fix|add|implement|chang|edit|writ|refactor|renam|remov|delet|mov|creat|updat|port|"
                    r"migrat|commit|patch|rewrit|wire|seed|ship|land)\w*\b", re.I)
READS = re.compile(r"^\W*(?:check|audit|verify|review|question|relay|ask|answer|report|investigate|look|read|find|"
                   r"explain|measure|compare|list|show|summari[sz]e|confirm|survey)\b", re.I)
READ_ONLY = re.compile(r"\bread[- ]only\b|\b(?:do not|don't|never|no)\s+(?:edit|chang|commit|writ)\w*|"
                       r"\b(?:chang|edit|commit|writ)\w*\s+(?:nothing|no\s+(?:tracked\s+)?files?)\b", re.I)
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
    """True when a brief or task list asks for changes, not a check, an audit, a question or a message to pass on."""
    text = str(text or "")
    if READ_ONLY.search(text):
        return False
    lead = re.sub(r"^[\s#*>`-]+", "", text)
    if READS.match(lead) and not WRITES.search(lead.split("\n", 1)[0]):
        return False
    return bool(WRITES.search(text))


SLUG = re.compile(r"(?<![\w./\\-])([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)(?![\w/\\-])")
SLUG_SAID = re.compile(r"(?:github\.com[:/]+|-R\s+|--repo\s+|\b(?:on|in|of|to|repo|repository)\s+)"
                       r"([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w-]*(?:\.[\w-]+)*?)(?=\.git\b|[#/\s,;:)]|\.?\s|\.?$)|"
                       r"(?<![\w./\\-])([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)#\d+")


def slugs_said(text):
    """The `owner/name` repositories a text names as repositories, in order: after github.com, `-R`, or a word
    like "on", or before `#N`. "ezexe/p4" is never read out of "ezexe/p4-phi"."""
    out = []
    for m in SLUG_SAID.finditer(str(text or "")):
        s = (m.group(1) or m.group(2) or "").rstrip(".")
        if s and s.lower() not in [x.lower() for x in out]:
            out.append(s)
    return out


def without_slugs(text, base):
    """The text with every `owner/name` token taken out that is no path under `base`: two parts, no file
    extension, and nothing on disk by that name, so a repository named as "on ezexe/p4" is never read as a path in
    the cwd's repository."""
    def keep(m):
        tok = m.group(1)
        if re.search(r"\.[A-Za-z0-9]{1,5}$", tok) and not tok.lower().endswith(".git"):
            return m.group(0)                      # lib/x.py: a file, there or still to be written
        if base and os.path.exists(os.path.join(base, tok)):
            return m.group(0)
        return " "
    return SLUG.sub(keep, str(text or ""))


def nested_repos(base):
    """The repositories one or two folders under `base`, such as a plugin checkout inside a project."""
    out = []
    if not base or not os.path.isdir(base):
        return out
    for pat in ("*/.git", "*/*/.git"):
        for g in sorted(glob.glob(os.path.join(base, pat)))[:40]:
            out.append(relay.norm(os.path.dirname(g)))
    return out


def repos_named(text, base):
    """The GitHub repositories the text is about, each as its path and its `owner/name`. A repository the text names
    by its `owner/name` comes first when a checkout of it is at hand: among the repositories of the paths named, the
    cwd's own, or one nested under the cwd. Then the repositories whose files the text names, in the order named. An
    `owner/name` token alone never names the cwd's repository."""
    text = str(text or "")
    out, seen = [], set()
    cands = [relay.repo_of(p) for p in relay.paths_in(without_slugs(text, base), base)]
    if base and FILE_RE.search(text):
        cands.append(relay.repo_of(base))
    said = [s.lower() for s in slugs_said(text)]
    if said:
        local = {}
        for repo in cands + [relay.repo_of(base) if base else ""] + nested_repos(base):
            if repo and repo not in local:
                local[repo] = github_of(repo).lower()
        first = [repo for s in said for repo, slug in local.items() if slug == s]
        cands = first + cands
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


def issue_title(title, brief):
    """An issue's title: the brief's own title line when it has one, else the session's title, else the brief's
    first sentence; cut at a clause or a sentence end, never mid-phrase and never with dots."""
    first = str(brief or "").strip().split("\n", 1)[0]
    head = re.sub(r"^[\s#*>]+", "", first) if re.match(r"\s*#+\s", first) else ""
    line = head or re.sub(r"^[\s#*>]+", "", str(title or "").strip().split("\n", 1)[0]) or re.sub(r"^[\s#*>]+", "", first)
    whole = re.sub(r"\s*(?:\.\.\.|\u2026)\s*$", "", line)
    if whole != line:
        whole = relay.whole_phrase(whole)          # a title the app cut already: its dangling end goes too
    return relay.clause_cut(whole, 100)


def ensure(home, s, text, base, where, rec=None):
    """At a child's first message, `where` "brief", or its first task list, `where` "plan": its issue, filed or
    taken from its brief, kept in s["issue"]; s is changed and the caller saves it. Returns the line for the child,
    '' for none."""
    parent = relay._parent(s)
    if not parent or not on(home):
        return ""
    if s.get("issue"):
        return ""
    if isinstance(s.get("reading"), dict):
        return ""                                  # a reading explores and commits nothing: no issue record
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
        title = issue_title(s.get("title"), whole)
        link = link_of(rec)
        body = (f"Filed by p4-phi for the child session `{s['sessionId']}`, started by `{parent}`."
                + (f" Session: {link}" if link else "") + "\n\n### Brief\n\n" + whole[:BODY_CHARS]
                + "\n\n### Task list\n\n" + (plan or "none yet")
                + "\n\nThe child's commits say `Closes #N`; p4-phi re-runs the regression test that proves it at Stop "
                  "and comments the result here, and the `Closes` commit closes this issue on reaching the default "
                  "branch.")
        r = gh(["issue", "create", "-R", slug, "--title", title, "--body", body])
        m = URL_NUM.search((r.stdout or "") if r is not None and r.returncode == 0 else "")
        if not m:
            return ""
        n, url = int(m.group(1)), r.stdout.strip().splitlines()[-1].strip()
    s["issue"] = {"repo": slug, "path": repo, "number": n, "url": url, "time": now(), "adopted": adopted,
                  "base": git(repo, "rev-parse", "HEAD"), "planPosted": bool(plan_lines(home, s["sessionId"]))}
    return (f"phi (p4-phi): this session's purpose is {slug}#{n}, {url}, "
            + ("named in its brief" if adopted else "filed now") + ". Its loop: each commit says `Closes #" + str(n)
            + "`; a step of its task list names the regression test that proves it fixed, as a backticked command or "
              "a test file, or `phi.py proof \"<command>\"` names it; p4-phi re-runs that test at Stop on the final "
              "head, comments the result on the issue and says what is still owed; the `Closes` commit closes the "
              "issue once it reaches the default branch.")


def done_text(home, s, cwd=""):
    """What `phi.py done` says about the issue this session closes, so a child that reports done learns which issue
    it closes and what it still owes before it closes: the commit, the regression test, the push. Nothing is read
    from GitHub."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not on(home):
        return ""
    if not iss:
        task = str(s.get("task") or "")
        for repo, slug in repos_named(task, s.get("cwd") or cwd or ""):
            nums = named_issues(task, slug)
            if nums:
                refs = ", ".join(f"{slug}#{n}" for n in nums[:8])
                return (f"this session has no issue record of its own; its task names {refs}. A commit closes one "
                        f"by saying `Closes #N` for it, once that commit reaches the default branch.")
        return ""
    slug, n = iss["repo"], iss["number"]
    owed = []
    closing = [(repo, sha) for repo, sha, _, body in own_commits(s, cwd) if closes(body, slug, n)]
    if not closing:
        owed.append(f"a commit that says `Closes #{n}`")
    proof = proof_of(home, s)
    if not proof:
        owed.append("the regression test that proves it, named in a step of the task list or with "
                    "`phi.py proof \"<command>\"`")
    if closing and not all(_pushed(repo, sha) for repo, sha in closing):
        owed.append(f"the push of {closing[-1][1]}")
    have = []
    if closing:
        have.append(f"commit {closing[-1][1]} says `Closes #{n}`")
    if proof:
        have.append(f"its regression test is `{proof['cmd']}`")
    return (f"this session closes {slug}#{n}, {iss.get('url')}"
            + (": " + "; ".join(have) if have else "") + ". "
            + ("Still owed before it closes: " + "; ".join(owed) + "." if owed else
               "Nothing is owed but the Stop check: p4-phi re-runs the test on the final head, and the commit closes "
               "the issue once it reaches the default branch."))


def post_plan(home, s):
    """The task list, commented on the issue once, when the issue was filed before the child had one."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or iss.get("planPosted") or iss.get("adopted"):
        return False
    plan = plan_lines(home, s["sessionId"])
    if not plan:
        return False
    iss["planPosted"] = True
    return comment(iss["repo"], iss["number"], "The child's task list:\n\n" + plan)


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
    """The commits made since the issue was taken, each as its repo, sha, subject and body, in the issue's
    repository and in the session's own checkout when that is a clone of the same one."""
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
            made = str(iss.get("time") or s.get("createdAt") or "")      # since the issue was taken
            out_ = git(repo, "log", "-40", "--reverse", f"--since={made}", "--format=%h%x1f%s%x1f%B%x1e") if made else ""
            rows = [tuple(r.strip().split("\x1f")[:3]) for r in out_.split("\x1e") if r.strip().count("\x1f") >= 2]
        for sha, subj, body in rows:
            if sha not in seen:
                seen.add(sha)
                out.append((repo, sha, subj, body))
    return out


def unclosed_text(home, s, cwd=""):
    """At a step boundary: this child's commits that do not say `Closes #N`, each named once; s is changed."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or not on(home):
        return ""
    told = list(iss.get("flagged") or [])
    # a commit that closes another issue is that issue's work, done on purpose: only one closing none is named
    new = [(sha, subj) for _, sha, subj, body in own_commits(s, cwd)
           if not relay.CLOSES.search(body or "") and sha not in told]
    if not new:
        return ""
    iss["flagged"] = (told + [sha for sha, _ in new])[-100:]
    n = iss["number"]
    named = ", ".join(f"{sha} \"{relay._short(subj, 60)}\"" for sha, subj in new[:5])
    return (f"phi (p4-phi): commit{'s' if len(new) > 1 else ''} {named} since this session took {iss['repo']}#{n} "
            f"{'do' if len(new) > 1 else 'does'} not say `Closes #{n}`. This session's commits close its issue: give "
            f"the next one `Closes #{n}`, or amend an unpushed one's message.")


# --- the regression test ----------------------------------------------------------------------------------------------

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
    """{'cmd', 'cwd', 'step'} of the regression test that proves the issue fixed: named by `phi.py proof`, else by a
    step of the task list that speaks of a test and names a backticked command or a test file; None when none is
    named."""
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
    """The exit code and the output's tail, or None and '' when it outlasted `timeout`."""
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
    if os.name == "nt":                 # a console of its own with no window, which sh, git and the test share;
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)       # DETACHED_PROCESS would give each its own window
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
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
    """At the Stop of a finished child with an issue: returns ok, the reason and the note. ok is true when the test
    passed on the final head and the issue is closed; the reason sends the turn back, said once for each state of the
    head; the note is what the child's replaces: note on its parent keeps when the child is counted as archived. s is
    changed; the caller saves it. A child with no issue is always ok."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or not on(home):
        return True, "", ""
    slug, n = iss["repo"], iss["number"]
    ref = f"{slug}#{n}"
    proof = proof_of(home, s)
    if not proof:
        return False, ("" if _told(iss, "no-test") else
                       f"phi (p4-phi): this session's work looks finished, but its task list names no regression test "
                       f"that proves {ref} fixed. Add a step naming it, a backticked command or a test file, or run "
                       f"`phi.py proof \"<command>\"`."), ""
    d = proven(home, s, proof)
    head, state = d.get("head") or "?", d.get("state") or "running"
    if state in ("passed", "failed") and d.get("commented") != f"{head}:{state}":
        body = (f"p4-phi re-ran the regression test `{proof['cmd']}` on {head}: **{state}**, exit code {d.get('code')}."
                + (f"\n\n```\n{str(d.get('tail') or '')[-1200:]}\n```" if d.get("tail") else ""))
        if comment(slug, n, body):
            d["commented"] = f"{head}:{state}"
            relay._write_json(proof_path(home, s["sessionId"]), d)
    if state == "running":
        return False, ("" if _told(iss, f"running:{head}") else
                       f"phi (p4-phi): the regression test `{proof['cmd']}` outlasted the Stop hook and runs on in "
                       f"the background on {head}. Run it yourself to see its result, then end the turn; p4-phi reads "
                       f"its own run's result at the next Stop."), ""
    if state == "failed":
        tail = relay._short(" ".join(str(d.get("tail") or "").split()[-80:]), 600)
        return False, ("" if _told(iss, f"failed:{head}") else
                       f"phi (p4-phi): the regression test `{proof['cmd']}` failed on {head} with exit code "
                       f"{d.get('code')}, so this session stays open until it passes. Its last "
                       f"lines: {tail}"), ""
    mine = own_commits(s, cwd)
    closing = [(repo, sha, subj) for repo, sha, subj, body in mine if closes(body, slug, n)]
    st = issue_state(slug, n)
    pushed = bool(closing) and all(_pushed(repo, sha) for repo, sha, _ in closing)
    if st == "CLOSED" or (not st and pushed):
        sha, subj = (closing[-1][1], closing[-1][2]) if closing else ("", "")
        iss["closed"] = now()
        note = (f"Issue: {iss['url']}, closed. Closing commit: "
                + (f"{sha} \"{relay._short(subj, 80)}\"" if sha else "none found") + f". Proven by `{proof['cmd']}` "
                f"on {head}: passed.")
        return True, "", note
    if not closing:
        why = (f"phi (p4-phi): the regression test passed on {head}, but no commit of this session says "
               f"`Closes #{n}`. Commit the work with `Closes #{n}` in its message, then push it at once, without "
               f"asking.")
        return False, ("" if _told(iss, f"no-close:{head}") else why), ""
    if not pushed:
        why = (f"phi (p4-phi): the regression test passed on {head}, and green issue work is pushed at once: push "
               f"the `Closes #{n}` commit {closing[-1][1]} now, without asking, and sync each store it touched with "
               f"`p4.py sync --push`; the push closes {ref}. Anything that cannot be undone, such as a force-push, a "
               f"history rewrite or a deletion, still asks.")
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
