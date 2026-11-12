#!/usr/bin/env python3
# seeded by p4-recall; remove this line to keep your own edits (a copy with it is replaced when the plugin's changes)
"""sync.py: keep every machine's branch of a p4 store in step, `p4.py sync` and the store's own GitHub workflow.

A store is pushed one branch per machine (win, mac, ...). This merges them: every machine branch into `main`, then
each machine branch fast-forwarded to `main`, so after a push to any branch all of them hold the same commit. The
layout hook seeds this file as `.github/p4_sync.py` beside `.github/workflows/p4-sync.yml`, which runs `all --push`
on every push; a machine catches up with `p4.py sync` (fetch, merge `origin/main` here, the same way).

    sync.py all [--main main] [--push]     # the workflow: merge every store branch into main, fast-forward them
    sync.py pull [--main main] [--push] [--snapshot]   # a machine: merge origin/<main> into the current branch;
                                           # --snapshot first commits the tracked files the hooks have changed
    sync.py catch-up                       # a machine: move the current branch up to its remote, when that is ahead

`all` works in a temporary worktree, so it never moves the checkout it is run from. When the remote moved while it
merged (the workflow and a machine can run at once), it fetches and merges once more. Measured 2026-11-10 on a
private three-branch store: the first push of a branch carrying the seeded workflow ran it, and its own token's
push of main, with the workflow file in it, went through. GitHub documents that a workflow's token cannot change
files under .github/workflows; should a repository refuse that push, the error says so and `p4.py sync --all
--push` on a machine does the same merge with ezexe's credentials.

Two machines write the same files, so a plain merge conflicts. Each conflicted file is settled by its kind:
  the store's entries (store/**/*.md)   entry by entry, field by field, against the common ancestor: an entry only
                    one machine has is kept, a field only one machine changed takes its value, and when both changed
                    a `status:` the one that is no longer LIVE wins, so a merge never brings back what ezexe
                    freed (measured: a union of lines kept both status lines and the rule read LIVE again)
  other text (*.md), tables (*.tsv, *.jsonl), .gitignore   both sides' lines (git merge-file --union); a
                    table's repeated rows and an index's repeated link lines (memory/MEMORY.md) are dropped
  settings (*.json)  key by key against the common ancestor; a list is both sides' items, so p4.json's
                    recall.deps.roots holds every machine's paths (a root that is not on a machine is skipped there)
  a trained model (models/ranker*, *.pt, *.phid)   one side whole, the one whose last training round is the
                    later: two machines' weights are never mixed
  the training log (models/eval.tsv)   both machines' rounds, in time order. It was once taken whole with the
                    model, and each sync swapped one machine's log for the other's (measured 2026-11-10: a
                    64-round log replaced by a 39-round one)
  anything else     the side that changed it last, whole: a script, a workflow or anything under .github/ is never
                    stitched from two versions
Settings and store entries are merged this way whenever both machines changed the file, conflict or not: git merges
two machines' p4.json line by line without complaint and leaves a key twice (measured 2026-11-10).
A file one side deleted and the other changed is kept. Stdlib and git only: the workflow needs no install.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TEXT_EXT = (".md", ".tsv", ".jsonl", ".txt", ".log")
MODEL_UNIT = ()
LOG = "models/eval.tsv"            # the training log: every machine's rounds are history, none is replaced
MODEL_PREFIX = ("models/ranker",)
MODEL_EXT = (".pt", ".phid")
INDEX_LINE = re.compile(rb"^- \[[^\]]+\]\([^)]+\)")        # `- [Title](file.md) ...`, as memory/MEMORY.md lists
NAME, EMAIL = "p4-sync", "p4-sync@users.noreply.github.com"
SEED = 13    # the seeded files' version: a store's copy from a newer plugin is never replaced by an older plugin's


def git(*args, check=True, cwd=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def show(spec):
    """The bytes of an index stage or a ref's file (`:2:path`, `ref:path`), or None when it is not there."""
    r = subprocess.run(["git", "show", spec], capture_output=True)
    return r.stdout if r.returncode == 0 else None


