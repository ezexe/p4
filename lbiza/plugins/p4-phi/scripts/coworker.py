#!/usr/bin/env python3
"""coworker.py: the terminal sessions p4-phi starts, for `phi.py coworkers`, `sections` and `draft --start`.

A terminal worker is a node, relay.claim makes it a store nested in its starter's, where its start file, settings
file, brief and report are, and it runs in the checkout and reaches them by their whole paths: one worker lands each
group of an approved plan's sections, sections.groups, and one starts for each draft that has a parent. A planner is
such a worker started in plan mode with the team variable set, which forms its three reading teammates in its own
session. `drafts` only prints a plan's groups. The pages, read on 2026-11-23:
- agent-teams.md: "In non-interactive mode with the `-p` flag, including Agent SDK sessions, Claude doesn't spawn
  teammates", so the run is interactive, and a team is enabled by "setting the
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable to `1`", which the start file does in its own shell.
- `claude --help`: `--session-id <uuid>`, "Use a specific session ID for the conversation", which finds a reading
  team's transcripts.
- cli-reference.md: `--settings` takes "Path to a settings JSON file or an inline JSON string".
The settings file turns p4's plugins off, so
no hook of p4 runs in the coworker and none sets up a store. The lead of the first read run this way, on 2026-11-23
with p4-phi and p4-temportal off, led three teammates, where no `.claude` folder appeared. Neither has `--add-dir`:
for a folder Claude Code has not seen it asks whether the folder is trusted, and a `claude -p` in auto mode read and
wrote a file of another folder's nested store by its whole path with none, on 2026-11-23.
"""

import glob
import hashlib
import json
import os
import re
import time

import p4conf
import plans
import relay
import sections
import transcript
import upkeep

SETTINGS_FILE = "coworker-settings.json"
TEAMS = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
PLAIN = re.compile(r"[^\w .,:#/-]")               # a task line holds no quote of any kind and no shell character


def settings(checkout, temportal=False):
    """The settings file's text: p4-phi and p4-temportal off, p4-temportal left on with `temportal`, which a planner
    needs for the skill `plan-planner`, and `claudeMdExcludes` naming, with forward slashes,
    each CLAUDE.local.md in a folder above `checkout` that holds the line p4conf.LINE, the key left out where there
    is none. Such a file's import resolves outside the checkout, and Claude Code then asks "Allow external CLAUDE.md
    file imports?" and starts nothing; with the file excluded an interactive `claude` asked nothing, on 2026-11-23.
    memory.md's "Exclude specific CLAUDE.md files" is the key; no setting approves the import, and the session has
    the p4 plugins off, so it needs no store text."""
    d = {"enabledPlugins": {f"{n}@{p4conf.MARKET}": bool(temportal and n == "p4-temportal")
                            for n in ("p4-phi", "p4-temportal")}}
    out, at = [], os.path.abspath(checkout)
    while True:
        up = os.path.dirname(at)
        if up == at:
            break
        at = up
        path = os.path.join(at, "CLAUDE.local.md")
        try:
            with open(path, encoding="utf-8") as f:
                held = p4conf.LINE in [x.strip() for x in f.read().splitlines()]
        except OSError:
            continue
        if held:
            out.append(path.replace("\\", "/"))
    if out:
        d["claudeMdExcludes"] = out
    return json.dumps(d)


def plain(text):
    return PLAIN.sub(" ", str(text).replace("\\", "/"))


def _named(prefix, title, numbers, path):
    stem = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:16].strip("-") or "plan"
    mark = hashlib.sha1(os.path.abspath(path).replace("\\", "/").lower().encode("utf-8")).hexdigest()[:4]
    return f"{prefix}-{stem}-" + "-".join(numbers) + f"-{mark}"


def worker_name(plan, numbers):
    """A terminal worker's name, which names its session and its files: `tw-` and the rest as name_of builds it,
    from the title of the plan file `plan` and the section numbers `numbers`."""
    with open(plan, encoding="utf-8") as f:
        title = sections.parse(f.read())[0]
    return _named("tw", title, list(numbers), plan)


