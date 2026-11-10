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
--push` on a machine does the same merge with the owner's credentials.

Two machines write the same files, so a plain merge conflicts. Each conflicted file is settled by its kind:
  the store's entries (store/**/*.md)   entry by entry, field by field, against the common ancestor: an entry only
                    one machine has is kept, a field only one machine changed takes its value, and when both changed
                    a `status:` the one that is no longer LIVE wins, so a merge never brings back what the owner
                    freed (measured: a union of lines kept both status lines and the rule read LIVE again)
  other text (*.md), tables (*.tsv, *.jsonl), .gitignore   both sides' lines (git merge-file --union); a
                    table's repeated rows and an index's repeated link lines (memory/MEMORY.md) are dropped
  settings (*.json)  key by key against the common ancestor; a list is both sides' items, so p4.json's
                    recall.deps.roots holds every machine's paths (a root that is not on a machine is skipped there)
  a trained model (models/ranker*, *.pt, *.phid) and its record (models/eval.tsv)   one side whole, the one whose
                    last training round is the later: two machines' weights are never mixed
  anything else     the side that changed it last
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
MODEL_UNIT = ("models/eval.tsv",)
MODEL_PREFIX = ("models/ranker",)
MODEL_EXT = (".pt", ".phid")
INDEX_LINE = re.compile(rb"^- \[[^\]]+\]\([^)]+\)")        # `- [Title](file.md) ...`, as memory/MEMORY.md lists
NAME, EMAIL = "p4-sync", "p4-sync@users.noreply.github.com"


def git(*args, check=True, cwd=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def show(spec):
    """The bytes of an index stage or a ref's file (`:2:path`, `ref:path`), or None when it is not there."""
    r = subprocess.run(["git", "show", spec], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def is_model(path):
    return path in MODEL_UNIT or path.startswith(MODEL_PREFIX) or path.endswith(MODEL_EXT)


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


def merge_json(base, ours, theirs):
    if isinstance(ours, dict) and isinstance(theirs, dict):
        b = base if isinstance(base, dict) else {}
        out = {}
        for k in list(ours) + [k for k in theirs if k not in ours]:
            if k in ours and k in theirs:
                out[k] = merge_json(b.get(k), ours[k], theirs[k])
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
    return theirs if base == ours else ours                 # both changed it: ours (main's, in the workflow)


def settle(path, ref, model_side):
    """The merged bytes of one conflicted path and the rule that gave them."""
    base, ours, theirs = show(f":1:{path}"), show(f":2:{path}"), show(f":3:{path}")
    if ours is None or theirs is None:
        return (ours if ours is not None else theirs), "kept (the other side deleted it)"
    if is_model(path):
        return (theirs if model_side == "theirs" else ours), f"model: the {'incoming' if model_side == 'theirs' else 'current'} side, whole"
    low = path.lower()
    if low.startswith("store/") and low.endswith(".md"):
        got = merge_entries(base, ours, theirs)
        if got is not None:
            return got, "entries: field by field"
    if low.endswith(".json"):
        try:
            got = merge_json(json.loads(base) if base else None, json.loads(ours), json.loads(theirs))
            return (json.dumps(got, indent=1, ensure_ascii=False) + "\n").encode("utf-8"), "settings: key by key"
        except ValueError:
            pass
    if low.endswith(TEXT_EXT) or os.path.basename(low) in (".gitignore", ".gitattributes") or b"\0" not in (ours + theirs)[:8192]:
        return union(base, ours, theirs, low.endswith((".tsv", ".jsonl"))), "both sides' lines"
    t_ours = git("log", "-1", "--format=%ct", "HEAD", "--", path, check=False).stdout.strip() or "0"
    t_theirs = git("log", "-1", "--format=%ct", ref, "--", path, check=False).stdout.strip() or "0"
    side = "theirs" if int(t_theirs) > int(t_ours) else "ours"
    return (theirs if side == "theirs" else ours), f"binary: the {'incoming' if side == 'theirs' else 'current'} side (changed last)"


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
    model_side = "theirs" if last_round(show(f"{ref}:models/eval.tsv")) > last_round(show("HEAD:models/eval.tsv")) else "ours"
    log = []
    for p in paths:
        data, rule = settle(p, ref, model_side)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        git("add", "--", p)
        log.append(f"  {p}: {rule}")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0 and not os.path.exists(
            os.path.join(git("rev-parse", "--git-dir").stdout.strip(), "MERGE_HEAD")):
        return [f"{ref}: nothing to merge"]
    git("-c", f"user.name={NAME}", "-c", f"user.email={EMAIL}", "commit", "-q", "--no-verify", "-m",
        f"p4 sync: {ref.removeprefix('origin/')} into {into}" + (f" ({len(paths)} files settled)" if paths else ""))
    return [f"{ref}: merged into {into}" + (f", {len(paths)} conflicts settled" if paths else "")] + log


def store_branches(main):
    """The remote's branches that hold a store (a store/ directory), the main one left out."""
    out = []
    for b in git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").stdout.split():
        name = b.removeprefix("origin/")
        if name in ("HEAD", main, "origin") or not b.startswith("origin/"):
            continue
        if "store" in git("ls-tree", "--name-only", b, check=False).stdout.split():
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


def cmd_catch_up():
    """Move the current branch up to origin's, when origin's is ahead and nothing here is in its way."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git("fetch", "-q", "origin")
    r = git("merge", "-q", "--ff-only", f"origin/{branch}", check=False)
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
    for ref in (f"origin/{branch}", f"origin/{main}"):
        if git("rev-parse", "-q", "--verify", ref, check=False).returncode == 0:
            print("\n".join(merge(ref, branch)))
    if push:
        git("push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        print(f"p4 sync: pushed {branch}")
    return 0


WORKFLOW = """# seeded by p4-recall; remove this line to keep your own edits (a copy with it is replaced when the plugin's changes)
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
    differ from the plugin's (an owner who removed the line keeps theirs). Returns the paths written."""
    here = os.path.abspath(__file__)
    with open(here, encoding="utf-8") as f:
        script = f.read()
    wrote = []
    for rel, text in ((os.path.join(".github", "workflows", "p4-sync.yml"), WORKFLOW.replace("{main}", main)),
                      (os.path.join(".github", "p4_sync.py"), script)):
        path = os.path.join(p4, rel)
        try:
            with open(path, encoding="utf-8") as f:
                old = f.read()
        except OSError:
            old = None
        if old == text or (old is not None and "# seeded by p4-recall" not in "\n".join(old.splitlines()[:2])):
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
