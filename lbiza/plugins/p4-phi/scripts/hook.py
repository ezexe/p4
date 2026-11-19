#!/usr/bin/env python3
"""hook.py <name>: the p4-phi hooks that hooks/recall-hook.sh runs with Claude Code's JSON payload on stdin: the
store's layout and catch-up, retrieval, the record of every tool call, and training. The check before a tool call
is here too, and the plugin's hooks module runs it with a PreToolUse hook's payload. Every handler resolves
`.claude/p4/` from CLAUDE_PROJECT_DIR or the payload's `cwd`, prints only what its row below names, and on any failure
exits 0 with one `systemMessage` for ezexe, never context for the model. Each row gives the handler's name, the
event and matcher hooks/hooks.json runs it on, and what it does.

  catch-up       SessionStart, matcher `startup`. One `systemMessage` from catchup.py when something fell behind on
                 this machine, such as the store's layout or its branch; nothing otherwise.
  layout         SessionStart, matcher `startup|resume|clear|compact`. Moves a store of an older layout through
                 p4conf.migrate_layout; makes `.claude/p4/` with its folders, its .gitignore, p4.json and its git
                 repository where they are missing; adds the `.git/info/exclude` line; seeds the store's sync
                 workflow once the store has an origin; on the `compact` source, marks the compaction in the
                 session's view record; runs p4conf.watch, the cheap comparison of the running Claude Code binary,
                 the p4 plugins' versions, the store's `claude` section and the P4_* variables its p4.json asks
                 for with p4conf's record, which on any change runs p4conf.keep_settings; runs
                 p4conf.read_changelog, which reads the versions a newer Claude Code left owed from Claude Code's
                 own cached changelog; and brings the repository's and the dependencies' documents and the index up
                 to date.
                 It prints a `systemMessage` only naming a key a store wants that p4 never writes, and never
                 `additionalContext`: a rule every session holds is a rules file, which Claude Code loads itself.
  settings       ConfigChange, matcher `local_settings|project_settings|user_settings`. p4conf.watch checks the
                 keys the record owns, never a block, and prints nothing.
  recall         UserPromptSubmit. A line for each change of Claude Code the changelog read found, once, then the
                 retrieval lines that `injected` lets through as `additionalContext`, with said.py's handles and
                 instruction unless `recall.said.mode` is off, and nothing when it lets none through. It opens the
                 message's row and logs what retrieval found, shown or held back.
  agent          PreToolUse, matcher `Agent`. Nothing: the call runs with its prompt as written. phi.py's text for
                 the subagent and the retrieval lines under "Notes from this repo's memory:" wait for its start.
  subagent-start SubagentStart. phi.py binds the subagent, by the `agent_id` the input carries, to the launching
                 session's step in progress. Then the lines of the Agent call that launched it as
                 `additionalContext`: the plugin's hooks module binds the subagent's id to that call's id at
                 `agent.spawn`, and launch_of reads the pair. Nothing where no launch is bound or it kept no line.
  lookup-check   No entry of hooks.json. The plugin's hooks module, hooks/register.ts, runs it at `tool.check`, only
                 for a call python has a check for, and reads what it prints as a PreToolUse hook's output: a deny
                 or an ask is the verdict, `additionalContext` reaches the model beside the call's result or in a
                 deny's reason, and a `systemMessage` goes to the debug log. The first answer of phi.py's checks
                 that PHI_CHECK names for the tool, or else lookups.py's check: an earlier finding beside a web
                 call, an earlier failure before a command expected to fail. A subagent's call also gets phi.py's
                 word of what changed since its launch beside that answer, when there is one.
  lookup-record  PostToolUseFailure, matcher `.*`, and PostToolUse for the tools of WAITED alone. phi.py's records
                 that PHI_RECORD names for the tool, whose answer is returned for `update_plan`, Write and Edit;
                 otherwise lookups.py writes the call's row and tells a failure what other sessions did about it.
  lookup-row     PostToolUse for every tool WAITED does not name, async. The call's row, and nothing printed.
  close          Stop. Nothing printed. It completes the message's row from the reply, writes the turn's usage and
                 repo labels and its task, notes the dependency files the turn opened, brings view.py's record of
                 the session up to date, and then the repository's and the dependencies' documents and the index.
  subagent-stop  SubagentStop, matcher `.*`. Nothing printed. It closes phi.py's record of the subagent, then writes
                 the usage and repo labels of what the agent hook served it, and its task.
  train          Stop, async. Nothing printed. `train --if-owed`, a round of the ranker when train.py's `owed` says
                 one is due, which calls no paid model; nothing when p4.json's `recall.learn` is false.

What the hooks reference, https://code.claude.com/docs/en/hooks, says of the events these handlers answer:
- UserPromptSubmit: `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}`
  adds context beside the submitted prompt and cannot replace the prompt.
- SessionStart: `hookSpecificOutput.additionalContext` adds context for Claude, and so does plain stdout, so a
  silent hook prints nothing at all. The layout hook hands no rules: memory.md, "Organize rules with
  `.claude/rules/`", says "Rules without `paths` frontmatter are loaded at launch with the same priority as
  `.claude/CLAUDE.md`" and "Personal rules in `~/.claude/rules/` apply to every project on your machine", and
  context-window.md, "What survives compaction", has the row "Project-root CLAUDE.md and unscoped rules |
  Re-injected from disk". catchup.py tells ezexe of a rule a store still marks pinned that no rules file carries.
- PreToolUse: the agent hook rewrites nothing, so the Agent call runs as written, and sets no `permissionDecision`
  unless P4_AGENT_ALLOW=1 adds "allow".
- SubagentStart: "SubagentStart hooks receive `agent_id` with the unique identifier for the subagent and
  `agent_type` with the agent name that the matcher filters on", and `additionalContext` is "added to the subagent's
  context at the start of its conversation, before its first prompt", so the subagent-start hook binds the id and
  gives the lines there, ezexe/p4#243 row D2. The page gives the input no field of the Agent call that launched the
  subagent, neither its `tool_use_id` nor its prompt. The hooks module's event does: `agent.spawn` carries the
  call's `tool_use_id`, "The Agent tool call this spawn belongs to", and answers "The started subagent's id: the
  same string its loop's `tool.call` events carry as `agentId`", by the types of Claude Code 2.1.326. hooks/
  register.ts writes that pair, and a start takes the lines of its own launch and of no other.
- PostToolUse and PostToolUseFailure: `additionalContext` adds context beside the call's result.
- Stop: the close hook reads the reply from `last_assistant_message`, since `transcript_path` can lag the
  conversation, and prints nothing, since a `decision` to block or an `additionalContext` would continue the turn.
- SubagentStop: the input adds `agent_id`, `agent_type`, `agent_transcript_path` and `last_assistant_message`.
- async: an async hook can't block or control Claude's behaviour, and its output is delivered on the next turn, so
  the train hook prints nothing. With `-p`, Claude Code kills an async hook still running at teardown.
- `systemMessage` is a warning shown to ezexe.
"""

