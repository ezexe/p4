#!/usr/bin/env python3
"""coworker.py: the terminal sessions p4-phi starts, for `phi.py coworkers`, `sections` and `draft --start`.

A terminal worker is a node, relay.claim makes it a folder of phi/tree nested in its starter's, where its start file, resume file,
settings file, brief, report and log are, and it runs in the checkout and reaches them by their whole paths: one
worker lands each group of an approved plan's sections, sections.groups, and one starts for each draft that has a
parent. By default (phi.json `worker_mode` `print`) a worker runs as `claude -p` with `--output-format stream-json
--verbose`, its output teed into its node's log, because the workers' sign-in bills a Console credit that covers
`claude -p` and not interactive Claude Code (measured on 2026-11-24: every interactive request got 400 "Your credit
balance is too low"). No teammate spawns under `-p`, so a headless planner reads its plan with three read-only
subagents and sets no team variable; in `interactive` mode a planner is a worker in plan mode with the team variable
set, which forms its three reading teammates in its own session. `drafts` only prints a plan's groups. The pages,
read on 2026-11-24:
- agent-teams.md: "In non-interactive mode with the `-p` flag, including Agent SDK sessions, Claude doesn't spawn
  teammates"; a team is enabled by "setting the `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable to `1`",
  which an interactive start file does in its own shell.
- headless.md: "The last line of the stream is a `result` message"; a failure inside the run is printed as the result.
- goal.md: "Setting a goal with `-p` runs the loop to completion in a single invocation".
- `claude --help`: `--session-id <uuid>`, "Use a specific session ID for the conversation", which finds a worker's
  transcripts and which `--resume` continues.
- cli-reference.md: `--settings` takes "Path to a settings JSON file or an inline JSON string".
The settings file turns p4's plugins off, so
no hook of p4 runs in the coworker and none sets up a store. The lead of the first read run this way, on 2026-11-23
with p4-phi and p4-temportal off, led three teammates, where no `.claude` folder appeared. Neither has `--add-dir`:
for a folder Claude Code has not seen it asks whether the folder is trusted, and a `claude -p` in auto mode read and
wrote a file of another folder's nested store by its whole path with none, on 2026-11-23.
See more: https://code.claude.com/docs/en/headless.md and https://code.claude.com/docs/en/goal.md
"""

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid

import p4conf
import plans
import relay
import sections
import transcript
import upkeep

SETTINGS_FILE = "coworker-settings.json"
TEAMS = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
LOG = "log-{}.jsonl"                     # a worker's stream-json, in its node beside its start file
PLAIN = re.compile(r"[^\w .,:#/-]")               # a task line holds no quote of any kind and no shell character


def settings(checkout, temportal=False, home=""):
    """The settings file's text: p4-phi and p4-temportal off, p4-temportal left on with `temportal`, which a planner
    needs for the skill `plan-planner`, and `claudeMdExcludes` naming, with forward slashes,
    each CLAUDE.local.md in a folder above `checkout` that holds the line p4conf.LINE, the key left out where there
    is none. Such a file's import resolves outside the checkout, and Claude Code then asks "Allow external CLAUDE.md
    file imports?" and starts nothing; with the file excluded an interactive `claude` asked nothing, on 2026-11-23.
    memory.md's "Exclude specific CLAUDE.md files" is the key; no setting approves the import, and the session has
    the p4 plugins off, so it needs no store text."""
    d = {"enabledPlugins": {f"{n}@{p4conf.MARKET}": bool(temportal and n == "p4-temportal")
                            for n in ("p4-phi", "p4-temportal")}}
    if temportal and home:             # a planner writes its plan into the store, not into ~/.claude/plans
        d["plansDirectory"] = p4conf.sub(os.path.abspath(home), "plans").replace("\\", "/")
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