# A store moved into each plugin's own directory (p4conf.LAYOUT): recall's files are under phi/, where p4-phi keeps
# them since recall is part of it, and were under recall/ before; the memory is under temportal/. A branch from a
# machine not yet updated may still have them under recall/ or at the top, so every rule here reads a path by its
# name inside the plugin's directory, and all three layouts merge alike.
PLUGIN_DIRS = ("phi/", "recall/", "temportal/")


def logical(path):
    """`phi/store/rules.md` or `recall/store/rules.md` -> `store/rules.md`, `temportal/memory/MEMORY.md` ->
    `memory/MEMORY.md`."""
    for d in PLUGIN_DIRS:
        if path.lower().startswith(d):
            return path[len(d):]
    return path


def is_model(path):
    path = logical(path)
    return path in MODEL_UNIT or path.startswith(MODEL_PREFIX) or path.endswith(MODEL_EXT)


def eval_log(spec_prefix):
    """The training log at a commit, in either layout."""
    for d in ("phi/", "recall/", ""):
        got = show(f"{spec_prefix}:{d}{LOG}")
        if got is not None:
            return got
    return None


def last_round(data):
    """The time of the last row of an eval.tsv (its second column), '' when there is none."""
    rows = [l for l in (data or b"").decode("utf-8", "replace").splitlines()[1:] if l.strip()]
    return rows[-1].split("\t")[1] if rows and "\t" in rows[-1] else ""


def union(base, ours, theirs, table):
    with tempfile.TemporaryDirectory() as t:
        names = []
        for n, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = os.path.join(t, n)
            with open(p, "wb") as f:
                f.write(data or b"")
            names.append(p)
        out = subprocess.run(["git", "merge-file", "-p", "--union", *names], capture_output=True).stdout
    seen, keep = set(), []
    for line in out.splitlines(keepends=True):
        key = line.rstrip(b"\r\n")
        if key and key in seen and (table or INDEX_LINE.match(key)):     # a table's row, or an index's link line
            continue
        seen.add(key)
        keep.append(line)
    return b"".join(keep)


ENTRY_HEAD = re.compile(r"^- \S")
FIELD = re.compile(r"^\s+([A-Za-z][\w-]*):(\s|$)")


def parse_entries(text):
    """(the lines before the first entry, [(key, head line, [(field name, [its lines])])]) of a store file. An entry
    starts at a `- ` in column 0; its key is that line and its `time:` value (a correction's key can repeat)."""
    header, entries, cur = [], [], None
    for line in text.splitlines():
        if ENTRY_HEAD.match(line):
            cur = [line, []]
            entries.append(cur)
        elif cur is None:
            header.append(line)
        elif not line.strip():
            continue
        else:
            m = FIELD.match(line)
            if m or not cur[1]:
                cur[1].append((m.group(1) if m else "", [line]))
            else:
                cur[1][-1][1].append(line)                # a field's continuation line
    out = []
    for head, fields in entries:
        time = next((" ".join(l).split(":", 1)[1].strip() for n, l in fields if n == "time"), "")
        out.append((head + "\0" + time, head, fields))
    return header, out


def three_way(base, ours, theirs, status=False):
    if ours == theirs or base == theirs:
        return ours
    if base == ours:
        return theirs
    if status and ours and theirs:                         # both changed it: what is no longer LIVE stays that way
        live = lambda v: " ".join(v).split(":", 1)[1].strip().upper().startswith("LIVE")
        return theirs if live(ours) and not live(theirs) else ours
    return ours if ours is not None else theirs


