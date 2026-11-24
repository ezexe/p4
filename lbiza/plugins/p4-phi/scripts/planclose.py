#!/usr/bin/env python3
"""planclose.py: the one way a plan closes into `plan-planner/complete/`, past the gate of its Evidence and audit.

A plan is shaped by p4-temportal's skill plan-planner: each section that changes files names them on a `Files:`
line and, once landed, holds its `Evidence:`. The session that holds the plan then writes its audit under a heading
`## Audit`:

    Audited: <date>: <base>..<head>, code-review and p4-phi:check
    - Finding: <text>: fixed, <sha>
    - Finding: <text>: answered, <reason>
    - Finding: <text>: open
    - Finding: none

check() is what stops the close, close() writes the STATUS line on line 2 and moves the plan into `complete/` under
its title's name, numbered where that name is taken, as plan-planner's `Moving a plan` says, and stamps it in
`complete/.closed.jsonl`, and guard() is the deny reason for every other way into `complete/`. A text guard cannot
follow every spelling a shell builds, so the stamp is the gate's own record: stamped() tells a plan the gate closed,
and p4-temportal's sweep moves one with no stamp back out.
"""

import datetime
import fnmatch
import hashlib
import json
import os
import posixpath
import re
import subprocess

COMPLETE = "complete"
SHELVES = ("complete", "todo", "unplanned")     # plan-planner's places of a sorted plan, beside the plans folder
TITLE_CHARS = 60                                # plan-planner, `Moving a plan`: the slug is cut within 60 characters
FENCE = re.compile(r"(?ms)^(`{3,}|~{3,}).*?^\1[ \t]*$")
TITLE = re.compile(r"(?m)^# +(.+?)\s*$")
HEAD = re.compile(r"(?m)^## +(.+?)\s*$")
AUDIT = "Audit"                                 # the record's heading is exactly this, so `## Audit notes` is none
AUDITED = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?audited(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$")
RANGE = re.compile(r"([^\s:,`]+?)\.\.([^\s,`]+)")
# a bullet of Markdown: `-`, `*`, `+`, or a number with `.` or `)`
MARK = r"(?:[-*+]|\d+[.)])"
# `- Finding: <text>`, `- Finding 2: <text>`, `- Finding #2: <text>`, `1. Finding: <text>` and `+ Finding: <text>`
FINDING = re.compile(r"(?i)^[ \t]*" + MARK + r"[ \t]+(?:\*\*)?finding(?:[ \t]*#?[ \t]*\d+)?(?:\*\*)?[ \t]*:[ \t]*"
                     r"(?:\*\*)?[ \t]*(.+?)[ \t]*$")
BULLET = re.compile(r"(?m)^[ \t]*" + MARK + r"[ \t]+.*$")
BULLET_MARK = re.compile(r"^[ \t]*" + MARK + r"[ \t]+")
NAMES_FINDING = re.compile(r"(?i)\bfinding")
# the outcome is the last `: fixed|answered|open` of the line, so a finding's text may hold one of those words
OUTCOME = re.compile(r"(?is)^(?P<text>.+):[ \t]*(?P<how>fixed|answered|open)\b[ \t]*,?[ \t]*(?P<rest>.*)$")
NONE = re.compile(r"(?i)^\W*none\W*$")
# a commit an Evidence line names: 7 to 40 lower hex digits with a digit among them, so a word such as `defaced`
# is none, and no part of a version, a path or an issue number such as `ezexe/p4#256`
SHA = re.compile(r"(?<![\w./#:-])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![\w/-]|\.\w)")
STATUS = re.compile(r"^STATUS:")
CLOSED = ".closed.jsonl"            # complete/'s record of the plans close() closed, one JSON row each
BEFORE_GATE = "before the gate"     # the audit of a stamp grandfather() writes

EDITS = ("Write", "Edit", "NotebookEdit")
SHELLS = ("Bash", "PowerShell", "mcp__terminal__run_in_terminal")
# a run of a shell line, once normalised, that may be one path segment: what sits between separators, spaces,
# quotes, brackets and the marks of a chain, a redirection or an option's value
RUN = re.compile(r"[^\s/'\"`(),;|&<>=:]+")
QUOTES = ("'", '"')
PLANS_FOLDER = "plan-planner"
UNDER_COMPLETE = re.compile(r"(?i)(?:^|/)plan-planner/complete(?:/|$)")
# what keeps a shell line from being one command alone: a chain (`;`, `|`, `&`, a newline, a backtick or a `$(`),
# a redirection (`>` or `<`) or a `#` comment, once a `&` that opens the line, PowerShell's call operator, is out
NOT_ONE = re.compile(r"[;|&\n\r`<>#]|\$\(")
NOT_READ_ONLY = re.compile(r"[;|&\n\r`<>]|\$\(")
CALL = re.compile(r"^&\s*")
TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|[^\s\"']+")
# the interpreter of a close line, by its basename: python, python3, python.exe or py, and python3.exe or py.exe
PYTHON = re.compile(r"(?i)^(?:python3?|py)(?:\.exe)?$")
FLAGS = ("-I", "-3", "-u", "-B", "-E", "-s", "-S")    # the interpreter's flags a close line may hold, one to a word
TAKES_VALUE = ("-X",)                                 # and `-X <opt>`, whose value is the next word
PHI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phi.py")    # the one phi.py a close line runs
READ_ONLY = ("ls", "dir", "cat", "type", "get-childitem", "get-content", "grep", "rg")
GIT_READ_ONLY = ("status", "log", "diff", "show")
WRITES_ANYWAY = re.compile(r"(?i)^--(?:output|pre)\b")      # `git diff --output=<file>`, `rg --pre <command>`


class Refused(Exception):
    """close() refused: `reasons` is check()'s list of what stops the close."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def _git(checkout, *args):
    try:
        ran = subprocess.run(["git", "-C", checkout, *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return ran


def commit_of(checkout, ref):
    """The full sha `ref` names in `checkout`, or '' where it names no commit there or opens with `-`, which git
    would read as an option."""
    if not ref or str(ref).startswith("-"):
        return ""
    ran = _git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return ran.stdout.strip() if ran is not None and ran.returncode == 0 else ""


def contains(checkout, ref, sha):
    """True where the commit `sha` is `ref` or an ancestor of it in `checkout`; False where either opens with `-`."""
    if not sha or not ref or str(sha).startswith("-") or str(ref).startswith("-"):
        return False
    ran = _git(checkout, "merge-base", "--is-ancestor", sha, ref)
    return ran is not None and ran.returncode == 0


def audit_of(text):
    """The body of the plan's `## Audit` section, outside any fence, or None where the plan holds none."""
    bare = FENCE.sub(lambda m: " " * len(m.group(0)), str(text or ""))
    marks = list(HEAD.finditer(bare))
    for k, m in enumerate(marks):
        if m.group(1).strip() == AUDIT:
            end = marks[k + 1].start() if k + 1 < len(marks) else len(bare)
            return bare[m.end():end]
    return None


def read(text):
    """What the gate reads of a plan: {"sections", "audit", "range", "findings", "none", "unread"}. `sections` are
    sections.parse's, `audit` the `## Audit` body or None, `range` the (base, head) its `Audited:` line names or
    None, `findings` each finding as {"text", "how", "rest"}, `none` True where it says `- Finding: none`, and
    `unread` the finding lines that state no outcome and each bullet that names a finding and does not parse as one."""
    import sections
    text = str(text or "").replace("\r\n", "\n")
    _, found = sections.parse(text)
    audit = audit_of(text)
    out = {"sections": found, "audit": audit, "range": None, "findings": [], "none": False, "unread": []}
    if audit is None:
        return out
    m = AUDITED.search(audit)
    if m:
        r = RANGE.search(m.group(1).replace("`", ""))
        out["range"] = (r.group(1), r.group(2)) if r else None
        out["audited"] = True
    for b in BULLET.finditer(audit):
        f = FINDING.match(b.group(0))
        if not f:
            if NAMES_FINDING.search(b.group(0)):
                out["unread"].append(BULLET_MARK.sub("", b.group(0)).strip())
            continue
        said = f.group(1).replace("**", "").strip()
        if NONE.match(said):
            out["none"] = True
            continue
        o = OUTCOME.match(said)
        if not o:
            out["unread"].append(said)
            continue
        out["findings"].append({"text": o.group("text").strip(), "how": o.group("how").lower(),
                                "rest": o.group("rest").strip().strip("`").strip()})
    return out


def evidence_shas(section):
    """The commits a section's `Evidence:` line names, in its order."""
    import sections
    m = sections.EVIDENCE.search(section.get("body") or "")
    return list(dict.fromkeys(SHA.findall(m.group(1)))) if m else []


def check(text, checkout):
    """The list of what stops the plan `text` from closing, read against the git checkout `checkout`; empty means it
    may close. It refuses where a section with a `Files:` line holds no `Evidence:`; where the plan holds no
    `## Audit` or it no `Audited: <date>: <base>..<head>` line; where that head is no commit or does not contain a
    commit an Evidence line names; where a finding is `open` or states no outcome, or the audit lists no finding and
    no `- Finding: none`; and where a `fixed` sha is no commit or is no ancestor of the checkout's HEAD."""
    got = read(text)
    out = []
    for s in got["sections"]:
        if not s.get("landed"):
            out.append(f"section {s['n']} ({s['head']}) holds no `Evidence:`")
        elif not evidence_shas(s):
            out.append(f"section {s['n']} ({s['head']})'s `Evidence:` names no commit")
    if got["audit"] is None:
        out.append("the plan holds no `## Audit` record")
        return out
    if not got.get("audited"):
        out.append("the audit holds no `Audited: <date>: <base>..<head>, code-review and p4-phi:check` line")
    elif not got["range"]:
        out.append("the `Audited:` line names no `<base>..<head>` range")
    else:
        base, head = got["range"]
        for name, ref in (("base", base), ("head", head)):
            if ref.startswith("-"):
                out.append(f"the audit's {name} `{ref}` opens with `-`, which git would read as an option")
        if not commit_of(checkout, base):
            out.append(f"the audit's base `{base}` is no commit of {checkout}")
        if not commit_of(checkout, head):
            out.append(f"the audit's head `{head}` is no commit of {checkout}")
        else:
            for s in got["sections"]:
                for sha in evidence_shas(s):
                    if not commit_of(checkout, sha):
                        out.append(f"section {s['n']}'s Evidence names `{sha}`, which is no commit of {checkout}")
                    elif not contains(checkout, head, sha):
                        out.append(f"the audit's head `{head}` does not contain `{sha}`, which section {s['n']}'s "
                                   f"Evidence names")
    if not got["findings"] and not got["none"] and not got["unread"]:
        out.append("the audit lists no finding, and no `- Finding: none`")
    for said in got["unread"]:
        out.append(f"the finding `{said}` states no outcome: `fixed, <sha>`, `answered, <reason>` or `open`")
    for f in got["findings"]:
        if f["how"] == "open":
            out.append(f"the finding `{f['text']}` is open")
        elif f["how"] == "answered" and not f["rest"]:
            out.append(f"the finding `{f['text']}` is answered with no reason")
        elif f["how"] == "fixed":
            sha = f["rest"].split()[0].strip("`.,;") if f["rest"] else ""
            if not sha:
                out.append(f"the finding `{f['text']}` is fixed with no sha")
            elif sha.startswith("-"):
                out.append(f"the finding `{f['text']}` is fixed by `{sha}`, which opens with `-` and git would read "
                           f"as an option")
            elif not commit_of(checkout, sha):
                out.append(f"the finding `{f['text']}` is fixed by `{sha}`, which is no commit of {checkout}")
            elif not contains(checkout, "HEAD", sha):
                out.append(f"the finding `{f['text']}` is fixed by `{sha}`, which is not in {checkout}'s HEAD")
    return out


def title_name(text):
    """The name plan-planner sorts a plan under: a slug of its first `# ` heading, lower case, each run of
    characters outside a to z and 0 to 9 one hyphen, no hyphen at either end, cut at the last hyphen that keeps it
    within TITLE_CHARS or at TITLE_CHARS where no hyphen does, and `.md`; None where it has no heading or the slug is
    empty, and the plan keeps its own name."""
    m = TITLE.search(FENCE.sub("", str(text or "")))
    if not m:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", m.group(1).lower()).strip("-")
    if len(slug) > TITLE_CHARS:
        cut = slug.rfind("-", 0, TITLE_CHARS + 1)
        slug = slug[:cut] if cut > 0 else slug[:TITLE_CHARS]
    return slug + ".md" if slug else None


def free_name(home, name, own=""):
    """`name`, or `<stem>.<n>.md` with the smallest n from 2 that no place of a plan holds, where the plans folder
    `home` or one of its SHELVES already holds it. The plan's own file, `own`, takes no name from itself."""
    places = [home] + [os.path.join(home, s) for s in SHELVES]
    mine = os.path.normcase(os.path.abspath(own)) if own else ""

    def taken(n):
        return any(os.path.lexists(p) and os.path.normcase(os.path.abspath(p)) != mine
                   for p in (os.path.join(place, n) for place in places))

    if not taken(name):
        return name
    stem = name[:-3] if name.lower().endswith(".md") else name
    n = 2
    while taken(f"{stem}.{n}.md"):
        n += 1
    return f"{stem}.{n}.md"


def status_line(got, today):
    fixed = sum(1 for f in got["findings"] if f["how"] == "fixed")
    answered = sum(1 for f in got["findings"] if f["how"] == "answered")
    k, n = len(got["findings"]), len(got["sections"])
    base, head = got["range"]
    return (f"STATUS: COMPLETED {today}: {n} section{'s' * (n != 1)}; audit {base}..{head}: {k} "
            f"finding{'s' * (k != 1)}, {fixed} fixed, {answered} answered")


def close(path, checkout, home=None, today=None):
    """Close the plan at `path` past the gate: raise Refused with check()'s list where it is not empty; else write
    line 2 as `STATUS: COMPLETED <date>: <n> sections; audit <base>..<head>: <k> findings, <f> fixed, <a>
    answered`, in place of a STATUS line already there, and move the plan into `complete/` of the plans folder
    `home`, under its title's name, numbered where that name is taken, or taken between free_name and the write.
    Where `home` is None it is the plan's own folder, or that folder's parent where the plan sits in one of the
    SHELVES. The plan's line ends, LF or CRLF, are kept. A plan already in `complete/` is refused as closed already.
    The plans already in `complete/` are grandfathered first, and the plan is stamped in `complete/.closed.jsonl`
    with {"name", "sha256", "closed", "audit"}, _sha256 of the bytes it writes, before it writes them there, so a
    sweep between the two never finds it unstamped. Returns the path it moved the plan to."""
    if os.path.basename(os.path.dirname(os.path.abspath(path))).lower() == COMPLETE:
        raise Refused([f"{path} is in complete/ already: the plan is closed"])
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    end = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    reasons = check(text, checkout)
    if reasons:
        raise Refused(reasons)
    if not home:
        home = os.path.dirname(os.path.abspath(path))
        if os.path.basename(home).lower() in SHELVES:
            home = os.path.dirname(home)
    got = read(text)
    today = today or datetime.date.today().isoformat()
    line = status_line(got, today)
    lines = text.split("\n")
    if len(lines) > 1 and STATUS.match(lines[1]):
        lines[1] = line
    else:
        lines.insert(1, line)
    shelf = os.path.join(home, COMPLETE)
    os.makedirs(shelf, exist_ok=True)
    grandfather(home, today)            # the plans closed before the gate keep their place once a stamp is there
    data = end.join(lines).encode("utf-8")
    wanted = title_name(text) or os.path.basename(path)
    own = os.path.normcase(os.path.abspath(path))
    base, head = got["range"]
    while True:
        dest = os.path.join(shelf, free_name(home, wanted, own=path))
        if os.path.normcase(os.path.abspath(dest)) == own:    # the plan sits where it would go: it is closed
            raise Refused([f"{path} is in complete/ already: the plan is closed"])
        # the stamp comes before the file, so a sweep between the two never finds the plan unstamped
        stamp(shelf, os.path.basename(dest), data, today, f"{base}..{head}")
        try:
            with open(dest, "xb") as f:
                f.write(data)
            break
        except FileExistsError:         # taken since free_name looked: free_name now passes it by
            continue
    os.remove(path)
    return dest


def _sha256(data):
    """The stamp's hash of a plan's bytes `data`: taken over its text with a leading BOM out and every CRLF and CR
    read as LF, encoded as UTF-8, so a line-end change such as a git autocrlf checkout leaves a plan stamped.
    p4-temportal's lifetime.py hashes the same way."""
    text = data.decode("utf-8", errors="surrogateescape")
    if text.startswith("﻿"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()


def stamp(shelf, name, data, closed, audit):
    """Append to `shelf`/.closed.jsonl the row {"name", "sha256", "closed", "audit"} of the plan `name` whose bytes
    are `data`, the hash _sha256's."""
    row = {"name": name, "sha256": _sha256(data), "closed": closed, "audit": audit}
    with open(os.path.join(shelf, CLOSED), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def stamps(shelf):
    """The rows of `shelf`/.closed.jsonl as {name: {sha256, ...}}, or None where it is not there or cannot be read. A
    line that is no JSON object with a name and a sha256 is left out."""
    try:
        with open(os.path.join(shelf, CLOSED), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    rows = {}
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("name"), str) and isinstance(row.get("sha256"), str):
            rows.setdefault(row["name"], set()).add(row["sha256"])
    return rows


def stamped(path):
    """True where _sha256 of the file at `path`'s current bytes matches a stamp row of its name in its folder's
    .closed.jsonl."""
    try:
        with open(path, "rb") as f:
            sha = _sha256(f.read())
    except OSError:
        return False
    return sha in ((stamps(os.path.dirname(os.path.abspath(path))) or {}).get(os.path.basename(path)) or ())


def grandfather(home, today=None):
    """Stamp, with `"audit": "before the gate"`, each `.md` already in `complete/` of the plans folder `home`, where
    its .closed.jsonl is not there yet, and return their names; where it is there, or there is no `complete/`, stamp
    nothing and return []. The record is written even where `complete/` holds no plan, so it runs once."""
    shelf = os.path.join(home, COMPLETE)
    if not os.path.isdir(shelf) or os.path.lexists(os.path.join(shelf, CLOSED)):
        return []
    today = today or datetime.date.today().isoformat()
    names = sorted(n for n in os.listdir(shelf)
                   if n.lower().endswith(".md") and os.path.isfile(os.path.join(shelf, n)))
    open(os.path.join(shelf, CLOSED), "a", encoding="utf-8").close()
    for n in names:
        with open(os.path.join(shelf, n), "rb") as f:
            stamp(shelf, n, f.read(), today, BEFORE_GATE)
    return names


def normal(text):
    """`text` with its paths normalised: either slash is `/`, repeated separators are one, and a `./` segment is
    gone, so `plan-planner\\.\\\\complete` reads `plan-planner/complete`. A backslash before `|`, `(`, `)`, `{`, `}`,
    `+`, `?`, `.` or `*` is a regex or shell escape, not a separator, and is dropped (`\\|` is `|`)."""
    out = re.sub(r"\\(?=[|(){}+?.*])", "", str(text or ""))
    out = re.sub(r"/{2,}", "/", out.replace("\\", "/"))
    out = re.sub(r"/\.(?=/)", "", out)
    out = re.sub(r"(?<![\w.])\./", "", out)
    return out


def resolved(path, cwd):
    """`path` normalised, and joined to `cwd` first where it is relative."""
    p = normal(path)
    if cwd and not (p.startswith("/") or re.match(r"^[A-Za-z]:/", p)):
        p = normal(cwd).rstrip("/") + "/" + p
    drive = re.match(r"^[A-Za-z]:", p)
    head, rest = (p[:2], p[2:]) if drive else ("", p)
    return head + posixpath.normpath(rest) if rest else p


def is_complete(run):
    """True where the run `run` is the segment `complete` in any case, or a glob that matches it, such as `comp*`
    or `compl[e]te`; a run of `*` alone, which matches every name, is none."""
    run = run.lower()
    return run == COMPLETE or (bool(re.search(r"[*?\[]", run)) and run.strip("*") != ""
                               and fnmatch.fnmatchcase(COMPLETE, run))


BRACES = re.compile(r"\{([^{}\s]*,[^{}\s]*)\}")     # a brace list `{a,b}`, the innermost first
MOST_WORDS = 256                                    # a brace list's words are read up to this many
SPLITS = "();|&<>"                                  # the marks that end a shell word, as whitespace does


def _parts(word):
    """The parts of the shell word `word` as (quote, text): quote is `'`, `"` or '' for an unquoted run; None where
    a quote is left open."""
    out, i = [], 0
    while i < len(word):
        c = word[i]
        if c in QUOTES:
            j = word.find(c, i + 1)
            if j < 0:
                return None
            out.append((c, word[i + 1:j]))
            i = j + 1
        else:
            j = i
            while j < len(word) and word[j] not in QUOTES:
                j += 1
            out.append(("", word[i:j]))
            i = j
    return out


def _split(line):
    """`line` cut into its words and, each on its own, the characters between them: whitespace and the marks of a
    chain, a redirection or a subexpression, SPLITS; a quote's characters are kept in its word."""
    out, word, quote = [], "", ""
    for c in line:
        if quote:
            word += c
            quote = "" if c == quote else quote
        elif c in QUOTES:
            word += c
            quote = c
        elif c.isspace() or c in SPLITS:
            if word:
                out.append(word)
                word = ""
            out.append(c)
        else:
            word += c
    if word:
        out.append(word)
    return out


def _braces(word):
    """The words the brace lists of `word` expand to, as a shell does: `a/{b,c}/` is `a/b/` and `a/c/`."""
    words, done = [word], []
    while words and len(done) + len(words) <= MOST_WORDS:
        w = words.pop(0)
        m = BRACES.search(w)
        if not m:
            done.append(w)
            continue
        words += [w[:m.start()] + part + w[m.end():] for part in m.group(1).split(",")]
    return done + words


def shell_words(cmd):
    """The shell line `cmd` read as a shell reads its words, so a guard sees the path it builds: a PowerShell
    backtick escape is its character (``comp`lete``); a word of more than one part with no whitespace in a quote
    loses its quotes (`comp''lete`, `"plan-planner/comp"lete`), while a word quoted whole, or whose quote holds a
    space, keeps them; a brace list is read as its words (`{complete,todo}/` is `complete/ todo/`); and a trailing
    dot of a path part (`complete./`), or a trailing space of one inside a quote, is dropped, as Windows does. A
    name built from a variable is left as it is."""
    line = re.sub(r"`(.)", r"\1", str(cmd or ""), flags=re.S)
    out = []
    for word in _split(line):
        parts = _parts(word)
        if parts is None:
            out.append(word)
            continue
        if any(q for q, _ in parts) and (len(parts) == 1 or any(q and re.search(r"\s", t) for q, t in parts)):
            out.append(re.sub(r"(?<=[^\s/\\.])[. ]+(?=[/\\])", "", word))
            continue
        word = "".join(t for _, t in parts)
        out.append(" ".join(_braces(word)))
    line = "".join(out)
    return re.sub(r"(?<=[^\s/\\.])\.+(?=[/\\'\"\s]|$)", "", line)


def names_complete(cmd, cwd):
    """True where the shell line `cmd`, normalised, names `complete` as a path segment, whether or not it names
    `plan-planner`, since the hook cannot know a shell's cwd after a `cd`: a run that is `complete`, or a glob that
    matches it, with a separator beside it (`complete/`, `/complete`, `/comp*`), or quoted alone as a path's part
    (`Join-Path 'E:/p/plan-planner' 'complete'`, `os.path.join('plan-planner', 'complete')`). A word with no
    separator beside it, as in `-m "audit complete"` or `grep complete`, is none. A glob outside a quote, as in
    `mv x.md comp*`, is a path the shell expands, and where the call's cwd is the plans folder, `plan-planner`, a
    `complete` outside a quote is a segment too. The line is read by shell_words first, so `comp''lete`,
    ``comp`lete``, `{complete,todo}/` and `complete./` are `complete`."""
    line = normal(shell_words(cmd))
    planners = posixpath.basename(normal(cwd or "").rstrip("/")).lower() == PLANS_FOLDER
    for m in RUN.finditer(line):
        if not is_complete(m.group(0)):
            continue
        before = line[m.start() - 1] if m.start() else ""
        after = line[m.end()] if m.end() < len(line) else ""
        if "/" in (before, after):
            return True
        if before and before in QUOTES and after == before:
            return True
        if (planners or m.group(0).lower() != COMPLETE) and before not in QUOTES and after not in QUOTES:
            return True
    return False


def tokens(cmd):
    """The words of the shell line `cmd`, quoted words whole, with a `&` that opens it, PowerShell's call operator,
    taken out; None where a quote is left open."""
    line = CALL.sub("", cmd.strip())
    words = TOKEN.findall(line)
    if re.sub(r"\s+", "", line) != "".join(words):
        return None
    return words


def bare(word):
    return word[1:-1] if len(word) > 1 and word[0] == word[-1] and word[0] in "\"'" else word


def same_file(word, cwd, path):
    """True where the path `word`, joined to `cwd` where it is relative, resolves to the file `path`. Either slash
    is read as a separator, as PowerShell reads one on every system, so `\\home\\x\\phi.py` resolves on Linux too."""
    p = normal(bare(word))
    if cwd and not os.path.isabs(p):
        p = os.path.join(cwd, p)
    try:
        return os.path.normcase(os.path.realpath(p)) == os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return False


def is_close_line(cmd, cwd=None):
    """True where the whole of `cmd` is one `phi.py plan close` invocation: an interpreter (a basename python,
    python3, python.exe or py) with flags of FLAGS and `-X <opt>` only, one to a word, then the phi.py beside this
    file by its resolved path, then `plan close` and its words, with no `#` comment, no `>` or `<` redirection and
    no chain. So `python -Ic "..." phi.py plan close` and a phi.py planted elsewhere are none. `cwd` is the one a
    relative phi.py is joined to, this process's own where it is None."""
    line = CALL.sub("", cmd.strip())
    if NOT_ONE.search(line):
        return False
    words = tokens(cmd)
    if not words or not PYTHON.match(posixpath.basename(normal(bare(words[0])))):
        return False
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] in TAKES_VALUE:
            i += 2
        elif words[i] in FLAGS:
            i += 1
        else:
            return False
    return (i + 2 < len(words) and same_file(words[i], cwd if cwd is not None else os.getcwd(), PHI)
            and [w.lower() for w in words[i + 1:i + 3]] == ["plan", "close"])


def is_read_only(cmd):
    """True where `cmd` is one read-only command with no redirection and no chain: `ls`, `dir`, `cat`, `type`,
    `Get-ChildItem`, `Get-Content`, `grep`, `rg`, or `git status`, `log`, `diff` or `show`, `git -C <path>` before
    it or not."""
    if NOT_READ_ONLY.search(CALL.sub("", cmd.strip())):
        return False
    words = tokens(cmd)
    if not words or any(WRITES_ANYWAY.match(bare(w)) for w in words):
        return False
    first = bare(words[0]).lower()
    if first in READ_ONLY:
        return True
    if first != "git":
        return False
    i = 1
    while i + 1 < len(words) and words[i] == "-C":
        i += 2
    return i < len(words) and words[i].lower() in GIT_READ_ONLY


def guard(tool, tool_input, cwd=None):
    """The deny reason for a way into `plan-planner/complete/` other than `phi.py plan close`, or None:
    - a Write, Edit or NotebookEdit whose path, joined to the call's `cwd` where it is relative and normalised, is
      under it;
    - a Bash, PowerShell or `mcp__terminal__run_in_terminal` line that, normalised, names a `complete` segment, as
      names_complete reads it, and is neither one `phi.py plan close` line alone nor a read-only line.
    `cwd` is the call's, this process's own where it is None."""
    inp = tool_input if isinstance(tool_input, dict) else {}
    tool = str(tool or "")
    cwd = cwd if cwd is not None else os.getcwd()
    if tool in EDITS:
        raw = inp.get("notebook_path") if tool == "NotebookEdit" else inp.get("file_path")
        raw = raw or inp.get("file_path") or inp.get("notebook_path")
        if raw and UNDER_COMPLETE.search(resolved(str(raw), cwd)):
            return (f"phi (p4-phi): this {tool} is refused: {raw} is under plan-planner/complete/, which a plan "
                    f"enters only by `phi.py plan close <plan> --checkout <repo>`, past the gate of its Evidence "
                    f"and its `## Audit`. A closed plan is the record ezexe goes back to, and no hand edits it.")
        return None
    if tool in SHELLS:
        cmd = str(inp.get("command") or "")
        if not names_complete(cmd, cwd) or is_close_line(cmd, cwd) or is_read_only(cmd):
            return None
        return ("phi (p4-phi): this command is refused: it names a `complete` folder, which a plan enters only "
                "by `phi.py plan close <plan> --checkout <repo>`, past the gate of its Evidence and its `## Audit`. "
                "Run that line alone, with python and the plugin's own phi.py, and it writes the STATUS line and "
                "makes the move.")
    return None