def planner_task(title, plan_file=""):
    """A planner's prompt, one line with no quote and no shell character. With `plan_file`, a headless planner's: the
    plan written into that file by the skill plan-planner, read in rounds by three read-only subagents, no
    ExitPlanMode, the plan put to ezexe by the session that started it. Without, an interactive planner's: the plan
    in plan mode, a team of three that only reads and the plan put to ezexe with ExitPlanMode."""
    if plan_file:
        return (f"Write the plan for {plain(title)} into the file {plain(plan_file)} by the skill plan-planner. This "
                "run is headless: no agent team forms and no ExitPlanMode is answered. Read the plan in rounds with "
                "three read-only subagents named fences, sources and checks, one lens each, mend what held, and log "
                "each round in the plan. Edit no file but the plan and the report, and start no worker: the session "
                "that started you puts the plan to ezexe.")
    return (f"Write the plan for {plain(title)} in plan mode by the skill plan-planner. Form three teammates named "
            f"fences, sources and checks that only read, run the rounds of the plan in this session, write your "
            f"report with the path of the plan and its rounds before you call ExitPlanMode, and then put the "
            f"plan to ezexe with ExitPlanMode.")


PROFILE = re.compile(r"[A-Za-z0-9_-]+")


NO_PROFILE = "ant-none"          # an empty folder in a worker's node: ANTHROPIC_CONFIG_DIR there, so no ant profile applies


def profile_lines(profile, windows, folder=""):
    """The one line of a start file that names the Anthropic profile `profile` for that tab alone, where the
    profile's credentials file is there: `credentials/<profile>.json` in `ANTHROPIC_CONFIG_DIR`, whose default is
    `%APPDATA%\\Anthropic` on Windows and, elsewhere, `${XDG_CONFIG_HOME:-$HOME/.config}/anthropic`, an assumption of
    this file. No key is named: a profile `ant auth login` wrote is a sign-in with none. Where `profile` is empty and
    `folder` is given, the line instead makes `<folder>/ant-none` and points ANTHROPIC_CONFIG_DIR at it for that tab,
    since Claude Code ranks the active `ant` profile above the stored claude.ai login, and an empty config folder has
    no profile apply, so the worker signs in with the user's own login. [] where both are empty; ValueError where
    `profile` holds a character outside letters, digits, `_` and `-`."""
    if not profile:
        if not folder:
            return []
        sep = "\\" if windows else "/"
        none = folder.replace("\\", "/").replace("/", sep).rstrip(sep) + sep + NO_PROFILE
        if windows:
            return [f"New-Item -ItemType Directory -Force -Path '{none}' | Out-Null; $env:ANTHROPIC_CONFIG_DIR = '{none}'"]
        return [f"mkdir -p '{none}' && export ANTHROPIC_CONFIG_DIR='{none}'"]
    if not PROFILE.fullmatch(profile):
        raise ValueError(f"a worker profile's name holds letters, digits, _ and - only: {profile}")
    if windows:
        return [f"$d = if ($env:ANTHROPIC_CONFIG_DIR) {{ $env:ANTHROPIC_CONFIG_DIR }} else {{ Join-Path $env:APPDATA 'Anthropic' }}; "
                f"if (Test-Path (Join-Path $d 'credentials\\{profile}.json')) {{ $env:ANTHROPIC_PROFILE = '{profile}' }}"]
    return ['d="${ANTHROPIC_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/anthropic}"; '
            f'[ -f "$d/credentials/{profile}.json" ] && export ANTHROPIC_PROFILE={profile}']