def merge_entries(base, ours, theirs):
    """The store file both sides' entries make, or None when it holds no entries (the caller falls back to lines)."""
    (hb, eb), (ho, eo), (ht, et) = (parse_entries((x or b"").decode("utf-8", "replace")) for x in (base, ours, theirs))
    if not eo and not et:
        return None
    def grouped(fields):                                   # {name: [each occurrence's lines]}: a name can repeat
        g = {}                                             # (vocabulary.md keeps one `because:` line a sighting)
        for n, v in fields:
            g.setdefault(n, []).append(v)
        return g
    b, o, t = ({k: (h, grouped(f)) for k, h, f in e} for e in (eb, eo, et))
    order = [k for k, _, _ in eo] + [k for k, _, _ in et if k not in o]
    lines = list(ho if ho else ht)
    while lines and not lines[-1].strip():
        lines.pop()
    for k in order:
        if k in o and k in t:
            fo, ft, fb = o[k][1], t[k][1], b.get(k, ("", {}))[1]
            names = list(fo) + [n for n in ft if n not in fo]
            fields = []
            for n in names:
                vo, vt, vb = fo.get(n, []), ft.get(n, []), fb.get(n, [])
                if max(len(vo), len(vt), len(vb)) > 1:     # a repeated field is a list: both sides' occurrences
                    fields += [(n, v) for v in vo + [x for x in vt if x not in vo]]
                else:
                    fields.append((n, three_way(vb[0] if vb else None, vo[0] if vo else None, vt[0] if vt else None,
                                                status=(n == "status"))))
            head = o[k][0]
        else:
            side = o if k in o else t
            if k in b and b[k][1] == side[k][1]:           # the other machine removed it and this one left it alone
                continue
            head, fields = side[k][0], [(n, v) for n, vs in side[k][1].items() for v in vs]
        lines += ["", head] + [l for _n, v in fields if v for l in v]
    return ("\n".join(lines) + "\n").encode("utf-8")


def merge_json(base, ours, theirs, dflt=None):
    """`dflt` is the plugin's default at this place (settings only): when a key is new on both sides, a value that
    is just the default a settings load wrote loses to one a person set (measured 2026-11-10: a machine's freshly
    written "off" overrode the other machine's "shadow")."""
    if isinstance(ours, dict) and isinstance(theirs, dict):
        b = base if isinstance(base, dict) else {}
        d = dflt if isinstance(dflt, dict) else {}
        out = {}
        for k in list(ours) + [k for k in theirs if k not in ours]:
            if k in ours and k in theirs:
                out[k] = merge_json(b.get(k), ours[k], theirs[k], d.get(k))
            elif k in ours:
                if not (k in b and b[k] == ours[k]):        # they removed a key we left alone: it goes
                    out[k] = ours[k]
            elif not (k in b and b[k] == theirs[k]):
                out[k] = theirs[k]
        return out
    if isinstance(ours, list) and isinstance(theirs, list):
        return ours + [x for x in theirs if x not in ours]
    if ours == theirs or base == theirs:
        return ours
    if base == ours:
        return theirs
    if base is None and dflt is not None and ours == dflt and theirs != dflt:
        return theirs                                       # ours is only the written default: theirs was set
    return ours                                             # both changed it: ours (main's, in the workflow)


def merge_log(base, ours, theirs):
    """A training log both machines appended to: every round of either, once, ordered by its time (the second
    column), under the one header."""
    lines = union(base, ours, theirs, True).decode("utf-8", "replace").splitlines()
    if not lines:
        return b""
    head, rows = lines[0], [l for l in lines[1:] if l.strip()]
    rows.sort(key=lambda l: (l.split(chr(9)) + [""])[1])
    return (chr(10).join([head] + rows) + chr(10)).encode("utf-8")