def level():
    """The model and effort a coworker starts on: the kind `static`, an integrator's, since it lands written fences,
    with the effort held to the starting session's own."""
    out = dict(plans.CHILD_LEVELS["static"])
    out["effort"] = plans.capped(out["effort"])
    return out


def planner_task(title):
    """A planner's prompt, one line with no quote and no shell character: the plan of the brief in plan mode by the
    skill plan-planner, a team of three that only reads, the rounds in this session and the plan put to ezexe."""
    return (f"Write the plan for {plain(title)} in plan mode by the skill plan-planner. Form three teammates named "
            f"fences, sources and checks that only read, run the rounds of the plan in this session, and put the "
            f"plan to ezexe with ExitPlanMode.")


def script(name, checkout, mode, said, folder, windows=None, team=True, extra=(), session=""):
    """A coworker's start script, as (its file's name, its lines, the line typed into the tab): what a desktop
    session's shell hands down is cleared, the team variable is set, and `claude` starts in the checkout, with no
    worktree, and the settings file of `folder`. `session` adds
    `--session-id <uuid>` right after the name. A terminal worker's has `team` off and its `extra`
    flags, each a word spelled as the shell reads it, after those. A quote in the prompt `said` is refused as one in
    a path is, since the prompt stands between quotes."""
    windows = upkeep.WINDOWS if windows is None else windows
    sep = "\\" if windows else "/"
    here, at = checkout.replace("\\", "/").replace("/", sep), folder.replace("\\", "/").replace("/", sep)
    for path in (here, at, said):
        if re.search(r"['\"`]", path):
            raise ValueError(f"a start file's paths hold no quote: {path}")
    lv = level()
    flags = "".join(f" --{k} {lv[k]}" for k in ("model", "effort") if str(lv.get(k) or "inherit") != "inherit")
    run = (f"claude --name {name}" + (f" --session-id {session}" if session else "")
           + "".join(f" {x}" for x in extra)
           + flags + (f" --permission-mode {mode}" if mode else "")
           + f" --settings '{at}{sep}{SETTINGS_FILE}' '{said}'")
    if windows:
        names = ", ".join(f"'{n}'" for n in upkeep.CARRIED)
        return (f"start-{name}.ps1",
                [f"foreach ($n in {names}) {{ Remove-Item -Path ('Env:' + $n) -ErrorAction SilentlyContinue }}",
                 *([f"$env:{TEAMS} = '1'"] if team else []), f"Set-Location '{here}'", run],
                f"& '{at}\\start-{name}.ps1'")
    return (f"start-{name}.sh", [f"unset {' '.join(upkeep.CARRIED)}", *([f"export {TEAMS}=1"] if team else []),
                                 f"cd '{here}'", run], f"sh '{at}/start-{name}.sh'")


def _quoted(*paths):
    for path in paths:
        if re.search(r"['\"`]", str(path)):
            raise ValueError(f"a start file's paths hold no quote: {path}")


def _node(home, store, name, kind, starter, nums, checkout, session=""):
    """(the folder `<node>/phi` of a new node `name`, ""), or (None, its folder) where the name has a node already,
    whose session was started once. Raises ValueError where no store could be made."""
    have = relay.nodes(home).get(name)
    if have:
        return None, os.path.join(have, "phi").replace("\\", "/")
    made = relay.claim(home, store, name, kind, starter, nums, session=session, checkout=checkout)
    if not made:
        raise ValueError(f"no store could be made for {name} under {store}: its path would be too long")
    return os.path.join(made, "phi").replace("\\", "/"), ""


def _undo(home, found):
    """Removes the nodes this call claimed, which hold only their node.json, so a name is not stranded by a call
    that failed after its claim."""
    for one in found:
        if one.get("folder"):
            relay.unclaim(home, one["name"])