def script(name, checkout, mode, said, folder, windows=None, team=True, extra=(), session="", profile="",
           resume=False, headless=True, level=None):
    """A coworker's start script, as (its file's name, its lines, the line typed into the tab): what a desktop
    session's shell hands down is cleared and `claude` starts in the checkout, with no worktree, and the settings
    file of `folder`. With `headless`, it is `claude -p` with `--output-format stream-json --verbose`, its output
    teed into `folder`/log-<name>.jsonl, and no team variable; without, it is an interactive `claude` with the team
    variable where `team`. `session` adds `--session-id <uuid>`, or with `resume` `--resume <uuid>` in a file named
    `resume-<name>`, since both together would fork the session. `extra` flags, each a word spelled as the shell
    reads it, follow. A quote in the prompt `said` is refused as one in a path is, since the prompt stands between
    quotes. `level`, {"model", "effort"} from a brief's own `Model:` and `Effort:` lines, is laid over level()."""
    windows = upkeep.WINDOWS if windows is None else windows
    named = profile_lines(profile, windows, folder)
    sep = "\\" if windows else "/"
    here, at = checkout.replace("\\", "/").replace("/", sep), folder.replace("\\", "/").replace("/", sep)
    for path in (here, at, said):
        if re.search(r"['\"`]", path):
            raise ValueError(f"a start file's paths hold no quote: {path}")
    if resume and not session:
        raise ValueError("a resume names the session it continues")
    lv = {**globals()["level"](), **{k: v for k, v in (level or {}).items() if k in ("model", "effort") and v}}
    if lv.get("effort") in plans.EFFORTS:
        lv["effort"] = plans.capped(lv["effort"])
    flags = "".join(f" --{k} {lv[k]}" for k in ("model", "effort") if str(lv.get(k) or "inherit") != "inherit")
    log = f"{at}{sep}{LOG.format(name)}"
    run = (f"claude{' -p' if headless else ''} --name {name}"
           + (f" --{'resume' if resume else 'session-id'} {session}" if session else "")
           + "".join(f" {x}" for x in extra)
           + flags + (f" --permission-mode {mode}" if mode else "")
           + f" --settings '{at}{sep}{SETTINGS_FILE}'"
           + (" --output-format stream-json --verbose" if headless else "") + f" '{said}'")
    kind = "resume" if resume else "start"
    team = team and not headless
    if windows:
        names = ", ".join(f"'{n}'" for n in upkeep.CARRIED)
        return (f"{kind}-{name}.ps1",
                [f"foreach ($n in {names}) {{ Remove-Item -Path ('Env:' + $n) -ErrorAction SilentlyContinue }}",
                 *named, *([f"$env:{TEAMS} = '1'"] if team else []), f"Set-Location '{here}'",
                 run + (f" 2>&1 | Tee-Object -FilePath '{log}' -Append" if headless else "")],
                f"& '{at}\\{kind}-{name}.ps1'")
    return (f"{kind}-{name}.sh", [f"unset {' '.join(upkeep.CARRIED)}", *named, *([f"export {TEAMS}=1"] if team else []),
                                  f"cd '{here}'", run + (f" 2>&1 | tee -a '{log}'" if headless else "")],
            f"sh '{at}/{kind}-{name}.sh'")


BACKGROUND_HINT = ("where `mcp__terminal__open_terminal_tab` is refused because every tab is held, run the same "
                   "command again with `--background`")


def start_background(one, windows=None):
    """Starts the `-p` worker `one` (an entry of land() or section_plans() that has a folder) as a detached process
    that runs its start file, which writes the same log and report as a tab's start would, and returns its log's
    path. The log is made empty first, so it is there at once. An interactive worker is never started so: it
    returns "", and the caller names it as needing a tab."""
    windows = upkeep.WINDOWS if windows is None else windows
    if not one.get("log") or (one.get("settings") or {}).get("mode") == "interactive":
        return ""
    start = os.path.join(one["folder"], one["file"])
    with open(one["log"], "a", encoding="utf-8"):
        pass
    if windows:
        argv = [shutil.which("pwsh") and "pwsh" or "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", start]
        kw = {"creationflags": 0x00000200 | 0x08000000}     # NEW_PROCESS_GROUP, NO_WINDOW: DETACHED_PROCESS left tee no log
    else:
        argv, kw = ["sh", start], {"start_new_session": True}
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, **kw)
    return one["log"].replace("\\", "/")


def rerun(path, checkout, home, n):
    """Withdraws the node of the run that holds section `n` where that run's worker reported and the plan holds no
    `Evidence:` for it, so the next land starts it again. The run's name, or "" where no run reported that section.
    The node's folder is removed whole: its report, brief and log are the old run's."""
    for r in plan_runs(path, checkout, home):
        if str(n) in r["sections"] and r["state"] == "done" and r["folder"]:
            shutil.rmtree(r["folder"], ignore_errors=True)
            relay.forget(home)
            row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "outcome", "name": r["name"], "how": "withdrawn"}
            path_ = os.path.join(home, "phi", "worker-starts.jsonl")      # its old start row holds a slot no longer
            os.makedirs(os.path.dirname(path_), exist_ok=True)
            with open(path_, "a", encoding="utf-8", newline=chr(10)) as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + chr(10))
            return r["name"]
    return ""


def _quoted(*paths):
    for path in paths:
        if re.search(r"['\"`]", str(path)):
            raise ValueError(f"a start file's paths hold no quote: {path}")


