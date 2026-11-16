#!/usr/bin/env python3
"""lifetime.py: p4-temportal's lifetimes, how long a file under `<project>/.claude/p4/temportal/` is kept.

Two kinds of lifetime clear files, as a browser clears its cache and its cookies. A cache rule per folder, in the
p4.json section `temportal.cache` with paths relative to temportal/, clears the files older than `max_age_days`, and
then the oldest files while the folder holds more than `max_mb`. A cookie is one file or folder with its own expiry,
set by `lifetime.py set <path> <lifetime>` and kept in temportal/expires.json, and the lifetime `session` clears it
when the session that set it ends. A cache rule whose path resolves to memory/, in any letter case, or to a folder
outside temportal/ clears nothing. A cookie is refused inside memory/, on tmp/ or anything in it, and on scratchpad/,
src/ or expires.json themselves: a session scratchpad directory in tmp/ is committed before it is removed, and the
others are never cleared whole.

A file the store's git tracks is removed with its removal staged, so its last version stays in the history, and an
ignored or untracked file is deleted.

  sweep                    the retention sweep at SessionStart: clears what has expired and prints one line when it
                           cleared something.
  session-end              the retention sweep at SessionEnd, which also clears the cookies of the session that ends,
                           silently.
  set <path> <lifetime>    gives a file or folder under temportal/ a cookie. The path must exist, and a relative
                           one is read from the working folder.
  list                     every cookie with its expiry, then every cache rule. An entry of expires.json that cannot
                           be read is listed as unreadable, and the retention sweep leaves it as it is.
  clear <path>             removes a cookie and keeps the file, reading a relative path from the working folder.
  now                      the retention sweep, run by hand.

A failure in a hook prints a one-line notice and exits 0.
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
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json

EXPIRES = "expires.json"
NEVER = ("memory",)                     # folders no lifetime ever clears
WHOLE = ("scratchpad", "src", EXPIRES)  # the notebook, the saved code and the cookies, which no cookie clears whole
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
        raise ValueError(f"not a lifetime: {text!r}; use 30m, 12h, 7d, 2w, an ISO date or 'session'")
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


def rel_in(p4, path):
    """`path`, absolute or relative to temportal/, as a path relative to temportal/ with forward slashes once links
    and `..` are resolved, or None when it is temportal/ itself or outside it."""
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
    return rel.split("/")[0].lower() in NEVER


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
    """Give `path`, a file or folder under temportal/, an expiry -> (rel, expiry). A relative `path` is read from
    temportal/, and the command line makes it absolute from the working folder first. Raises ValueError for a path
    outside temportal/, inside memory/, on tmp/ or inside it, that is one of WHOLE or that does not exist, and for a
    lifetime it cannot read."""
    rel = rel_in(p4, path)
    if rel is None:
        raise ValueError(f"{path} is not under {home(p4)}")
    if never(rel):
        raise ValueError(f"{rel} is in {rel.split('/')[0]}/, which is never cleared")
    if rel.split("/")[0].lower() == "tmp":
        raise ValueError(f"{rel} takes no cookie: a session scratchpad directory is committed before it is removed")
    if rel.lower() in WHOLE:
        raise ValueError(f"{rel} takes no cookie: scratchpad/, src/ and {EXPIRES} are never cleared whole")
    if not os.path.lexists(os.path.join(home(p4), *rel.split("/"))):
        raise ValueError(f"{path} does not exist")
    when = parse_lifetime(lifetime, now)
    d = read_expires(p4)
    if when == SESSION:
        if not session_id:
            raise ValueError("a 'session' lifetime needs the session id: pass --session")
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
    """Delete a file or a whole folder, removing a link as a link -> the count of files removed."""
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
    """Clear by each cache rule in the folder its key resolves to under temportal/ -> [(folder, files cleared)]."""
    now = time.time() if now is None else now
    out = []
    for key, rule in sorted(rules(p4).items()):
        rel = rel_in(p4, key.strip("/"))
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
    """Clear every cookie whose time is up, and the session cookies of `ended_session` -> [rel cleared]. An entry
    whose expiry cannot be read is left as it is."""
    now = time.time() if now is None else now
    d = read_expires(p4)
    cleared, changed = [], False
    for rel, v in sorted(d.items()):
        try:
            due = (isinstance(v, dict) and (("expires" in v and float(v["expires"]) <= now)
                                             or (ended_session and v.get("session") == ended_session)))
        except (TypeError, ValueError):
            due = False
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
    """The retention sweep: the cache rules, then the cookies, with a tracked removal staged -> the line to print,
    or ''."""
    if not os.path.isdir(home(p4)):
        return ""
    cache = sweep_cache(p4, now)
    cookies = sweep_cookies(p4, now, ended_session)
    if not cache and not cookies:
        return ""
    if _own_repo(p4):
        _git(p4, "add", "-u", "--", "temportal")
    parts = [f"files past the cache rule: {n}, in {rel}/" for rel, n in cache]
    if cookies:
        shown = ", ".join(cookies[:5]) + (f" and {len(cookies) - 5} more" if len(cookies) > 5 else "")
        parts.append(f"expired files: {len(cookies)}, {shown}")
    return "p4-temportal: cleared " + "; ".join(parts) + "."


def listing(p4, now=None):
    now = time.time() if now is None else now
    lines = []
    for rel, v in sorted(read_expires(p4).items()):
        line = ""
        try:
            if "expires" in v:
                t = float(v["expires"])
                when = datetime.fromtimestamp(t, timezone.utc).astimezone().isoformat(timespec="minutes")
                line = f"cookie  {rel}  expires {when}" + ("  past due" if t <= now else "")
            elif "session" in v:
                line = f"cookie  {rel}  until session {v['session'][:8]} ends"
        except (TypeError, ValueError, OverflowError, OSError):
            pass
        lines.append(line or f"cookie  {rel}  unreadable, so never cleared: {json.dumps(v)}")
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
            print(f"p4-temportal lifetime {sub} degraded: {type(e).__name__}: {e}")
        return 0
    import argparse
    ap = argparse.ArgumentParser(prog="lifetime.py", description="p4-temportal: cookie and cache lifetimes")
    ap.add_argument("--p4", default=None, help="the store, <project>/.claude/p4, by default from CLAUDE_PROJECT_DIR")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("set", help="give a file or folder under temportal/ an expiry")
    s.add_argument("path")
    s.add_argument("lifetime", help="30m, 12h, 7d, 2w, an ISO date, or 'session'")
    s.add_argument("--session", default=os.environ.get("CLAUDE_SESSION_ID", ""))
    c = sp.add_parser("clear", help="remove a file's expiry, keeping the file")
    c.add_argument("path")
    sp.add_parser("list", help="every cookie and cache rule")
    sp.add_parser("now", help="run the retention sweep now")
    a = ap.parse_args(args)
    p4 = a.p4 or store_of(project_root({}))
    if a.cmd == "set":
        try:
            rel, v = set_cookie(p4, os.path.abspath(a.path), a.lifetime, a.session)
        except ValueError as e:
            print(f"lifetime.py: {e}", file=sys.stderr)
            return 2
        print(f"{rel}: " + (f"until session {v['session'][:8]} ends" if "session" in v else
                            "expires " + datetime.fromtimestamp(v["expires"]).isoformat(timespec="minutes")))
    elif a.cmd == "clear":
        print("cleared" if clear_cookie(p4, os.path.abspath(a.path)) else "no expiry was set")
    elif a.cmd == "list":
        print("\n".join(listing(p4)) or "nothing has a lifetime")
    else:
        print(sweep(p4) or "nothing has expired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
