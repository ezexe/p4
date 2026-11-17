"""
What an old-layout p4 store says could have gone better: the lessons its sessions recorded while the old contracts ran.
test_migrate.py checks migrate.py's counts of an old tree against these, and the script runs on any p4 tree by hand.

A lesson is an entry the store wrote because something went wrong or had to be undone:
  correction   ledger.md        a reading that steered work and was wrong, its `match:` against its `meant:`
  retraction   tombstones.md    a rule or reading ezexe freed, with `freed:` and ezexe's words
  missed       briefs.md        what a picker left out, so that ezexe had to ask, with `omitted:`
  repeat       dispatch.md      a message the barrier caught as a repeat or as superseded, in state ECHO or SUPERSEDED
Rulings, in local-storage.md, are counted too, as ezexe's standing words, but are not lessons.

The store files mix two shapes, fenced yaml blocks and dash-led entries, so entries are cut at blank lines and fences
and kept by the field each kind carries; a file's own header, whose schema lines hold `[placeholders]`, is skipped.

Run:
  python lbiza/plugins/p4-phi/scripts/store_lessons.py --p4 <a .claude/p4 directory, or a p4 repository> [--out lessons.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

KINDS = {"correction": ("ledger.md", re.compile(r"(?m)^\s*-?\s*meant:")),
         "retraction": ("tombstones.md", re.compile(r"(?m)^\s*-?\s*freed:")),
         "missed": ("briefs.md", re.compile(r"(?m)^\s*-?\s*omitted:")),
         "repeat": ("dispatch.md", re.compile(r"(?m)^\s*state:\s*(ECHO|SUPERSEDED)\s*$")),
         "ruling": ("local-storage.md", re.compile(r"(?m)^\s*-?\s*(ruling|rule|owner-words|words):"))}
TEMPLATE = re.compile(r":\s*\[|\[YYYY|\|\s*ECHO\s*\|")


def entries(text):
    """Blocks cut at blank lines and code fences, the fence lines themselves dropped."""
    text = re.sub(r"(?m)^```[a-z]*\s*$", "\n", text)
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def stores(p4):
    p4 = Path(p4)
    found = sorted(p.parent for p in p4.glob("sessions/*/vlds/index.md")) + sorted(
        {p.parent for p in p4.glob("sessions/*/vlds/*.md")})
    for legacy in (p4 / "vlds", p4.parent / "vlds", p4.parent.parent / ".vlds"):
        if legacy.is_dir():
            found.append(legacy)
    return list(dict.fromkeys(found))


def lessons(p4):
    out, counts = [], {k: 0 for k in KINDS}
    for store in stores(p4):
        session = store.parent.name if store.name == "vlds" and store.parent.parent.name == "sessions" else store.name
        for kind, (fname, sel) in KINDS.items():
            f = store / fname
            if not f.exists():
                continue
            for e in entries(f.read_text(encoding="utf-8", errors="replace")):
                if sel.search(e) and not TEMPLATE.search(e):
                    counts[kind] += 1
                    if kind != "ruling":
                        out.append({"kind": kind, "session": session, "file": fname, "text": e[:1500]})
    return {"stores": len(stores(p4)), "counts": counts, "lessons": out}


def live_rules(p4):
    """ezexe's LIVE rulings, newest first, each text once: every entry of local-storage.md whose status is LIVE, read
    for its `ruling:`, or else its `owner-words:`, whatever field scopes it."""
    seen, out = set(), []
    for store in stores(p4):
        f = store / "local-storage.md"
        if not f.exists():
            continue
        for e in entries(f.read_text(encoding="utf-8", errors="replace")):
            if TEMPLATE.search(e) or not re.search(r"(?m)^\s*status:\s*LIVE\b", e):
                continue
            words = re.search(r'(?m)^\s*owner-words:\s*"?(.*?)"?\s*$', e)
            ruling = re.search(r"(?m)^\s*-?\s*ruling:\s*(.*)$", e)
            when = re.search(r"(?m)^\s*time:\s*(.*)$", e)
            text = (ruling.group(1) if ruling else words.group(1) if words else "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append({"time": when.group(1).strip() if when else "", "ruling": text,
                            "words": words.group(1).strip() if words else ""})
    return sorted(out, key=lambda r: r["time"], reverse=True)


def labels(p4):
    """How whole an old tree's training labels are, since the operator's pool, the barrier's verdicts and the
    completed dispatch rows were what its models learned from. Per p4 tree: the sessions with a dispatch record, those
    whose operator ran, which left a recall-pool.md, and the dispatch rows completed, with a state and an addressed
    line, against those left open."""
    p4 = Path(p4)
    out = {"sessions": 0, "operator_ran": 0, "rows": 0, "completed": 0, "open": 0, "judged": 0}
    for d in sorted(p4.glob("sessions/*/vlds")):
        f = d / "dispatch.md"
        if not f.exists():
            continue
        out["sessions"] += 1
        out["operator_ran"] += (d / "recall-pool.md").exists()
        for e in entries(f.read_text(encoding="utf-8", errors="replace")):
            if not re.search(r"(?m)^-\s*fingerprint:", e) or TEMPLATE.search(e):
                continue
            out["rows"] += 1
            state = re.search(r"(?m)^\s*state:\s*(FRESH|ECHO|SUPERSEDED)\b", e)
            done = state and re.search(r"(?m)^\s*addressed:\s*\S", e)
            out["completed" if done else "open"] += 1
            out["judged"] += bool(state and state.group(1) != "FRESH") or bool(re.search(r"(?m)^\s*match:\s*\S", e))
    out["launch_rate"] = round(out["operator_ran"] / out["sessions"], 4) if out["sessions"] else None
    out["completion_rate"] = round(out["completed"] / out["rows"], 4) if out["rows"] else None
    # what the models learned from those labels: the baseline a rework must not drop below
    for name, keys in (("pick-model.json", ("trained", "pools", "heldout")), ("dispatch-model.json", ("trained", "rows"))):
        f = p4 / "models" / name
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[name.split(".")[0]] = {k: (len(d[k]) if isinstance(d.get(k), (list, dict)) and k != "heldout" else d.get(k))
                                   for k in keys}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--p4", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    got = lessons(args.p4)
    got["live_rules"] = live_rules(args.p4)
    got["labels"] = labels(args.p4)
    if args.out:
        Path(args.out).write_text(json.dumps(got, indent=1), encoding="utf-8")
    lb = got["labels"]
    print(f"{got['stores']} stores; " + ", ".join(f"{k} {v}" for k, v in got["counts"].items())
          + f"; live rules {len(got['live_rules'])}; operator ran in {lb['operator_ran']} of {lb['sessions']} sessions; "
          f"dispatch rows completed {lb['completed']} of {lb['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