def _node(home, name, kind, starter, nums, checkout, session=""):
    """(the folder of a new node `name`, ""), or (None, its folder) where the name has a node already, whose
    session was started once; relay.claim finds the folder from the starter's id. Raises ValueError where no
    folder could be made."""
    have = relay.nodes(home).get(name)
    if have:
        return None, have.replace("\\", "/")
    made = relay.claim(home, name, kind, starter, nums, session=session, checkout=checkout)
    if not made:
        raise ValueError(f"no folder could be made for {name} under {starter}: its path would be too long")
    return made.replace("\\", "/"), ""


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
    """The settings file, settings(checkout), each worker's start file, resume file and brief,
    written into the node folder of each entry that has one. The paths written. Where a write fails, what this call
    wrote is removed and, with `home`, the nodes of those entries too, and the error goes out."""
    wrote = []
    try:
        for one in found:
            if not one.get("folder"):
                continue
            files = {SETTINGS_FILE: settings(checkout, bool(one.get("temportal")), home)}
            if one.get("file"):
                files[one["file"]] = "\n".join(one["lines"])
            if one.get("resume_file"):
                files[one["resume_file"]] = "\n".join(one["resume_lines"])
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


def land(path, checkout, who, mode, home="", starter="", claim=False, windows=None, profile="",
         headless=True, settings=None):
    """One entry for each run of the plan at `path` that is ready, plan_runs, in the plan's order: the terminal
    worker that lands it, started once ezexe approved the plan, so every run whose `Depends on:` is met starts at
    once and the next wave is the next call's. `name` and `sections`, and with `claim` the node relay.claim
    makes for it under its starter `starter`, and in the node's folder the `brief` text and its
    file, the `report` file the worker writes, its `goal`, and the start file's name, `lines` and the line `typed` in
    its tab; a name that has a node already gets `started`, its node's folder, and nothing else. The worker has no
    worktree, no team (none spawns under -p), no p4 plugin and no `--add-dir`: its goal is its prompt, since no hooks module sets one. It
    starts in LAND_MODE, and `mode`, its starter's, is not read. With `settings`, a function of the title and brief
    and the run's `Runner:` that returns phi.worker_settings' dict, or None where no pool has a slot for the run,
    each worker's profile and mode are its own and its entry holds them as `settings`; a run with None gets `waits`
    and no node. `profile` and `headless` are then not read. A section's `Model:` and `Effort:` lines set its
    worker's, and `Runner: team` an interactive worker's team."""
    windows = upkeep.WINDOWS if windows is None else windows
    plan = os.path.abspath(path).replace("\\", "/")
    checkout = checkout.replace("\\", "/")
    if claim:                                      # every path before the first claim
        _quoted(plan, checkout, home)
    title = plan_title(path)
    every = plan_runs(path, checkout, home)
    out = [{"name": r["name"], "sections": r["sections"], "group": r["group"], "runner": r["runner"]}
           for r in every if r["state"] == "ready"]
    if not claim:
        return [{k: v for k, v in one.items() if k not in ("group", "runner")} for one in out]
    try:
        for one in out:
            _worker(one, plan, title, checkout, mode, home, starter, windows, profile, headless, settings)
    except Exception:
        _undo(home, out)
        raise
    order = {r["name"]: k for k, r in enumerate(every)}
    out += [{"name": r["name"], "sections": r["sections"], "started": r["folder"]}
            for r in every if r["state"] in ("running", "ended")]
    return sorted(out, key=lambda one: order[one["name"]])


def plan_title(path):
    with open(path, encoding="utf-8") as f:
        return sections.parse(f.read())[0]


def _reported(path, plan_sections, home):
    """{section number: (node id, node folder)} of every section with no `Evidence:` whose last worker's node, a
    worker node of this plan, holds its report: landed by its run whether or not the plan holds its line yet."""
    pre, post = _named("tw", plan_title(path), ["@"], path).split("@")
    open_ = {s["n"] for s in plan_sections if not s["landed"]}
    out, at = {}, {}
    for ident, folder in relay.nodes(home).items():
        rec = relay.node_record(home, ident)
        folder = folder.replace("\\", "/")
        if (rec.get("kind") != "worker" or not (ident.startswith(pre) and ident.endswith(post))
                or not os.path.exists(f"{folder}/report-{ident}.md")):
            continue
        when = relay.node_time(home, ident)
        for n in (str(n) for n in rec.get("sections") or []):
            if n in open_ and when >= at.get(n, 0.0):
                at[n], out[n] = when, (ident, folder)
    return out


