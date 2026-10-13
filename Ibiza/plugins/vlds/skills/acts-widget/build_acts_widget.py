#!/usr/bin/env python3
"""Keep a session's one acts page: every closing appends a round of acts, every pick is recorded into it.

Usage:
  build_acts_widget.py append ACTS.json (--page PAGE | --session ID [--root DIR]) [--now TIME]
  build_acts_widget.py pick (--page PAGE | --session ID [--root DIR]) (--acts ID,ID | --skipped)
                            [--round N] [--note ID=TEXT ...] [--now TIME]
  build_acts_widget.py show (--page PAGE | --session ID [--root DIR])
  build_acts_widget.py widget (--page PAGE | --session ID [--root DIR]) [--out FILE]
  build_acts_widget.py stored (--page PAGE | --session ID [--root DIR]) --store DIR
                              (--record FILE | --entry FILE:HEAD ...) [--round N] [--act ID]

ACTS.json is one closing:
  {"title": "...", "repo": "owner/name", "branch": "...",
   "acts": [{"id": "...", "title": "...", "summary": "...", "goal": "...",
             "files": ["..."], "constraints": ["..."], "done": "...", "recommended": true,
             "briefs": {"changes": "...", "scope": "..."}}]}

Every act needs id, title and goal; ids are unique within a round. --session alone puts the page at
<root>/.claude/scratchpad/acts-widget/<session>.html (root defaults to the working directory), so a session
recycles one page. `widget` prints that page as a chat widget's code, for show_widget, where its Send button posts
the assembled prompt as the next message. The page is its own state: the rounds live in a JSON block inside it, read back on every
append or pick, and the page is rewritten whole. It inlines assemble.js, so the prompt it shows is built by the
same function the test runs.
"""
import argparse
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIRED = ("id", "title", "goal")
STATE_RE = re.compile(r'<script type="application/json" id="acts-state">(.*?)</script>', re.S)


def validate(data):
    acts = data.get("acts")
    if not isinstance(acts, list) or not acts:
        raise ValueError("acts: a non-empty list is required")
    seen = set()
    for i, act in enumerate(acts):
        missing = [k for k in REQUIRED if not str(act.get(k, "")).strip()]
        if missing:
            raise ValueError(f"acts[{i}]: missing {', '.join(missing)}")
        if act["id"] in seen:
            raise ValueError(f"acts[{i}]: duplicate id {act['id']!r}")
        seen.add(act["id"])
        for key in ("files", "constraints"):
            if not isinstance(act.get(key, []), list):
                raise ValueError(f"acts[{i}].{key}: a list is required")
        briefs = act.get("briefs", {})
        if not isinstance(briefs, dict) or not all(isinstance(v, str) for v in briefs.values()):
            raise ValueError(f"acts[{i}].briefs: a {{label: text}} object is required")


def new_state(session=None):
    return {"session": session or "", "rounds": []}


def load_state(page_path):
    """The rounds a page already holds; a fresh state when the page does not exist yet."""
    if not os.path.exists(page_path):
        return None
    with open(page_path, encoding="utf-8") as f:
        m = STATE_RE.search(f.read())
    if not m:
        raise ValueError(f"{page_path}: no acts-state block — not an acts page, refusing to overwrite it")
    return json.loads(m.group(1))


def append_round(state, data, now=None):
    validate(data)
    open_round = state["rounds"][-1] if state["rounds"] else None
    if open_round and open_round.get("picked") is None:
        # a closing the owner never answered is superseded by the next one, not left pending beside it
        open_round["picked"], open_round["skipped"], open_round["superseded"] = [], True, True
    for key in ("title", "repo", "branch"):
        if data.get(key):
            state[key] = data[key]
    rnd = {"n": len(state["rounds"]) + 1, "at": now or "", "title": data.get("title", ""),
           "acts": data["acts"], "picked": None, "notes": {}}
    state["rounds"].append(rnd)
    return rnd


def record_pick(state, ids=None, round_n=None, notes=None, skipped=False, now=None):
    if not state["rounds"]:
        raise ValueError("no round to record a pick into: append a closing first")
    rnd = state["rounds"][-1] if round_n is None else next((r for r in state["rounds"] if r["n"] == round_n), None)
    if rnd is None:
        raise ValueError(f"no round {round_n}")
    known = [a["id"] for a in rnd["acts"]]
    ids = [] if skipped else list(ids or [])
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise ValueError(f"round {rnd['n']}: unknown act id(s) {', '.join(unknown)}; known: {', '.join(known)}")
    if not skipped and not ids:
        raise ValueError("a pick names at least one act, or is --skipped")
    rnd["picked"] = [i for i in known if i in ids]
    rnd["skipped"] = skipped
    rnd["notes"] = {k: v for k, v in (notes or {}).items() if k in rnd["picked"] and v.strip()}
    rnd["picked_at"] = now or ""
    return rnd


