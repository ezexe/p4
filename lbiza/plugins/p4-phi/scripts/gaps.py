"""gaps.py: a feedback memory that patches over a plugin's behaviour gets its gap written up as a finding.

A session writes a feedback memory into the store's temportal/memory/ when a plugin did not do what ezexe wanted,
such as "a child never merges" or "a plan is written in the plans folder". Such a memory hides a gap that belongs in the
plugin. No session publishes a new issue on its own, so when a session writes a feedback memory whose rule describes
session or plugin behaviour, p4-phi tells it to write the gap into this turn's report as one `Finding:` line. That
line goes up to the puppeteer that controls its session tree, or to its orchestrator where none does, which
places the session that resolves it, and the session controls.publisher names for that tree publishes the issue on
the plugin's repository: the line names that session by full title. A memory about code
style gets nothing, nor does one that says the plugin already carries its rule, nor a write that only shortens or
removes text.

The plugin's project is read from CLAUDE_PLUGIN_ROOT: the git top level of the marketplace checkout it runs from,
with `origin` as the issue repository, and the folder above it that holds a store, `.claude/p4`, when one does. A
plugin installed from a GitHub marketplace runs from a cache that is no checkout: the repository is read from
known_marketplaces.json, and a clone of it found beside a store this machine knows is its project; with none, no
checkout of it is known here.
"""

import hashlib
import os
import re

import relay

BEHAVIOUR = re.compile(
    r"\b(sessions?|child(?:ren)?|parent|top session|orchestrat\w*|sub-?agents?|worktrees?|branch(?:es)?|relay\w*|"
    r"archiv\w*|push\w*|merg\w*|sync\w*|hooks?|plugins?|p4-\w+|phi|stores?|scratchpad|tmp|plan steps?|task list|"
    r"turns?|SendMessage|start_session|briefs?|reports?|memor(?:y|ies)|temportal|wait\w*|ask\w* first|"
    r"go-?ahead|issues?)\b", re.I)
STYLE = re.compile(r"\b(indent\w*|tabs?|spaces|naming|variable names?|braces?|semicolons?|quotes?|line length|"
                   r"formatt\w*|lint\w*|code style|docstrings?|comments?|camel\w*|snake\w*|imports?|typing|"
                   r"type hints?|prose|parenthetical\w*|markdown|line breaks?)\b", re.I)
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


# a memory that says the plugin carries its rule records a gap as closed, the opposite of a new one, so it gets no
# advice and no start request
CARRIED = re.compile(r"\b(?:p4-[\w-]+|phi|the plugins?)\b[^.\n]{0,80}?\bcarr(?:y|ies|ied)\s+(?:this|it|that|the rule)\b"
                     r"|\bcarr(?:y|ies|ied)\s+(?:this|it|that)\s+(?:now|already)\b"
                     r"|\b(?:is|are)\s+(?:now\s+)?built into\s+(?:p4-[\w-]+|phi|the plugins?)\b", re.I)
WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_'-]{2,}")


NEGATED = re.compile(r"\b(?:not|never|no longer|cannot|yet to|fails? to|should|must|ought to|needs? to|has to|"
                     r"have to|will|would|could|might|may)\b|n['’]t\b", re.I)
NOT_YET = re.compile(r"^\W*(?:yet|either|at all)\b", re.I)


def carried(body):
    """True when a memory's body says the plugin already carries its rule. A negated or wished-for form, such as
    "p4-phi does not carry this yet" or "p4-phi should carry this", says the opposite: a real gap."""
    text = str(body or "")
    for m in CARRIED.finditer(text):
        said = m.group(0)
        before = "" if re.match(r"(?i)p4-|phi\b|the plugin", said) else text[max(0, m.start() - 40):m.start()]
        before = re.split(r"[.!?\n]", before)[-1]
        if NEGATED.search(before + " " + said) or NOT_YET.match(text[m.end():m.end() + 12]):
            continue
        return True
    return False


def body_of(text):
    """A memory file's body, without its front matter."""
    m = FRONT.match(str(text or "").replace("\r\n", "\n"))
    return (m.group(2) if m else str(text or "")).strip()