def drafts(path, checkout):
    """One entry for each group of the plan at `path`, in the plan's order: its sections, its fences and whether it
    earns a team. Nothing is made and nothing is checked: a planner reads it to write its Distribution."""
    with open(path, encoding="utf-8") as f:
        title, found = sections.parse(f.read(), checkout)
    return [{"sections": [s["n"] for s in group], "fences": sections.fences(group), "team": sections.team(group)}
            for group in sections.groups(found)]


def write(found, checkout, home=""):
    """The settings file, settings(checkout), each worker's start file and each worker's brief,
    written into the node folder of each entry that has one. The paths written. Where a write fails, what this call
    wrote is removed and, with `home`, the nodes of those entries too, and the error goes out."""
    wrote = []
    try:
        for one in found:
            if not one.get("folder"):
                continue
            files = {SETTINGS_FILE: settings(checkout, bool(one.get("temportal")))}
            if one.get("file"):
                files[one["file"]] = "\n".join(one["lines"])
            if one.get("brief"):
                files[os.path.basename(one["brief_file"])] = one["brief"]
            os.makedirs(one["folder"], exist_ok=True)
            for name, body in files.items():
                at = os.path.join(one["folder"], name)
                with open(at, "w", encoding="utf-8", newline="\n") as f:
                    wrote.append(at.replace("\\", "/"))
                    f.write(body + "\n")
    except Exception:
        for at in wrote:
            try:
                os.remove(at)
            except OSError:
                pass
        if home:
            _undo(home, found)
        raise
    return wrote


QUIET = 90                       # seconds with no line written by a coworker or an agent under it
FIRST = 300                      # the most a watch waits for a round's first line, in seconds
LONGEST = 3600                   # the most one watch waits, in seconds


def kept(name, home, checkout, deep=False):
    """The transcripts Claude Code keeps for the coworker `name`, its own and with `deep` those of the agents under
    it, by the session id of its node.json: `<session>.jsonl` and the files under the folder `<session>`, in the
    folder of `projects` Claude Code names after the checkout its node.json keeps, or `checkout` where it keeps
    none, with each character that is no letter or digit as "-", or in any folder of `projects` where neither
    names one. [] where the name has no node or no session id."""
    n = relay.node_record(home, name) if home else {}
    session = str(n.get("session") or "")
    if not re.fullmatch(r"[A-Za-z0-9-]+", session):
        return []
    checkout = str(n.get("checkout") or checkout or "")
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    folder = os.path.join(base, "projects", re.sub(r"[^A-Za-z0-9]", "-", checkout) if checkout else "*")
    found = glob.glob(os.path.join(folder, session + ".jsonl"))
    if deep:
        found += glob.glob(os.path.join(folder, session, "**", "*.jsonl"), recursive=True)
    return sorted(found)


def watch(names, home, checkout, quiet=QUIET, longest=LONGEST, first=FIRST, clock=time.time, sleep=time.sleep):
    """A round's wait, as (how it ended, the seconds waited). `quiet`: a coworker of `names`, or an agent under one,
    wrote a line of its transcript after the watch began, and then none did for `quiet` seconds. `silent`: none
    wrote a line in the first `first` seconds, as where the round's message did not arrive or a name is no
    coworker's, so a coworker that was idle before the round is not taken for one that finished it. `long`:
    `longest` seconds passed. The planner runs it as one background command after it sends a round, in place of an
    idle notice from each coworker."""
    start = clock()
    while clock() - start < longest:
        last = max((os.path.getmtime(p) for name in names for p in kept(name, home, checkout, deep=True)),
                   default=0.0)
        now = clock()
        if last < start and now - start >= first:
            return "silent", int(now - start)
        if last >= start and now - last >= quiet:
            return "quiet", int(now - start)
        sleep(10)
    return "long", int(clock() - start)


