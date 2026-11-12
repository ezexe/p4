"""git clean/smudge filter for the store's tracked phi/ files (PL1).

The session tree names files by this machine's absolute paths: E:/projects/x, /e/projects/x, E:\\projects\\x. In git
the project's root is held as {project}, and each machine's checkout writes its own root back in its place, so a tree
synced from another machine names this machine's files. Paths outside the project, such as a session's temp folder,
name that machine's own files and stay as they are.

    python pathfilter.py clean|smudge [store]     stdin to stdout; the store is the current folder by default, as git
                                                  runs a filter from the top of its work tree
"""

import os
import re
import sys

TOKEN = "{project}"


def project_of(home):
    """The project a store serves: the folder holding its .claude/p4, else the store itself."""
    h = os.path.abspath(home).replace("\\", "/").rstrip("/")
    if h.lower().endswith("/.claude/p4"):
        return h[: -len("/.claude/p4")]
    return h


def pattern(root):
    """Every spelling of `root` a session writes: either slash, doubled backslashes inside JSON, and the Git Bash and
    WSL forms of a drive, ending where the path's next part or the text around it begins."""
    m = re.match(r"^([A-Za-z]):/(.*)$", root)
    if m:
        drive, parts = m.group(1), [p for p in m.group(2).split("/") if p]
        sep = r"[/\\]+"
        tail = sep + sep.join(re.escape(p) for p in parts) if parts else ""
        forms = [re.escape(drive) + ":" + (tail or sep.rstrip("+")),
                 r"/(?:mnt/)?" + re.escape(drive) + ("/" + "/".join(re.escape(p) for p in parts) if parts else "")]
    else:
        forms = [re.escape(root)]
    return re.compile("(?:" + "|".join(forms) + r")(?=[/\\\"'`\s,;:)\]}>]|$)", re.I)


def clean(text, root):
    return pattern(root).sub(lambda _: TOKEN, text)


def smudge(text, root):
    return text.replace(TOKEN, root)


def main(argv):
    if len(argv) < 2 or argv[1] not in ("clean", "smudge"):
        print(__doc__)
        return 2
    root = project_of(argv[2] if len(argv) > 2 else os.getcwd())
    data = sys.stdin.buffer.read().decode("utf-8", "surrogateescape")
    out = clean(data, root) if argv[1] == "clean" else smudge(data, root)
    sys.stdout.buffer.write(out.encode("utf-8", "surrogateescape"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