def parse_record(path):
    """[(store file, head line)] for every entry a turn record (the notebook file scripts/record.py applies) holds:
    a `## <file>` heading opens a file's blocks, and each `- key: …` line at column zero is an entry's head."""
    out, fname = [], None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("## "):
                fname = line[3:].strip()
            elif fname and line.startswith("- ") and ":" in line:
                out.append((fname, line.rstrip()))
    return out


def locate(store, fname, head):
    """(absolute path, store-relative path, line number) of an entry's head, looked up in its hot file first and
    then in the keyspace runs it is poured into (newest first), since a pour moves an entry and its line; None
    when it is found nowhere."""
    stem = os.path.splitext(fname)[0]
    runs = sorted(glob.glob(os.path.join(store, "idb", "runs", f"{stem}-*.md")), reverse=True)
    for path in [os.path.join(store, fname)] + runs:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [l.rstrip() for l in f]
        hits = [i for i, l in enumerate(lines) if l == head]
        if hits:
            return os.path.abspath(path), os.path.relpath(path, store).replace(os.sep, "/"), hits[-1] + 1
    return None


def record_stored(state, store, entries, round_n=None, act=None):
    """Attach the store entries a finished act's turn wrote to that act — or to its round when the round picked
    several acts and the turn did not say which one wrote them. Entries are kept by file and head, never by line:
    every build re-finds them, so a link follows an entry into the run a pour moved it to."""
    answered = [r for r in state["rounds"] if r.get("picked")]
    if not answered:
        raise ValueError("no answered round to attach store entries to")
    rnd = answered[-1] if round_n is None else next((r for r in answered if r["n"] == round_n), None)
    if rnd is None:
        raise ValueError(f"round {round_n} is not an answered round")
    if act is not None and act not in rnd["picked"]:
        raise ValueError(f"round {rnd['n']}: {act!r} was not picked; picked: {', '.join(rnd['picked'])}")
    target = act or (rnd["picked"][0] if len(rnd["picked"]) == 1 else None)
    state["store"] = os.path.abspath(store)
    stored = rnd.setdefault("stored", [])
    added = 0
    # an entry is its file, head and act; the location fields a build fills in are not part of its identity
    have = {(i["file"], i["head"], i["act"]) for i in stored}
    for fname, head in entries:
        if (fname, head, target) not in have:
            stored.append({"file": fname, "head": head, "act": target})
            have.add((fname, head, target))
            added += 1
    return rnd, added


def resolve_stored(state):
    """Fill each stored entry's current location (path, rel, line) from the store, or mark it not found."""
    store = state.get("store")
    for rnd in state["rounds"]:
        for item in rnd.get("stored", []):
            loc = locate(store, item["file"], item["head"]) if store else None
            item["path"], item["rel"], item["line"] = loc if loc else (None, item["file"], None)


def build(state):
    """The whole page for a state; its title is the latest closing's."""
    if not state["rounds"]:
        raise ValueError("a page needs at least one round")
    resolve_stored(state)
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        page = f.read()
    with open(os.path.join(HERE, "assemble.js"), encoding="utf-8") as f:
        assemble = f.read()
    # "</" or "<!--" inside an inlined script can end it early; "<" is the same JSON string, and in
    # assemble.js "<\/" and "<\!--" are the same JS strings
    payload = json.dumps(state, ensure_ascii=False, indent=1).replace("<", "\\u003c")
    assemble = assemble.replace("</", "<\\/").replace("<!--", "<\\!--")
    title = state["rounds"][-1].get("title") or state.get("title") or "Pending acts"
    # this order keeps an act's own text from being taken for a later placeholder: each first match is the template's
    page = page.replace("/*__ASSEMBLE__*/", assemble, 1)
    page = page.replace("__STATE__", payload, 1)
    page = page.replace("__TITLE__", html.escape(title), 1)
    return page


FRAGMENT_DROP_RE = re.compile(r"<!doctype[^>]*>|</?html[^>]*>|</?head>|<meta[^>]*>|<title>.*?</title>|</?body>", re.I | re.S)
CSS_LINE_COMMENT_RE = re.compile(r"^[ \t]*/\*.*?\*/[ \t]*\n", re.M | re.S)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
JS_LINE_COMMENT_RE = re.compile(r"^[ \t]*//[^\n]*\n", re.M)


def strip_comments(code):
    """The chat widget's rules forbid code comments in a widget, so the fragment drops them: CSS block comments from
    the style block (a comment on a line of its own takes its line with it), whole-line JS comments from the rest.
    A `//` inside a line — a file:/// or vscode:// URL, a regex — is code and stays, and the state block's JSON lines
    always open with a quote or a bracket, never with `//`."""
    end = code.index("</style>")
    style = CSS_COMMENT_RE.sub("", CSS_LINE_COMMENT_RE.sub("", code[:end]))
    return style + JS_LINE_COMMENT_RE.sub("", code[end:])