def stopped(name, home, checkout):
    """True where an error of the API ended the last turn of the coworker `name`: the last row of type `assistant`
    in its newest transcript is marked `isApiErrorMessage`, as Claude Code marks `API Error: 529 Overloaded`."""
    mains = sorted(kept(name, home, checkout), key=os.path.getmtime)
    rows = [r for r in transcript.read_lines(mains[-1]) if r.get("type") == "assistant"] if mains else []
    return bool(rows) and bool(rows[-1].get("isApiErrorMessage"))


PHI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phi.py").replace("\\", "/")
TEAMMATES = ("fences", "sources", "checks")
AGENT_ID = re.compile(r"a[0-9a-f]{6,}(?:-[0-9a-z]+)*|local_[0-9a-f-]+")
TURNS = 60                                     # the goal page: a goal with no turn or time clause has no cap
# The mode every terminal worker of land() starts in, whatever its starter's: a worker is unattended, and in auto
# mode the classifier refused a step of the plan it was landing, a nested `claude -p`, seen on 2026-11-23 with
# the worker tw-one-checkout-for-1-2-cf08. permission-modes.md gives `bypassPermissions` as the mode that asks
# for nothing but a protected path. See more: https://code.claude.com/docs/en/permission-modes.md
LAND_MODE = "bypassPermissions"


def land(path, checkout, who, mode, home="", starter="", store="", claim=False, windows=None):
    """One entry for each group of the plan at `path` that is not landed, in the plan's order: the terminal worker
    that lands it, started once ezexe approved the plan. `name` and `sections`, and with `claim` the node relay.claim
    makes for it in the store `store` of its starter `starter`, and in the node's folder the `brief` text and its
    file, the `report` file the worker writes, its `goal`, and the start file's name, `lines` and the line `typed` in
    its tab; a name that has a node already gets `started`, its node's folder, and nothing else. The worker has no
    worktree, no team, no p4 plugin and no `--add-dir`: its goal is its prompt, since no hooks module sets one. It
    starts in LAND_MODE, and `mode`, its starter's, is not read."""
    windows = upkeep.WINDOWS if windows is None else windows
    plan = os.path.abspath(path).replace("\\", "/")
    checkout = checkout.replace("\\", "/")
    if claim:                                      # every path before the first claim
        _quoted(plan, checkout, home, store)
    with open(path, encoding="utf-8") as f:
        title, found = sections.parse(f.read(), checkout)
    out = []
    for group in sections.groups(found):
        nums = [s["n"] for s in group]
        out.append({"name": worker_name(path, nums), "sections": nums, "group": group})
    if not claim:
        return [{k: v for k, v in one.items() if k != "group"} for one in out]
    try:
        for one in out:
            _worker(one, plan, title, checkout, mode, home, starter, store, windows)
    except Exception:
        _undo(home, out)
        raise
    return out


def _worker(one, plan, title, checkout, mode, home, starter, store, windows):
    """The node of one terminal worker of land(), and its brief, goal and start file in it."""
    group, nums = one.pop("group"), one["sections"]
    many = "s" if len(group) > 1 else ""
    done = f"Every fence of section{many} {', '.join(nums)} of the plan {plan} is landed, its Checks pass"
    one.update(worker(one["name"], sections.brief(plan, title, group, checkout, []), done, checkout, home, starter,
                      store, nums, windows))