def plan_runs(path, checkout, home=""):
    """Every run of the plan at `path`, in the plan's order, landed ones too, so a run keeps its name from wave to
    wave: the sections that share a file, sections.file_runs, each as {"name", "sections", "group", "needs",
    "runner", "state", "folder", "report"}. `sections` are the run's sections not landed, `group` those sections
    whole and `needs` the sections of other runs it waits for. The state: `landed` where every section holds its
    `Evidence:`; `done` where its worker's node holds its report, which the land output names `reported`, the
    section's `Evidence:` being the session's to write; `ended` where its log's last row is a final
    result and no report came; `running` where its node is there and neither; `ready` where it was never started
    and every need is met, a met section being landed or in a run that is landed or done; `waiting` for the rest."""
    with open(path, encoding="utf-8") as f:
        _, found = sections.parse(f.read(), checkout)
    by_n = {s["n"]: s for s in found}
    nodes = relay.nodes(home) if home else {}
    reported = _reported(path, found, home) if home else {}
    rest = [dict(s, landed=False) for s in found if s["n"] not in reported]
    out = []
    for run in sections.file_runs(rest):
        real = [by_n[s["n"]] for s in run]
        left = [s for s in real if not s.get("landed")]
        name = worker_name(path, [s["n"] for s in run])
        one = {"name": name, "sections": [s["n"] for s in left], "group": left, "needs": sections.needs(run),
               "runner": next((s["runner"] for s in run if s.get("runner")), {}), "folder": "", "report": ""}
        folder = (nodes.get(name) or "").replace("\\", "/")
        if not left:
            one["state"] = "landed"
        elif folder:
            one.update(folder=folder, report=f"{folder}/report-{name}.md")
            if os.path.exists(one["report"]):
                one["state"] = "done"
            elif last_result(f"{folder}/{LOG.format(name)}", final=True):
                one["state"] = "ended"
            else:
                one["state"] = "running"
        else:
            one["state"] = "todo"
        out.append(one)
    met = {s["n"] for s in found if s.get("landed")}
    for r, run in zip(out, sections.file_runs(rest)):
        if r["state"] in ("landed", "done"):
            met |= {s["n"] for s in run}
    met |= set(reported)
    for ident in dict.fromkeys(v[0] for _, v in sorted(reported.items(), key=lambda kv: sections._key(kv[0]))):
        folder = next(v[1] for v in reported.values() if v[0] == ident)
        out.append({"name": ident, "sections": sorted((n for n, v in reported.items() if v[0] == ident), key=sections._key),
                    "group": [], "needs": [], "runner": {}, "folder": folder,
                    "report": f"{folder}/report-{ident}.md", "state": "done"})
    for r in out:
        if r["state"] == "todo":
            r["state"] = "ready" if all(d in met or d not in by_n for d in r["needs"]) else "waiting"
    return out


def _worker(one, plan, title, checkout, mode, home, starter, windows, profile="", headless=True,
            settings=None):
    """The node of one terminal worker of land(), and its brief, goal and start file in it."""
    group, nums = one.pop("group"), one["sections"]
    runner = one.pop("runner", None) or next((s["runner"] for s in group if s.get("runner")), {})
    many = "s" if len(group) > 1 else ""
    done = f"Every fence of section{many} {', '.join(nums)} of the plan {plan} is landed, its Checks pass"
    brief = sections.brief(plan, title, group, checkout, [])
    if settings:
        one["settings"] = settings(title + "\n" + brief, runner)
        if one["settings"] is None:                # no pool has a free slot: the run waits, and nothing is claimed
            one["waits"] = True
            return
        profile, headless = one["settings"]["profile"], one["settings"]["mode"] == "print"
    one.update(worker(one["name"], brief, done, checkout, home, starter, nums, windows, profile=profile,
                      headless=headless, team=bool(runner.get("team")) and not headless,
                      level=runner.get("level")))


