"""gaps.py: a memory that patches over a plugin's behaviour starts a new top session for that plugin gap.

A session writes a feedback memory into the store's temportal/memory/ when a plugin did not do what the owner wanted:
"a child never merges", "a store moves only by p4.py sync". Each such memory hid a gap that belonged in the plugin,
and an audit had to find six of them later and file them as issues. So when a session writes a feedback memory whose
rule describes session or plugin behaviour, phi advises a new top session in the plugin's own project, to file the
issue on the plugin's repository and have a child fix it. A memory about code style gets nothing.

The plugin's project is read from CLAUDE_PLUGIN_ROOT: the git top level of the marketplace checkout it runs from,
with `origin` as the issue repository, and the folder above it that holds a p4 store, when one does, so the new
session keeps its tree there. A plugin installed from a GitHub marketplace runs from a cache that is no checkout: the
repository is read from known_marketplaces.json, a clone of it found beside a store this machine knows is used, and
with none the session goes to the cloud for that repository.
"""

import hashlib
import json
import os
import re

import relay

BEHAVIOUR = re.compile(
    r"\b(sessions?|child(?:ren)?|parent|top session|orchestrat\w*|sub-?agents?|worktrees?|branch(?:es)?|relay\w*|"
    r"archiv\w*|push\w*|merg\w*|sync\w*|hooks?|plugins?|p4-\w+|phi|stores?|scratchpad|tmp|plan steps?|task list|"
    r"turns?|SendMessage|start_session|briefs?|reports?|memor(?:y|ies)|temportal|wait\w*|ask\w* first|"
    r"go-?ahead|issues?)\b", re.I)
STYLE = re.compile(r"\b(indent\w*|tabs?|spaces|naming|variable names?|braces?|semicolons?|quotes?|line length|"
                   r"formatt\w*|lint\w*|code style|docstrings?|comments?|camel\w*|snake\w*|imports?|typing|"
                   r"type hints?|prose|parenthetical\w*|markdown|line breaks?)\b", re.I)
FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def memory_dir(store):
    import p4conf
    return relay.norm(p4conf.sub(store, "memory")) if store else ""


def memory_of(store, path):
    """(name, rule body) of a feedback memory written at `path` in the store's memory folder; None otherwise."""
    p, mem = relay.norm(path), memory_dir(store)
    if not mem or not p.startswith(mem + "/") or not p.endswith(".md") or p.endswith("/memory.md"):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            m = FRONT.match(f.read().replace("\r\n", "\n"))
    except (OSError, UnicodeDecodeError):
        return None
    if not m or not re.search(r"(?m)^\s*type:\s*feedback\b", m.group(1)):
        return None
    name = re.search(r"(?m)^name:\s*(.+)$", m.group(1))
    return (name.group(1).strip() if name else os.path.basename(path)[:-3]), m.group(2).strip()


def rule_text(body):
    """The rule itself: the body before its **Why:** and **How to apply:** lines."""
    head = re.split(r"\n\s*\*\*(?:Why|How to apply)", body, maxsplit=1)[0]
    return " ".join(head.split())


def about_behaviour(body):
    """True when a rule describes how sessions or the plugins behave, not how code is written: two behaviour words
    or more, and more of them than style words."""
    text = rule_text(body)
    beh = {m.lower() for m in BEHAVIOUR.findall(text)}
    sty = {m.lower() for m in STYLE.findall(text)}
    return len(beh) >= 2 and len(beh) > len(sty)


def _git(path, *args):
    r = relay._git(path, *args)
    return r.stdout.strip() if r is not None and r.returncode == 0 else ""


def repo_name(url):
    """owner/name of a GitHub remote, '' for another host."""
    key = relay.remote_key(url)
    return key.split("/", 1)[1] if key.startswith("github.com/") and key.count("/") == 2 else ""


def _marketplace_repo(root):
    """owner/name of the GitHub marketplace a cached plugin was installed from, '' when unknown."""
    p = relay.norm(root)
    m = re.search(r"/plugins/cache/([^/]+)/", p + "/")
    if not m:
        return ""
    conf = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    known = relay._read_json(os.path.join(conf, "plugins", "known_marketplaces.json"))
    for name, d in known.items():
        if str(name).lower() != m.group(1):
            continue
        src = (d or {}).get("source") or {}
        if src.get("repo"):
            return str(src["repo"])
        if src.get("url"):
            return repo_name(src["url"])
    return ""


