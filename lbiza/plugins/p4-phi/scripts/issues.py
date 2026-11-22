#!/usr/bin/env python3
"""issues.py: the one loop a worker that changes a repository runs.

  issue    at its first hook, a child whose brief or task list names files in a repository with a GitHub `origin`
           takes the open issue its brief names on that repository as its own: the number is kept in session.json as
           `issue`, and a line tells the child. p4-phi files no issue, since no session publishes a new issue on its
           own: a child that takes none is told to write each finding into its report as one `Finding:` line, which
           its parent session passes up unchanged to the puppeteer that controls its session tree, or to its
           orchestrator where none does, and the one session that publishes for that tree, which
           controls.publisher names, publishes what needs an issue. A read-only child, such as a check, an audit,
           a question or a message to pass on, takes no issue and is handed the same line at its first message, for
           the repository its brief names or the one it runs in. A repository with no GitHub remote
           gets neither. A shell call that runs `gh issue create` in any other session than that publisher is
           refused by phi.py's issue guard, which `publishes` reads the call for.
  commits  at each step boundary, a commit made since the issue was taken that closes no issue gets one line.
  proof    before the child counts as finished, its task list names the regression test that proves the issue fixed:
           a backticked command or a test file in a step that speaks of a test, or `phi.py proof "<command>"`. p4-phi
           runs it again at Stop on the final head and comments the result on the issue; a failing test keeps the
           child open.
  push     only the tree's orchestrator lands and pushes: the child commits on its own branch, in its own worktree,
           and is told its proven work waits on that push, while the orchestrator gets relay.push_text with what the
           change still
           owes; the `Closes #N` commit closes the issue once it reaches the default branch. A child's own push asks.
  archive  a finished child, marked `disposable` or archiving itself, is counted as archived only with the issue
           closed and the test passed, its outcome note on the parent carrying the issue link, the commit and the test.
           A child that archives itself before it is finished is counted as archived at once, its open steps named.
  memory   a memory that an `issue: owner/name#N` line in its front matter ties to an issue is cut back at a Stop
           whose turn ran a push, pull, fetch or merge, once that issue's closing commit is on the remote default
           branch: one pointer line names the issue and the code that carries its rule, and its own line in
           MEMORY.md says the same, in the folder Claude Code loads auto memory from and in the store's.

`gh` is P4_PHI_GH when set, and a .py file named there is run with this Python; else `gh` on PATH. P4_PHI_ISSUES
set to 0 or false, read as p4conf reads it, or p4.json's phi.issues false turns the loop off. phi.py calls these from its hooks.
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
TEST_WORD = re.compile(r"\btest|\bsuite|\bpytest\b|\bunittest\b", re.I)
TEST_CMD = re.compile(r"`([^`\n]{3,})`")
TEST_FILE = re.compile(r"((?:[A-Za-z]:)?[\w./\\-]*?\btest_[\w-]+\.py|[\w./\\-]*?[\w-]+_test\.py)\b")
FINDING_FORM = ("Finding: <the claim>; source: <the file and line it was read at>; test: <the deciding test>; files: <the paths a "
                "fix changes>")
FINDING = re.compile(r"(?m)^(?:[ \t>*+-]|\d+[.)])*(Finding:[ \t]*\S[^\n]*)$")
FINDINGS_REST = (
    "A finding on a file another live session holds, or on an issue another live session owns, "
    "goes straight to that session with SendMessage, as this session's address book names it, and nowhere else. "
    "Write each finding no live session covers into this session's report as one line in this form: `"
    + FINDING_FORM + "`. Its parent session passes those lines up unchanged, to the puppeteer that controls "
    "this session tree, or to its orchestrator where none does, which places the session that resolves it, and the "
    "one session that publishes for this tree publishes what needs an issue: `gh issue create` is refused in every "
    "other session.")
FINDINGS_LINE = (
    "phi (p4-phi): this session's brief names no open issue, and p4-phi files none, since no session publishes a new "
    "issue on its own. " + FINDINGS_REST)
FINDINGS_READS = (                                 # a read-only worker, whose brief may name an issue it only reads
    "phi (p4-phi): this session's brief asks for no change, so it takes no issue as its own, and p4-phi files none, "
    "since no session publishes a new issue on its own. " + FINDINGS_REST)


def findings(text):
    """The `Finding:` lines of a report, in order and each once, with their spaces made single."""
    out = []
    for m in FINDING.finditer(str(text or "")):
        line = " ".join(m.group(1).split())
        if line not in out:
            out.append(line)
    return out


def on(home=""):
    """False when the issue loop is off: P4_PHI_ISSUES and p4.json's phi.issues read by p4conf, the variable ahead
    of p4.json when a person set it, 1, 0, true and false alike."""
    try:
        import p4conf
        if not home:
            return p4conf.env_value("phi.issues", os.environ.get("P4_PHI_ISSUES"), True) is not False
        return p4conf.section(home, "phi", write=False).get("issues", True) is not False
    except Exception:  # noqa: BLE001
        return True


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def gh(args, cwd=None, timeout=GH_S):
    """gh's CompletedProcess, None when there is no gh or it failed to start: relay.gh, the one way p4-phi runs gh,
    with a hook's time for one gh call."""
    return relay.gh(args, cwd=cwd, timeout=timeout)