def seeded_defaults():
    """The plugin's settings defaults as the layout hook seeded them beside this script (.github/p4_defaults.json),
    or None: the workflow has no plugin to ask."""
    try:
        with open(os.path.join(".github", "p4_defaults.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


PHI_JSONL = re.compile(r"^phi/(?:sessions/[^/]+/(?:turns|notes|reports)|reports)\.jsonl$")
PHI_PLAN = re.compile(r"^phi/sessions/[^/]+/plan\.json$")
PHI_ANCHOR = re.compile(r"^phi/sessions/[^/]+/anchor\.json$")
STATUS_ORDER = {"pending": 0, "in_progress": 1, "completed": 2}


def merge_jsonl(base, ours, theirs):
    """Both sides' rows of a session-tree log, each once, in time order."""
    rows, seen = [], set()
    for data in (base, ours, theirs):
        for line in (data or b"").decode("utf-8", "replace").splitlines():
            if not line.strip() or line in seen:
                continue
            seen.add(line)
            try:
                when = str(json.loads(line).get("time") or "")
            except (ValueError, AttributeError):
                when = ""
            rows.append((when, len(rows), line))
    return "".join(l + "\n" for _, _, l in sorted(rows)).encode("utf-8")


def _union_tasks(into, extra):
    """Tasks of both sides by id, the later status winning."""
    have = {t.get("id"): t for t in into if t.get("id")}
    for t in extra or []:
        mine = have.get(t.get("id"))
        if mine is None:
            into.append(dict(t))
            have[t.get("id")] = into[-1]
        elif t.get("status") not in (None, "open") and mine.get("status") in (None, "open"):
            mine["status"] = t["status"]
    return into


def merge_plan(ours, theirs, base=None):
    """A session's plan from two machines. The side of the higher version gives the order and the rest. A step is
    matched by its words, else by its address while the other side left that step's words as the base had them;
    the later status wins and both sides' tasks are kept by id. A step only the lower side added since the base is
    kept after the others, never lost (MP1)."""
    a, b = json.loads(ours), json.loads(theirs)
    hi, lo = (a, b) if int(a.get("version") or 0) >= int(b.get("version") or 0) else (b, a)
    try:
        was = json.loads(base) if base else {}
    except ValueError:
        was = {}
    base_text = {x.get("addr"): x.get("content", "") for x in was.get("steps") or []}
    base_words = set(base_text.values())
    steps = hi.setdefault("steps", [])
    by_words = {x.get("content", ""): x for x in steps}
    by_addr = {x.get("addr"): x for x in steps}
    for o in lo.get("steps") or []:
        words = o.get("content", "")
        st = by_words.get(words)
        if st is None and base_text.get(o.get("addr")) == words:
            st = by_addr.get(o.get("addr"))     # the higher side reworded this step; the lower left it as it was
        if st is None:
            if words in base_words or not words:
                continue                          # the higher side removed it
            st = dict(o)
            if st.get("addr") in by_addr:         # its address is taken: the next free one under the same root
                root = st["addr"].rsplit(".", 1)[0] if "." in str(st["addr"]) else ""
                n = len(steps) + 1
                while (f"{root}.{n}" if root else str(n)) in by_addr:
                    n += 1
                st["addr"] = f"{root}.{n}" if root else str(n)
            st.pop("tasks", None)
            steps.append(st)
            by_words[words], by_addr[st["addr"]] = st, st
        if STATUS_ORDER.get(o.get("status"), 0) > STATUS_ORDER.get(st.get("status"), 0):
            st["status"] = o["status"]
        if o.get("tasks"):
            st["tasks"] = _union_tasks(st.setdefault("tasks", []), o["tasks"])
    if lo.get("loose"):
        hi["loose"] = _union_tasks(hi.setdefault("loose", []), lo["loose"])
    return (json.dumps(hi, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def merge_anchor(ours, theirs):
    """An anchor is made again at the next Stop: the side of the higher version, whole."""
    a, b = json.loads(ours), json.loads(theirs)
    return ours if int(a.get("version") or 0) >= int(b.get("version") or 0) else theirs


def structured(path):
    """A file whose lines git must never merge by itself: settings (a clean textual merge of two machines' p4.json
    left `recall` holding its keys twice, measured 2026-11-10) and the store's entries."""
    low = logical(path).lower()
    return low.endswith(".json") or (low.startswith("store/") and low.endswith(".md")) or bool(PHI_JSONL.match(path))


def settle(path, ref, model_side, sides=None):
    """The merged bytes of one path both sides changed and the rule that gave them. `sides` is (base, ours, theirs)
    when git saw no conflict; a conflicted path's are read from the index."""
    base, ours, theirs = sides or (show(f":1:{path}"), show(f":2:{path}"), show(f":3:{path}"))
    if ours is None or theirs is None:
        return (ours if ours is not None else theirs), "kept (the other side deleted it)"
    if PHI_JSONL.match(path):
        return merge_jsonl(base, ours, theirs), "session tree: both sides' rows, by time"
    try:
        if PHI_PLAN.match(path):
            return merge_plan(ours, theirs, base), "plan: step by step, the later status, both sides' steps"
        if PHI_ANCHOR.match(path):
            return merge_anchor(ours, theirs), "anchor: the higher version, whole"
    except ValueError:
        pass
    if logical(path) == LOG:
        return merge_log(base, ours, theirs), "training log: both sides' rounds, by time"
    if is_model(path):
        return (theirs if model_side == "theirs" else ours), f"model: the {'incoming' if model_side == 'theirs' else 'current'} side, whole"
    low = logical(path).lower()
    if low.startswith("store/") and low.endswith(".md"):
        got = merge_entries(base, ours, theirs)
        if got is not None:
            return got, "entries: field by field"
    if low.endswith(".json"):
        try:
            got = merge_json(json.loads(base) if base else None, json.loads(ours), json.loads(theirs),
                             seeded_defaults() if low == "p4.json" else None)
            return (json.dumps(got, indent=1, ensure_ascii=False) + "\n").encode("utf-8"), "settings: key by key"
        except ValueError:
            pass
    name = os.path.basename(low)
    prose = low.endswith(TEXT_EXT) or name in (".gitignore", ".gitattributes") or "." not in name.lstrip(".")
    if prose and not low.startswith(".github/") and b"\0" not in (ours + theirs)[:8192]:
        return union(base, ours, theirs, low.endswith((".tsv", ".jsonl"))), "both sides' lines"
    # code and configuration (a script, a workflow, anything under .github/) is never stitched from two versions
    t_ours = git("log", "-1", "--format=%ct", "HEAD", "--", path, check=False).stdout.strip() or "0"
    t_theirs = git("log", "-1", "--format=%ct", ref, "--", path, check=False).stdout.strip() or "0"
    side = "theirs" if int(t_theirs) > int(t_ours) else "ours"
    return (theirs if side == "theirs" else ours), f"whole: the {'incoming' if side == 'theirs' else 'current'} side (changed last)"


def merge(ref, into):
    """Merge `ref` into the checked-out branch, settling every conflict; returns what was done, in lines."""
    if git("merge-base", "--is-ancestor", ref, "HEAD", check=False).returncode == 0:
        return [f"{ref}: already in {into}"]
    if git("merge-base", "--is-ancestor", "HEAD", ref, check=False).returncode == 0:
        git("merge", "-q", "--ff-only", ref)           # nothing of ours it lacks: move up, no merge commit
        return [f"{ref}: {into} moved up to it"]
    r = git("-c", f"user.name={NAME}", "-c", f"user.email={EMAIL}", "merge", "--no-ff", "--no-commit",
            "--allow-unrelated-histories", ref, check=False)
    paths = [p for p in git("diff", "--name-only", "--diff-filter=U", "-z").stdout.split("\0") if p]
    if r.returncode != 0 and not paths:
        raise RuntimeError(f"merge of {ref}: {(r.stderr or r.stdout).strip()[:300]}")
    model_side = "theirs" if last_round(eval_log(ref)) > last_round(eval_log("HEAD")) else "ours"
    log = []
    for p in paths:
        data, rule = settle(p, ref, model_side)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        git("add", "--", p)
        log.append(f"  {p}: {rule}")
    # a structured file both sides changed is merged by its structure even where git merged its lines cleanly
    mb = git("merge-base", "HEAD", ref, check=False).stdout.strip()
    if mb:
        changed = lambda tip: {p for p in git("diff", "--name-only", "-z", mb, tip).stdout.split("\0") if p}
        for p in sorted((changed("HEAD") & changed(ref)) - set(paths)):
            if not structured(p) or is_model(p):
                continue
            sides = (show(f"{mb}:{p}"), show(f"HEAD:{p}"), show(f"{ref}:{p}"))
            if sides[1] is None or sides[2] is None:
                continue
            data, rule = settle(p, ref, model_side, sides)
            try:
                with open(p, "rb") as f:
                    same = f.read().replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n")
            except OSError:
                same = False
            if not same:
                with open(p, "wb") as f:
                    f.write(data)
                git("add", "--", p)
                log.append(f"  {p}: {rule} (git had merged its lines)")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0 and not os.path.exists(
            os.path.join(git("rev-parse", "--git-dir").stdout.strip(), "MERGE_HEAD")):
        return [f"{ref}: nothing to merge"]
    git("-c", f"user.name={NAME}", "-c", f"user.email={EMAIL}", "commit", "-q", "--no-verify", "-m",
        f"p4 sync: {ref.removeprefix('origin/')} into {into}" + (f" ({len(paths)} files settled)" if paths else ""))
    return [f"{ref}: merged into {into}" + (f", {len(paths)} conflicts settled" if paths else "")] + log


def store_branches(main):
    """The remote's branches that hold a store (a recall/ directory, or store/ in the flat layout), the main one left
    out."""
    out = []
    for b in git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").stdout.split():
        name = b.removeprefix("origin/")
        if name in ("HEAD", main, "origin") or not b.startswith("origin/"):
            continue
        top = git("ls-tree", "--name-only", b, check=False).stdout.split()
        if "phi" in top or "recall" in top or "store" in top:
            out.append(name)
    return sorted(out)


def cmd_all(main, push):
    git("fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    branches = store_branches(main)
    if not branches:
        print("p4 sync: no store branch on the remote; nothing to do")
        return 0
    have_main = git("rev-parse", "-q", "--verify", f"origin/{main}", check=False).returncode == 0
    home, tmp = os.getcwd(), tempfile.mkdtemp(prefix="p4-sync-")
    wt = os.path.join(tmp, "wt")
    git("worktree", "add", "-q", "--detach", wt, f"origin/{main if have_main else branches[0]}")
    try:
        os.chdir(wt)
        try:
            return _all_in_worktree(main, branches, push)
        except RuntimeError as e:
            if "rejected" not in str(e) and "fetch first" not in str(e):
                raise
            # the remote moved while this merged (the workflow, or another machine): take it in and merge once more
            print("p4 sync: the remote moved meanwhile; merging once more")
            git("fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
            git("checkout", "-q", "--detach", f"origin/{main}")
            return _all_in_worktree(main, store_branches(main), push)
    finally:
        os.chdir(home)
        git("worktree", "remove", "--force", wt, check=False)
        git("worktree", "prune", check=False)
        shutil.rmtree(tmp, ignore_errors=True)       # the worktree's parent: nothing of a run stays in the temp folder


def _all_in_worktree(main, branches, push):
    for b in branches:
        print("\n".join(merge(f"origin/{b}", main)))
    if not push:
        print(f"p4 sync: merged to {git('rev-parse', '--short', 'HEAD').stdout.strip()}, nothing pushed (--push)")
        return 0
    r = git("push", "-q", "origin", f"HEAD:refs/heads/{main}", check=False)
    if r.returncode != 0:
        why = (r.stderr or r.stdout).strip()
        if "workflow" in why:
            why += ("\np4 sync: if this push was refused for changing a workflow file with the workflow's own token, "
                    "run `p4.py sync --all --push` once on a machine.")
        raise RuntimeError(f"push of {main}: {why[:700]}")
    late = []
    for b in branches:                       # each machine's branch moves up to main; never forced
        r = git("push", "-q", "origin", f"HEAD:refs/heads/{b}", check=False)
        if r.returncode != 0:
            late.append(b)
            print(f"{b}: moved while this ran; its next push brings it in")
    print(f"p4 sync: {main} and {len(branches) - len(late)} of {len(branches)} branches at {git('rev-parse', '--short', 'HEAD').stdout.strip()}")
    return 0


def snapshot(branch):
    """Commit the tracked files that changed (a live store's hooks rewrite its tables all day); True when it did."""
    if not git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return False
    git("-c", f"user.name={NAME}", "-c", f"user.email={EMAIL}", "commit", "-q", "--no-verify", "-a", "-m",
        f"p4 sync: {branch}'s work so far")
    return True


def entry_changes(old, new):
    """Every store entry whose fields a move from `old` to `new` changed, a line each, its `status:` first: a clean
    merge is no proof that an entry still reads as it should (#21: a line-union kept both `status:` lines of a rule
    and it read LIVE again after ezexe had freed it)."""
    if not old or not new or old == new:
        return []
    out = []

    def val(v):
        return " ".join(" ".join(v).split(":", 1)[1:]).strip()[:60] if v else "(none)"

    for path in git("diff", "--name-only", "-z", old, new, check=False).stdout.split("\0"):
        low = logical(path).lower()
        if not (low.startswith("store/") and low.endswith(".md")):
            continue
        before, after = ({k: (h, f) for k, h, f in
                          parse_entries((show(f"{c}:{path}") or b"").decode("utf-8", "replace"))[1]} for c in (old, new))
        for k, (head, fields) in after.items():
            if k not in before:
                out.append(f"  {path}: new entry {head[:80]}")
                continue
            a, b = {}, {}
            for d, fs in ((a, before[k][1]), (b, fields)):
                for n, v in fs:
                    d.setdefault(n, []).append(v)
            changed = sorted((n for n in set(a) | set(b) if a.get(n) != b.get(n)), key=lambda n: (n != "status", n))
            for n in changed:
                va = [val(v) for v in a.get(n) or [None]]
                vb = [val(v) for v in b.get(n) or [None]]
                out.append(f"  {path}: {head[:60]}: {n or 'text'}: {' | '.join(va)} -> {' | '.join(vb)}")
        for k, (head, _f) in before.items():
            if k not in after:
                out.append(f"  {path}: entry gone: {head[:80]}")
    return out


def report_changes(old):
    """Print the entries the move from `old` to HEAD changed, so the session checks them instead of trusting a
    clean merge."""
    lines = entry_changes(old, git("rev-parse", "HEAD", check=False).stdout.strip())
    if lines:
        print(f"p4 sync: {len(lines)} store entr{'y' if len(lines) == 1 else 'ies'} changed in this sync; check that "
              f"each reads as it should:\n" + "\n".join(lines[:200]))


def cmd_catch_up():
    """Move the current branch up to origin's, when origin's is ahead and nothing here is in its way."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git("fetch", "-q", "origin")
    before = git("rev-parse", "HEAD", check=False).stdout.strip()
    r = git("merge", "-q", "--ff-only", f"origin/{branch}", check=False)
    if r.returncode == 0:
        report_changes(before)
    print(f"p4 sync: {branch} is at origin/{branch}" if r.returncode == 0 else
          f"p4 sync: {branch} could not move up to origin/{branch} ({(r.stderr or r.stdout).strip()[:160]}); run `p4.py sync`")
    return 0 if r.returncode == 0 else 1


def cmd_pull(main, push, snap=False):
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if snap and snapshot(branch):
        print(f"p4 sync: committed {branch}'s changed files first")
    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        print("p4 sync: this checkout has uncommitted changes to tracked files; commit them first", file=sys.stderr)
        return 1
    git("fetch", "-q", "origin")
    before = git("rev-parse", "HEAD", check=False).stdout.strip()
    for ref in (f"origin/{branch}", f"origin/{main}"):
        if git("rev-parse", "-q", "--verify", ref, check=False).returncode == 0:
            print("\n".join(merge(ref, branch)))
    report_changes(before)
    if push:
        git("push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        print(f"p4 sync: pushed {branch}")
    return 0


WORKFLOW = """# seeded by p4-recall; remove this line to keep your own edits (a copy with it is replaced when the plugin's changes)
# seed {seed}
# A push to any branch of this store merges every machine's branch into main and moves each branch up to it
# (.github/p4_sync.py says how a file two machines both changed is settled).
name: p4 sync
on:
  push:
    branches: ['**']
  workflow_dispatch:
permissions:
  contents: write
concurrency:
  group: p4-sync
  cancel-in-progress: false
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - name: Merge every store branch into {main}, fast-forward the branches
        run: python3 .github/p4_sync.py all --main {main} --push
"""


def seed(p4, main="main"):
    """Write the workflow and this script into the store's .github/ when they are absent, or carry the seed line and
    differ from the plugin's (ezexe, having removed the line, keeps that copy). A copy seeded by a newer plugin (a higher
    SEED, which another machine's sync brought in) is left alone. Returns the paths written."""
    here = os.path.abspath(__file__)
    with open(here, encoding="utf-8") as f:
        script = f.read()
    wrote = []

    def seed_of(text):
        m = re.search(r"(?m)^(?:SEED = |# seed )(\d+)", text)
        return int(m.group(1)) if m else 0
    try:
        import p4conf
        dflt = json.dumps({"_seed": SEED, **p4conf.DEFAULTS}, indent=1, ensure_ascii=False) + "\n"
        dpath = os.path.join(p4, ".github", "p4_defaults.json")
        try:
            with open(dpath, encoding="utf-8") as f:
                old_d = f.read()
        except OSError:
            old_d = None
        newer = False
        try:
            newer = old_d is not None and int(json.loads(old_d).get("_seed", 0)) > SEED
        except (ValueError, AttributeError, TypeError):
            pass
        if old_d != dflt and not newer:
            os.makedirs(os.path.dirname(dpath), exist_ok=True)
            with open(dpath, "w", encoding="utf-8", newline="\n") as f:
                f.write(dflt)
            wrote.append(".github/p4_defaults.json")
    except ImportError:
        pass
    for rel, text in ((os.path.join(".github", "workflows", "p4-sync.yml"),
                       WORKFLOW.replace("{main}", main).replace("{seed}", str(SEED))),
                      (os.path.join(".github", "p4_sync.py"), script)):
        path = os.path.join(p4, rel)
        try:
            with open(path, encoding="utf-8") as f:
                old = f.read()
        except OSError:
            old = None
        if old == text or (old is not None and "# seeded by p4-recall" not in "\n".join(old.splitlines()[:2])):
            continue
        if old is not None and seed_of(old) > SEED:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        wrote.append(rel.replace(os.sep, "/"))
    return wrote


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("all", "pull", "catch-up"))
    ap.add_argument("--main", default="main")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "catch-up":
            return cmd_catch_up()
        return cmd_all(a.main, a.push) if a.cmd == "all" else cmd_pull(a.main, a.push, a.snapshot)
    except RuntimeError as e:
        if os.path.exists(os.path.join(git("rev-parse", "--git-dir", check=False).stdout.strip() or ".git", "MERGE_HEAD")):
            git("merge", "--abort", check=False)
        print(f"p4 sync: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
