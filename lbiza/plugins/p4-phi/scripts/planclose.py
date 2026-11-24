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
import re
import subprocess

COMPLETE = "complete"
SHELVES = ("complete", "todo", "unplanned")     # plan-planner's places of a sorted plan, beside the plans folder
TITLE_CHARS = 60                                # plan-planner, `Moving a plan`: the slug is cut within 60 characters
FENCE = re.compile(r"(?ms)^(`{3,}|~{3,}).*?^\1[ \t]*$")
TITLE = re.compile(r"(?m)^# +(.+?)\s*$")
HEAD = re.compile(r"(?m)^## +(.+?)\s*$")
AUDIT = re.compile(r"(?i)^audit\b")
AUDITED = re.compile(r"(?im)^[ \t>*-]*(?:\*\*)?audited(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$")
RANGE = re.compile(r"([^\s:,`]+?)\.\.([^\s,`]+)")
FINDING = re.compile(r"(?im)^[ \t]*[-*][ \t]+(?:\*\*)?finding(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?[ \t]*(.+?)[ \t]*$")
OUTCOME = re.compile(r"(?is)^(?P<text>.+?):[ \t]*(?P<how>fixed|answered|open)\b[ \t]*,?[ \t]*(?P<rest>.*)$")
NONE = re.compile(r"(?i)^\W*none\W*$")
# a commit an Evidence line names: 7 to 40 lower hex digits with a digit among them, so a word such as `defaced`
# is none, and no part of a version, a path or an issue number such as `ezexe/p4#256`
SHA = re.compile(r"(?<![\w./#:-])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![\w/-]|\.\w)")
STATUS = re.compile(r"^STATUS:")

EDITS = ("Write", "Edit", "NotebookEdit")
SHELLS = ("Bash", "PowerShell")
NAMES_COMPLETE = re.compile(r"(?i)plan-planner[\\/]+complete(?![\w-])")
UNDER_COMPLETE = re.compile(r"(?i)(?:^|/)plan-planner/+complete(?:/|$)")
CLOSE_LINE = re.compile(r"(?i)phi\.py[\"']?\s+plan\s+close(?![\w-])")
# what makes one shell line more than one command: `;`, `|`, `&`, a newline, a backtick or a `$(`, once a `&` that
# opens the line, PowerShell's call operator, and a redirection such as `2>&1` are taken out
CHAINED = re.compile(r"[;|&\n`]|\$\(")
REDIRECT = re.compile(r"\d?>&\d")
CALL = re.compile(r"^&\s*")


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
    """The full sha `ref` names in `checkout`, or '' where it names no commit there."""
    ran = _git(checkout, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return ran.stdout.strip() if ran is not None and ran.returncode == 0 else ""


def contains(checkout, ref, sha):
    """True where the commit `sha` is `ref` or an ancestor of it in `checkout`."""
    ran = _git(checkout, "merge-base", "--is-ancestor", sha, ref)
    return ran is not None and ran.returncode == 0


def audit_of(text):
    """The body of the plan's `## Audit` section, outside any fence, or None where the plan holds none."""
    bare = FENCE.sub(lambda m: " " * len(m.group(0)), str(text or ""))
    marks = list(HEAD.finditer(bare))
    for k, m in enumerate(marks):
        if AUDIT.match(m.group(1).strip()):
            end = marks[k + 1].start() if k + 1 < len(marks) else len(bare)
            return bare[m.end():end]
    return None


def read(text):
    """What the gate reads of a plan: {"sections", "audit", "range", "findings", "none", "unread"}. `sections` are
    sections.parse's, `audit` the `## Audit` body or None, `range` the (base, head) its `Audited:` line names or
    None, `findings` each finding as {"text", "how", "rest"}, `none` True where it says `- Finding: none`, and
    `unread` the finding lines that state no outcome."""
    import sections
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
    for f in FINDING.finditer(audit):
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
    if got["audit"] is None:
        out.append("the plan holds no `## Audit` record")
        return out
    if not got.get("audited"):
        out.append("the audit holds no `Audited: <date>: <base>..<head>, code-review and p4-phi:check` line")
    elif not got["range"]:
        out.append("the `Audited:` line names no `<base>..<head>` range")
    else:
        base, head = got["range"]
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
    `home`, the plan's own folder where it is None, under its title's name, numbered where that name is taken.
    Returns the path it moved the plan to."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    reasons = check(text, checkout)
    if reasons:
        raise Refused(reasons)
    home = home or os.path.dirname(os.path.abspath(path))
    got = read(text)
    line = status_line(got, today or datetime.date.today().isoformat())
    lines = text.split("\n")
    if len(lines) > 1 and STATUS.match(lines[1]):
        lines[1] = line
    else:
        lines.insert(1, line)
    shelf = os.path.join(home, COMPLETE)
    os.makedirs(shelf, exist_ok=True)
    name = free_name(home, title_name(text) or os.path.basename(path), own=path)
    dest = os.path.join(shelf, name)
    with open(dest, "x", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines))
    os.remove(path)
    return dest


def guard(tool, tool_input):
    """The deny reason for a way into `plan-planner/complete/` other than `phi.py plan close`, or None: a Write,
    Edit or NotebookEdit whose path is under it, and a Bash or PowerShell command that names `plan-planner/complete`
    or `plan-planner\\complete` and is not one `phi.py plan close` line."""
    inp = tool_input if isinstance(tool_input, dict) else {}
    tool = str(tool or "")
    if tool in EDITS:
        raw = inp.get("notebook_path") if tool == "NotebookEdit" else inp.get("file_path")
        raw = raw or inp.get("file_path") or inp.get("notebook_path")
        if raw and UNDER_COMPLETE.search(str(raw).replace("\\", "/")):
            return (f"phi (p4-phi): this {tool} is refused: {raw} is under plan-planner/complete/, which a plan "
                    f"enters only by `phi.py plan close <plan> --checkout <repo>`, past the gate of its Evidence "
                    f"and its `## Audit`. A closed plan is the record ezexe goes back to, and no hand edits it.")
        return None
    if tool in SHELLS:
        cmd = str(inp.get("command") or "")
        if not NAMES_COMPLETE.search(cmd):
            return None
        if CLOSE_LINE.search(cmd) and not CHAINED.search(CALL.sub("", REDIRECT.sub("", cmd.strip()))):
            return None
        return ("phi (p4-phi): this command is refused: it names plan-planner/complete, which a plan enters only "
                "by `phi.py plan close <plan> --checkout <repo>`, past the gate of its Evidence and its `## Audit`. "
                "Run that line alone, and it writes the STATUS line and makes the move.")
    return None