import json
import os
import re
import sys
import time

# subprocess, hashlib, contextlib and io are imported where they are used, so the `recall` hook, which runs on every
# message, does not pay for them: h_recall states its budget

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

NOTES_HEAD = "Notes from this repo's memory:"
REPO_DEADLINE_S = 8.0
HOOK_BUDGET_S = 11.0             # the layout hook's 15 s, less the index build: what the two reads share
SEED_MARKER = "# seeded by p4-recall"
# a seed marker: the GITIGNORE header, SEED_MARKER, or the header that the vlds plugin's layout hook wrote in the
# stores this plugin inherits
SEED_MARKER_RE = re.compile(r"(?i)^#\s*seeded (once )?by (p4-recall|the vlds plugin)\b")
GITIGNORE = """# seeded once by p4-recall; your edits win
temportal/notebook/.out/
phi/models/served/
phi/models/index.json
phi/models/repo.json
phi/models/deps.json
phi/models/near.json
phi/models/lookups.db*
phi/models/view/
phi/models/*.tmp
.layout.lock
.settings.lock
claude-settings.json
phi/claude-code-watch.pending.json*
phi/sessions/*/log.jsonl
phi/sessions/*/session.md
phi/sessions.md
phi/rules.md
phi/catchup.json
phi/**/*.tmp
phi/**/*.lock
phi/sessions/*/.calls/
phi/.agents/
phi/.nudge/
__pycache__/
*.pyc
*.png
*.jpg
*.zip
*.gz
phi/models/ranker.pt
"""
# phi/models/ranker.pt is each machine's own build of the .pt ranker's chain, the format of ezexe/phi's phi_rank, and
# is never tracked. The chain itself, phi/models/ranker-anchor.pt and phi/models/ranker.rNNN.phid, and the pretrained
# base are tracked in git LFS through the store's .gitattributes, so a blanket *.pt or *.phid here would hide the very
# files the other machines pull.
# inject is "rules-facts" by default: only the rule and fact lines reach the model. A paid validation over two seeds
# with a Haiku judge decides it. Every line shown, inject: true, is never better than Claude Code with no line on the
# general tasks, is worse on one lesson task on both seeds and on held-out short turns, 0.373 and 0.360 against 0.393
# and 0.373, and is better only on tasks newer than the model, 0.75 against 0.50; a mode worse anywhere stays off.
# The rule and fact lines alone change nothing where every line costs, and score 0.667 against 0.50 on the newer
# tasks on both seeds. The other lines are held back while the query still runs and logs what it would have shown,
# so usage labels keep teaching the model. inject: false shows no line at all.
CONFIG = {"inject": "rules-facts"}


RULES_FACTS = re.compile(r"^- \S+ (rule|fact): ")


def inject_mode(p4):
    """"off", "rules-facts" or "all": which retrieval lines reach the main agent or a subagent, by p4.json's
    recall.inject, which is false, "rules-facts" or true. P4_RECALL_INJECT set to 0, 1, true, false or rules-facts
    overrides it as p4conf reads every variable: for the session's own store and only when a person set it."""
    v = p4conf.section(p4, "recall", write=False).get("inject", CONFIG["inject"])
    return "rules-facts" if v == "rules-facts" else ("all" if v is True else "off")


