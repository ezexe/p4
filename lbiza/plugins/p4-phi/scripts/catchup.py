"""catchup.py: at a session's start, close what fell behind on this machine, and say what only ezexe can close.

Run by hooks/recall-hook.sh as `catch-up` on SessionStart startup, a command of its own with its own timeout. It
prints nothing when nothing is behind. Otherwise one `systemMessage` for ezexe, never context for the model:

  layout    the lines of p4conf.migrate_layout, when it moved the store.
  branch    when the store is a git repository of its own with an origin, and this machine's branch is behind
            origin's `<main>`, which p4.json's `recall.sync.main` names, `p4.py sync` runs behind it, so the start
            never waits on a merge, and its output goes to `<git dir>/p4-sync.log`; when it cannot start, the line
            gives the whole command that syncs the store, as phi.py builds it. The fetch that finds out is given
            FETCH_S seconds. Nothing is forced, and nothing is pulled outside `p4.py sync`.
  plugins   a former plugin, enabled or only installed, and an installed p4-phi or p4-temportal older than the
            marketplace's get the exact `claude plugin` commands that close them, in order. A former plugin is a key
            of the marketplace's `renames` map that names a plugin in its place, and which the marketplace no longer
            offers. The commands are printed, never run: plugin settings are ezexe's.
  cache     the version folders under <config>/plugins/cache/p4-marketplace/ that no install uses: how many and
            their size, in one line, said again only when the count changes. Nothing is deleted here: Claude Code
            removes a version folder 14 days after an update or uninstall orphans it, and `catchup.py prune-cache`
            deletes them at once when ezexe runs it.

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
CURRENT = ("p4-phi", "p4-temportal")
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
    """`{(name, scope): True|False}` for the p4 plugins the settings files name, user scope first."""
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
    """`{name: [(scope, version, installPath)]}` of the installs that apply in `project`."""
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


def market_location():
    """Where Claude Code keeps this machine's copy of the marketplace, '' when it knows none."""
    return (read_json(os.path.join(config_dir(), "plugins", "known_marketplaces.json")).get(MARKET) or {}).get(
        "installLocation") or ""


def retired():
    """{former plugin: the plugin in its place}: the marketplace's `renames` map, which maps a former name to its new
    one or to null, less the names mapped to null, which nothing takes the place of."""
    loc = market_location()
    renames = read_json(os.path.join(loc, ".claude-plugin", "marketplace.json")).get("renames") if loc else None
    return {k: v for k, v in (renames or {}).items() if isinstance(k, str) and isinstance(v, str) and v}


def market_versions():
    """{name: version} the marketplace offers: each plugin's own plugin.json, else marketplace.json."""
    loc = market_location()
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
    """`[(name, scope, version, projectPath)]` of every p4 install on this machine, any project."""
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
    former = retired()
    every = every_install()
    out, need, seen = [], {}, set()

    def retire(name, scope, where=""):
        key = (name, scope, os.path.normcase(where))
        if key in seen:
            return
        seen.add(key)
        out.append(f"claude plugin uninstall {name}@{MARKET} --scope {scope}" + (f" (in {where})" if where else ""))
        if scope == "user" or need.get(former[name]) != "user":
            need[former[name]] = scope
    # a renamed plugin is former only where the marketplace no longer offers it: a marketplace that still lists
    # p4-recall holds a p4-phi without retrieval, and uninstalling p4-recall there would leave no retrieval at all.
    # A former plugin installed but disabled is listed too: its install record and cache folders stay until it is
    # uninstalled.
    for (name, scope), state in sorted(on.items()):
        if state and name in former and name not in offer:
            retire(name, scope)
    for name, scope, _, where in sorted(every):
        if name in former and name not in offer:
            retire(name, scope, "" if scope == "user" or same_path(where, project) else where)
    moves, updates = [], []
    for name in CURRENT:
        rows = have.get(name, [])
        # the successor goes where the former plugin was: after p4-recall at user scope, p4-phi in two projects
        # alone would leave every other project without retrieval. Each project's own install is removed first, in
        # that project, so the plugin is never installed twice where both scopes reach.
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
    cmds = plugin_commands(project)
    n, size = old_cache()
    if cmds:
        shown = []
        for c in cmds:
            cmd, _, where = c.partition(" (in ")
            shown.append(f"`{cmd}`" + (f" in {where.rstrip(')')}" if where else ""))
        parts.append("plugins behind; run, in this order: " + " ; ".join(shown))
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


# --- Claude Code's settings and version, ezexe/p4#246 -----------------------------------------------------------

