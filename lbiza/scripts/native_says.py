"""native_says.py: fills the lines for sessions of p4-native's record, hooks/weighed.json, from Claude Code's own words.

    python native_says.py --types <claude-code.d.ts> --hooks <hooks.md> --index <llms.txt> [--check]

A row's `says` is one line that tells a session what the thing does. A hooks module can list the slash commands and
the tools of the session it runs in, each with its own description, so p4-native reads those two kinds live. It
cannot list the hook events or the events and methods of the hooks module, and the docs pages are no part of a
session, so this script writes those lines into the record, at each change of the Claude Code version:

- a hook event's line is its row of the table "Hook lifecycle" of hooks.md, the page given by --hooks,
- a module event's and a module method's line is the first sentence of its own comment in the types file given by
  --types, which the bundled skill `plugin-authoring` holds as `types/claude-code.d.ts`, and where the file gives
  none in a form this script reads, the line says the row's kind,
- a row of the kind `doc` stands for one page of the docs index given by --index, the file
  https://code.claude.com/docs/llms.txt, with the page's own title and description as its line.

It adds a `doc` row for a page that has none and removes the row of a page the index dropped. It adds no row of any
other kind, since each of those carries the verdict of every p4 plugin, which is a walk made by hand: it prints the
hook events, module events and module methods the sources hold with no row, and the rows the sources no longer
hold. With --check it writes nothing and exits 1 where the record differs from what it would write.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RECORD = Path(__file__).resolve().parents[1] / "plugins" / "p4-native" / "hooks" / "weighed.json"
DOCS = "https://code.claude.com/docs/en/"
KIND_LINE = {
    "event": "An event of the hooks module, which a plugin's module hooks with `on`: its types are in the skill `plugin-authoring`.",
    "method": "A method of the hooks module, which a plugin's module calls on `$`: its types are in the skill `plugin-authoring`.",
}
# the most characters of a line
MOST = 300


def first_sentence(lines):
    """The first sentence of a comment's lines, with the comment's own marks taken off."""
    text = " ".join(line.strip().lstrip("*").strip() for line in lines)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.split(r"\s@(?:example|remarks|param|returns|see)\b", text, maxsplit=1)[0]
    found = re.match(r"(.+?\.)(?:\s|$)", text)
    said = (found.group(1) if found else text).strip().rstrip(":").strip()
    said = said[:1].upper() + said[1:]
    if said and said[-1] not in ".!?":
        said += "."
    return said if len(said) <= MOST else said[: MOST - 3].rstrip() + "..."


def methods_of(types):
    """Each method of `$` with the first sentence of its comment: a noun stands at six spaces, a method at ten, and
    the comment just above it. The second answer holds the names declared as a call, which a property is not."""
    out, calls = {}, set()
    noun, comment, inside = None, [], False
    for line in types:
        opened = re.match(r"^      (\w+): \{$", line)
        if opened:
            noun, comment = opened.group(1), []
            continue
        if re.match(r"^      \};?$", line):
            noun = None
        if noun is None:
            continue
        if line.startswith("          /**"):
            comment, inside = [], True
            continue
        if inside:
            if line.strip().startswith("*/"):
                inside = False
            else:
                comment.append(line)
            continue
        named = re.match(r"^          (\w+)\??: ", line)
        if named and comment:
            out.setdefault(f"$.{noun}.{named.group(1)}", first_sentence(comment))
            if re.search(r": (?:\(|<|EventCalls\[)", line):
                calls.add(f"$.{noun}.{named.group(1)}")
            comment = []
    return out, calls


def events_of(types):
    """Each event of the hooks module with what its input's comment says after `The input of`. A comment can name
    two events and put a folder's name in brackets after the event's. The second answer holds every event a comment
    names at all, with a line or with none, so an event is known to exist however its comment goes on."""
    out, named = {}, set()
    for at, line in enumerate(types):
        named.update(re.findall(r"`([a-z]+\.[A-Za-z.]+)`", line.split("The input of", 1)[1].split(":", 1)[0].split(";", 1)[0])
                     if "* The input of `" in line else [])
        found = re.search(r"\* The input of `([a-z]+\.[A-Za-z.]+)`(?: and `([a-z]+\.[A-Za-z.]+)`)?(?: \([^)]*\))?: (.*)$", line)
        if not found:
            # a comment that goes on after a semicolon says how the input is held, and not what the event is
            continue
        rest, on = [found.group(3)], at + 1
        while on < len(types) and types[on].strip().startswith("*") and not types[on].strip().startswith("*/"):
            rest.append(types[on])
            on += 1
        for name in (found.group(1), found.group(2)):
            if name:
                out.setdefault(name, first_sentence(rest))
    return out, named


def hooks_of(page):
    """Each hook event with its cell of the lifecycle table of hooks.md."""
    table = page.split("| Event", 1)[1].split("\n\n", 1)[0]
    out = {}
    for name, cell in re.findall(r"(?m)^\| `([A-Z][A-Za-z]+)` +\| (.+?) +\|$", table):
        said = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cell).strip()
        out[name] = said if said[-1] in ".!?" else said + "."
    return out


def pages_of(index):
    """Each page of the docs index as (key, url, line): the key is `docs:` and the page's path with no `.md`."""
    out = []
    for title, url, said in re.findall(r"(?m)^- \[([^\]]+)\]\((https://code\.claude\.com/docs/en/[^)]+)\)(?:: (.*))?$", index):
        path = url[len(DOCS):].removesuffix(".md")
        line = f"{title}: {said.strip()}" if said.strip() else f"{title}."
        out.append((f"docs:{path}", url, line if len(line) <= MOST else line[: MOST - 3].rstrip() + "..."))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--types", required=True)
    parser.add_argument("--hooks", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--record", default=str(RECORD))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    was = Path(args.record).read_text(encoding="utf-8")
    record = json.loads(was)
    rows = record["rows"]
    types = Path(args.types).read_text(encoding="utf-8").split("\n")
    methods, calls = methods_of(types)
    events, named = events_of(types)
    read = {
        "method": methods,
        "event": events,
        "hook": hooks_of(Path(args.hooks).read_text(encoding="utf-8")),
    }
    # what the sources hold of a kind, by name: a line is read off every property under a noun, so only a name
    # declared as a call counts as a method, and an event counts wherever a comment names its input
    known = {"method": calls, "event": named, "hook": set(read["hook"])}
    for kind, got in read.items():
        have = {key for key, row in rows.items() if row["kind"] == kind}
        for key in sorted(have):
            line = got.get(key) or KIND_LINE.get(kind)
            if line:
                rows[key]["says"] = line
        new = sorted(known[kind] - have)
        print(f"{kind}: {len(have)} rows, {sum(1 for key in have if key in got)} with a line of their own, "
              f"{len(new)} in the sources with no row: {', '.join(new) or 'none'}; "
              f"rows the sources no longer hold: {', '.join(sorted(have - set(got))) if kind == 'hook' else 'not read for this kind'}")

    pages = pages_of(Path(args.index).read_text(encoding="utf-8"))
    held = {key for key, row in rows.items() if row["kind"] == "doc"}
    named = {key for key, _, _ in pages}
    for key in held - named:
        del rows[key]
    for key, url, line in pages:
        rows[key] = {"kind": "doc", "page": url, "says": line}
    print(f"doc: {len(pages)} pages in the index, {len(named - held)} new: {', '.join(sorted(named - held)[:12]) or 'none'}"
          f"{' and more' if len(named - held) > 12 else ''}; {len(held - named)} dropped: {', '.join(sorted(held - named)) or 'none'}")

    now = json.dumps(record, indent=1, ensure_ascii=False) + "\n"
    if args.check:
        print("the record is as the sources have it" if now == was else "the record differs from what the sources give")
        return 0 if now == was else 1
    Path(args.record).write_text(now, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