def injected(p4, lines):
    """The lines that may reach the model under inject_mode: all of them, only the rule and fact lines, or none."""
    mode = inject_mode(p4)
    if mode == "all":
        return list(lines)
    if mode == "rules-facts":
        return [l for l in lines if RULES_FACTS.match(l)]
    return []


def project_of(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def p4_of(payload):
    return os.path.join(project_of(payload), ".claude", "p4")


def ready(payload):
    """The .claude/p4 directory, with REPO_DEADLINE_S set from its p4.json, when the layout hook has made its corpus
    or models folder; None otherwise."""
    p4 = p4_of(payload)
    p4conf.migrate_layout(p4)             # a store in an older layout is moved first
    if not (os.path.isdir(p4conf.sub(p4, "store")) or os.path.isdir(p4conf.sub(p4, "models"))):
        return None
    p4conf.configure(globals(), p4, "recall", {"repo_deadline_s": "REPO_DEADLINE_S"})
    return p4


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def sha8(s):
    import hashlib
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:8]


def git(*args, cwd, timeout=10):
    import subprocess
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)


# --- `layout`, on SessionStart ---------------------------------------------------------------------------

def init_layout(project):
    """Make .claude/p4/ with its folders, its .gitignore, p4.json and its git repository where they are missing, add
    its line to the project's .git/info/exclude, and seed the store's sync workflow once it has an origin.
    Returns the p4 path."""
    import subprocess
    p4 = os.path.join(project, ".claude", "p4")
    os.makedirs(p4, exist_ok=True)
    p4conf.migrate_layout(p4)             # a store in an older layout is moved first
    for sub in (p4conf.sub(p4, "store"), p4conf.sub(p4, "store", "messages"), p4conf.sub(p4, "models")):
        os.makedirs(sub, exist_ok=True)
    seed_gitignore(os.path.join(p4, ".gitignore"))
    p4conf.load(p4)                       # p4.json: every plugin's settings, written when missing
    if not os.path.exists(os.path.join(p4, ".git")):
        try:
            git("init", "-q", cwd=p4)
        except (OSError, subprocess.SubprocessError):
            pass
    exclude_line(project)
    try:                       # the store's sync workflow and script, once it has an origin, unless recall.sync.seed is false
        conf = p4conf.section(p4, "recall", write=False).get("sync", {})
        if conf.get("seed", True) and git("remote", "get-url", "origin", cwd=p4).returncode == 0:
            import sync
            sync.seed(p4, conf.get("main", "main"))
    except (OSError, ImportError, subprocess.SubprocessError):
        pass
    return p4


def seeded_lines():
    return [l for l in GITIGNORE.splitlines() if l and not l.startswith("#")]


def seed_gitignore(gi, today=None):
    """The store's .gitignore: written whole when there is none. Otherwise each seeded line the file lacks is appended
    under a marker line, `# seeded by p4-recall <date>`, and nothing else is touched or reordered. A line ezexe
    deleted on purpose cannot be told from one a newer plugin added, so the marker decides. A file with a seed marker
    gets the lines it lacks. A file with no marker and some seeded line is one where ezexe deleted the marker block,
    and gets nothing. A file with no marker and no seeded line is ezexe's own, and gets the whole block. Returns the
    lines added."""
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8", newline="\n") as f:
            f.write(GITIGNORE)
        return seeded_lines()
    try:
        text = open(gi, encoding="utf-8").read()
    except OSError:
        return []
    have = {l.strip() for l in text.splitlines()}
    missing = [l for l in seeded_lines() if l not in have]
    if not missing:
        return []
    marked = any(SEED_MARKER_RE.match(l.strip()) for l in text.splitlines())
    if not marked and len(missing) < len(seeded_lines()):
        return []                          # ezexe removed the marker block: their edits win
    today = today or time.strftime("%Y-%m-%d")
    with open(gi, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + f"{SEED_MARKER} {today}\n"
                + "".join(l + "\n" for l in missing))
    return missing


def exclude_line(project):
    """Add the line `.claude/p4/` to the project's info/exclude unless a line there already names `.claude/p4`. In a
    worktree, `git rev-parse --git-path` names the common git dir's file. Returns whether the line was added."""
    import subprocess
    try:
        r = git("rev-parse", "--git-path", "info/exclude", cwd=project)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0 or not r.stdout.strip():
        return False
    path = r.stdout.strip()
    path = path if os.path.isabs(path) else os.path.join(project, path)
    try:
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    except OSError:
        return False
    if any(l.strip() in (".claude/p4/", ".claude/p4", "/.claude/p4/", "/.claude/p4") for l in text.splitlines()):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + ".claude/p4/\n")
    return True