def fragment(state):
    """The page as a chat widget's code: no document skeleton (the widget host supplies its own), the body's
    rules scoped to a wrapper with a transparent background, the rest — the state block, the scripts — as is.
    In the widget frame the host defines sendPrompt, so the page's Send button shows and posts the prompt."""
    page = build(state)
    page = page.replace("\nbody {", "\n.acts-page {", 1)
    page = page.replace("background: var(--bg); color: var(--fg);", "background: transparent; color: var(--fg);", 1)
    page = FRAGMENT_DROP_RE.sub("", page)
    style_end = page.index("</style>") + len("</style>")
    return strip_comments(page[:style_end].strip() + '\n<div class="acts-page">\n' + page[style_end:].strip() + "\n</div>\n")


def write_page(page_path, state):
    os.makedirs(os.path.dirname(os.path.abspath(page_path)), exist_ok=True)
    tmp = page_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(build(state))
    os.replace(tmp, page_path)


def page_path_of(args):
    if args.page:
        return args.page
    if not args.session:
        raise ValueError("--page or --session is required")
    return os.path.join(args.root or os.getcwd(), ".claude", "scratchpad", "acts-widget", f"{args.session}.html")


def summary(state):
    out = []
    for r in state["rounds"]:
        if r.get("picked") is None:
            what = "open"
        elif r.get("skipped"):
            what = "superseded" if r.get("superseded") else "skipped"
        else:
            what = "picked " + ", ".join(r["picked"])
        out.append(f"  round {r['n']} ({len(r['acts'])} acts{', ' + r['at'] if r.get('at') else ''}): {what}")
    return "\n".join(out)


def main(argv):
    p = argparse.ArgumentParser(prog="build_acts_widget.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("append", "pick", "show", "widget", "stored"):
        s = sub.add_parser(name)
        if name == "stored":
            s.add_argument("--store", required=True, help="the VLDS store, <working dir>/.claude/p4/sessions/<s8>/vlds")
            s.add_argument("--record", help="the turn record scripts/record.py applied")
            s.add_argument("--entry", action="append", default=[], help="FILE:HEAD, one entry by its head line")
            s.add_argument("--round", type=int)
            s.add_argument("--act")
        if name == "widget":
            s.add_argument("--out", help="write the fragment here instead of stdout")
        if name == "append":
            s.add_argument("acts_json")
        s.add_argument("--page")
        s.add_argument("--session")
        s.add_argument("--root")
        if name in ("append", "pick"):
            s.add_argument("--now")
        if name == "pick":
            s.add_argument("--acts", default="")
            s.add_argument("--skipped", action="store_true")
            s.add_argument("--round", type=int)
            s.add_argument("--note", action="append", default=[])
    args = p.parse_args(argv[1:])
    try:
        path = page_path_of(args)
        state = load_state(path)
        if args.cmd == "show":
            if state is None:
                raise ValueError(f"{path}: no page yet")
            print(f"{path}\n{summary(state)}")
            return 0
        if args.cmd == "stored":
            if state is None:
                raise ValueError(f"{path}: no page yet — append a closing first")
            entries = parse_record(args.record) if args.record else []
            for e in args.entry:
                fname, sep, head = e.partition(":")
                if not sep or not head.strip():
                    raise ValueError(f"--entry {e!r}: expected FILE:HEAD")
                entries.append((fname.strip(), head.strip()))
            if not entries:
                raise ValueError("no entries: pass --record or --entry")
            rnd, added = record_stored(state, args.store, entries, args.round, args.act)
            write_page(path, state)
            found = [i for i in rnd["stored"] if i.get("line")]
            print(f"attached {added} store entr{'y' if added == 1 else 'ies'} to round {rnd['n']} in {path}; "
                  f"{len(found)} of {len(rnd['stored'])} located")
            for i in rnd["stored"]:
                where = f"{i['rel']}:{i['line']}" if i.get("line") else f"{i['file']} (not found)"
                print(f"  {where}  {i['head'][:70]}")
            return 0
        if args.cmd == "widget":
            if state is None:
                raise ValueError(f"{path}: no page yet — append a closing first")
            code = fragment(state)
            if args.out:
                os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
                with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                    f.write(code)
                print(f"wrote the widget fragment of {path} to {args.out} ({len(code):,} chars)")
            else:
                sys.stdout.reconfigure(encoding="utf-8")
                sys.stdout.write(code)
            return 0
        if args.cmd == "append":
            with open(args.acts_json, encoding="utf-8") as f:
                data = json.load(f)
            state = state or new_state(args.session)
            rnd = append_round(state, data, args.now)
            write_page(path, state)
            print(f"appended round {rnd['n']} ({len(rnd['acts'])} acts) to {path}\n{summary(state)}")
            return 0
        if state is None:
            raise ValueError(f"{path}: no page yet — append a closing first")
        notes = {}
        for n in args.note:
            k, sep, v = n.partition("=")
            if not sep:
                raise ValueError(f"--note {n!r}: expected ID=TEXT")
            notes[k] = v
        ids = [i.strip() for i in args.acts.split(",") if i.strip()]
        rnd = record_pick(state, ids, args.round, notes, args.skipped, args.now)
        write_page(path, state)
        print(f"recorded round {rnd['n']} in {path}\n{summary(state)}")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"build_acts_widget: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
