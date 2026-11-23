#!/usr/bin/env python3
"""coworker.py: a plan's groups of sections as the coworkers that read and land them, for `phi.py coworkers`.

A coworker is a terminal session that leads an agent team for one group of a plan's sections, sections.groups, in a
git worktree of its own, and lands that group there once ezexe approved the plan. The pages, read on 2026-11-23:
- agent-teams.md: "In non-interactive mode with the `-p` flag, including Agent SDK sessions, Claude doesn't spawn
  teammates", so the run is interactive, and a team is enabled by "setting the
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable to `1`", which the start file does in its own shell.
- worktrees.md: `--worktree <name>` makes `.claude/worktrees/<name>/` "at your repository root, on a new branch
  named `worktree-<name>`", branched "from the repository's default branch on the remote".
- cli-reference.md: `--settings` takes "Path to a settings JSON file or an inline JSON string".
The settings file turns p4's three plugins off, as the terminal worker's turns off two, upkeep.WORKER_SETTINGS, so
no hook of p4 runs in the coworker and none sets up a store in its worktree. The lead of the first read run this
way, on 2026-11-23 with p4-phi and p4-temportal off, led three teammates in its worktree, where no `.claude` folder
appeared.
"""

import glob
import hashlib
import os
import re
import time

import p4conf
import plans
import sections
import transcript
import upkeep

SETTINGS_FILE = "coworker-settings.json"
SETTINGS = ('{"enabledPlugins": {' + ", ".join(f'"{n}@{p4conf.MARKET}": false'
                                               for n in ("p4-phi", "p4-temportal")) + "}}")
TEAMS = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
PLAIN = re.compile(r"[^\w .,:#/-]")               # a task line holds no quote of any kind and no shell character


def plain(text):
    return PLAIN.sub(" ", str(text).replace("\\", "/"))


def name_of(title, group, path):
    """A coworker's name, which names its session, its worktree and its branch: lower-case letters, digits and
    hyphens, made of the plan's title, its sections' numbers and four characters of a hash of the plan's path, so
    two plans of one title make two names."""
    stem = re.sub(r"[^a-z0-9]+", "-", str(title).lower()).strip("-")[:16].strip("-") or "plan"
    mark = hashlib.sha1(os.path.abspath(path).replace("\\", "/").lower().encode("utf-8")).hexdigest()[:4]
    return f"cw-{stem}-" + "-".join(s["n"] for s in group) + f"-{mark}"


def level():
    """The model and effort a coworker starts on: the kind `static`, an integrator's, since it lands written fences,
    with the effort held to the starting session's own."""
    out = dict(plans.CHILD_LEVELS["static"])
    out["effort"] = plans.capped(out["effort"])
    return out


def task(path, group, who):
    """A coworker's task, one line with no quote and no shell character: the team, the sections, what each lens
    judges, where the list goes and that it stays open."""
    nums = ", ".join(s["n"] for s in group)
    part = f"section{'s' if len(group) > 1 else ''} {nums}"
    return (f"Form an agent team of three teammates named fences, sources and checks. Each teammate runs on the "
            f"model of this session and only reads files. All three read the Context and {part} of the plan file "
            f"{plain(path)} and judge them against this folder, a git worktree of the checkout at its remote "
            f"default branch. They open no file under the folders complete, todo or unplanned. The teammate fences "
            f"checks that each fenced edit applies to the file it names as that file stands here. The teammate "
            f"sources checks each Documented line and each Observed line against the source it names, a file and "
            f"line here or a live page, tries to show each Assumed line from the code or a page, and sends you each "
            f"live page with the words quoted from it, which you have one web-fetch subagent read before the "
            f"challenge. The teammate checks reads each Checks line, names what it would not prove and what those "
            f"sections leave out, and traces each new hook from its event to its handler. Each gives its findings "
            f"with file and line, then they challenge each other once and drop what does not hold. Change no file "
            f"until the session named below says the plan is approved. After each round send one list of the "
            f"findings that held, each on one line with its section and its reason, an "
            f"Assumed line that was shown on a line that opens Observed with its source, and a finding on a section "
            f"outside {part} on a line that opens Other, or the one word clean, with SendMessage to the session "
            f"named {plain(who)}, or to the session ListAgents lists under the name nearest to that. Close the list "
            f"by saying how many agents ran and the minutes the round took by the clock. Then stay open and shut no "
            f"teammate down, since later rounds and the word to land come by message from that session.")


def script(name, checkout, mode, said, folder, windows=None):
    """A coworker's start script, as (its file's name, its lines, the line typed into the tab): what a desktop
    session's shell hands down is cleared, the team variable is set, and `claude` starts in the checkout with a
    worktree of the coworker's name and the settings file of `folder`."""
    windows = upkeep.WINDOWS if windows is None else windows
    sep = "\\" if windows else "/"
    here, at = checkout.replace("\\", "/").replace("/", sep), folder.replace("\\", "/").replace("/", sep)
    for path in (here, at):
        if re.search(r"['\"`]", path):
            raise ValueError(f"a start file's paths hold no quote: {path}")
    lv = level()
    flags = "".join(f" --{k} {lv[k]}" for k in ("model", "effort") if str(lv.get(k) or "inherit") != "inherit")
    run = (f"claude --name {name} --worktree {name}{flags}" + (f" --permission-mode {mode}" if mode else "")
           + f" --settings '{at}{sep}{SETTINGS_FILE}' '{said}'")
    if windows:
        names = ", ".join(f"'{n}'" for n in upkeep.CARRIED)
        return (f"start-{name}.ps1",
                [f"foreach ($n in {names}) {{ Remove-Item -Path ('Env:' + $n) -ErrorAction SilentlyContinue }}",
                 f"$env:{TEAMS} = '1'", f"Set-Location '{here}'", run], f"& '{at}\\start-{name}.ps1'")
    return (f"start-{name}.sh", [f"unset {' '.join(upkeep.CARRIED)}", f"export {TEAMS}=1", f"cd '{here}'", run],
            f"sh '{at}/start-{name}.sh'")


