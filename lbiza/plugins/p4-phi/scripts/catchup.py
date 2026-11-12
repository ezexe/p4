"""catchup.py: at a session's start, close what fell behind on this machine, and say what only the owner can close.

Run by hooks/recall-hook.sh as `catch-up` on SessionStart startup, a command of its own with its own timeout. It
prints nothing when nothing is behind. Otherwise one `systemMessage` for the owner, never context for the model:

  layout    p4conf.migrate_layout moves a store an older plugin wrote into each plugin's directory.
  branch    when the store's git repository has an origin and this machine's branch is behind `<main>` there, the
            same flow as `p4.py sync` runs, detached, so the start never waits on a merge; its output goes to
            `<git dir>/p4-sync.log`. The fetch that finds out is given FETCH_S seconds. Nothing is forced and nothing
            is pulled by hand outside that flow.
  plugins   a retired plugin still enabled (p4-memory, p4-scratchpad, p4-recall) that the marketplace no longer
            offers, or an installed p4-phi or
            p4-temportal older than the marketplace's, gets the exact `claude plugin` commands that close it. They
            are printed, never run: plugin settings are the owner's.
  cache     the version folders under <config>/plugins/cache/p4-marketplace/ that no install uses: how many, and
            their size, in the same line. Nothing is deleted; the CLI never removes them either.

P4_PHI_CATCHUP=0 turns it off. CLAUDE_CONFIG_DIR stands in for ~/.claude, as Claude Code reads it.
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
RETIRED = {"p4-memory": "p4-temportal", "p4-scratchpad": "p4-temportal", "p4-recall": "p4-phi"}
CURRENT = ("p4-phi", "p4-temportal")
FETCH_S = 5.0                 # what the fetch that finds a branch behind may take at a start
SIZE_S = 2.0                  # what measuring the old cache folders may take
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


def version(v):
    out = []
    for part in str(v or "").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def same_path(a, b):
    return os.path.normcase(os.path.normpath(a or "")) == os.path.normcase(os.path.normpath(b or ""))


# --- plugins -------------------------------------------------------------------------------------------------

def enabled(project):
    """{(name, scope): True|False} for the p4 plugins the settings files name, user scope first."""
    out = {}
    for scope, path in (("user", os.path.join(config_dir(), "settings.json")),
                        ("project", os.path.join(project, ".claude", "settings.json")),
                        ("local", os.path.join(project, ".claude", "settings.local.json"))):
        for key, on in (read_json(path).get("enabledPlugins") or {}).items():
            name, _, market = str(key).partition("@")
            if market == MARKET:
                out[(name, scope)] = bool(on)
    return out


def installs(project):
    """{name: [(scope, version, installPath)]} of the installs that apply in `project`."""
    data = read_json(os.path.join(config_dir(), "plugins", "installed_plugins.json")).get("plugins") or {}
    out = {}
    for key, rows in data.items():
        name, _, market = str(key).partition("@")
        if market != MARKET:
            continue
        for r in rows if isinstance(rows, list) else [rows]:
            if not isinstance(r, dict):
                continue
            if r.get("scope") in ("local", "project") and not same_path(r.get("projectPath"), project):
                continue
            out.setdefault(name, []).append((r.get("scope") or "user", r.get("version") or "", r.get("installPath") or ""))
    return out


def all_install_paths():
    data = read_json(os.path.join(config_dir(), "plugins", "installed_plugins.json")).get("plugins") or {}
    return [r.get("installPath") for rows in data.values() for r in (rows if isinstance(rows, list) else [rows])
            if isinstance(r, dict) and r.get("installPath")]


def market_versions():
    """{name: version} the marketplace offers now: each plugin's own plugin.json, else marketplace.json."""
    loc = (read_json(os.path.join(config_dir(), "plugins", "known_marketplaces.json")).get(MARKET) or {}).get(
        "installLocation") or ""
    if not loc:
        return {}
    out = {}
    for p in read_json(os.path.join(loc, ".claude-plugin", "marketplace.json")).get("plugins") or []:
        if isinstance(p, dict) and p.get("name"):
            out[p["name"]] = p.get("version") or ""
            own = read_json(os.path.join(loc, str(p.get("source") or "").lstrip("./").replace("/", os.sep),
                                         ".claude-plugin", "plugin.json"))
            if own.get("version"):
                out[p["name"]] = own["version"]
    return out