def worker(name, brief, done, checkout, home, starter, nums=(), windows=None, team=False, mode=LAND_MODE,
           extra=(), prompt="", profile="", plan_file="", headless=True, level=None):
    """The node of one terminal worker and its brief, goal and start file in it, as one entry: `name`, and either
    `started`, the folder of a node that holds that name already, or `folder`, `brief` and `brief_file`, `report`,
    `goal`, the `session` id (a uuid4 kept in its node.json), its `log`, and the start file's `file`, `lines` and the
    line `typed` in its tab, with `resume_file`, `resume_lines` and `resume_typed` for the file that continues the
    session. `done` is what the goal waits for, one sentence with no quote. The worker has no worktree and no p4
    plugin, and its goal is its prompt. With `prompt`, a planner's, that line stands in place of the goal, closed with
    the brief's file, and the settings file leaves p4-temportal on for the skill plan-planner; a headless planner's
    mode is LAND_MODE whatever `mode` is, since `plan` cannot be approved under `-p`, its prompt is a /goal, and
    `plan_file` is where its plan is."""
    windows = upkeep.WINDOWS if windows is None else windows
    checkout = checkout.replace("\\", "/")
    _quoted(checkout, home)
    one = {"name": name}
    session = str(uuid.uuid4())
    folder, there = _node(home, name, "worker", starter, list(nums), checkout, session=session)
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
    if prompt and headless:
        mode = LAND_MODE
        goal = f"/goal {prompt} The brief is {brief_file}, and the report {report} is written when the plan is whole."
    elif prompt:
        goal = f"{prompt} The brief is {brief_file}, and the report {report} is written before the plan is put."
    try:
        kw = dict(team=team, extra=extra, session=session, profile=profile, headless=headless, level=level)
        file, lines, typed = script(name, checkout, mode, goal, folder, windows, **kw)
        rfile, rlines, rtyped = script(name, checkout, mode, goal, folder, windows, resume=True, **kw)
    except Exception:
        relay.unclaim(home, name)
        raise
    one.update(brief="\n".join([*where, brief]), brief_file=brief_file, report=report, goal=goal, session=session,
               log=f"{folder}/{LOG.format(name)}", file=file, lines=lines, typed=typed, resume_file=rfile,
               resume_lines=rlines, resume_typed=rtyped, temportal=bool(prompt))
    if plan_file:
        one["plan"] = plan_file
    return one


PLANNER_PREFIX = "tp"                     # a section planner's name: tp-<section>-<n>-<mark>
PLANNER_RUNNER = {"mode": "interactive", "pool": "max", "team": True, "said": "interactive"}


def section_runs(path, checkout, home=""):
    """(the top plan's title, one entry for each brief not landed, in the plan's order): {"name", "n", "head",
    "needs", "text" (the planner's brief), "folder", "report", "state"}. The state: `done` where the
    planner's node holds its report, which it writes before ExitPlanMode; `running` where its node is there and
    no report; `ready` where it never started and every `Depends on:` is a section whose planner is done or no
    section of the plan; `waiting` for the rest."""
    with open(path, encoding="utf-8") as f:
        title, found = sections.parse(f.read(), checkout)
    nodes = relay.nodes(home) if home else {}
    out = []
    for s in found:
        if s["landed"]:
            continue
        name = _named(PLANNER_PREFIX, s["head"], [s["n"]], path)
        folder = (nodes.get(name) or "").replace("\\", "/")
        one = {"name": name, "n": s["n"], "head": s["head"], "needs": list(s["after"]),
               "text": sections.plan_brief(title, s), "folder": folder, "state": "todo",
               "report": f"{folder}/report-{name}.md" if folder else ""}
        if folder:
            one["state"] = "done" if os.path.exists(one["report"]) else "running"
        out.append(one)
    by = {r["n"]: r for r in out}
    for r in out:
        if r["state"] == "todo":
            r["state"] = "ready" if all(d not in by or by[d]["state"] == "done" for d in r["needs"]) else "waiting"
    return title, out


