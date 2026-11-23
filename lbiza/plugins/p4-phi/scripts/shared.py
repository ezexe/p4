"""What a session in a git worktree takes from its main checkout, so it pays no second install.

A fresh worktree holds nothing git ignores, so the project's environment is absent there. Two keys of p4.json's `phi`
section, read when a project sets them, name what its worktrees share:
- `worktree_python`: the project's interpreter, a path from the main checkout's root, which a worktree's session runs
  by its full path. https://docs.python.org/3/library/venv.html: "you can just specify the full path to that
  environment's Python interpreter."
- `worktree_lines`: the project's own sentences for its other tools, with `{main}` for the main checkout's root.
This module copies nothing and makes no link: a copy is `.worktreeinclude`'s and a link `worktree.symlinkDirectories`',
both Claude Code's own. It finds a link a worktree holds and takes one away without touching its target, since Git for
Windows before 2.54.0 empties a junction's target when it removes the worktree, git-for-windows/git#6151.
"""
import os
import stat

import p4conf

PYTHON = ("This project's Python environment is the main checkout's, which every worktree shares: run Python and the "
          "tests with `{python}` by that full path, from this worktree's own folder, and build no environment here. "
          "Where the project is installed into that environment in editable form, its import path names the main "
          "checkout's source, so see that a module under test loads from this worktree before a test result counts.")
NONE = "phi: this project's p4.json names nothing its worktrees share"
JUNCTION = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def tree_of(base):
    """(the checkout the folder `base` lies in, its main checkout), which differ in a linked worktree; ('', '')
    outside a repository."""
    d = os.path.abspath(base)
    while not os.path.exists(os.path.join(d, ".git")):
        up = os.path.dirname(d)
        if up == d:
            return "", ""
        d = up
    main, found = p4conf.main_root(d)
    return (d, str(main)) if found else ("", "")


def conf(main):
    """(the interpreter's path as p4.json gives it, the project's own lines), each empty where its key is unset or
    of another type."""
    try:
        d = p4conf.section(os.path.join(main, ".claude", "p4"), "phi", write=False)
    except Exception:  # noqa: BLE001
        d = {}
    d = d if isinstance(d, dict) else {}
    py, more = d.get("worktree_python"), d.get("worktree_lines")
    return (py.strip() if isinstance(py, str) else "",
            [x.strip() for x in more if isinstance(x, str) and x.strip()] if isinstance(more, list) else [])


def lines(base):
    """The lines a brief or a session's start carries for a worktree of the checkout `base` lies in: none where the
    project sets neither key, and no interpreter line where its file is not on disk."""
    main = tree_of(base)[1] if base else ""
    if not main:
        return []
    py, more = conf(main)
    root, out = main.replace("\\", "/"), []
    if py:
        full = os.path.normpath(os.path.join(main, py))
        if os.path.isfile(full):
            out.append(PYTHON.format(python=full.replace("\\", "/")))
    return out + [x.replace("{main}", root) for x in more]


def text(base):
    return "\n".join(lines(base))


def start_text(here):
    """The same lines for a session whose folder `here` lies in a linked worktree, '' in a main checkout."""
    top, main = tree_of(here) if here else ("", "")
    if not top or os.path.normcase(os.path.realpath(top)) == os.path.normcase(os.path.realpath(main)):
        return ""
    return text(top)


def is_link(path):
    """True for a symbolic link or a Windows junction, read from the entry itself and never from its target."""
    try:
        got = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(got.st_mode) or getattr(got, "st_reparse_tag", 0) == JUNCTION


def links(tree, status):
    """The links among what git does not track in the worktree `tree`, from `status`, the text
    `git status --porcelain --ignored` prints there."""
    out = []
    for line in (status or "").splitlines():
        if line[:3] in ("!! ", "?? "):
            p = os.path.join(tree, line[3:].strip().strip('"').rstrip("/"))
            if is_link(p):
                out.append(p.replace("\\", "/"))
    return out


def unlink(path):
    """Take the link at `path` away and leave what it points at; True when it is gone. os.rmdir and os.unlink each
    remove one entry and never descend, so the target's contents are out of reach of both."""
    if not is_link(path):
        return False
    for take in (os.rmdir, os.unlink):
        try:
            take(path)
            return True
        except OSError:
            continue
    return False
