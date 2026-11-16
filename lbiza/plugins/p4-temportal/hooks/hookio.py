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


def remove_link(path):
    """Remove a symlink or a junction itself, never what it points at: a junction is removed as a folder, which drops
    only its reparse point."""
    if os.path.islink(path):
        os.unlink(path)
    else:
        os.rmdir(path)