def refresh_index(p4, project, deadline_s=None):
    """Bring the repository's documents, then the dependencies', up to date incrementally within their deadlines,
    and then rebuild the index when a source is newer than it."""
    deadline_s = REPO_DEADLINE_S if deadline_s is None else deadline_s
    import subprocess
    import deps
    import repo
    import store as st
    t0 = time.time()
    if project and repo.is_repo(project):
        try:
            repo.build(p4, project, deadline_s=deadline_s)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass
    if project:
        try:
            deps.configure(p4)
            left = HOOK_BUDGET_S - (time.time() - t0)
            deps.build(p4, project, deadline_s=max(1.0, min(deps.DEADLINE_S, left)))
        except (RuntimeError, OSError, ValueError):
            pass
    if st.index_stale(p4):
        st.build_index(p4)


SERVED_MAX_S = 86400            # a served record no Stop or SubagentStop took: swept at a layout hook once this old


def sweep_served(p4, now_s=None):
    """Remove the served records older than SERVED_MAX_S: a Stop or a SubagentStop removes the one it reads, and one
    whose session never got there, as one a crash ended, is left; returns how many went."""
    d = p4conf.sub(p4, "models", "served")
    cut = (now_s or time.time()) - SERVED_MAX_S
    n = 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for name in names:
        p = os.path.join(d, name)
        try:
            if name.endswith(".json") and os.path.getmtime(p) < cut:
                os.remove(p)
                n += 1
            elif name.startswith("start-") and os.path.isdir(p):
                # a session's launches no SubagentStart took, and the origin of a prompt long since entered: gone
                # once PENDING_S old, and the folder once empty
                for f in os.listdir(p):
                    q = os.path.join(p, f)
                    if os.path.getmtime(q) < (now_s or time.time()) - PENDING_S:
                        os.remove(q)
                        n += 1
                if not os.listdir(p):
                    os.rmdir(p)
        except OSError:
            pass
    return n


def h_layout(payload):
    project = project_of(payload)
    p4 = init_layout(project)
    asks = settings_watch(project, payload)
    sweep_served(p4)
    if payload.get("source") == "compact" and payload.get("session_id"):
        try:                    # view.py: the compaction marked where it happened, not guessed from the transcript
            import view
            view.compacted(p4, project, payload["session_id"], payload.get("transcript_path") or "")
        except (OSError, ValueError, KeyError, ImportError):
            pass
    refresh_index(p4, project)
    return {"systemMessage": "phi (p4-phi): " + "; ".join(asks) + "."} if asks else None


# --- `settings`, on ConfigChange, and the watcher the layout hook runs ----------------------------------------

LIMITS = os.path.join(HERE, "claude_code_limits.json")


def settings_watch(project, payload):
    """p4conf.watch at a start or a settings change: the asks to show ezexe. At a start it then reads the versions
    the record owes from Claude Code's own cached changelog, a local file read in the hook's own time, with no web
    call and no process of its own. A failure of any kind is one line among the asks, which the layout hook shows as
    its systemMessage, never the hook's own failure, so the rest of the layout handler runs."""
    try:
        got = p4conf.watch(project, payload)
        if payload.get("hook_event_name") != "ConfigChange":
            p4conf.read_changelog(os.path.join(p4conf.main_root(project)[0], ".claude", "p4"), limits=LIMITS)
    except Exception as e:  # noqa: BLE001
        return [f"the settings watcher failed: {type(e).__name__}: {e}"]
    return got["asks"]


def h_settings(payload):
    """ConfigChange of the local, project or user settings file: the keys the record owns checked, never a block."""
    settings_watch(project_of(payload), payload)
    return None


# --- `recall`, on UserPromptSubmit -----------------------------------------------------------------------

def h_recall(payload):
    """The retrieval lines, and before them a line for each change the read of Claude Code's cached changelog
    found, taken once."""
    out = _recall(payload)
    p4 = p4_of(payload)
    if not os.path.exists(os.path.join(p4, "phi", "claude-code-watch.pending.json")):
        return out
    watch = p4conf.claim_watch(p4)
    if not watch:
        return out
    hso = dict((out or {}).get("hookSpecificOutput") or {"hookEventName": "UserPromptSubmit"})
    hso["additionalContext"] = "\n".join(watch + [x for x in (hso.get("additionalContext"),) if x])
    return {**(out or {}), "hookSpecificOutput": hso}


def _recall(payload):
    """The retrieval lines for the submitted message, beside it. The hook runs on every message, so its budget is
    300 ms from the start of `sh hooks/recall-hook.sh recall` to its answer, on an index of about 5,000 documents whose
    index is fresh; RecallLatency in test_hooks.py asserts it."""
    import labels as lb
    import p4 as cli
    import rows
    p4 = ready(payload)
    if not p4:
        return None
    prompt = payload.get("prompt") or ""
    session = payload.get("session_id") or ""
    by = rows.whose(rows.origin_of(payload))          # whose words it is, by the origin the hooks module kept
    if rows.harness(prompt, by):
        rows.row_open(p4, session, prompt, now(), by=by)   # a notification: its row, complete on arrival, no retrieval
        return None
    node, node_ids = cli.live_node(p4, session)
    r = cli.query(p4, prompt, session[:8] if session else None, now(), node=node, node_ids=node_ids)
    rid = rows.row_open(p4, session, prompt, now(), by=by)
    ids = [i for i in r["ids"] if not i.startswith(("history:", "repeat"))]
    shown = injected(p4, r["lines"])
    shadow = not shown
    handles = {}
    if shown:
        import said
        if said.mode(p4) != "off":
            # said.py: the rule, correction, retraction and fact lines get handles, and the session is asked to
            # state what it did with them
            keep = set(shown)
            shown, handles = said.tag([(l, i) for l, i in zip(r["lines"], r["ids"]) if l in keep])
            if handles:
                shown.append(said.instruction(handles, session, p4))
                said.asked(p4, session, rid, handles, now())
    lb.write_served(p4, f"turn-{session}", {"ids": ids, "text": prompt[:2000], "task": rid, "session": session,
                                            "time": now(), "lines": len(r["lines"]), "shown": len(shown),
                                            "shadow": shadow, "handles": handles})
    if shadow:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(shown)}}


