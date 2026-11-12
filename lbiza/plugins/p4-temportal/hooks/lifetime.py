#!/usr/bin/env python3
"""lifetime.py — p4-temportal's lifetimes: how long a file under `<project>/.claude/p4/temportal/` is kept.

A browser keeps two kinds of short-lived files, and so does p4-temportal:

  cache    a rule per directory in p4.json `temportal.cache`: files older than `max_age_days` are cleared, and when
           the directory holds more than `max_mb` the oldest are cleared until it fits. Paths are relative to
           temportal/. The defaults cover the notebook's swept logs and build output (scratchpad/.out) and the older
           copies a layout move kept aside (.layout-conflicts).
  cookie   one file or directory with its own expiry, set when it is written: `lifetime.py set <path> <lifetime>`,
           where the lifetime is `30m`, `12h`, `7d`, `2w` or an ISO date. The expiries are kept in
           temportal/expires.json. A cookie whose time is up is cleared at the next sweep. `session` is a lifetime
           too: the file is cleared when the session that set it ends.

memory/ is never cleared by a cache rule, and a cookie set inside it is refused: a memory is meant to last. tmp/<session>
keeps its own lifetime, scratchpad.tmp_idle_days, because a tmp is committed before it is deleted.

A file the store's git repository tracks is removed with its removal staged, so its last version stays in history.
An ignored or untracked file is simply deleted, as a browser drops its cache.

  sweep (SessionStart, SessionEnd)   clear what has expired; prints one line when it cleared something.
  set <path> <lifetime>              set a cookie (also the CLI: python3 lifetime.py set ...).
  list                               every cookie with its expiry, then every cache rule.
  clear <path>                       remove a cookie, keeping the file.

Every failure in a hook prints a one-line notice and exits 0.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402  (the settings file, .claude/p4/p4.json)

EXPIRES = "expires.json"
NEVER = ("memory",)                     # directories no lifetime ever clears
UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}
SESSION = "session"


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def store_of(root):
    return os.path.join(root, ".claude", "p4")


def home(p4):
    return os.path.join(p4, "temportal")


def rules(p4):
    return p4conf.section(p4, "temportal").get("cache", {})


def parse_lifetime(text, now=None):
    """`30m`, `12h`, `7d`, `2w`, an ISO date or time, or `session` -> the expiry as epoch seconds, or SESSION."""
    now = time.time() if now is None else now
    t = str(text).strip().lower()
    if t == SESSION:
        return SESSION
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([mhdw])", t)
    if m:
        return now + float(m.group(1)) * UNITS[m.group(2)]
    try:
        d = datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise ValueError(f"not a lifetime: {text!r} (use 30m, 12h, 7d, 2w, an ISO date or 'session')")
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def rel_in(p4, path):
    """`path` relative to temportal/ with forward slashes, or None when it is outside it."""
    h = os.path.realpath(home(p4))
    a = os.path.realpath(path if os.path.isabs(path) else os.path.join(h, path))
    try:
        r = os.path.relpath(a, h)
    except ValueError:
        return None
    if r == "." or r.startswith(".."):
        return None
    return r.replace("\\", "/")


def never(rel):
    return rel.split("/")[0] in NEVER


def read_expires(p4):
    try:
        with open(os.path.join(home(p4), EXPIRES), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_expires(p4, d):
    p = os.path.join(home(p4), EXPIRES)
    if not d:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    os.makedirs(home(p4), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(d, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def set_cookie(p4, path, lifetime, session_id="", now=None):
    """Give `path` (under temportal/) an expiry -> (rel, expiry). Raises ValueError for a path outside temportal/,
    inside memory/, or a lifetime it cannot read."""
    rel = rel_in(p4, path)
    if rel is None:
        raise ValueError(f"{path} is not under {home(p4)}")
    if never(rel):
        raise ValueError(f"{rel} is in {rel.split('/')[0]}/, which is never cleared")
    when = parse_lifetime(lifetime, now)
    d = read_expires(p4)
    if when == SESSION:
        if not session_id:
            raise ValueError("a 'session' lifetime needs the session id (--session)")
        d[rel] = {"session": session_id}
    else:
        d[rel] = {"expires": round(when, 3)}
    write_expires(p4, d)
    return rel, d[rel]


def clear_cookie(p4, path):
    rel = rel_in(p4, path)
    d = read_expires(p4)
    if rel in d:
        del d[rel]
        write_expires(p4, d)
        return True
    return False


def _git(p4, *args):
    try:
        return subprocess.run(["git", "-C", p4, *args], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None


def _own_repo(p4):
    r = _git(p4, "rev-parse", "--show-toplevel")
    if not (r and r.returncode == 0):
        return False
    try:
        return os.path.samefile(r.stdout.decode("utf-8", "replace").strip(), p4)
    except OSError:
        return False


def remove(path):
    """Delete a file or a whole directory; links are removed as links. -> files removed."""
    if p4conf.is_link(path):
        try:
            os.unlink(path) if os.path.islink(path) else os.rmdir(path)
            return 1
        except OSError:
            return 0
    if os.path.isdir(path):
        n = sum(len(fs) for _, _, fs in os.walk(path))
        shutil.rmtree(path, ignore_errors=True)
        return n if not os.path.exists(path) else 0
    try:
        os.remove(path)
        return 1
    except OSError:
        return 0


def _files(d):
    """[(mtime, size, path)] of every file under `d`, links not followed."""
    out = []
    for base, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if not p4conf.is_link(os.path.join(base, x))]
        for n in names:
            p = os.path.join(base, n)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            out.append((st.st_mtime, st.st_size, p))
    return out


def _prune_empty(d, keep):
    for base, dirs, names in os.walk(d, topdown=False):
        if base == keep:
            continue
        try:
            if not os.listdir(base):
                os.rmdir(base)
        except OSError:
            pass


def sweep_cache(p4, now=None):
    """Clear by the cache rules -> [(rule, files cleared)]."""
    now = time.time() if now is None else now
    out = []
    for rel, rule in sorted(rules(p4).items()):
        rel = rel.strip("/")
        if not rel or never(rel) or not isinstance(rule, dict):
            continue
        d = os.path.join(home(p4), *rel.split("/"))
        if not os.path.isdir(d):
            continue
        files = sorted(_files(d))                       # oldest first
        gone = 0
        age = rule.get("max_age_days")
        if age is not None:
            cutoff = now - float(age) * 86400
            keep = []
            for mt, size, p in files:
                if mt < cutoff and not os.path.basename(p) == ".gitignore" and remove(p):
                    gone += 1
                else:
                    keep.append((mt, size, p))
            files = keep
        cap = rule.get("max_mb")
        if cap is not None:
            total, limit = sum(s for _, s, _ in files), float(cap) * 1024 * 1024
            for mt, size, p in files:
                if total <= limit:
                    break
                if os.path.basename(p) != ".gitignore" and remove(p):
                    total -= size
                    gone += 1
        _prune_empty(d, d)
        if gone:
            out.append((rel, gone))
    return out


def sweep_cookies(p4, now=None, ended_session=""):
    """Clear every cookie whose time is up, and the session cookies of `ended_session` -> [rel cleared]."""
    now = time.time() if now is None else now
    d = read_expires(p4)
    cleared, changed = [], False
    for rel, v in sorted(d.items()):
        due = (isinstance(v, dict) and (("expires" in v and float(v["expires"]) <= now)
                                         or (ended_session and v.get("session") == ended_session)))
        if not due:
            continue
        p = os.path.join(home(p4), *rel.split("/"))
        if os.path.lexists(p):
            remove(p)
        if not os.path.lexists(p):
            cleared.append(rel)
            del d[rel]
            changed = True
    if changed:
        write_expires(p4, d)
    return cleared


def sweep(p4, now=None, ended_session=""):
    """Both sweeps; a tracked removal is staged. -> the line to print, or ''."""
    if not os.path.isdir(home(p4)):
        return ""
    cache = sweep_cache(p4, now)
    cookies = sweep_cookies(p4, now, ended_session)
    if not cache and not cookies:
        return ""
    if _own_repo(p4):
        _git(p4, "add", "-u", "--", "temportal")
    parts = [f"{n} file(s) past the cache rule for {rel}/" for rel, n in cache]
    if cookies:
        shown = ", ".join(cookies[:5]) + (f" (+{len(cookies) - 5} more)" if len(cookies) > 5 else "")
        parts.append(f"{len(cookies)} expired file(s): {shown}")
    return "p4-temportal: cleared " + "; ".join(parts) + "."


def listing(p4, now=None):
    now = time.time() if now is None else now
    lines = []
    for rel, v in sorted(read_expires(p4).items()):
        if "expires" in v:
            left = float(v["expires"]) - now
            when = datetime.fromtimestamp(float(v["expires"]), timezone.utc).astimezone().isoformat(timespec="minutes")
            lines.append(f"cookie  {rel}  expires {when}" + ("  (due)" if left <= 0 else ""))
        elif "session" in v:
            lines.append(f"cookie  {rel}  until session {v['session'][:8]} ends")
    for rel, rule in sorted(rules(p4).items()):
        lines.append(f"cache   {rel}/  " + ", ".join(f"{k}={v}" for k, v in rule.items()))
    return lines


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    sub = args[0] if args else ""
    if sub in ("sweep", "session-end"):
        payload = payload_from_stdin()
        try:
            p4 = store_of(project_root(payload))
            p4conf.migrate_layout(p4)
            ended = str(payload.get("session_id") or "") if sub == "session-end" else ""
            line = sweep(p4, ended_session=ended)
            if line and sub == "sweep":
                print(line)
        except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
            print(f"p4-temportal lifetime ({sub}) degraded: {type(e).__name__}: {e}")
        return 0
    import argparse
    ap = argparse.ArgumentParser(prog="lifetime.py", description="p4-temportal: cookie and cache lifetimes")
    ap.add_argument("--p4", default=None, help="the store, <project>/.claude/p4 (default: from CLAUDE_PROJECT_DIR)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("set", help="give a file or directory under temportal/ an expiry")
    s.add_argument("path")
    s.add_argument("lifetime", help="30m, 12h, 7d, 2w, an ISO date, or 'session'")
    s.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""))
    c = sp.add_parser("clear", help="remove a file's expiry, keeping the file")
    c.add_argument("path")
    sp.add_parser("list", help="every cookie and cache rule")
    sp.add_parser("now", help="sweep now")
    a = ap.parse_args(args)
    p4 = a.p4 or store_of(project_root({}))
    if a.cmd == "set":
        try:
            rel, v = set_cookie(p4, a.path, a.lifetime, a.session)
        except ValueError as e:
            print(f"lifetime.py: {e}", file=sys.stderr)
            return 2
        print(f"{rel}: " + (f"until session {v['session'][:8]} ends" if "session" in v else
                            "expires " + datetime.fromtimestamp(v["expires"]).isoformat(timespec="minutes")))
    elif a.cmd == "clear":
        print("cleared" if clear_cookie(p4, a.path) else "no expiry was set")
    elif a.cmd == "list":
        print("\n".join(listing(p4)) or "nothing has a lifetime")
    else:
        print(sweep(p4) or "nothing has expired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
