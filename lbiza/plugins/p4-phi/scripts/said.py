#!/usr/bin/env python3
"""said.py: what a session states about the retrieval lines it was shown, `p4.py said`.

Nothing in a store says which rule a session acted on. Matching the words of a turn against a rule's rare words
labels every rule on hundreds of turns, no later message is like the message a rule was made on, and ezexe does not
have to repeat a rule. Only the session knows it when it acts, so it is asked to say so with one of three fixed
statements, run as a command and not written in its reply:

    applied r1               a line shown this turn changed what it did
    set-aside r1 --why ...   it saw the line and decided against it
    lacked --why ...         ezexe corrected it and no line covered it

`recall.said.mode` of p4.json:
    off      the default: nothing is asked, and the retrieval lines carry no handles
    shadow   each rule, correction, retraction and fact line shown gets a handle such as `[r1]`, one instruction
             follows the lines, and what the session states is written down; nothing trains on it
    on       the same, and training reads the statements as labels of source `said`: 1 for applied, 0 for set-aside

A statement is a claim, not a fact, and the instruction is one more thing a session is told. So `shadow` comes
before `on`, to measure two things: `p4.py check` prints how many asked turns stated anything, and how often a
statement is true takes a judged sample.

Every statement is a row of phi/models/said.tsv, and so is every turn that was asked. Its columns are time, session,
task, act, entry and note. The store tracks the table, and its sync merges every machine's rows into it. An applied
or set-aside statement is also a row of phi/models/labels.tsv, which training skips unless the mode is on.
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

FILE = "said.tsv"
HEAD = ["time", "session", "task", "act", "entry", "note"]
ACTS = ("applied", "set-aside", "lacked")


def mode(p4):
    import p4conf
    v = (p4conf.section(p4, "recall", write=False).get("said") or {}).get("mode", "off")
    return v if v in ("off", "shadow", "on") else "off"


def path(p4):
    return p4conf.sub(p4, "models", FILE)


def tag(pairs):
    """The lines and {handle: document id} for a list of pairs of a line and its id. The line of a rule, correction,
    retraction or fact gets the next handle of `[r1]`, `[r2]` and so on, after its leading `- ` or first when it has
    none; any other line is left as it is."""
    import store as st
    lines, handles = [], {}
    for line, eid in pairs:
        if isinstance(eid, str) and eid.startswith(tuple(st.STORE_FILES)):
            h = f"r{len(handles) + 1}"
            handles[h] = eid
            line = (f"- [{h}] " + line[2:]) if line.startswith("- ") else f"[{h}] {line}"
        lines.append(line)
    return lines, handles


def command():
    """The command a session runs, in a form both Bash and PowerShell take: this interpreter and this plugin's p4.py
    with forward slashes. The script's path is in double quotes only when it holds a space, and `python` stands in
    for an interpreter whose path holds one."""
    exe = sys.executable.replace("\\", "/")
    script = os.path.join(HERE, "p4.py").replace("\\", "/")
    return f"{exe if ' ' not in exe else 'python'} -I {script if ' ' not in script else chr(34) + script + chr(34)} said"


def instruction(handles, session, p4):
    where = p4.replace(chr(92), "/")
    cmd = f"{command()} --session {session} --p4 {where if ' ' not in where else chr(34) + where + chr(34)}"
    first = next(iter(handles))
    # the command is spelled out one time, as SAID: it holds long paths, and a copy on each line would triple them
    return ("If a line above with a handle changes what you do this turn or you decide against one, record it for the "
            "store with one command outside your reply before you finish. Use the third if ezexe corrected you and no "
            "line covered it:\n"
            f"  SAID applied {first}\n"
            f"  SAID set-aside {first} --why \"a few words\"\n"
            "  SAID lacked --why \"what was missing\"\n"
            f"where SAID is: {cmd}")


def log(p4, rows):
    import labels as lb
    lb.append_tsv(path(p4), HEAD, rows)


def asked(p4, session, task, handles, now):
    """One row saying this turn was asked, so the share of asked turns that stated anything can be counted."""
    log(p4, [{"time": now, "session": (session or "")[:8], "task": task, "act": "asked", "entry": "",
              "note": " ".join(sorted(handles))}])


def state(p4, session, act, names, why="", now=None):
    """Record one statement of the turn in flight, and return the lines to print and the exit code. The handles are
    those of the lines `h_recall` in hook.py showed this session's current turn, which it keeps in
    phi/models/served/turn-<session>.json."""
    import labels as lb
    now = now or time.strftime("%Y-%m-%d %H:%M")
    if act not in ACTS:
        return [f"said: unknown statement {act!r}; one of {', '.join(ACTS)}"], 2
    served = lb.read_served(p4, f"turn-{session}") or {}
    handles, task = served.get("handles") or {}, served.get("task") or ""
    why = " ".join((why or "").split())[:200]
    if act == "lacked":
        if not why:
            return ["said: `lacked` needs --why: what was missing"], 2
        log(p4, [{"time": now, "session": (session or "")[:8], "task": task, "act": "lacked", "entry": "", "note": why}])
        return ["said: noted"], 0
    if not names:
        return [f"said: `{act}` needs a handle: {' '.join(sorted(handles)) or 'none were shown this turn'}"], 2
    bad = [n for n in names if n not in handles]
    if bad:
        return [f"said: no line with the handle {', '.join(bad)} was shown this turn"
                + (f"; the handles shown were {' '.join(sorted(handles))}" if handles else "")], 2
    rows, labels = [], []
    for n in dict.fromkeys(names):
        note = act + (f": {why}" if why else "")
        rows.append({"time": now, "session": (session or "")[:8], "task": task, "act": act, "entry": handles[n], "note": why})
        labels.append({"task": task, "entry": handles[n], "label": "1" if act == "applied" else "0", "source": "said",
                       "weight": "1.0", "time": now, "teacher": "", "edited": "", "note": note})
    log(p4, rows)
    lb.append_tsv(lb.mpath(p4, lb.TRAIN), lb.TRAIN_HEAD, labels)
    return ["said: noted"], 0


def stats(p4):
    """{asked, stated, applied, set-aside, lacked}: turns that were asked, how many of them stated anything, and the
    statements by kind."""
    import labels as lb
    rows = lb.read_tsv(path(p4))
    asked_tasks = {r["task"] for r in rows if r.get("act") == "asked"}
    stated = {r["task"] for r in rows if r.get("act") in ACTS and r.get("task") in asked_tasks}
    out = {"asked": len(asked_tasks), "stated": len(stated)}
    for a in ACTS:
        out[a] = sum(1 for r in rows if r.get("act") == a)
    return out


def stats_line(p4):
    m = mode(p4)
    s = stats(p4)
    if m == "off" and not s["asked"]:
        return ""
    return (f"said ({m}): asked on {s['asked']} turns, stated on {s['stated']}; applied {s['applied']}, "
            f"set aside {s['set-aside']}, lacked {s['lacked']}")