def worker(name, brief, done, checkout, home, starter, store, nums=(), windows=None, team=False, mode=LAND_MODE,
           extra=(), prompt=""):
    """The node of one terminal worker and its brief, goal and start file in it, as one entry: `name`, and either
    `started`, the folder of a node that holds that name already, or `folder`, `brief` and `brief_file`, `report`,
    `goal`, and the start file's `file`, `lines` and the line `typed` in its tab. `done` is what the goal waits
    for, one sentence with no quote. The worker has no worktree and no p4 plugin, and its goal is its prompt. With
    `prompt`, a planner's, that line stands in place of the goal, closed with the brief's file, and the settings file
    leaves p4-temportal on for the skill plan-planner."""
    windows = upkeep.WINDOWS if windows is None else windows
    checkout = checkout.replace("\\", "/")
    _quoted(checkout, home, store)
    one = {"name": name}
    folder, there = _node(home, store, name, "worker", starter, list(nums), checkout)
    if there:
        one["started"] = there
        return one
    one["folder"] = folder
    brief_file, report = f"{folder}/brief-{name}.md", f"{folder}/report-{name}.md"
    where = [f"Work in {checkout}, on the branch that is checked out, and make no worktree and no branch.",
             "Commit only with this command, one commit for each part, naming every path it changed, added or "
             "removed and no other:",
             f'python -I -X utf8 {PHI} commit --checkout {checkout} -m "<message>" -- <path> ...',
             "Never `git add -A`, `git commit -a` or a plain `git commit`. Push nothing and merge nothing.",
             "Publish no issue: a finding goes into the report as one line that opens `Finding:`.",
             f"When every check passes, write your report to {report} and end.", ""]
    goal = (f"/goal {plain(done)}, as the brief {brief_file} says, and the report {report} is written; or a part "
            f"does not fit the tree and the report says which and why. Stop after {TURNS} turns, and write the "
            "report first with what is done and what is not.")
    if prompt:
        goal = f"{prompt} The brief is {brief_file}, and the report {report} is written when the plan is put."
    try:
        file, lines, typed = script(name, checkout, mode, goal, folder, windows, team=team, extra=extra)
    except Exception:
        relay.unclaim(home, name)
        raise
    one.update(brief="\n".join([*where, brief]), brief_file=brief_file, report=report, goal=goal,
               file=file, lines=lines, typed=typed, temportal=bool(prompt))
    return one


def draft_name(title, did):
    """A drafted worker's name: `tw-`, the title's slug cut at 24 characters, and the draft id's last four."""
    stem = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:24].strip("-") or "work"
    return f"tw-{stem}-{str(did)[-4:]}"


def wait_report(report, home="", name="", longest=LONGEST, clock=time.time, sleep=time.sleep):
    """A terminal worker's wait, as (how it ended, the seconds waited): `done` as soon as its report file is there
    and was written after the wait began, so the first report of a worker that went on working is no answer to a wait
    made after it, whatever the claim time of its node `name`. `long` after `longest` seconds. It reads no
    transcript."""
    since = time.time()
    start = clock()

    def written():
        try:
            return os.path.getmtime(report) >= since - 1      # a file system's times can be a second coarse
        except OSError:
            return False
    while clock() - start < longest:
        if written():
            return "done", int(clock() - start)
        sleep(10)
    return ("done" if written() else "long"), int(clock() - start)


def last_list(name, who, home, checkout):
    """The last list the reading team `name` sent, read from the newest transcript `kept` finds for it: the `message`
    of the lead's last tool call whose name ends `SendMessage` and whose `to` is `who`, the title of the session that
    holds the plan; where no call names `who`, since the lead may send under the nearest name ListAgents shows, the
    last such call whose `to` is none of the teammates and no agent's id. The row's time and the `to`, on one line,
    then the message whole; "" where there is none."""
    mains = sorted(kept(name, home, checkout), key=os.path.getmtime)
    sent = []
    for row in transcript.read_lines(mains[-1]) if mains else []:
        content = (row.get("message") or {}).get("content") if row.get("type") == "assistant" else None
        for c in content if isinstance(content, list) else []:
            inp = c.get("input") if isinstance(c, dict) else None
            if (isinstance(inp, dict) and c.get("type") == "tool_use"
                    and str(c.get("name") or "").endswith("SendMessage")
                    and isinstance(inp.get("message"), str) and inp.get("to")):
                sent.append((str(row.get("timestamp") or ""), str(inp["to"]), inp["message"]))
    named = [x for x in sent if who and x[1] == who]
    outside = [x for x in sent if x[1] not in TEAMMATES and not AGENT_ID.fullmatch(x[1])]
    found = (named or outside or [None])[-1]
    return f"{found[0]} to {found[1]}\n{found[2]}" if found else ""