def section_plans(path, checkout, home, starter, settings, windows=None):
    """One entry for each ready brief: the interactive planner that plans it, started once ezexe has the top plan,
    as worker() makes it (a node, its brief, goal and start file, its pool settings), or `waits` where
    `settings` (phi.slot_assigner's) has no slot for it, with no node claimed. Call it again, once a report is
    there, to start what that frees."""
    plan, checkout = os.path.abspath(path).replace("\\", "/"), checkout.replace("\\", "/")
    _quoted(plan, checkout, home)
    title, every = section_runs(plan, checkout, home)
    with open(plan, encoding="utf-8") as f:
        by = {s["n"]: s for s in sections.parse(f.read(), checkout)[1]}
    out = []
    try:
        for r in every:
            if r["state"] != "ready":
                continue
            st = settings(r["text"], PLANNER_RUNNER)
            if st is None:
                out.append({"name": r["name"], "sections": [r["n"]], "waits": True})
                continue
            one = worker(r["name"], r["text"], "The plan of the brief is written and put to ezexe", checkout, home,
                         starter, [r["n"]], windows, team=True, mode="plan",
                         prompt=planner_task(sections.plan_name(title, by[r["n"]])),
                         profile=st["profile"], headless=False, level=plans.own_level(r["text"]) or None)
            one.update(settings=st, sections=[r["n"]])
            out.append(one)
    except Exception:
        _undo(home, out)
        raise
    return out


def _bring_in(plan, home):
    """(the plan's path, where it was brought in from): `plan` copied into the store's plans folder under its name
    where it lies outside that folder. A file of that name there with the same text is the copy; one with other text
    is left alone and (plan, "") comes back."""
    folder = os.path.abspath(p4conf.sub(os.path.abspath(home), "plans"))
    src = os.path.abspath(plan)
    inside = os.path.normcase(folder).rstrip("\\/") + os.sep
    if (os.path.normcase(src) + os.sep).startswith(inside):          # anywhere under the plans folder
        return plan, ""
    dest = os.path.join(folder, os.path.basename(src))
    if os.path.isfile(dest):
        with open(src, "rb") as a, open(dest, "rb") as b:
            same = a.read() == b.read()
        return (dest.replace("\\", "/"), plan) if same else (plan, "")
    os.makedirs(folder, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest.replace("\\", "/"), plan


def collect(path, checkout, home=""):
    """One entry for each brief, in the plan's order: {"name", "n", "head", "state", "plan" (the file the planner's
    report names on its line `Plan file:`, "" where there is none), "report" (where the planner reported, else ""),
    "read" (the plan's line that opens `Read:`, else ""), "moved_from"}, for the orchestrator to review and put to
    ezexe. A plan file outside the store's plans folder is copied into it under the same name, and "plan" is the copy
    and "moved_from" the original; where a file of that name is there with other text it is never overwritten, "plan"
    stays the original and "moved_from" is ""."""
    out = []
    for r in section_runs(path, checkout, home)[1]:
        plan, read, moved = "", "", ""
        if r["state"] == "done":
            try:
                with open(r["report"], encoding="utf-8") as f:
                    text = f.read()
                for m in re.finditer(r"(?im)^[ \t>*-]*plan file(?:\*\*[ \t]*:|[ \t]*:(?:\*\*)?)[ \t]*`?([^`\r\n]*?)`?[ \t]*$",
                                     text):                # one colon is required, so prose that opens "Plan file" is no line
                    plan = m.group(1).strip().replace("\\", "/")
                    if os.path.isfile(plan):
                        break
                    plan = ""
                if plan and home:
                    plan, moved = _bring_in(plan, home)
                with open(plan, encoding="utf-8") as f:
                    read = next((x.strip() for x in f.read().splitlines() if x.startswith("Read:")), "")
            except OSError:
                pass
        out.append({"name": r["name"], "n": r["n"], "head": r["head"], "state": r["state"],
                    "plan": plan if plan and os.path.isfile(plan) else "", "moved_from": moved,
                    "report": r["report"] if r["state"] == "done" else "", "read": read})
    return out


def draft_name(title, did):
    """A drafted worker's name: `tw-`, the title's slug cut at 24 characters, and the draft id's last four."""
    stem = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:24].strip("-") or "work"
    return f"tw-{stem}-{str(did)[-4:]}"


BOM16LE, BOM16BE = bytes([0xFF, 0xFE]), bytes([0xFE, 0xFF])
GOAL_TAIL = 1 << 20              # the most of a log's end read for its last result row