def every_install():
    """[(name, scope, version, projectPath)] of every p4 install on this machine, any project."""
    data = read_json(os.path.join(config_dir(), "plugins", "installed_plugins.json")).get("plugins") or {}
    out = []
    for key, rows in data.items():
        name, _, market = str(key).partition("@")
        if market != MARKET:
            continue
        for r in rows if isinstance(rows, list) else [rows]:
            if isinstance(r, dict):
                out.append((name, r.get("scope") or "user", r.get("version") or "", r.get("projectPath") or ""))
    return out


def plugin_commands(project):
    """The `claude plugin` commands that bring the p4 plugins up to date, in order; [] when none. A command that
    has to run inside another project, to remove an install scoped to it, ends with `(in <project>)`."""
    on = enabled(project)
    have = installs(project)
    offer = market_versions()
    every = every_install()
    out, need, seen = [], {}, set()

    def retire(name, scope, where=""):
        key = (name, scope, os.path.normcase(where))
        if key in seen:
            return
        seen.add(key)
        out.append(f"claude plugin uninstall {name}@{MARKET} --scope {scope}" + (f" (in {where})" if where else ""))
        if scope == "user" or need.get(RETIRED[name]) != "user":
            need[RETIRED[name]] = scope
    # retired only once the marketplace stops offering it: a machine whose marketplace still lists p4-recall has no
    # p4-phi that carries recall yet, and uninstalling it there would leave no recall at all. A retired plugin
    # installed but disabled is listed too: its install record and cache folders stay until it is uninstalled.
    for (name, scope), state in sorted(on.items()):
        if state and name in RETIRED and name not in offer:
            retire(name, scope)
    for name, scope, _, where in sorted(every):
        if name in RETIRED and name not in offer:
            retire(name, scope, "" if scope == "user" or same_path(where, project) else where)
    moves, updates = [], []
    for name in CURRENT:
        rows = have.get(name, [])
        # the successor goes where the retired plugin was: p4-recall for the whole user and p4-phi in two projects
        # would leave every other project without recall. Each project's own install is removed first, in that
        # project, so the plugin is never installed twice where both scopes reach (the tester's C1).
        to_user = need.get(name) == "user" and name in offer and "user" not in {sc for sc, _, _ in rows}
        if to_user:
            for n, scope, _, where in sorted(every, key=lambda r: (not same_path(r[3], project), r[3], r[1])):
                if n == name and scope in ("local", "project"):
                    here = same_path(where, project)
                    moves.append(f"claude plugin uninstall {name}@{MARKET} --scope {scope}"
                                 + ("" if here else f" (in {where})"))
            moves.append(f"claude plugin install {name}@{MARKET} --scope user")
        elif name in need and name in offer and need[name] not in {sc for sc, _, _ in rows}:
            moves.append(f"claude plugin install {name}@{MARKET} --scope {need[name]}")
        for scope, v, _ in rows:
            if to_user and scope in ("local", "project"):
                continue                            # removed above: no update for it
            if offer.get(name) and version(v) < version(offer[name]):
                updates.append(f"claude plugin update {name}@{MARKET} --scope {scope}")
    if moves or updates:
        out = [f"claude plugin marketplace update {MARKET}"] + out + moves + updates
    return out


def old_cache():
    """(folders, bytes) of the version folders under cache/p4-marketplace that no install uses."""
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
    """(branch, commits behind origin/<main>) when the store is its own repository with an origin and the fetch
    answers within FETCH_S; None otherwise."""
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
    """`p4.py sync --p4 <p4>`, detached, its output in <git dir>/p4-sync.log. True when it started."""
    gd = git(p4, "rev-parse", "--absolute-git-dir")
    log = os.path.join(gd.stdout.strip(), "p4-sync.log") if gd and gd.returncode == 0 else os.devnull
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
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

def run(project, p4, sync=True):
    """The line for the owner, '' when nothing is behind."""
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
                                else "run `p4.py sync` to merge it"))
    cmds = plugin_commands(project)
    n, size = old_cache()
    if cmds:
        shown = []
        for c in cmds:
            cmd, _, where = c.partition(" (in ")
            shown.append(f"`{cmd}`" + (f" in {where.rstrip(')')}" if where else ""))
        parts.append("plugins behind; run, in this order: " + " ; ".join(shown))
    # the cache line once per new count (C3): nothing removes those folders by itself, so it would print forever
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
    return ("p4-phi catch-up: " + ". ".join(parts) + ".") if parts else ""


def prune_cache():
    """Delete the version folders under cache/p4-marketplace that no install uses; the owner runs this."""
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
    print("usage: catchup.py prune-cache   (delete the plugin cache's version folders no install uses)", file=sys.stderr)
    sys.exit(2)
