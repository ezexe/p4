#!/usr/bin/env python3
"""notices.py: the retrain notices a session leaves when a model fails it, `phi/models/retrain-needed.tsv`.

Two places append a row, and each goes on: p4.py's `query` when `phi/models/ranker.json` is there and is not a
readable ranker of its kind, falling back to BM25, and hook.py's `main` when a hook raises, exiting 0 all the same.
Neither retries or retrains. The p4-model skill of ezexe/phi, `python -m phi_model check|update`, reads the rows,
retrains, and answers the notices of each model it rebuilt by appending to `phi/models/retrain-resolved.tsv`. This
file is never rewritten, so a notice appended while a training runs is never lost.

Rows are tab-separated: time, epoch, session, component, kind, error, and the p4-phi version that wrote the row. A
line that begins with `#` is the header, and no reader parses it. A component is `json ranker`, for a ranker file
that is unreadable or not of its kind, or `hook <name>`, for a hook that raised, the two the plugin writes;
notice_family also files `pt ranker` and `ranker server` under the .pt ranker that ezexe/phi's p4-model trains, and
`train` under a training round. A hook's notice is of the family `release`: no training fixes a hook, so p4-model
owes none for it, and open_notices answers it once a later p4-phi release reads it. The same component and kind is
noted once a day: a store whose model is broken for a week has seven rows, not one per message.

    notify(p4, "json ranker", ValueError("unreadable"), session)   -> True when a row was appended
    open_notices(p4)                                                -> the rows not yet answered
    notice_family(component)                                        -> "json" | "ranker" | "release" | "train"
"""

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

NOTICES = "retrain-needed.tsv"
RESOLVED = "retrain-resolved.tsv"
HEAD = "# p4-phi retrain notices — time\tepoch\tsession\tcomponent\tkind\terror\n"
FAMILIES = (("json ranker", "json"), ("pt ranker", "ranker"), ("ranker server", "ranker"), ("hook", "release"),
            ("train", "train"))
PLUGIN_JSON = os.path.join(os.path.dirname(HERE), ".claude-plugin", "plugin.json")


def plugin_version():
    """The version of p4-phi this code runs as, from its plugin.json, or '' when it cannot be read."""
    try:
        with open(PLUGIN_JSON, encoding="utf-8") as f:
            v = json.load(f).get("version")
    except (OSError, ValueError, AttributeError):
        return ""
    return v if isinstance(v, str) else ""


def _later(now, then):
    """Whether version `now` is a release after `then`: by number where both are dotted numbers, else by
    difference. A notice written before notices carried a version, `then` empty, is older than any version."""
    if not now:
        return False
    if not then:
        return True
    try:
        return tuple(int(x) for x in now.split(".")) > tuple(int(x) for x in then.split("."))
    except ValueError:
        return now != then


def path(p4, name=NOTICES):
    return p4conf.sub(p4, "models", name)


def _rows(p):
    try:
        with open(p, encoding="utf-8") as f:
            lines = [l.rstrip("\n") for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return []
    out = []
    for l in lines:
        c = l.split("\t")
        if len(c) >= 6:
            try:
                epoch = float(c[1])
            except ValueError:
                epoch = 0.0
            # the 7th field: a notice's p4-phi version, an answer's resolution
            out.append({"time": c[0], "epoch": epoch, "session": c[2], "component": c[3], "kind": c[4],
                        "error": c[5], "resolved": c[6] if len(c) > 6 else "", "version": c[6] if len(c) > 6 else ""})
    return out


def notify(p4, component, error, session="", now=None):
    """Append one row unless the same component and kind was noted today; returns whether a row was appended."""
    stamp = now or time.strftime("%Y-%m-%d %H:%M")
    kind = type(error).__name__ if isinstance(error, BaseException) else str(error or "failure")
    text = " ".join(str(error).split())[:300] if isinstance(error, BaseException) else ""
    p = path(p4)
    for r in _rows(p):
        if r["component"] == component and r["kind"] == kind and r["time"][:10] == stamp[:10]:
            return False
    os.makedirs(os.path.dirname(p), exist_ok=True)
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write(HEAD)
        f.write(f"{stamp}\t{time.time():.6f}\t{(session or '')[:8]}\t{component}\t{kind}\t{text}\t{plugin_version()}\n")
    return True


def open_notices(p4):
    """The notices no row of retrain-resolved.tsv answers: a row answers the notice of its time, component, kind and
    error, the kind telling apart two notices of one minute whose plain-string errors leave the error field empty.
    A notice of the "release" family, a hook that raised, has no training that fixes it: the first p4-phi release
    after the one that wrote it answers it here, with a row ending in `released p4-phi <version>`."""
    key = lambda r: (r["time"], r["component"], r["kind"], r["error"])  # noqa: E731
    done = {key(r) for r in _rows(path(p4, RESOLVED))}
    rows = [r for r in _rows(path(p4)) if key(r) not in done]
    now = plugin_version()
    released = [r for r in rows if notice_family(r["component"]) == "release" and _later(now, r["version"])]
    if released:
        p = path(p4, RESOLVED)
        try:
            with open(p, "a", encoding="utf-8", newline="\n") as f:
                for r in released:
                    f.write("\t".join([r["time"], f"{r['epoch']:.6f}", r["session"], r["component"], r["kind"],
                                       r["error"], f"released p4-phi {now}"]) + "\n")
        except OSError:
            return rows                                # not recorded: they stay open
        rows = [r for r in rows if r not in released]
    return rows


def notice_family(component):
    for prefix, fam in FAMILIES:
        if component.startswith(prefix):
            return fam
    return "json"
