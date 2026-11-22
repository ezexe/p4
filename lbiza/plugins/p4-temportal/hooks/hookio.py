"""hookio.py: what every p4-temportal hook script reads the same way, kept once here. A hook's input is the JSON
Claude Code writes on its stdin, and its project is CLAUDE_PROJECT_DIR, which Claude Code sets for a hook, else the
input's `cwd`, as the hooks reference describes both. A link into the store is removed as a link, never by entering
it. Only p4-temportal's hooks import it; p4conf.py, which each plugin carries a copy of, holds is_link and the store's
own-repository test.
"""

import json
import os
import sys


def payload_from_stdin():
    """The hook's JSON input on stdin, or {} when it cannot be read."""
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    """The project a hook runs for: CLAUDE_PROJECT_DIR, else the input's cwd, else the working folder."""
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def same(a, b):
    """True when two paths name one place."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def settings_store(p4):
    """The store whose p4.json holds for a session whose own store is `p4`: the main checkout's `.claude/p4` where
    `p4` lies in a git worktree, or under a folder of a repository, and the main checkout has a store, and `p4`
    itself anywhere else.

    p4.json holds what ezexe turned on for the project, and a worktree is one more checkout of that project. Claude
    Code keeps a project's own configuration the same way. https://code.claude.com/docs/en/settings.md, "Where
    Claude Code keeps the local file in a git repository": "In a worktree, it uses the file at the main checkout's
    root". https://code.claude.com/docs/en/worktrees.md, "What worktrees share with the main checkout": in a
    worktree session started from the desktop app "Claude Code reads project configuration such as settings, hooks,
    skills, agents, commands" and more "from the main checkout's root", and `${CLAUDE_PROJECT_DIR}` points at it.
    So a p4.json a worktree's own store came to hold is read by nobody, and none is written there."""
    import p4conf                                       # beside this file, where each script puts its folder first
    p4 = os.path.abspath(p4)
    if os.path.basename(p4) != "p4" or os.path.basename(os.path.dirname(p4)) != ".claude":
        return p4
    root = os.path.dirname(os.path.dirname(p4))
    main, in_git = p4conf.main_root(root)
    there = os.path.join(main, ".claude", "p4")
    return there if in_git and not same(main, root) and os.path.isdir(there) else p4


def remove_link(path):
    """Remove a symlink or a junction itself, never what it points at: a junction is removed as a folder, which drops
    only its reparse point."""
    if os.path.islink(path):
        os.unlink(path)
    else:
        os.rmdir(path)