def git(repo, *args):
    r = relay._git(repo, *args)
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


def github_of(repo):
    """'owner/name' of a repository's `origin` on GitHub, '' for none."""
    m = GITHUB.search(git(repo, "remote", "get-url", "origin")) if repo else None
    return f"{m.group(1)}/{m.group(2)}" if m else ""


# a link, a backticked span, a path or a file name: a path has a root or a drive, two separators, or one separator
# and a file's extension, so a slash-joined pair of words such as add/remove is no path and its work word is still
# read; a pair of backticks is taken as one span of code, so the words between two spans stay
PATH_WORDS = re.compile(r"[A-Za-z][\w+.-]*://\S+|`[^`\n]*`|(?:(?:[A-Za-z]:|\.{1,2}|~)|(?<![\w.~-]))"
                        r"[\\/][\w.\\/*~:-]+|"
                        r"[\w.~-]+(?:[\\/][\w.~*-]+){2,}[\\/]?|[\w.~-]+[\\/][\w~*-]*\.\w[\w.*~-]*|"
                        + FILE_RE.pattern)


def writing(text):
    """True when a brief or task list asks for changes, not a check, an audit, a question or a message to pass on.
    The paths, links and file names it names are taken out first, so a folder named `land` or `build` is no work
    word: only the message's own words decide."""
    text = PATH_WORDS.sub(" ", str(text or ""))
    if READ_ONLY.search(text):
        return False
    lead = re.sub(r"^[\s#*>`-]+", "", text)
    if READS.match(lead) and not WRITES.search(lead.split("\n", 1)[0]):
        return False
    return bool(WRITES.search(text))


# --- a shell command that lands work -----------------------------------------------------------------------------------

