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
its title's name, numbered where that name is taken, as plan-planner's `Moving a plan` says, and guard() is the
deny reason for every other way into `complete/`.
"""

import datetime
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
# `- Finding: <text>`, `- Finding 2: <text>` and `- Finding #2: <text>`
FINDING = re.compile(r"(?i)^[ \t]*[-*][ \t]+(?:\*\*)?finding(?:[ \t]*#?[ \t]*\d+)?(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*"
                     r"(.+?)[ \t]*$")
BULLET = re.compile(r"(?m)^[ \t]*[-*][ \t]+.*$")
NAMES_FINDING = re.compile(r"(?i)\bfinding")
# the outcome is the last `: fixed|answered|open` of the line, so a finding's text may hold one of those words
OUTCOME = re.compile(r"(?is)^(?P<text>.+):[ \t]*(?P<how>fixed|answered|open)\b[ \t]*,?[ \t]*(?P<rest>.*)$")
NONE = re.compile(r"(?i)^\W*none\W*$")
# a commit an Evidence line names: 7 to 40 lower hex digits with a digit among them, so a word such as `defaced`
# is none, and no part of a version, a path or an issue number such as `ezexe/p4#256`
SHA = re.compile(r"(?<![\w./#:-])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![\w/-]|\.\w)")
STATUS = re.compile(r"^STATUS:")

EDITS = ("Write", "Edit", "NotebookEdit")
SHELLS = ("Bash", "PowerShell", "mcp__terminal__run_in_terminal")
PLANNER = re.compile(r"(?i)(?<![\w-])plan-planner(?![\w-])")
# `complete` as a path segment once a line's paths are normalised: `complete/`, `/complete`, `'complete'` in a
# Join-Path, and no `completed`, `complete.md` or `auto-complete`
SEGMENT = re.compile(r"(?i)(?<![\w.-])complete(?![\w-]|\.\w)")
UNDER_COMPLETE = re.compile(r"(?i)(?:^|/)plan-planner/complete(?:/|$)")
# what keeps a shell line from being one command alone: a chain (`;`, `|`, `&`, a newline, a backtick or a `$(`),
# a redirection (`>` or `<`) or a `#` comment, once a `&` that opens the line, PowerShell's call operator, is out
NOT_ONE = re.compile(r"[;|&\n\r`<>#]|\$\(")
NOT_READ_ONLY = re.compile(r"[;|&\n\r`<>]|\$\(")
CALL = re.compile(r"^&\s*")
TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|[^\s\"']+")
PYTHON = re.compile(r"(?i)^(?:python[\d.]*|pythonw|py)(?:\.exe)?$")
TAKES_VALUE = ("-X", "-W")                      # python's options whose value is the next word
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
                out["unread"].append(b.group(0).strip().lstrip("-*").strip())
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
    SHELVES. The plan's line ends, LF or CRLF, are kept. Returns the path it moved the plan to."""
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
    line = status_line(got, today or datetime.date.today().isoformat())
    lines = text.split("\n")
    if len(lines) > 1 and STATUS.match(lines[1]):
        lines[1] = line
    else:
        lines.insert(1, line)
    shelf = os.path.join(home, COMPLETE)
    os.makedirs(shelf, exist_ok=True)
    wanted = title_name(text) or os.path.basename(path)
    while True:
        dest = os.path.join(shelf, free_name(home, wanted, own=path))
        try:
            with open(dest, "x", encoding="utf-8", newline="") as f:
                f.write(end.join(lines))
            break
        except FileExistsError:         # taken since free_name looked: free_name now passes it by
            continue
    os.remove(path)
    return dest


def normal(text):
    """`text` with its paths normalised: either slash is `/`, repeated separators are one, and a `./` segment is
    gone, so `plan-planner\\.\\\\complete` reads `plan-planner/complete`."""
    out = re.sub(r"/{2,}", "/", str(text or "").replace("\\", "/"))
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


def names_complete(cmd, cwd):
    """True where the shell line `cmd`, normalised, names `complete` as a path segment and names `plan-planner`
    too, or is run with the plans folder, `plan-planner`, as its cwd."""
    line = normal(cmd)
    if not SEGMENT.search(line):
        return False
    return bool(PLANNER.search(line)) or posixpath.basename(normal(cwd or "").rstrip("/")).lower() == "plan-planner"


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


def is_close_line(cmd):
    """True where the whole of `cmd` is one `phi.py plan close` invocation: a python launcher and its options or
    phi.py itself, then `plan close` and its words, with no `#` comment, no `>` or `<` redirection and no chain."""
    line = CALL.sub("", cmd.strip())
    if NOT_ONE.search(line):
        return False
    words = tokens(cmd)
    if not words:
        return False
    i = 0
    if PYTHON.match(posixpath.basename(normal(bare(words[0])))):
        i = 1
        while i < len(words) and words[i].startswith("-"):
            if words[i] in ("-c", "-m") or words[i].startswith(("-c", "-m")):
                return False
            i += 2 if words[i] in TAKES_VALUE else 1
    return (i + 2 < len(words) and posixpath.basename(normal(bare(words[i]))).lower() == "phi.py"
            and [w.lower() for w in words[i + 1:i + 3]] == ["plan", "close"])


def is_read_only(cmd):
    """True where `cmd` is one read-only command with no redirection and no chain: `ls`, `dir`, `cat`, `type`,
    `Get-ChildItem`, `Get-Content`, `grep`, `rg`, or `git status`, `log`, `diff` or `show`."""
    if NOT_READ_ONLY.search(CALL.sub("", cmd.strip())):
        return False
    words = tokens(cmd)
    if not words or any(WRITES_ANYWAY.match(bare(w)) for w in words):
        return False
    first = bare(words[0]).lower()
    if first in READ_ONLY:
        return True
    return first == "git" and len(words) > 1 and words[1].lower() in GIT_READ_ONLY


def guard(tool, tool_input, cwd=None):
    """The deny reason for a way into `plan-planner/complete/` other than `phi.py plan close`, or None:
    - a Write, Edit or NotebookEdit whose path, joined to the call's `cwd` where it is relative and normalised, is
      under it;
    - a Bash, PowerShell or `mcp__terminal__run_in_terminal` line that, normalised, names `plan-planner` and a
      `complete` segment, or a `complete` segment with the plans folder as its cwd, and is neither one
      `phi.py plan close` line alone nor a read-only line.
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
        if not names_complete(cmd, cwd) or is_close_line(cmd) or is_read_only(cmd):
            return None
        return ("phi (p4-phi): this command is refused: it names plan-planner/complete, which a plan enters only "
                "by `phi.py plan close <plan> --checkout <repo>`, past the gate of its Evidence and its `## Audit`. "
                "Run that line alone, and it writes the STATUS line and makes the move.")
    return None