SETTINGS_ENV = "P4_PHI_SETTINGS"          # 0 turns the settings watcher off
VERSION_S = 5.0                           # what one `--version` may take
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
CHANGELOG_S = 20.0
LIMITS = os.path.join(HERE, "claude_code_limits.json")
WATCH_PAGE = ("phi", "claude-code-watch.md")
WATCH_PENDING = ("phi", "claude-code-watch.pending.json")
CONFIG_SOURCES = ("local_settings", "project_settings", "user_settings")
# The documented defaults p4 relies on, each with the issue to act on when the changelog names it.
WATCHED = {
    "autoMemoryDirectory": "ezexe/p4#246", "autoMemoryEnabled": "ezexe/p4#246",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "ezexe/p4#246", "MEMORY.md": "ezexe/p4#92",
    "blockReadsOutsideWorkingDirectories": "ezexe/p4#246", "blockWritesOutsideWorkingDirectories": "ezexe/p4#246",
    "additionalDirectories": "ezexe/p4#246", "settings.local.json": "ezexe/p4#246", "attribution": "ezexe/p4#246",
    "includeCoAuthoredBy": "ezexe/p4#246", "cleanupPeriodDays": "ezexe/p4#131",
    "desktopSessionCleanupPeriodDays": "ezexe/p4#131", "enableArtifact": "ezexe/p4#131",
    "scratchpad_dir": "ezexe/p4#131", "CLAUDE_PID": "ezexe/p4#246", "10,000 characters": "ezexe/p4#243",
    "CLAUDE_CODE_STOP_HOOK_BLOCK_CAP": "ezexe/p4#246", "BASH_DEFAULT_TIMEOUT_MS": "ezexe/p4#243",
    "ConfigChange": "ezexe/p4#246", "SessionStart": "ezexe/p4#246", "crossSessionInbound": "ezexe/p4#246",
}


def exe_of_pid(pid):
    """The executable path of process `pid`: QueryFullProcessImageNameW on Windows, /proc/<pid>/exe on Linux and
    `ps -o comm=` elsewhere; None when it cannot be read."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        h = k32.OpenProcess(0x1000, False, int(pid))            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
        finally:
            k32.CloseHandle(h)
    try:
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError):
        pass
    try:
        r = subprocess.run(["ps", "-o", "comm=", "-p", str(int(pid))], capture_output=True, text=True, timeout=2)
        p = r.stdout.strip()
        return p if r.returncode == 0 and os.path.isabs(p) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def claude_binary():
    """(path, weak) of the Claude Code binary running this session: the process CLAUDE_PID names, or, when it is
    unset as before v2.1.214 or unreadable, `claude` on the PATH, a weaker reading since the desktop app runs its own
    copy. (None, True) when neither is found."""
    pid = os.environ.get("CLAUDE_PID")
    if pid and pid.isdigit():
        try:
            p = exe_of_pid(int(pid))
        except (OSError, ValueError, AttributeError):
            p = None
        if p and os.path.isfile(p):
            return p, False
    import shutil
    return shutil.which("claude"), True


def read_version(path):
    """The version `<path> --version` prints, '' when it prints none in VERSION_S."""
    import re
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=VERSION_S,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"\d+\.\d+\.\d+", r.stdout or "")
    return m.group(0) if m else ""


def plugin_versions(project):
    """{name: version} of the p4 plugins installed for `project`, the highest of each."""
    out = {}
    for name, rows in installs(project).items():
        vs = [v for _, v, _ in rows if v]
        if vs:
            out[name] = max(vs, key=version)
    return out


def section_of(p4):
    """The `claude` section of the store's p4.json as it stands, read without p4conf's merge."""
    return p4conf._flat(read_json(p4conf.path(p4)).get(p4conf.SECTION) or {})


def settings_hook(payload):
    """At every SessionStart: the cheap comparison of the running Claude Code binary, the p4 plugins' versions and
    the store's `claude` section with the record; any change runs p4conf.keep_settings, and a newer Claude Code starts
    the changelog read. At a ConfigChange of a settings file: keep_settings on the keys the record owns, never a
    block. One `systemMessage` naming a key a store wants that p4 never writes; nothing otherwise."""
    if os.environ.get(SETTINGS_ENV) == "0":
        return None
    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    p4 = os.path.join(p4conf.main_root(project)[0], ".claude", "p4")
    if not os.path.isdir(p4):
        return None
    if payload.get("hook_event_name") == "ConfigChange":
        if payload.get("source") in CONFIG_SOURCES:
            p4conf.keep_settings(project, owned_only=True, p4=p4)
        return None
    rec = p4conf.read_record(p4)
    seen = rec.get("claude") or {}
    note, newer = {}, None
    path, weak = claude_binary()
    if path:
        try:
            st = os.stat(path)
        except OSError:
            st = None
        if st and (seen.get("path"), seen.get("size"), seen.get("mtime")) != (path, st.st_size, st.st_mtime):
            v = read_version(path)
            note["claude"] = {"path": path, "size": st.st_size, "mtime": st.st_mtime,
                              "version": v or seen.get("version") or "", "weak": weak}
            if v and seen.get("version") and version(v) > version(seen["version"]):
                newer = (seen["version"], v)
    plugins = plugin_versions(project)
    if plugins != (rec.get("plugins") or {}):
        note["plugins"] = plugins
    section = section_of(p4)
    if not note and section == rec.get("section"):
        return None
    out = p4conf.keep_settings(project, p4=p4, note=note, tell=True)
    if newer:
        start_changelog(p4, *newer)
    if out["asks"]:
        return {"systemMessage": "phi (p4-phi): " + "; ".join(out["asks"]) + "."}
    return None


def start_changelog(p4, old, new):
    """`catchup.py changelog` in a process of its own, so no web call runs in a hook's time; True when it started."""
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen([sys.executable, "-I", "-X", "utf8", os.path.join(HERE, "catchup.py"), "changelog",
                          "--p4", p4, "--from", old, "--to", new], cwd=p4, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags,
                         start_new_session=(os.name != "nt"))
        return True
    except OSError:
        return False