def drafts(path, checkout, who, mode="", folder="<folder>", windows=None):
    """One entry for each group of the plan at `path`, in the plan's order: its sections, its fences and whether it
    earns a team, and for a group that does, the coworker's name, its start file's name and lines, and the line
    typed into its tab. `who` is the planner's title, where the lists go."""
    with open(path, encoding="utf-8") as f:
        title, found = sections.parse(f.read(), checkout)
    out = []
    for group in sections.groups(found):
        one = {"sections": [s["n"] for s in group], "fences": sections.fences(group), "team": sections.team(group)}
        if one["team"]:
            one["name"] = name_of(title, group, path)
            one["file"], one["lines"], one["typed"] = script(one["name"], checkout, mode, task(path, group, who),
                                                             folder, windows)
        out.append(one)
    return out


def write(folder, found):
    """The settings file and each coworker's start file, written into `folder`, which is made where it is not
    there. The paths written."""
    os.makedirs(folder, exist_ok=True)
    files = {SETTINGS_FILE: SETTINGS}
    files.update({one["file"]: "\n".join(one["lines"]) for one in found if one.get("team")})
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    return [os.path.join(folder, name).replace("\\", "/") for name in files]


QUIET = 90                       # seconds with no line written by a coworker or an agent under it
FIRST = 300                      # the most a watch waits for a round's first line, in seconds
LONGEST = 3600                   # the most one watch waits, in seconds


def kept(name, deep=False):
    """The transcripts Claude Code keeps for the coworker `name`, its own and with `deep` those of the agents under
    it: the files of the folder under `projects` that ends in `-worktrees-<name>`, as a worktree of that name is
    kept. [] for a name that could be no worktree's."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", str(name or "")):
        return []
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    folder = os.path.join(base, "projects", f"*-worktrees-{name}")
    return sorted(glob.glob(os.path.join(folder, "**", "*.jsonl"), recursive=True) if deep
                  else glob.glob(os.path.join(folder, "*.jsonl")))


def watch(names, quiet=QUIET, longest=LONGEST, first=FIRST, clock=time.time, sleep=time.sleep):
    """A round's wait, as (how it ended, the seconds waited). `quiet`: a coworker of `names`, or an agent under one,
    wrote a line of its transcript after the watch began, and then none did for `quiet` seconds. `silent`: none
    wrote a line in the first `first` seconds, as where the round's message did not arrive or a name is no
    coworker's, so a coworker that was idle before the round is not taken for one that finished it. `long`:
    `longest` seconds passed. The planner runs it as one background command after it sends a round, in place of an
    idle notice from each coworker."""
    start = clock()
    while clock() - start < longest:
        last = max((os.path.getmtime(p) for name in names for p in kept(name, deep=True)), default=0.0)
        now = clock()
        if last < start and now - start >= first:
            return "silent", int(now - start)
        if last >= start and now - last >= quiet:
            return "quiet", int(now - start)
        sleep(10)
    return "long", int(clock() - start)


def stopped(name):
    """True where an error of the API ended the last turn of the coworker `name`: the last row of type `assistant`
    in its newest transcript is marked `isApiErrorMessage`, as Claude Code marks `API Error: 529 Overloaded`."""
    mains = sorted(kept(name), key=os.path.getmtime)
    rows = [r for r in transcript.read_lines(mains[-1]) if r.get("type") == "assistant"] if mains else []
    return bool(rows) and bool(rows[-1].get("isApiErrorMessage"))


def land(path, checkout, who):
    """For each coworker of the plan at `path`, (its name, the message that has it land its group): sent once ezexe
    approved the plan, to a coworker that still runs."""
    with open(path, encoding="utf-8") as f:
        title, found = sections.parse(f.read(), checkout)
    ref = upkeep.default_ref(checkout) or "origin/main"
    out = []
    for group in sections.groups(found):
        if not sections.team(group):
            continue
        name = name_of(title, group, path)
        out.append((name, "\n".join([
            "ezexe approved the plan, so the files of your sections are now yours to change. Shut down every "
            "teammate first. Then, in this worktree, run `git fetch origin` "
            f"and `git merge --ff-only {ref}`, so the fences meet the tree as it now is.", "",
            sections.brief(path, title, group, checkout), "",
            "One commit for each section, in the order the task above names them, with the trailer this "
            "repository's recent commits "
            f"end with. Push nothing, merge nothing else and raise no version. Then send one message with the "
            f"branch `worktree-{name}`, each commit and each check's output, by SendMessage to the session named "
            f"{plain(who)}, and stay open until that session says the tab closes."])))
    return out