def only_shortens(before, after):
    """True when a write only shortens or removes text: the body it leaves is no longer than the one before it and
    holds no word that body did not."""
    old, new = body_of(before), body_of(after)
    if not old.strip() or len(new) > len(old):
        return False
    return not ({w.lower() for w in WORD.findall(new)} - {w.lower() for w in WORD.findall(old)})


def before_write(path, tool_input, tool_response):
    """What a memory file held before a Write or an Edit, '' when it cannot be told: the tool's own
    `originalFile` where its result carries one, else an Edit's `new_string` put back to its `old_string`."""
    resp = tool_response if isinstance(tool_response, dict) else {}
    if isinstance(resp.get("originalFile"), str):
        return resp["originalFile"]
    inp = tool_input if isinstance(tool_input, dict) else {}
    old, new = inp.get("old_string"), inp.get("new_string")
    if isinstance(old, str) and isinstance(new, str) and old != new:
        try:
            with open(path, encoding="utf-8") as f:
                now = f.read()
        except (OSError, UnicodeDecodeError):
            return ""
        if new and new in now:
            return now.replace(new, old) if inp.get("replace_all") else now.replace(new, old, 1)
        if not new:
            return now + "\n" + old                # a removal: what was there held at least this more
    return ""


def memory_dir(store):
    import p4conf
    return relay.norm(p4conf.sub(store, "memory")) if store else ""


def memory_of(store, path):
    """The name and rule body of a feedback memory written at `path` in the store's memory folder; None otherwise."""
    p, mem = relay.norm(path), memory_dir(store)
    if not mem or not p.startswith(mem + "/") or not p.endswith(".md") or p.endswith("/memory.md"):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            m = FRONT.match(f.read().replace("\r\n", "\n"))
    except (OSError, UnicodeDecodeError):
        return None
    if not m or not re.search(r"(?m)^\s*type:\s*feedback\b", m.group(1)):
        return None
    name = re.search(r"(?m)^name:\s*(.+)$", m.group(1))
    return (name.group(1).strip() if name else os.path.basename(path)[:-3]), m.group(2).strip()


def rule_text(body):
    """The rule itself: the body before its **Why:** and **How to apply:** lines."""
    head = re.split(r"\n\s*\*\*(?:Why|How to apply)", body, maxsplit=1)[0]
    return " ".join(head.split())


def about_behaviour(body):
    """True when a rule describes how sessions or the plugins behave, not how code is written: two behaviour words
    or more, and more of them than style words."""
    text = rule_text(body)
    beh = {m.lower() for m in BEHAVIOUR.findall(text)}
    sty = {m.lower() for m in STYLE.findall(text)}
    return len(beh) >= 2 and len(beh) > len(sty)


def _git(path, *args):
    r = relay._git(path, *args)
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


def repo_name(url):
    """owner/name of a GitHub remote, '' for another host."""
    key = relay.remote_key(url)
    return key.split("/", 1)[1] if key.startswith("github.com/") and key.count("/") == 2 else ""


def _marketplace_repo(root):
    """owner/name of the GitHub marketplace a cached plugin was installed from, '' when unknown."""
    p = relay.norm(root)
    m = re.search(r"/plugins/cache/([^/]+)/", p + "/")
    if not m:
        return ""
    conf = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    known = relay._read_json(os.path.join(conf, "plugins", "known_marketplaces.json"))
    for name, d in known.items():
        if str(name).lower() != m.group(1):
            continue
        src = (d or {}).get("source") or {}
        if src.get("repo"):
            return str(src["repo"])
        if src.get("url"):
            return repo_name(src["url"])
    return ""


def _known_clone(repo):
    """A checkout of `repo` on this machine: a project of a store this machine knows, or a folder in it."""
    want = "github.com/" + repo.lower()
    for store in set(relay._read_json(relay.stores_map_path()).values()):
        project = os.path.dirname(os.path.dirname(str(store)))
        try:
            subs = [os.path.join(project, n) for n in os.listdir(project)]
        except OSError:
            continue
        for d in [project] + [x for x in subs if os.path.isdir(os.path.join(x, ".git"))]:
            if relay.remote_key(_git(d, "remote", "get-url", "origin")) == want:
                return relay.norm(d)
    return ""