# --- `agent`, on PreToolUse for the Agent tool ---------------------------------------------------------

def agent_lines(p4, prompt):
    import p4 as cli
    r = cli.query(p4, prompt, None, now())
    return r


def agent_input(inp):
    """The Agent call's answer: none, since its input runs as written, or `permissionDecision: allow` when
    P4_AGENT_ALLOW=1."""
    if os.environ.get("P4_AGENT_ALLOW") == "1":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
    return None


def phi_text(name, payload):
    """The text of phi.py's routed handler `name`, '' when it has none or fails."""
    try:
        import phi
        out = phi.routed(name, payload)
    except Exception:  # noqa: BLE001
        return ""
    return str(((out or {}).get("hookSpecificOutput") or {}).get("additionalContext") or "")


PENDING_S = 600                  # a launch's lines no subagent start took within this long are dropped


def pending_dir(payload):
    """Where a launch's lines wait for its subagent's start: the store's served folder, which git ignores and the
    layout hook sweeps, or a folder of the temp directory in a project with no store. The plugin's hooks module
    writes into the store's one too: a subagent's binding to its launch, and the origin of the session's latest
    prompt, origin.json, which rows.origin_of reads."""
    import tempfile
    p4 = p4_of(payload)
    base = p4conf.sub(p4, "models", "served") if os.path.isdir(p4conf.sub(p4, "models")) else os.path.join(
        tempfile.gettempdir(), "p4-phi-subagent-start", sha8(os.path.normcase(os.path.abspath(project_of(payload)))))
    return os.path.join(base, "start-" + re.sub(r"[^\w-]", "_", payload.get("session_id") or "none"))


def hold_for_start(payload, kind, text, key):
    """The launch's lines, kept for its SubagentStart under the Agent call's tool_use_id, which is how launch_of's
    answer finds them. A launch whose call was denied or failed starts no subagent, so no start is bound to it, and
    its lines go at PENDING_S. phi.py binds its own record of the subagent by the `agent_id` alone."""
    d = pending_dir(payload)
    tid = re.sub(r"[^\w-]", "_", str(payload.get("tool_use_id") or ""))
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{time.time_ns()}-{sha8(kind)}-{tid}.json"), "w", encoding="utf-8") as f:
            json.dump({"type": kind, "text": text, "key": key, "time": time.time(),
                       "tool_use_id": payload.get("tool_use_id") or ""}, f, ensure_ascii=False)
    except OSError:
        pass


BOUND = "bound-"                 # in pending_dir, before a subagent's id: the file that names its launch


def launch_of(payload):
    """The Agent call that launched the subagent a SubagentStart names: that call's `tool_use_id`, read from the
    file the plugin's hooks module wrote for the subagent's id when `agent.spawn` answered, and taken. '' where no
    launch is bound: a session with no hooks module, a subagent no Agent call started, such as a workflow's, or a
    project with no store, where no line is kept either."""
    aid = re.sub(r"[^\w-]", "_", str(payload.get("agent_id") or ""))
    if not aid:
        return ""
    path = os.path.join(pending_dir(payload), BOUND + aid)
    try:
        with open(path, encoding="utf-8") as f:
            tid = f.read().strip()
        os.remove(path)
    except OSError:
        return ""
    return tid


def h_agent(payload):
    """The Agent call runs with its prompt as written. phi.py's text for the subagent and the retrieval lines wait
    in pending_dir for its SubagentStart, which adds them as context, ezexe/p4#243 row D2."""
    import labels as lb
    inp = payload.get("tool_input")
    if not isinstance(inp, dict) or not isinstance(inp.get("prompt"), str):
        return None
    kind = str(inp.get("subagent_type") or "general-purpose")
    # phi.py's text for the subagent: the plan step it serves, and what this session's parent holds for its paths
    node = phi_text("agent-launch", payload)
    node = node if node and node not in inp["prompt"] else ""
    prompt = inp["prompt"]
    notes, key = "", sha8(prompt.rstrip())
    p4 = ready(payload)
    if p4 and NOTES_HEAD not in prompt:
        r = agent_lines(p4, prompt)
        if r["lines"]:
            shown = injected(p4, r["lines"])
            lb.write_served(p4, f"agent-{key}", {"ids": [i for i in r["ids"] if ":" in i], "text": prompt[:2000],
                                                 "task": f"agent:{key}", "time": now(),
                                                 "tool_use_id": payload.get("tool_use_id", ""), "shadow": not shown})
            if shown:
                notes = NOTES_HEAD + "\n" + "\n".join(shown)
    text = "\n\n".join(x for x in (notes, node) if x)
    if text or p4:
        hold_for_start(payload, kind, text, key)
    return agent_input(inp)