LANDS = ("push", "merge", "rebase", "pull")
MOVES = LANDS + ("fetch",)                         # what may bring a closing commit onto the default branch here
GIT_VALUED = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
SEPS = {";", "&", "&&", "|", "||", "(", ")", ";;", "|&", "{", "}", "\n"}
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][\w.-]*)\1([^\n]*)\n.*?\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
SH_LIKE = {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell"}
EVALS = {"iex", "invoke-expression"}


def _tokens(cmd):
    """A shell line's tokens with each quoted string kept whole and its quotes taken off, as shlex reads it in posix
    mode, with no escape character, so a Windows path keeps its backslashes, and no comment character. Operators
    stand as tokens of their own. A heredoc's body is data and is left out. Unbalanced quotes fall back to the line
    split at whitespace."""
    import shlex
    text = HEREDOC.sub(lambda m: " " + m.group(3), str(cmd or "")).replace("`", " ; ")
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
        lex.whitespace_split, lex.escape, lex.commenters = True, "", ""
        return list(lex)
    except ValueError:
        return text.split()


def _exe(tok):
    """A program's own name, the last part of its path, lowercased, without `.exe`."""
    base = re.split(r"[\\/]", str(tok).strip())[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _gh_api(args):
    """'gh api' when a `gh api` call's arguments, up to the end of its command, land work, else ''."""
    if args[:1] and args[0].lower() == "graphql":
        if any(re.search(r"\bmutation\b", a, re.I) and re.search(r"merge|ref", a, re.I) for a in args[1:]):
            return "gh api graphql"
        return ""
    method, fields = "", False
    for k, a in enumerate(args):
        m = re.match(r"^(?:-X|--method=?)(\w*)$", a)
        if m:
            method = (m.group(1) or (args[k + 1] if k + 1 < len(args) else "")).upper()
        elif re.match(r"^(?:-[fF]|--field|--raw-field|--input)(?:=|$)", a):
            fields = True
    return "gh api" if (method or ("POST" if fields else "GET")) != "GET" else ""


def _scan(cmd, hit, depth=0):
    """The first answer `hit` gives for a word of a shell line as a program's name with the words after it, '' for
    none. The line's tokens are read with each quoted string whole, so a quoted argument such as a commit message, a
    grep pattern or a path with spaces is data. A quoted string is read again as a command only where it is the
    script of bash, sh, zsh, pwsh or powershell after -c, -lc or -Command, of cmd after /c or /k, or of iex or
    Invoke-Expression."""
    toks = _tokens(cmd)
    for i, w in enumerate(toks):
        exe, nxt = _exe(w), toks[i + 1:]
        got = ""
        if depth < 3 and exe in SH_LIKE:
            for k, a in enumerate(nxt[:4]):
                if re.fullmatch(r"-[a-z]*c|-command|-c(?:ommand)?", a, re.I) and k + 1 < len(nxt):
                    got = got or _scan(nxt[k + 1], hit, depth + 1)
        elif depth < 3 and exe == "cmd":
            for k, a in enumerate(nxt[:4]):
                if a.lower() in ("/c", "/k"):
                    got = got or _scan(" ".join(nxt[k + 1:]), hit, depth + 1)
        elif depth < 3 and exe in EVALS and nxt:
            got = _scan(nxt[0], hit, depth + 1)
        else:
            got = hit(exe, nxt)
        if got:
            return got
    return ""


def _args(nxt):
    """The words after a program's name up to the end of its command."""
    args = []
    for a in nxt:
        if a in SEPS:
            break
        args.append(a)
    return args


def _lands(exe, nxt, verbs):
    """What one program's name and the words after it run that lands work, '' for none."""
    if exe == "git":
        k = 0
        while k < len(nxt) and nxt[k].startswith("-") and nxt[k] not in SEPS:
            k += 2 if nxt[k] in GIT_VALUED else 1
        if k < len(nxt) and nxt[k].lower() in verbs:
            return f"git {nxt[k].lower()}"
    elif exe == "gh" and "merge" in verbs:
        args = _args(nxt)
        low = [a.lower() for a in args]
        if low[:2] == ["pr", "merge"]:
            return "gh pr merge"
        if low[:1] == ["api"]:
            return _gh_api(args[1:])
    return ""


def landing(cmd, verbs=LANDS):
    """What a shell line runs that lands work, '' for none, read as `_scan` reads a line: git or git.exe, by the
    last part of its path, followed past its own options by one of `verbs`; `gh pr merge`; a `gh api` call with a
    method other than GET; or a graphql mutation that names a merge or a ref."""
    return _scan(cmd, lambda exe, nxt: _lands(exe, nxt, verbs))


def landings(cmd, verbs=LANDS):
    """Every command of a shell line that lands work, in the line's order and each once, as `landing` names it. A
    line that rebases and then pushes holds both, where `landing` names the first alone."""
    found = []

    def hit(exe, nxt):
        got = _lands(exe, nxt, verbs)
        if got and got not in found:
            found.append(got)
        return ""                                  # never the scan's answer, so it reads on to the line's end
    _scan(cmd, hit)
    return found


GH_VALUED = {"-R", "--repo"}                       # gh's options that take the next word as their value


def publishes(cmd):
    """'gh issue create' when a shell line runs it, or its alias `gh issue new`, '' for none, read as `_scan` reads
    a line: gh or gh.exe, by the last part of its path, followed past its options by those two words. The words in
    a quoted argument, such as a commit message that names the command, are data."""
    if "issue" not in str(cmd or ""):
        return ""

    def hit(exe, nxt):
        if exe != "gh":
            return ""
        said, args, k = [], _args(nxt), 0
        while k < len(args) and len(said) < 2:
            if args[k].startswith("-"):
                k += 2 if args[k] in GH_VALUED else 1
                continue
            said.append(args[k].lower())
            k += 1
        return "gh issue create" if said in (["issue", "create"], ["issue", "new"]) else ""
    return _scan(cmd, hit)


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


def repos_at(base):
    """The GitHub repositories at a folder, one at a time, each as its path and its `owner/name`: the folder's own,
    then those nested one or two folders under it. A caller that only needs to know there is one takes the first,
    which costs one git call where the folder's own repository is on GitHub."""
    own = relay.repo_of(base) if base else ""
    slug = github_of(own)
    if slug:
        yield own, slug
    for repo in nested_repos(base):
        slug = github_of(repo) if repo != own else ""
        if slug:
            yield repo, slug


def ensure(home, s, text, base, where):
    """At a child's first message, `where` "brief", or its first task list, `where` "plan": the open issue its brief
    names, taken as its own and kept in s["issue"], or else FINDINGS_LINE, which sends its findings up in its report.
    A child whose brief asks for no change takes no issue and is handed FINDINGS_READS, for the repository its brief
    names or else the one it runs in. p4-phi files no issue. s is changed and the caller saves it. Returns the line
    for the child, '' for none."""
    parent = relay._parent(s)
    if not parent or not on(home):
        return ""
    if s.get("issue") or s.get("findingsTold"):
        return ""
    looked = list(s.get("issueLooked") or [])
    if where in looked:
        return ""
    s["issueLooked"] = looked + [where]
    task, text = str(s.get("task") or ""), str(text or "")
    whole = text if task[:200] in text else "\n".join(p for p in (task, text) if p)
    if not writing(whole):                         # a check, an audit, a question: its findings go up all the same
        if not (repos_named(whole, base) or next(repos_at(base), None)):
            return ""
        s["findingsTold"] = now()
        return FINDINGS_READS
    repos = repos_named(whole, base)
    if not repos:
        return ""
    repo, slug = repos[0]
    n = next((k for k in named_issues(whole, slug) if issue_state(slug, k) == "OPEN"), 0)
    if not n:                                      # it names none, or each one it names is closed: findings go up
        s["findingsTold"] = now()
        return FINDINGS_LINE
    url = f"https://github.com/{slug}/issues/{n}"
    s["issue"] = {"repo": slug, "path": repo, "number": n, "url": url, "time": now(),
                  "base": git(repo, "rev-parse", "HEAD")}
    return (f"phi (p4-phi): this session's purpose is {slug}#{n}, {url}, named in its brief. Its loop: each commit "
            f"says `Closes #{n}`; a step of its task list names the regression test that proves it fixed, as a "
            f"backticked command or a test file, or `phi.py proof \"<command>\"` names it; p4-phi re-runs that test "
            f"at Stop on the final head, comments the result on the issue and says what is still owed; the tree's "
            f"orchestrator, the one session that lands and pushes, pushes the `Closes` commit, and it closes the "
            f"issue once it reaches the default branch. This session never pushes it.")


def done_text(home, s, cwd=""):
    """What `phi.py done` says about the issue this session closes, so a child that reports done learns which issue
    it closes, what it still owes, the commit and the regression test, and that its orchestrator pushes. Nothing is
    read from GitHub."""
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
    unpushed = bool(closing) and not all(_pushed(repo, sha) for repo, sha in closing)
    have = []
    if closing:
        have.append(f"commit {closing[-1][1]} says `Closes #{n}`")
    if proof:
        have.append(f"its regression test is `{proof['cmd']}`")
    top_id, top_title = lander(home, s)
    return (f"this session closes {slug}#{n}, {iss.get('url')}"
            + (": " + "; ".join(have) if have else "") + ". "
            + ("Still owed before it closes: " + "; ".join(owed) + "." if owed else
               "Nothing is owed but the Stop check: p4-phi re-runs the test on the final head, and the commit closes "
               "the issue once it reaches the default branch.")
            + (f" The push of {closing[-1][1]} is its orchestrator's, \"{top_title}\" `{top_id}`, the one session "
               f"that lands and pushes; this session does not push it." if unpushed else ""))


def _commits(repo, rng, limit=40):
    out = git(repo, "log", f"-{limit}", "--reverse", "--format=%h%x1f%s%x1f%B%x1e", *([rng] if rng else []))
    rows = []
    for rec in out.split("\x1e"):
        parts = rec.strip().split("\x1f")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


# GitHub's closing keywords, each a whole word at a line's start or after whitespace, so "prefix #7" and "disclose #7"
# close nothing; a negation before it on its line, as in "does not close #7", closes nothing either
KEYWORD = re.compile(r"(?im)(?:^|(?<=\s))(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?[ \t]+"
                     r"((?:[\w.-]+/[\w.-]+)?#\d+)(?!\d)")
NEGATION = re.compile(r"(?i)(?:\b(?:not|never|no longer|cannot)|n['’]t)\s+(?:\w+\s+){0,2}$")
KEYWORD_GREP = "(^|[[:space:]])(close[sd]?|fix(e[sd])?|resolve[sd]?):?[[:space:]]+"


def closing_refs(body):
    """The issues a commit message closes, each as `#N` or `owner/name#N`, in order and each once."""
    text, out = str(body or ""), []
    for m in KEYWORD.finditer(text):
        if NEGATION.search(text[text.rfind("\n", 0, m.start()) + 1:m.start()]):
            continue
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def closing_on(repo, revs, n, limit=50):
    """The short sha and subject of the newest commit in `revs` whose message closes issue `n` of this repository,
    as a bare `#N` or as its own `owner/name#N`; None for none. git's --grep finds the candidates and closing_refs
    decides."""
    here = github_of(repo)
    whose = f"({here.replace('.', '[.]')})?" if here else ""
    out = git(repo, "log", *revs, "-E", "-i", f"-n{limit}", "--format=%h%x1f%s%x1f%B%x1e",
              f"--grep={KEYWORD_GREP}{whose}#{n}([^0-9]|$)")
    for rec in out.split("\x1e"):
        parts = rec.strip().split("\x1f")
        if len(parts) >= 3 and closes(parts[2], here, n):
            return parts[0], parts[1]
    return None


def closes(body, slug, n):
    for ref in closing_refs(body):
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


def closing_commits(home, s, cwd=""):
    """The commits the push line its orchestrator gets names: only a session with an issue of its own has any, and
    only its commits in that issue's own repository whose own message closes that issue, as closes() reads it. A
    session with no issue record gets none: it reports its `Closes #N` commit and its orchestrator decides. No
    record says which session made a commit in a checkout siblings share, and each commits as the same git author,
    so a sibling's commit there is told apart only by the issue it closes."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or not on(home):
        return []
    slug, n = iss["repo"], iss["number"]
    mine, seen = [], set()
    for repo, sha, subj, body in own_commits(s, cwd):
        if closes(body, slug, n) and sha not in seen:
            seen.add(sha)
            mine.append((repo, sha, subj, [f"#{n}"]))
    return mine


def unclosed_text(home, s, cwd=""):
    """At a step boundary: this child's commits that do not say `Closes #N`, each named once; s is changed."""
    iss = s.get("issue") if isinstance(s.get("issue"), dict) else None
    if not iss or not on(home):
        return ""
    told = list(iss.get("flagged") or [])
    # a commit that closes another issue is that issue's work, done on purpose: only one closing none is named
    new = [(sha, subj) for _, sha, subj, body in own_commits(s, cwd)
           if not closing_refs(body) and sha not in told]
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


def git_bash_sh():
    """On Windows, Git Bash's sh.exe where PATH holds no `sh`, or None. A `bash` that PATH finds there can be the
    bash.exe in System32, the launcher of WSL, which would run a proof's command in a Linux guest and not in the
    Git Bash that Claude Code runs a command hook with. Git's own folder is one to three above the `git` PATH
    finds, for cmd, usr/bin or mingw64/libexec/git-core."""
    if os.name != "nt":
        return None
    starts = []
    git = shutil.which("git")
    if git:
        starts.append(os.path.dirname(git))
    for var, under in (("ProgramFiles", ()), ("ProgramW6432", ()), ("ProgramFiles(x86)", ()),
                       ("LOCALAPPDATA", ("Programs",))):
        if os.environ.get(var):
            starts.append(os.path.join(os.environ[var], *under, "Git", "cmd"))
    for folder in starts:
        for _ in range(3):
            folder = os.path.dirname(folder)
            sh = os.path.join(folder, "usr", "bin", "sh.exe")
            if os.path.isfile(sh):
                return sh
    return None


def _argv(cmd):
    sh = shutil.which("sh") or (git_bash_sh() if os.name == "nt" else shutil.which("bash"))
    return ([sh, "-c", cmd], False) if sh else (cmd, True)


def run_now(cmd, cwd, timeout):
    """The exit code and the output's tail, or None and '' when it outlasted `timeout`. Past the limit the test and
    every process it started are stopped: on Windows stopping `sh` alone leaves the test holding the pipes, and
    reading them would wait for its whole length."""
    argv, shell = _argv(cmd)
    try:
        p = subprocess.Popen(argv, shell=shell, cwd=cwd or None, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                             start_new_session=os.name != "nt",
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0)
    except OSError as e:
        return 127, str(e)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_tree(p)
        return None, ""
    return p.returncode, ((out or "") + (err or ""))[-TAIL_CHARS:]


def stop_tree(p):
    """Stops a process and every process it started, then reaps it without reading its pipes: on Windows a pipe a
    stopped test's helper still holds would keep a read waiting, and communicate's reader threads end on their own."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=10)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        p.kill()
    except OSError:
        pass
    try:
        p.wait(timeout=2)
    except subprocess.SubprocessError:
        pass


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
    except OSError:                                # proof.json names no process, so the next Stop runs the test again
        pass


def proof_run(path):
    """The `proof-run` entry: runs the test proof.json names and writes its result there; while the test runs,
    proof.json names this process as `pid`."""
    d = dict(relay._read_json(path), pid=os.getpid())
    relay._write_json(path, d)
    code, tail = run_now(d.get("cmd") or "", d.get("cwd") or "", 3600)
    d.update(state="passed" if code == 0 else "failed", code=code, tail=tail, time=now())
    relay._write_json(path, d)


def _alive(pid):
    """True while the process `pid` runs."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes
    k = ctypes.WinDLL("kernel32")
    k.OpenProcess.restype = ctypes.c_void_p
    h = k.OpenProcess(0x00100000, False, pid)                       # SYNCHRONIZE
    if not h:
        return False
    try:
        return k.WaitForSingleObject(ctypes.c_void_p(h), 0) == 0x102    # WAIT_TIMEOUT: it has not ended
    finally:
        k.CloseHandle(ctypes.c_void_p(h))


def proven(home, s, proof):
    """proof.json for the test on the current head: run now when it has no result for that head and no live process
    runs it, in the background when it outlasts PROOF_S."""
    cwd = proof.get("cwd") or (s.get("issue") or {}).get("path") or ""
    head = git(cwd, "rev-parse", "--short", "HEAD") if cwd else ""
    path = proof_path(home, s["sessionId"])
    d = relay._read_json(path)
    if d.get("cmd") == proof["cmd"] and d.get("head") == head and (
            d.get("state") in ("passed", "failed") or d.get("state") == "running" and _alive(d.get("pid"))):
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


def lander(home, s):
    """The sessionId and title of the top session of a child's tree, the one session that lands and pushes."""
    seen, cur = [], relay._parent(s)
    while cur and cur not in seen and len(seen) < 32:
        seen.append(cur)
        cur = relay._parent(relay._session(home, cur))
    top = seen[-1] if seen else ""
    return top, relay._title(relay._session(home, top)) if top else ""


def proven_now(s):
    """True when a session's work may be pushed: it has no issue, or the last gate saw its regression test pass."""
    iss = s.get("issue") if isinstance(s, dict) else None
    return not isinstance(iss, dict) or bool(iss.get("passed"))


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
    iss.pop("passed", None)                        # set again below only when the test passed on this head
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
    iss["passed"] = head
    mine = own_commits(s, cwd)
    closing = [(repo, sha, subj) for repo, sha, subj, body in mine if closes(body, slug, n)]
    st = issue_state(slug, n)
    pushed = bool(closing) and all(_pushed(repo, sha) for repo, sha, _ in closing)
    if st == "CLOSED":
        sha, subj = (closing[-1][1], closing[-1][2]) if closing else ("", "")
        iss["closed"] = now()
        note = (f"Issue: {iss['url']}, closed. Closing commit: "
                + (f"{sha} \"{relay._short(subj, 80)}\"" if sha else "none found") + f". Proven by `{proof['cmd']}` "
                f"on {head}: passed.")
        return True, "", note
    top_id, top_title = lander(home, s)
    top = f"\"{top_title}\" `{top_id}`" if top_id else "the top session of this tree"
    if not closing:
        why = (f"phi (p4-phi): the regression test passed on {head}, but no commit of this session says "
               f"`Closes #{n}`. Commit the work on this session's own branch, in its own worktree, with `Closes #{n}` "
               f"in its message and report; "
               f"this session does not push it, since only the tree's orchestrator, {top}, lands and pushes.")
        return False, ("" if _told(iss, f"no-close:{head}") else why), ""
    if not pushed:
        why = (f"phi (p4-phi): the regression test passed on {head}, so this work is proven. Its orchestrator, {top}, "
               f"the one session of this tree that lands and pushes, pushes the `Closes #{n}` commit "
               f"{closing[-1][1]} with what the change still owes, and that push closes {ref}; this session does "
               f"not push it. It is counted as archived once that commit is on the default branch and {ref} is "
               f"closed.")
        return False, ("" if _told(iss, f"lander:{head}") else why), ""
    why = (f"phi (p4-phi): the `Closes #{n}` commit {closing[-1][1]} is pushed, but "
           + (f"{ref} is still open" if st else f"gh could not say whether {ref} is closed")
           + f": GitHub closes it when that commit reaches the default branch, where its orchestrator, {top}, "
             f"lands it.")
    return False, ("" if _told(iss, f"{st.lower() or 'unknown'}:{head}") else why), ""


def _pushed(repo, sha):
    """True when a commit is on a remote branch."""
    out = git(repo, "branch", "-r", "--contains", sha)
    return bool(out.strip())


# --- a behaviour memory tied to its issue, cut back to a pointer once that issue lands ---------------------------------

FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
TIED = re.compile(r"(?mi)^issue:\s*(?:https?://github\.com/)?([\w.-]+/[\w.-]+?)(?:#|/issues/)(\d+)\s*$")
LANDED_KEY = re.compile(r"(?mi)^landed:")
INDEX = "MEMORY.md"
SEEN_FILE = "memory-landed.json"                   # in the store's phi folder: each repository's default head checked


def memory_dirs(home):
    """The memory folders a cut-back edits: the one Claude Code loads auto memory from, by `autoMemoryDirectory`
    in the managed, local, project and user settings in that order of precedence, or its own folder for the project
    where none sets it; then the store's temportal/memory, which p4 keeps beside it."""
    out = []
    try:
        import p4conf
        project = p4conf.session_project(home) if home else None
        if project:
            local = p4conf.settings_file(project)
            files = next((v for k, v in p4conf.MANAGED.items() if sys.platform.startswith(k)), [])
            files = list(files) + [local, os.path.join(project, ".claude", "settings.json"),
                                   os.path.join(p4conf._config_dir(), "settings.json")]
            loaded = ""
            for f in files:
                v = p4conf._get(p4conf.read_json(f) or {}, "autoMemoryDirectory")
                if isinstance(v, str) and v.strip():
                    loaded = os.path.expanduser(v.strip())
                    break
            out.append(loaded or p4conf.default_memory(project))
        if home:
            out.append(p4conf.sub(home, "memory"))
    except Exception:  # noqa: BLE001
        pass
    seen, dirs = set(), []
    for d in out:
        k = relay.norm(d)
        if d and k not in seen:
            seen.add(k)
            dirs.append(d)
    return dirs


def tied_memories(home):
    """Each memory in the memory folders that an `issue: owner/name#N` line in its front matter ties to an issue and
    that is not cut back yet, as its path, front matter, `owner/name` and number. Nothing runs git."""
    out = []
    for d in memory_dirs(home):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for f in names:
            if not f.endswith(".md") or f.lower() == INDEX.lower():
                continue
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    m = FRONT.match(fh.read().replace("\r\n", "\n"))
            except (OSError, UnicodeDecodeError):
                continue
            t = TIED.search(m.group(1)) if m else None
            if t and not LANDED_KEY.search(m.group(1)):
                out.append((os.path.join(d, f), m.group(1), t.group(1), int(t.group(2))))
    return out


def default_ref(repo):
    """The remote default branch as fetched, such as origin/main, '' for none."""
    ref = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref
    return next((r for r in ("origin/main", "origin/master") if git(repo, "rev-parse", "--verify", "-q", r)), "")


def closed_on_default(repo, n):
    """The short sha and subject of the commit on the remote default branch whose message closes issue `n` of this
    repository; None when none is there."""
    ref = default_ref(repo)
    return closing_on(repo, [ref], n) if ref else None


def pointer(slug, n, sha, subj, files):
    """The one line a memory is cut back to: the issue, and the commit and files that carry its rule."""
    shown = ", ".join(f"`{f}`" for f in files[:4]) + (f" and {len(files) - 4} more" if len(files) > 4 else "")
    return (f"Pointer: the plugin carries this rule since {slug}#{n} landed in commit {sha} \"{relay._short(subj, 80)}\""
            + (f", in {shown}" if shown else "") + "; the rule lives there, not in this memory.")


def cut_back(home, cwd="", commands=()):
    """At a Stop whose turn ran a command that can bring a closing commit onto the default branch, a push, pull,
    fetch, merge or rebase, `gh pr merge` or a `gh api` merge: each memory tied to an issue whose closing commit is
    now on the remote default branch of a checkout at hand, the cwd's repository or one nested under it, is cut back
    to its pointer. The body becomes one line naming the issue and the code that carries the rule, the front
    matter's description says the same and gains a `landed:` line, and the memory's own line in MEMORY.md, the one
    whose first link is the memory, is rewritten to match. A repository whose default head is the one the last check
    saw is not searched again. Returns the paths cut back."""
    if not on(home) or not any(landing(c, MOVES) for c in commands or () if c):
        return []
    tied = tied_memories(home)
    if not tied:
        return []
    try:
        import p4conf
        seen_path = p4conf.sub(home, "phi", SEEN_FILE)
    except Exception:  # noqa: BLE001
        seen_path = ""
    seen = relay._read_json(seen_path) if seen_path else {}
    repos, heads = {}, {}
    for repo in [relay.repo_of(cwd) if cwd else ""] + nested_repos(cwd):
        slug = github_of(repo).lower() if repo else ""
        if slug and slug not in repos:
            ref = default_ref(repo)
            head = git(repo, "rev-parse", ref) if ref else ""
            if head and seen.get(relay.norm(repo)) != head:
                repos[slug], heads[relay.norm(repo)] = repo, head
    out = []
    for path, front, slug, n in tied:
        repo = repos.get(slug.lower())
        hit = closed_on_default(repo, n) if repo else None
        if not hit:
            continue
        sha, subj = hit
        files = [f for f in git(repo, "show", "--name-only", "--format=", sha).splitlines() if f.strip()]
        line = pointer(slug, n, sha, subj, files)
        short = f"carried by the plugin since {slug}#{n} landed in {sha}"
        head = re.sub(r"(?mi)^description:.*$", lambda _: f"description: {short}", front)
        if not re.search(r"(?mi)^description:", head):
            head += f"\ndescription: {short}"
        _write(path, f"---\n{head}\nlanded: {sha}\n---\n\n{line}\n")
        _reindex(os.path.dirname(path), os.path.basename(path), short)
        out.append(path)
    if heads and seen_path:
        relay._write_json(seen_path, dict(seen, **heads))
    return out


def _write(path, text):
    """A memory file written by the kit's one writer: Claude Code and other sessions' hooks read these files, and
    the temp is this writer's own, where two writers of one file shared `<path>.tmp`."""
    import p4conf
    p4conf.write_whole(path, text)


def _reindex(folder, name, short):
    """The memory's own line in MEMORY.md, the one whose first link is the memory, its link kept and the rest made
    `short`. A line that links the memory only after another link is another memory's, and is left as it is; with no
    MEMORY.md, or no line of its own there, nothing is written."""
    p = os.path.join(folder, INDEX)
    try:
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return
    end = "\r\n" if "\r\n" in text else "\n"            # its line endings are kept as found
    lines = text.replace("\r\n", "\n").split("\n")
    link =re.compile(r"^([^\[]*\[[^\]]*\]\(" + re.escape(name) + r"\))")
    changed = False
    for i, ln in enumerate(lines):
        m = link.match(ln)
        if m and ln != f"{m.group(1)} — {short}":
            lines[i] = f"{m.group(1)} — {short}"
            changed = True
    if changed:
        _write(p, end.join(lines))


def landed(repo, sha, closes):
    """True when a commit that closes the issues `closes` names, each as `#N` or `owner/name#N`, has landed: it is on
    a remote branch, a commit on a remote branch closes the same issue of this repository, as a bare `#N` or as its
    own `owner/name#N`, or a patch-equivalent commit is on one, as `git cherry` finds a commit an orchestrator
    landed by cherry-pick or rebase under a new hash."""
    if _pushed(repo, sha):
        return True
    here = github_of(repo)
    for c in closes:
        slug, _, n = str(c).rpartition("#")
        if not n.isdigit() or slug and slug.lower() != here.lower():
            continue                               # another repository's issue: no commit here closes it
        if closing_on(repo, ["--remotes"], n):    # a bare #N, or this repository's own owner/name#N
            return True
    for branch in git(repo, "branch", "-r", "--format=%(refname:short)").split():
        if "->" in branch or branch.endswith("/HEAD"):
            continue
        if any(x.startswith("-") for x in git(repo, "cherry", branch, sha, sha + "~1").splitlines()):
            return True
    return False


if __name__ == "__main__":
    if sys.argv[1:2] == ["proof-run"] and len(sys.argv) > 2:
        proof_run(sys.argv[2])