def watched_terms():
    """{term: issue}: WATCHED, and the `terms` of every entry of claude_code_limits.json, each with its issue. A
    missing or unreadable file adds nothing."""
    out = dict(WATCHED)
    try:
        with open(LIMITS, encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, ValueError):
        rows = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        issue = f"{r.get('repo') or 'ezexe/p4'}#{r.get('issue')}" if r.get("issue") else (r.get("repo") or "")
        for t in r.get("terms") or []:
            if isinstance(t, str) and t.strip():
                out.setdefault(t.strip(), issue)
    return out


def changelog_hits(text, old, new, terms):
    """[(term, version, issue, line)] for each watched term in the `## <version>` sections after `old` up to `new`."""
    import re
    hits, ver = [], None
    lo, hi = version(old), version(new)
    for line in text.splitlines():
        m = re.match(r"^##\s+v?(\d+\.\d+\.\d+)", line)
        if m:
            ver = m.group(1) if lo < version(m.group(1)) <= hi else None
            continue
        if not ver:
            continue
        low = line.lower()
        for term, issue in terms.items():
            if term.lower() in low:
                hits.append((term, ver, issue, line.strip().lstrip("-* ").strip()[:300]))
    return hits


def read_changelog(p4, old, new, text=None):
    """Read the changelog between `old` and `new` and write each hit to the store's watch page and to its pending
    file, which the next prompt's hook hands a session line by line. Returns the hits."""
    if text is None:
        import urllib.request
        try:
            with urllib.request.urlopen(CHANGELOG_URL, timeout=CHANGELOG_S) as r:
                text = r.read().decode("utf-8", "replace")
        except (OSError, ValueError):
            return []
    hits = changelog_hits(text, old, new, watched_terms())
    page = os.path.join(p4, *WATCH_PAGE)
    os.makedirs(os.path.dirname(page), exist_ok=True)
    head = "" if os.path.exists(page) else (
        "# Claude Code changes p4 watches\n\nEach section is one read of Claude Code's changelog after a new version"
        " ran here, by p4-phi's catchup.py.\n")
    body = f"\n## {time.strftime('%Y-%m-%d %H:%M')}, {old} to {new}\n\n"
    body += "".join(f"- `{t}` in {v}, act on {i}: {l}\n" for t, v, i, l in hits) or "- No watched term.\n"
    with open(page, "a", encoding="utf-8", newline="\n") as f:
        f.write(head + body)
    if hits:
        pend = os.path.join(p4, *WATCH_PENDING)
        have = read_json(pend).get("lines") or []
        lines = have + [f"phi (p4-phi): Claude Code {v} changed `{t}` by its changelog; read that entry and "
                        f"{os.path.join(*WATCH_PAGE)} in the store, and act on {i}." for t, v, i, _ in hits]
        p4conf.replace_text(pend, json.dumps({"lines": list(dict.fromkeys(lines))}, ensure_ascii=False) + "\n")
    return hits


def claim_watch(p4):
    """The pending watch lines, taken by one rename so one session gets each once; [] when there are none."""
    pend = os.path.join(p4, *WATCH_PENDING)
    mine = f"{pend}.{os.getpid()}"
    try:
        os.replace(pend, mine)
    except OSError:
        return []
    try:
        return [l for l in read_json(mine).get("lines") or [] if isinstance(l, str)]
    finally:
        try:
            os.remove(mine)
        except OSError:
            pass


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
    if sys.argv[1:2] == ["changelog"]:
        import argparse
        ap = argparse.ArgumentParser(prog="catchup.py changelog")
        ap.add_argument("--p4", required=True)
        ap.add_argument("--from", dest="old", required=True)
        ap.add_argument("--to", dest="new", required=True)
        a = ap.parse_args(sys.argv[2:])
        read_changelog(a.p4, a.old, a.new)
        sys.exit(0)
    print("usage: catchup.py prune-cache   deletes the plugin cache's version folders that no install uses",
          file=sys.stderr)
    sys.exit(2)