def project_with_store(top):
    """The plugin's project: the checkout's top level, or the nearest folder above it holding a store, `.claude/p4`."""
    d = top
    for _ in range(3):
        if os.path.isdir(os.path.join(d, ".claude", "p4")):
            return relay.norm(d)
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return relay.norm(top)


def plugin_project(root=None):
    """{"cwd", "repo", "store", "cloud"} for the plugin running this hook; {} when its repository is unknown."""
    root = root or os.environ.get("P4_PHI_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    if not root:
        return {}
    top = _git(root, "rev-parse", "--show-toplevel")
    repo = repo_name(_git(top, "remote", "get-url", "origin")) if top else ""
    if top and repo and "/plugins/marketplaces/" not in relay.norm(top) + "/":
        cwd = project_with_store(top)
        return {"cwd": cwd, "repo": repo, "store": os.path.join(cwd, ".claude", "p4") if
                os.path.isdir(os.path.join(cwd, ".claude", "p4")) else "", "cloud": False}
    repo = repo or _marketplace_repo(root)
    if not repo:
        return {}
    clone = _known_clone(repo)
    if clone:
        cwd = project_with_store(clone)
        return {"cwd": cwd, "repo": repo, "store": os.path.join(cwd, ".claude", "p4") if
                os.path.isdir(os.path.join(cwd, ".claude", "p4")) else "", "cloud": False}
    return {"cwd": "", "repo": repo, "store": "", "cloud": True}


ISSUE_URL = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)\b")
CREATES = re.compile(r"\bgh(?:\.exe)?\b[^|;&\n]*?\bissue\s+create\b")
SOURCE = re.compile(r"source:\s*([^;\n\"']+?\.md)\b")
TIE = "issue: {repo}#N"


def tie(store, command, response):
    """The tie of a behaviour memory to the issue filed for it, ezexe/p4#226. When a `gh issue create` whose text
    carries a `Finding:` line naming a feedback memory of the store's memory folder as its `source:` answered with
    the address of the issue it made, that memory's front matter takes the line `issue: owner/name#N`, once: a memory
    that holds an `issue:` line is left as it is. The publisher makes the call, and p4-phi files nothing itself.
    Returns each memory tied, as its path and the issue."""
    command, mem = str(command or ""), memory_dir(store)
    made = ISSUE_URL.search(str(response or ""))
    if not mem or not made or not CREATES.search(command):
        return []
    slug, n = made.group(1), int(made.group(2))
    out = []
    for raw in SOURCE.findall(command):
        path = relay.norm(raw.strip().replace("\\\\", "/"))
        if not path.startswith(mem + "/") or memory_of(store, path) is None:
            continue
        try:
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        eol = "\r\n" if "\r\n" in text else "\n"
        m = re.match(r"\A(---[ \t]*\r?\n)(.*?)(\r?\n---[ \t]*(?:\r?\n|\Z))", text, re.S)
        if not m or re.search(r"(?mi)^issue:\s*\S", m.group(2)):
            continue
        tied = f"{m.group(1)}{m.group(2)}{eol}issue: {slug}#{n}{m.group(3)}{text[m.end():]}"
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(tied)
        except OSError:
            continue
        out.append((path, f"{slug}#{n}"))
    return out


def unlanded(store):
    """Each feedback memory of the store's memory folder that still holds a behaviour rule with no landed feature,
    ezexe/p4#226: one with no `issue:` line, and one whose issue GitHub shows open or cannot show. A fact, a
    preference, a memory whose body says the plugin carries it, and one whose issue landed are left out. Returns
    (name, path, issue, state) for each, the issue '' and the state 'no issue' for one that names none, else the
    state 'open' or 'unknown'."""
    import issues
    mem, out = memory_dir(store), []
    try:
        names = sorted(n for n in os.listdir(mem) if n.endswith(".md") and n != "MEMORY.md")
    except OSError:
        return out
    for n in names:
        path = relay.norm(os.path.join(mem, n))
        got = memory_of(store, path)
        if not got or not about_behaviour(got[1]) or carried(got[1]):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                front = FRONT.match(f.read().replace("\r\n", "\n"))
        except (OSError, UnicodeDecodeError):
            continue
        head = front.group(1) if front else ""
        if issues.LANDED_KEY.search(head):
            continue                               # cut back at its issue's landing
        named = issues.TIED.search(head)
        if not named:
            out.append((got[0], path, "", "no issue"))
            continue
        slug, num = named.group(1), int(named.group(2))
        state = issues.issue_state(slug, num)
        if state != "CLOSED":
            out.append((got[0], path, f"{slug}#{num}", "open" if state == "OPEN" else "unknown"))
    return out


