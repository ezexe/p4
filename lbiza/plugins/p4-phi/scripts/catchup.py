"""catchup.py: at a session's start, close what fell behind on this machine, and say what only ezexe can close.

Run by hooks/recall-hook.sh as `catch-up` on SessionStart startup, a command of its own with its own timeout. It
prints nothing when nothing is behind. Otherwise one `systemMessage` for ezexe, never context for the model:

  layout    the lines of p4conf.migrate_layout, when it moved the store.
  branch    when the store is a git repository of its own with an origin, and this machine's branch is behind
            origin's `<main>`, which p4.json's `recall.sync.main` names, `p4.py sync` runs behind it, so the start
            never waits on a merge, and its output goes to `<git dir>/p4-sync.log`; when it cannot start, the line
            gives the whole command that syncs the store, as phi.py builds it. The fetch that finds out is given
            FETCH_S seconds. Nothing is forced, and nothing is pulled outside `p4.py sync`.

P4_PHI_CATCHUP=0 turns it off.

An installed p4 plugin behind its marketplace, and a former name the marketplace's `renames` map gives, are Claude
Code's own: marketplace auto-update, once ezexe turns it on for p4-marketplace, updates the installed copies after a
session starts, and a renamed plugin's settings keys are rewritten by the renames map, by
https://code.claude.com/docs/en/plugins/install.md and https://code.claude.com/docs/en/plugins/host-marketplace.md.
So are the version folders no install uses: Claude Code marks a previous version when an update or uninstall orphans
it and removes it 14 days later, by https://code.claude.com/docs/en/plugins/loading.md.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

FETCH_S = 5.0                 # what the fetch that finds a branch behind may take at a start
ENV = "P4_PHI_CATCHUP"


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


# --- the store's branch ----------------------------------------------------------------------------------------

def git(p4, *args, timeout=10):
    try:
        return subprocess.run(["git", "-C", p4, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def behind(p4, main="main"):
    """The branch and how many commits it is behind origin/<main>, when the store is a git repository of its own
    with an origin and the fetch answers within FETCH_S; None otherwise."""
    top = git(p4, "rev-parse", "--show-toplevel")
    if not top or top.returncode != 0 or not same_path(top.stdout.strip(), p4):
        return None
    origin = git(p4, "remote", "get-url", "origin")
    if not origin or origin.returncode != 0:
        return None
    branch = git(p4, "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch.returncode != 0 or branch.stdout.strip() in ("", "HEAD"):
        return None
    f = git(p4, "fetch", "-q", "origin", main, timeout=FETCH_S)
    if not f or f.returncode != 0:
        return None
    n = git(p4, "rev-list", "--count", f"HEAD..origin/{main}")
    if not n or n.returncode != 0:
        return None
    return branch.stdout.strip(), int(n.stdout.strip() or 0)


def start_sync(p4):
    """Start `p4.py sync --p4 <p4>` in a process of its own with a console that has no window, its output appended
    to <git dir>/p4-sync.log; True when it started."""
    gd = git(p4, "rev-parse", "--absolute-git-dir")
    log = os.path.join(gd.stdout.strip(), "p4-sync.log") if gd and gd.returncode == 0 else os.devnull
    flags = 0
    if os.name == "nt":                 # a console of its own with no window, which git and the rest it starts share;
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)       # DETACHED_PROCESS would give each its own window
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        with open(log, "a", encoding="utf-8") as out:
            out.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} catch-up\n")
            out.flush()
            subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "p4.py"), "sync", "--p4", p4],
                             cwd=p4, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=flags, start_new_session=(os.name != "nt"))
        return True
    except OSError:
        return False


# --- the hook ------------------------------------------------------------------------------------------------

def sync_command(p4):
    """The whole command that syncs the store, as phi.py builds it for the line that orders a push."""
    return f"python -I -X utf8 \"{os.path.join(HERE, 'p4.py')}\" sync --push --p4 \"{p4}\"".replace("\\", "/")


def run(project, p4, sync=True):
    """The line for ezexe, '' when nothing is behind. On the way it calls p4conf.migrate_layout and, when the
    store's branch is behind, starts `p4.py sync`."""
    parts = []
    if os.path.isdir(p4):
        moved = p4conf.migrate_layout(p4)
        if moved:
            parts.append("store layout: " + "; ".join(moved))
        if sync:
            main = (p4conf.section(p4, "recall", write=False).get("sync") or {}).get("main") or "main"
            got = behind(p4, main)
            if got and got[1] > 0:
                started = start_sync(p4)
                parts.append(f"the store's branch {got[0]} is {got[1]} commit(s) behind origin/{main}; "
                             + ("`p4.py sync` is merging it in the background" if started
                                else f"run `{sync_command(p4)}` to merge it"))
    return ("phi (p4-phi): " + ". ".join(parts) + ".") if parts else ""


def hook(payload):
    if os.environ.get(ENV) == "0" or (payload.get("source") or "startup") != "startup":
        return None
    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    line = run(project, os.path.join(project, ".claude", "p4"))
    return {"systemMessage": line} if line else None

