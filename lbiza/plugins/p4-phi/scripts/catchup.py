"""catchup.py: at a session's start, close what fell behind on this machine, and say what only ezexe can close.

Run by hooks/recall-hook.sh as `catch-up` on SessionStart startup, a command of its own with its own timeout. It
prints nothing when nothing is behind. Otherwise one `systemMessage` for ezexe, never context for the model:

  layout    the lines of p4conf.migrate_layout, when it moved the store.
  branch    when the store is a git repository of its own with an origin, and this machine's branch is behind
            origin's `<main>`, which p4.json's `recall.sync.main` names, `p4.py sync` runs behind it, so the start
            never waits on a merge, and its output goes to `<git dir>/p4-sync.log`; when it cannot start, the line
            gives the whole command that syncs the store, as phi.py builds it. The fetch that finds out is given
            FETCH_S seconds. Nothing is forced, and nothing is pulled outside `p4.py sync`.
  cache     the version folders under <config>/plugins/cache/p4-marketplace/ that no install uses: how many and
            their size, in one line, said again only when the count changes. Nothing is deleted here: Claude Code
            removes a version folder 14 days after an update or uninstall orphans it, and `catchup.py prune-cache`
            deletes them at once when ezexe runs it.

P4_PHI_CATCHUP=0 turns it off. CLAUDE_CONFIG_DIR stands in for ~/.claude, as Claude Code reads it.

An installed p4 plugin behind its marketplace, and a former name the marketplace's `renames` map gives, are Claude
Code's own: marketplace auto-update, once ezexe turns it on for p4-marketplace, updates the installed copies after a
session starts, and a renamed plugin's settings keys are rewritten by the renames map, by
https://code.claude.com/docs/en/plugins/install.md and https://code.claude.com/docs/en/plugins/host-marketplace.md.
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

MARKET = "p4-marketplace"
FETCH_S = 5.0                 # what the fetch that finds a branch behind may take at a start
SIZE_S = 2.0                  # what measuring the unused version folders may take
ENV = "P4_PHI_CATCHUP"


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


# --- cache --------------------------------------------------------------------------------------------------

def all_install_paths():
    data = read_json(os.path.join(config_dir(), "plugins", "installed_plugins.json")).get("plugins") or {}
    return [r.get("installPath") for rows in data.values() for r in (rows if isinstance(rows, list) else [rows])
            if isinstance(r, dict) and r.get("installPath")]


def old_cache():
    """How many version folders under cache/p4-marketplace no install uses, and their size in bytes, negative when
    SIZE_S ran out and the size is a floor."""
    base = os.path.join(config_dir(), "plugins", "cache", MARKET)
    used = all_install_paths()
    folders, size, end = [], 0, time.monotonic() + SIZE_S
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return 0, 0
    for name in names:
        try:
            vers = sorted(os.listdir(os.path.join(base, name)))
        except OSError:
            continue
        for v in vers:
            p = os.path.join(base, name, v)
            if os.path.isdir(p) and not any(same_path(p, u) for u in used):
                folders.append(p)
    for p in folders:
        for d, _, files in os.walk(p):
            for f in files:
                try:
                    size += os.lstat(os.path.join(d, f)).st_size
                except OSError:
                    pass
            if time.monotonic() > end:
                return len(folders), -size          # measured in part: said as "at least"
    return len(folders), size


def size_text(n):
    at_least = n < 0
    n = abs(n)
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            s = f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
            return ("at least " if at_least else "") + s
        n /= 1024.0


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
    n, size = old_cache()
    # the cache line is said again only when the count changes: until Claude Code removes the folders, the same
    # line would print at every start
    mark = os.path.join(p4, "phi", "catchup.json")
    told = read_json(mark).get("cacheFolders")
    if n and n != told:
        parts.append(f"{n} old version folder(s) under {os.path.join(config_dir(), 'plugins', 'cache', MARKET)} "
                     f"hold {size_text(size)}, used by no install; nothing was deleted. To delete them: "
                     f"`python -I -X utf8 \"{os.path.join(HERE, 'catchup.py')}\" prune-cache`")
    if n != told and os.path.isdir(p4):
        try:
            os.makedirs(os.path.dirname(mark), exist_ok=True)
            with open(mark, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"cacheFolders": n}) + "\n")
        except OSError:
            pass
    return ("phi (p4-phi): " + ". ".join(parts) + ".") if parts else ""


def prune_cache():
    """Delete the version folders under cache/p4-marketplace that no install uses; ezexe runs this."""
    import shutil
    base = os.path.join(config_dir(), "plugins", "cache", MARKET)
    used = all_install_paths()
    gone = []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        for v in sorted(os.listdir(os.path.join(base, name))):
            p = os.path.join(base, name, v)
            if os.path.isdir(p) and not any(same_path(p, u) for u in used):
                shutil.rmtree(p, ignore_errors=True)
                if not os.path.exists(p):
                    gone.append(p)
    return gone


def hook(payload):
    if os.environ.get(ENV) == "0" or (payload.get("source") or "startup") != "startup":
        return None
    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    line = run(project, os.path.join(project, ".claude", "p4"))
    return {"systemMessage": line} if line else None


if __name__ == "__main__":
    if sys.argv[1:] == ["prune-cache"]:
        removed = prune_cache()
        print("\n".join(f"deleted {p}" for p in removed) or "no unused version folder")
        sys.exit(0)
    print("usage: catchup.py prune-cache   deletes the plugin cache's version folders that no install uses",
          file=sys.stderr)
    sys.exit(2)
