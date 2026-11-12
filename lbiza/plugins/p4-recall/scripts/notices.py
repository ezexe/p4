#!/usr/bin/env python3
"""notices.py: the retrain notices a session leaves when a model fails it, `models/retrain-needed.tsv`.

A hook that meets an unexpected model failure falls back (the no-ranker road, the children, the operator) and
appends one row here: nothing more, never a retry in the hook's own 300 ms. The p4-model skill (ezexe/phi,
`python -m phi_model check|update`) reads the rows, retrains the model each one names, and answers them by
appending to `models/retrain-resolved.tsv`; this file is never rewritten, so a notice appended while a training
runs is never lost.

Rows: time, epoch, session, component, kind, error (tab-separated; a `#` line is the header). A component is
`json ranker` (models/ranker.json: unreadable, not this kind, or scoring raised), `pt ranker` (the .pt chain or
its server), `hook <name>` (a hook that raised), `train` (a round that raised). The same component and kind is
noted once a day: a store whose model is broken for a week has seven rows, not one per message.

    notify(p4, "json ranker", ValueError("unreadable"), session)   -> True when a row was appended
    open_notices(p4)                                                -> the rows not yet answered
    notice_family(component)                                        -> "json" | "ranker" | "hook" | "train"
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

NOTICES = "retrain-needed.tsv"
RESOLVED = "retrain-resolved.tsv"
HEAD = "# p4-recall retrain notices — time\tepoch\tsession\tcomponent\tkind\terror\n"
FAMILIES = (("json ranker", "json"), ("pt ranker", "ranker"), ("ranker server", "ranker"), ("hook", "hook"),
            ("train", "train"))


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
            out.append({"time": c[0], "epoch": epoch, "session": c[2], "component": c[3], "kind": c[4],
                        "error": c[5], "resolved": c[6] if len(c) > 6 else ""})
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
        f.write(f"{stamp}\t{time.time():.6f}\t{(session or '')[:8]}\t{component}\t{kind}\t{text}\n")
    return True


def open_notices(p4):
    """The notices no row of retrain-resolved.tsv answers (matched on time, component and error)."""
    done = {(r["time"], r["component"], r["error"]) for r in _rows(path(p4, RESOLVED))}
    return [r for r in _rows(path(p4)) if (r["time"], r["component"], r["error"]) not in done]


def notice_family(component):
    for prefix, fam in FAMILIES:
        if component.startswith(prefix):
            return fam
    return "json"