def unlanded_text(store):
    """What `phi.py gaps` prints: a line for each memory `unlanded` finds, or one line saying none is left."""
    rows = unlanded(store)
    if not rows:
        return "no feedback memory holds a behaviour rule with no landed feature"
    return "\n".join(f"{name}: " + ("no issue" if not issue else f"{issue}, {state}") + f", {path}"
                     for name, path, issue, state in rows)


def advice(home, store, s, path, root=None, before=""):
    """The line a session gets after writing a plugin-gap memory into its project's store, once per memory content:
    the gap as one `Finding:` line to write into this turn's report, and the session it goes up to, which publishes
    the issue. '' for any other write, for a memory whose body says the plugin already carries it, and for a write
    that only shortens or removes text, `before` being what the file held. `home` holds the session tree, and `store`
    is the project's store, whose memory folder holds the memory."""
    got = memory_of(store, path)
    if not got or not about_behaviour(got[1]):
        return ""
    name, body = got
    if carried(body):
        return ""
    if before:
        try:
            with open(path, encoding="utf-8") as f:
                if only_shortens(before, f.read()):
                    return ""
        except (OSError, UnicodeDecodeError):
            pass
    rule = rule_text(body)
    sig = hashlib.sha1((name + "\n" + rule).encode("utf-8", "replace")).hexdigest()[:12]
    spath = os.path.join(relay._dir(home, s["sessionId"]), "session.json")
    disk = relay._read_json(spath)
    told = [x for x in disk.get("gapsTold") or [] if isinstance(x, str)]
    if sig in told:
        return ""
    proj = plugin_project(root)
    if not proj:
        return ""
    if disk:
        disk["gapsTold"] = (told + [sig])[-50:]
        relay._write_json(spath, disk)
    import controls                                # the session that publishes the issues of this session tree
    sid = controls.publisher(home, s, store)
    title = controls.full_title(sid)
    repo = proj["repo"]
    says = re.sub(r"(?<!\.)\.$", "", relay._short(rule, 600))      # its last full stop would stand before the `;`
    line = (f"Finding: the plugin in {repo} does not carry the feedback memory \"{name}\", which says: {says}; "
            f"source: {relay.norm(path)}; test: <the test in {repo} that shows the plugin does it>; files: <the paths "
            f"in {repo} a fix changes>")
    if sid == s["sessionId"]:
        up = ("This session is the session nobody started at the top of its tree, so the finding is its own to "
              f"publish and place: it publishes the issue in {repo} and places the session that resolves it.")
    else:
        up = (f"The report carries it up unchanged, and the session nobody started at the top of this session tree, "
              f"\"{title}\" `{sid}`, publishes the issue and places the session that resolves it. This session "
              f"publishes no issue and starts no session for it.")
    where = (f" Its project on this machine is {proj['cwd']}." if proj.get("cwd") else
             " No checkout of it is known on this machine.")
    tied = (f" Once the issue is filed, the memory is tied to it by one line in its front matter, "
            f"`{TIE.format(repo=repo)}`: p4-phi writes that line when the publisher's call that files it carries "
            f"this `Finding:` line with its `source:`, and whoever files it another way writes the line by hand. "
            f"The landing that closes the issue then cuts the memory back to a pointer.")
    import issues
    if not issues.new_on(home):
        up = ("This project files no new GitHub issue, by `phi.new_issues` false in its p4.json: the report carries "
              "the line up unchanged, and the session that plans this tree's work places the session that carries "
              "the rule into the plugin.")
        tied = ""
    return (f"phi (p4-phi): the memory `{name}` you just wrote describes session or plugin behaviour, so it patches "
            f"over a gap in the plugin, whose repository is {repo}.{where} Check whether the plugin does this already; "
            f"if not, write the gap into this turn's report as this one line, with its test and files filled in:\n"
            f"{line}\n{up}{tied}")