def _known_clone(repo):
    """A checkout of `repo` on this machine: a project of a store this machine knows, or a folder in it."""
    want = "github.com/" + repo.lower()
    for store in set(relay._read_json(relay.stores_map_path()).values()):
        project = os.path.dirname(os.path.dirname(str(store)))
        try:
            subs = [os.path.join(project, n) for n in os.listdir(project)]
        except OSError:
            continue
        for d in [project] + [x for x in subs if os.path.isdir(os.path.join(x, ".git"))]:
            if relay.remote_key(_git(d, "remote", "get-url", "origin")) == want:
                return relay.norm(d)
    return ""


def project_with_store(top):
    """The plugin's project: the checkout's top level, or the nearest folder above it holding a p4 store."""
    d = top
    for _ in range(3):
        if os.path.isdir(os.path.join(d, ".claude", "p4")):
            return relay.norm(d)
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return relay.norm(top)


def plugin_project(root=None):
    """{"cwd", "repo", "store", "cloud"} for the plugin running this hook; {} when its repository is unknown."""
    root = root or os.environ.get("P4_PHI_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT") or ""
    if not root:
        return {}
    top = _git(root, "rev-parse", "--show-toplevel")
    repo = repo_name(_git(top, "remote", "get-url", "origin")) if top else ""
    if top and repo and "/plugins/marketplaces/" not in relay.norm(top) + "/":
        cwd = project_with_store(top)
        return {"cwd": cwd, "repo": repo, "store": os.path.join(cwd, ".claude", "p4") if
                os.path.isdir(os.path.join(cwd, ".claude", "p4")) else "", "cloud": False}
    repo = repo or _marketplace_repo(root)
    if not repo:
        return {}
    clone = _known_clone(repo)
    if clone:
        cwd = project_with_store(clone)
        return {"cwd": cwd, "repo": repo, "store": os.path.join(cwd, ".claude", "p4") if
                os.path.isdir(os.path.join(cwd, ".claude", "p4")) else "", "cloud": False}
    return {"cwd": "", "repo": repo, "store": "", "cloud": True}


def brief_of(name, path, rule, repo, new_top):
    return (f"A session wrote a feedback memory that patches over plugin behaviour, so the gap belongs in the plugin. "
            f"The memory, `{name}` at {relay.norm(path)}, says: \"{rule}\" Check whether the plugin does this "
            f"already; if not, file the issue with `gh issue create -R {repo}`, quoting the rule and saying what the "
            f"plugin does now and what it should do, then have a child fix it, archive when done. {new_top}")


def advice(home, store, s, path, owner_turn, commands, new_top, root=None):
    """The line a session gets after writing a plugin-gap memory into its project's store, once per memory content;
    '' for any other write. `home` holds the session tree, `store` the project's memory."""
    got = memory_of(store, path)
    if not got or not about_behaviour(got[1]):
        return ""
    name, body = got
    rule = rule_text(body)
    sig = hashlib.sha1((name + "\n" + rule).encode("utf-8", "replace")).hexdigest()[:12]
    spath = os.path.join(relay._dir(home, s["sessionId"]), "session.json")
    disk = relay._read_json(spath)
    told = [x for x in disk.get("gapsTold") or [] if isinstance(x, str)]
    if sig in told:
        return ""
    proj = plugin_project(root)
    if not proj:
        return ""
    if disk:
        disk["gapsTold"] = (told + [sig])[-50:]
        relay._write_json(spath, disk)
    title = f"Plugin gap: {name}"
    brief = brief_of(name, path, relay._short(rule, 600), proj["repo"], new_top)
    head = (f"phi (p4-phi): the memory `{name}` you just wrote describes session or plugin behaviour, so it patches "
            f"over a gap in the plugin ({proj['repo']}). A new top session takes it, in the plugin's own project: ")
    if proj["cloud"]:
        call = {"initiation": "user_asked", "title": title, "context": "fresh", "target": "cloud",
                "repository": proj["repo"], "prompt": brief}
        where = "no clone of it is known on this machine, so it runs in the cloud on that repository"
    else:
        call = {"initiation": "user_asked", "title": title, "context": "fresh", "use_worktree": False,
                "cwd": proj["cwd"], "prompt": brief}
        where = f"in {proj['cwd']}"
    if not owner_turn and not proj["cloud"] and proj["store"]:
        import starts
        rid, new = starts.add(proj["store"], s["sessionId"], title, brief)
        return (head + f"this turn was started by another session, not the user, so the app refuses `user_asked`; "
                f"phi kept it as start request {rid} in {relay.norm(proj['store'])}, {where}: the next turn the user "
                f"begins in a session of that store starts it. Ask the user nothing about it, and carry on.")
    if not owner_turn:
        return (head + f"this turn was started by another session, so write it as a start request, `{commands} "
                f"request \"{title}\" --brief \"<the brief below>\"`, and carry on. Its brief: {brief}")
    return head + f"start it now, {where}, with `mcp__ccd_session__start_session` and {json.dumps(call)}."