def last_result(log, offset=0, final=False):
    """The last `result` row of the stream-json log `log` written past byte `offset`, {} where there is none or the
    file is not there. A log that opens with a UTF-16 BOM or holds NUL bytes is read as UTF-16. Lines that are no
    JSON object (a stderr line, a BOM) are skipped. With `final`, the row only
    where it is the last JSON row of the log, since a run under `/goal` may write a `result` row for a turn and go on."""
    try:
        with open(log, "rb") as f:
            head = f.read(2)
            f.seek(0, 2)
            at = max(int(offset), f.tell() - GOAL_TAIL)
            f.seek(at)
            data = f.read()
        if head in (BOM16LE, BOM16BE) or bytes(1) in data:                  # a Windows PowerShell 5.1 log is UTF-16
            if head == BOM16LE and at % 2:
                data = data[1:]                                           # keep the code units aligned
            text = data.decode("utf-16-be" if head == BOM16BE else "utf-16-le", "replace")
        else:
            text = data.decode("utf-8", "replace")
    except OSError:
        return {}
    for line in reversed(text.splitlines()):
        line = line.strip().lstrip("\ufeff")
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("type") == "result":
            return row
        if final and isinstance(row, dict):
            return {}
    return {}


def wait_report(report, home="", name="", longest=LONGEST, clock=time.time, sleep=time.sleep, log="", quiet=QUIET):
    """A terminal worker's wait, as (how it ended, the seconds waited): `done` as soon as its report file is there
    and was written after the wait began, so the first report of a worker that went on working is no answer to a wait
    made after it, whatever the claim time of its node `name`. `ended` where `log` names a stream-json log that got a
    `result` row after the wait began (past the log's size when it began, so a resumed run is not ended by the old
    run's row), that row is the log's last JSON row and the log was last written `quiet` seconds ago or more, and the report is
    not there, as a run that an error ended does; a run under `/goal` can write a `result` row for a turn and go on. `long` after `longest` seconds. It
    reads no transcript."""
    since = time.time()
    start = clock()
    try:
        offset = os.path.getsize(log) if log else 0
    except OSError:
        offset = 0

    def written():
        try:
            return os.path.getmtime(report) >= since - 1      # a file system's times can be a second coarse
        except OSError:
            return False
    def ended():
        try:
            idle = time.time() - os.path.getmtime(log) if log else -1
        except OSError:
            return False
        return idle >= quiet and bool(last_result(log, offset, final=True))
    while clock() - start < longest:
        if written():
            return "done", int(clock() - start)
        if ended():
            return "ended", int(clock() - start)
        sleep(10)
    if written():
        return "done", int(clock() - start)
    return ("ended" if ended() else "long"), int(clock() - start)


def wait_any(reports, longest=LONGEST, clock=time.time, sleep=time.sleep, quiet=QUIET):
    """The wait of a wave: (the report that came first, how it ended, the seconds waited), as wait_report reads
    each of `reports` (each beside its worker's log in its node), so the session that lands a plan starts the next
    wave as soon as one worker of this one is through, rather than at the last. `done` where a report is there,
    since each names a worker the last land printed as running, so one written before the wait began counts, `ended` where a log got a final `result` row past its size when the wait began, idle
    `quiet` seconds, and its report is not there; (`""`, `long`, seconds) after `longest` seconds."""
    start = clock()
    logs = {}
    for report in reports:
        tab = os.path.basename(report)[len("report-"):].rsplit(".", 1)[0]
        log = os.path.join(os.path.dirname(report), LOG.format(tab))
        try:
            logs[report] = (log, os.path.getsize(log))
        except OSError:
            logs[report] = (log, 0)

    def one():
        for report in reports:
            if os.path.exists(report):             # a wave's reports are of workers that ran at its land
                return report, "done"
            log, offset = logs[report]
            try:
                idle = clock() - os.path.getmtime(log)
            except OSError:
                continue
            if idle >= quiet and last_result(log, offset, final=True):
                return report, "ended"
        return "", ""
    while clock() - start < longest:
        report, how = one()
        if how:
            return report, how, int(clock() - start)
        sleep(10)
    report, how = one()
    return report, how or "long", int(clock() - start)


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