def h_subagent_start(payload):
    """SubagentStart: phi.py binds the subagent by the `agent_id` the input carries. Then the launch launch_of
    names for it gives its lines as `additionalContext`, and its served record is bound to the subagent's id for
    its SubagentStop. A start no launch is bound to gets no line."""
    import labels as lb
    phi_text("agent-start", payload)              # phi.py: the subagent's id bound to the step in progress
    tid = launch_of(payload)
    d = pending_dir(payload)
    tail = "-" + re.sub(r"[^\w-]", "_", tid) + ".json"
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return None
    for name in names:
        p = os.path.join(d, name)
        try:
            if time.time() - os.path.getmtime(p) > PENDING_S:
                os.remove(p)
                continue
            if not tid or not name.endswith(tail):
                continue
            with open(p, encoding="utf-8") as f:
                row = json.load(f)
            os.remove(p)                                  # taken by the one start it launched
        except (OSError, ValueError):
            continue
        p4 = p4_of(payload)
        if payload.get("agent_id") and row.get("key") and os.path.isdir(p4conf.sub(p4, "models")):
            lb.write_served(p4, f"bind-{payload['agent_id']}", {"key": row["key"]})
        if not row.get("text"):
            return None
        return {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": row["text"]}}
    return None


# --- `close` and `subagent-stop`, on Stop and SubagentStop -----------------------------------------------

def turn_for(transcript_path, prompt, sidechain=False):
    """The transcript's last turn whose prompt starts like this one, or else its last turn."""
    import transcript as tr
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    lines = tr.read_lines(transcript_path)
    if sidechain:
        for d in lines:
            d["isSidechain"] = False
            if d.get("type") == "user" and isinstance((d.get("message") or {}).get("content"), str):
                d.setdefault("origin", {})
    ts = tr.turns(lines)
    if not ts:
        return None
    head = (prompt or "")[:80].strip()
    for t in reversed(ts):
        if head and t["prompt"].strip().startswith(head[:40]):
            return t
    return ts[-1]


def labels_for_turn(p4, project, idx, task_id, served, reply, turn, when):
    import labels as lb
    rows_out = []
    if served:
        rows_out += lb.usage_labels(p4, idx, served, reply, turn, task_id, when)
    if turn is not None:
        ri = lb.repo_index(idx)
        if ri[0]:
            got, _ = lb.turn_repo_labels(turn, project, ri, task_id, reply, when, p4=p4)
            rows_out += got
        try:                    # a dependency's file the turn opened and the index lacks: read at the next build
            import deps
            deps.note_opened(p4, [p for p in deps.opened_in_turn(turn, project) if p not in ri[0]])
        except (ImportError, OSError, ValueError, KeyError):
            pass
    lb.append_tsv(lb.mpath(p4, lb.TRAIN), lb.TRAIN_HEAD, rows_out)
    return rows_out


def h_close(payload):
    import labels as lb
    import rows
    import store as st
    p4 = ready(payload)
    if not p4:
        return None
    project = project_of(payload)
    session = payload.get("session_id") or ""
    reply = payload.get("last_assistant_message") or ""
    when = now()
    row, done = rows.row_close(p4, session, reply, when)
    served = lb.read_served(p4, f"turn-{session}")
    idx, _ = st.ensure_index(p4)
    prompt = (served or {}).get("text") or (st.unquote(row.fields.get("fingerprint", "")) if row else "")
    task_id = (served or {}).get("task") or (row.id if row else f"turn:{session[:8]}:{when}")
    turn = turn_for(payload.get("transcript_path") or "", prompt)
    got = labels_for_turn(p4, project, idx, task_id, served, reply, turn, when)
    if got or served:
        lb.add_tasks(p4, [{"id": task_id, "session": session[:8], "time": when, "text": st.collapse(prompt)[:2000],
                           "kind": rows.task_kind(p4, session, row, prompt)}])
    if served:
        try:
            os.remove(lb.served_path(p4, f"turn-{session}"))
        except OSError:
            pass
    try:                        # view.py: what this session has in view, brought up to date with its transcript
        import view
        view.refresh(p4, project, session, payload.get("transcript_path") or "",
                     served_now=list(((served or {}).get("handles") or {}).values()))
    except (OSError, ValueError, KeyError, ImportError):
        pass
    refresh_index(p4, project)
    return None


def h_subagent_stop(payload):
    phi_text("agent-stop", payload)               # phi.py: the subagent's record closed with its last message
    import labels as lb
    import store as st
    import transcript as tr
    p4 = ready(payload)
    if not p4:
        return None
    project = project_of(payload)
    path = payload.get("agent_transcript_path") or ""
    reply = payload.get("last_assistant_message") or ""
    first = ""
    for d in tr.read_lines(path):
        if d.get("type") == "user":
            c = (d.get("message") or {}).get("content")
            if isinstance(c, list):
                c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            if isinstance(c, str) and c.strip():
                first = c
                break
    original = first.split("\n\n" + NOTES_HEAD, 1)[0]
    key = f"agent-{sha8(original.rstrip())}"
    bind = lb.read_served(p4, f"bind-{payload.get('agent_id', '')}") if payload.get("agent_id") else None
    if bind and bind.get("key"):
        key = f"agent-{bind['key']}"                  # bound at its SubagentStart, whatever its first message reads
        try:
            os.remove(lb.served_path(p4, f"bind-{payload['agent_id']}"))
        except OSError:
            pass
    served = lb.read_served(p4, key)
    if not served:
        return None
    idx, _ = st.ensure_index(p4)
    task_id = served.get("task") or f"agent:{payload.get('agent_id', '')}"
    turn = turn_for(path, first, sidechain=True)
    when = now()
    labels_for_turn(p4, project, idx, task_id, served, reply, turn, when)
    lb.add_tasks(p4, [{"id": task_id, "session": (payload.get("session_id") or "")[:8], "time": when,
                       "text": st.collapse(served.get("text") or original)[:2000], "kind": "agent"}])
    try:
        os.remove(lb.served_path(p4, key))
    except OSError:
        pass
    return None


# --- `lookup-check` before a checked tool call, and `lookup-record` after every tool call ---------------

PHI_CHECK = {"mcp__ccd_session__start_session": "start-advice",
             "mcp__ccd_session_mgmt__archive_session": "self-archive",
             "SendMessage": "go-guard", "mcp__ccd_session_mgmt__send_message": "go-guard",
             "Bash": ("cards-guard", "issue-guard", "store-guard", "branch-guard", "restart-check", "nudge",
                      "puppeteer-tool"),
             "PowerShell": ("cards-guard", "issue-guard", "store-guard", "branch-guard", "restart-check", "nudge",
                            "puppeteer-tool"),
             "Edit": ("nudge", "puppeteer-tool"), "Write": ("nudge", "puppeteer-tool"),
             "NotebookEdit": ("nudge", "puppeteer-tool")}
PHI_RECORD = {"mcp__ccd_turn__update_plan": "plan", "mcp__ccd_turn__wrap_up": "wrap-up", "Write": "memory-gap",
              "Edit": "memory-gap", "TaskStop": "task-stop"}


# The tools whose PostToolUse entry a call waits on, as the first matcher of hooks.json lists them: a record of
# phi.py can answer for a tool of PHI_RECORD, and lookups.py reads an error only out of a shell tool's output when
# the call worked, so it has words for no other. Every other tool has the async entry `lookup-row` alone, which
# writes the same row h_lookup_record would, and a call that failed has the PostToolUseFailure entry whatever its
# tool.
WAITED = ("Bash", "PowerShell", "Write", "Edit", "TaskStop", "mcp__ccd_turn__update_plan",
          "mcp__ccd_turn__wrap_up")

# After a shell call: phi.py's tie of a behaviour memory to the issue a `gh issue create` filed for it. It answers
# nothing, so it runs behind a clean call with the lookup row and beside a failed one, and needs no gate of its own.
PHI_TIE = {"Bash": "issue-tie", "PowerShell": "issue-tie"}

# A call a plugin's hooks module made itself, with `$.tool.call`, carries an id that begins so. Seen with a probe mod
# on Claude Code 2.1.326 in the desktop app and on 2.1.328 in a scripted run: the PreToolUse and PostToolUse command
# hooks run for it as for a session's own call, it leaves no row in the transcript and no model reads its result. So
# it is no lookup of the session's: the record hooks write no row for it and phi.py keeps nothing of it. p4-phi's own
# module makes such calls unless a store turns `app_tools` off, once a minute at most.
PLUGIN_CALL = "toolu_plugin_"


def plugins_own(payload):
    """Whether a tool call is one a plugin's hooks module made itself, by its id."""
    return str(payload.get("tool_use_id") or "").startswith(PLUGIN_CALL)


def phi_route(payload, table):
    """phi.py's handlers that `table` names for this tool, run in this process in their order until one answers:
    that answer, or None. A failure in phi.py is swallowed and never touches the lookup hooks. A session registers a
    plugin's hooks when it loads the plugin, at its start or at `/reload-plugins`, and a record added to phi.py
    needs no hook of its own in hooks.json, only its tool in WAITED and in the two PostToolUse matchers there. A check added to phi.py
    needs none either, and its tool must be one hooks/register.ts lists, where the plugin's hooks module tells
    which calls python has a check for."""
    names = table.get(str(payload.get("tool_name") or ""))
    for name in (names,) if isinstance(names, str) else names or ():
        try:
            import phi
            out = phi.routed(name, payload)
        except Exception:  # noqa: BLE001
            out = None
        if out:
            return out
    return None


def h_lookup_check(payload):
    """Before a tool runs. The first answer of phi.py's checks that PHI_CHECK names for the tool, or else
    lookups.py's check: an earlier finding beside a web call, an earlier failure before a command expected to
    fail. A subagent's call also gets phi.py's word of what changed since its launch, when there is one, as
    additionalContext beside that answer."""
    out = phi_route(payload, PHI_CHECK)
    if not out:
        import lookups
        p4 = ready(payload)
        out = lookups.check(p4, payload, now()) if p4 else None
    news = phi_text("agent-pre", payload) if payload.get("agent_id") else ""
    if not news:
        return out
    out = dict(out or {})
    hso = dict(out.get("hookSpecificOutput") or {"hookEventName": "PreToolUse"})
    hso["additionalContext"] = "\n\n".join(x for x in (hso.get("additionalContext"), news) if x)
    out["hookSpecificOutput"] = hso
    return out


def h_lookup_phi(payload):
    """After a clean call the app does not wait on for its lookup row: phi.py's records alone, which must be in
    place before the next call, run here in the entry the call waits on. Its answer is returned for a Write or an
    Edit, as h_lookup_record returns it."""
    if plugins_own(payload):
        return None
    out = phi_route(payload, PHI_RECORD)
    if out and str(payload.get("tool_name") or "") in ("Write", "Edit"):
        return out
    return None


def h_lookup_row(payload):
    """A call's lookup row, written in the background by an async entry; nothing printed. It is a clean call's row
    for a tool of WAITED, and the row of every call that worked for any other tool."""
    if plugins_own(payload):
        return None
    phi_route(payload, PHI_TIE)                    # a `gh issue create` that filed a memory's finding ties it
    import lookups
    p4 = ready(payload)
    if p4:
        lookups.record(p4, payload, now())
    return None


def h_lookup_record(payload):
    """After a tool ran or failed, phi.py's
    records that PHI_RECORD names for the tool run, such as the task list with its step boundary and a background
    task under its step; their answer is returned for `update_plan`, `wrap_up`, Write and Edit. Otherwise lookups.py writes the
    call's row, and a failure other sessions already met is told what they did about it. A call a plugin's hooks
    module made itself gets none of it."""
    if plugins_own(payload):
        return None
    phi_route(payload, PHI_TIE)                    # as h_lookup_row does behind a clean call: one of the two runs
    out = phi_route(payload, PHI_RECORD)
    if out and str(payload.get("tool_name") or "") in ("mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up", "Write", "Edit"):
        return out
    import lookups
    p4 = ready(payload)
    if not p4:
        return None
    text = lookups.record(p4, payload, now())
    if not text:
        return None
    return {"hookSpecificOutput": {"hookEventName": payload.get("hook_event_name") or "PostToolUse",
                                   "additionalContext": text}}


def h_train(payload):
    import contextlib
    import io
    import train
    p4 = ready(payload)
    if not p4:
        return None
    if not p4conf.section(p4, "recall", write=False).get("learn", True):
        return None             # recall.learn false, set by the p4-model skill's mode off: the models stay untouched

    class A:
        pass
    a = A()
    a.p4, a.if_owed, a.now, a.sources = p4, True, "", ""
    with contextlib.redirect_stdout(io.StringIO()):
        train.cmd_train(a)
    return None


def h_catch_up(payload):
    import catchup
    return catchup.hook(payload)


HANDLERS = {"catch-up": h_catch_up, "settings": h_settings, "layout": h_layout, "recall": h_recall, "agent": h_agent, "subagent-start": h_subagent_start,
            "close": h_close, "subagent-stop": h_subagent_stop, "train": h_train,
            "lookup-check": h_lookup_check, "lookup-record": h_lookup_record, "lookup-phi": h_lookup_phi, "lookup-row": h_lookup_row}


def parse_payload(raw: str):
    """The hook's stdin as JSON. A payload written by hand with bare Windows paths, such as `{"cwd":"E:\\projects"}`,
    is read with every backslash that does not escape a quote or a backslash taken literally, rather than failing."""
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        if "escape" not in e.msg:
            raise
        return json.loads(re.sub(r'\\(?![\\"])', r"\\\\", raw))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    name = argv[0] if argv else ""
    payload = {}
    try:
        raw = sys.stdin.read()
        payload = parse_payload(raw)
        if not isinstance(payload, dict):
            payload = {}
        out = HANDLERS[name](payload)
    except Exception as e:  # noqa: BLE001 — a broken hook never blocks a call
        out = {"systemMessage": f"phi (p4-phi): the {name or '?'} hook failed with {type(e).__name__}: {str(e)[:200]};"
                                " nothing was added"}
        try:                # one retrain notice in notices.py's file for the p4-model skill, never a second failure
            import notices
            p4 = p4_of(payload if isinstance(payload, dict) else {})
            if os.path.isdir(p4conf.sub(p4, "store")) or os.path.isdir(p4conf.sub(p4, "models")):
                notices.notify(p4, f"hook {name or '?'}", e, (payload.get("session_id") or "") if isinstance(payload, dict) else "")
        except Exception:  # noqa: BLE001
            pass
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
