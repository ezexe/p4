#!/usr/bin/env python3
"""hook.py <name>: the p4-phi hooks that hooks/recall-hook.sh runs with Claude Code's JSON payload on stdin: the
store's layout, the watch of Claude Code's changelog, the hand-over of a launch's text to its subagent, and the
records phi.py keeps after a tool call. The check before a tool call is here too, and the plugin's hooks module runs
it with a PreToolUse hook's payload. Every handler resolves `.claude/p4/` from CLAUDE_PROJECT_DIR or the payload's
`cwd`, prints only what its row below names, and on any failure exits 0 with one `systemMessage` for ezexe, never
context for the model. Each row gives the handler's name, the event and matcher hooks/hooks.json runs it on, and what
it does.

  layout         SessionStart, matcher `startup|resume|clear|compact|fork`. Moves a store of an older layout through
                 p4conf.migrate_layout; makes `.claude/p4/` with its .gitignore, p4.json and its git repository
                 where they are missing; adds the `.git/info/exclude` line; sweeps the served folder; runs
                 p4conf.watch, the cheap comparison of the running Claude Code binary, the p4 plugins' versions, the
                 store's `claude` section and the P4_* variables its p4.json asks for with p4conf's record, which on
                 any change runs p4conf.keep_settings; and runs p4conf.read_changelog, which reads the versions a
                 newer Claude Code left owed from Claude Code's own cached changelog.
                 It prints a `systemMessage` only with the layout move's lines and a key a store wants that p4 never
                 writes, and never `additionalContext`: a rule every session holds is a rules file, which Claude Code
                 loads itself.
  settings       ConfigChange, matcher `local_settings|project_settings|user_settings`. p4conf.watch checks the
                 keys the record owns, never a block, and prints nothing.
  watch          UserPromptSubmit. A line for each change of Claude Code the changelog read found, once, as
                 `additionalContext`; nothing when there is none.
  agent          PreToolUse, matcher `Agent`. Nothing: the call runs with its prompt as written. phi.py's text for
                 the subagent waits for its start.
  subagent-start SubagentStart. phi.py binds the subagent, by the `agent_id` the input carries, to the launching
                 session's step in progress. Then the text of the Agent call that launched it as
                 `additionalContext`: the plugin's hooks module binds the subagent's id to that call's id at
                 `agent.spawn`, and launch_of reads the pair. Nothing where no launch is bound or it kept no text.
  lookup-check   No entry of hooks.json. The plugin's hooks module, hooks/register.ts, runs it at `tool.check`, only
                 for a call python has a check for, and reads what it prints as a PreToolUse hook's output: a deny
                 or an ask is the verdict, `additionalContext` reaches the model beside the call's result or in a
                 deny's reason, and a `systemMessage` goes to the debug log. The first answer of phi.py's checks
                 that PHI_CHECK names for the tool. A subagent's call also gets phi.py's word of what changed since
                 its launch beside that answer, when there is one.
  lookup-record  PostToolUseFailure, matcher `.*`, and PostToolUse for the tools of WAITED alone. phi.py's records
                 that PHI_RECORD names for the tool, whose answer is returned for `update_plan`, Write and Edit.
  lookup-batch   PostToolBatch, async. phi.py's tie of a memory to the issue a `gh issue create` filed, for each
                 call of the batch that worked, and nothing printed.
  subagent-stop  SubagentStop, matcher `.*`. Nothing printed. It closes phi.py's record of the subagent.

What the hooks reference, https://code.claude.com/docs/en/hooks, says of the events these handlers answer:
- UserPromptSubmit: `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}`
  adds context beside the submitted prompt and cannot replace the prompt.
- SessionStart: `hookSpecificOutput.additionalContext` adds context for Claude, and so does plain stdout, so a
  silent hook prints nothing at all. The layout hook hands no rules: memory.md, "Organize rules with
  `.claude/rules/`", says "Rules without `paths` frontmatter are loaded at launch with the same priority as
  `.claude/CLAUDE.md`" and "Personal rules in `~/.claude/rules/` apply to every project on your machine", and
  context-window.md, "What survives compaction", has the row "Project-root CLAUDE.md and unscoped rules |
  Re-injected from disk".
- PreToolUse: the agent hook rewrites nothing, so the Agent call runs as written, and sets no `permissionDecision`
  unless P4_AGENT_ALLOW=1 adds "allow".
- SubagentStart: "SubagentStart hooks receive `agent_id` with the unique identifier for the subagent and
  `agent_type` with the agent name that the matcher filters on", and `additionalContext` is "added to the subagent's
  context at the start of its conversation, before its first prompt", so the subagent-start hook binds the id and
  gives the text there, ezexe/p4#243 row D2. The page gives the input no field of the Agent call that launched the
  subagent, neither its `tool_use_id` nor its prompt. The hooks module's event does: `agent.spawn` carries the
  call's `tool_use_id`, "The Agent tool call this spawn belongs to", and answers "The started subagent's id: the
  same string its loop's `tool.call` events carry as `agentId`", by the types of Claude Code 2.1.326. hooks/
  register.ts writes that pair, and a start takes the text of its own launch and of no other.
- PostToolUse and PostToolUseFailure: `additionalContext` adds context beside the call's result.
- SubagentStop: the input adds `agent_id`, `agent_type`, `agent_transcript_path` and `last_assistant_message`.
- async: an async hook can't block or control Claude's behaviour, and its output is delivered on the next turn, so
  the lookup-batch hook prints nothing. With `-p`, Claude Code kills an async hook still running at teardown.
- `systemMessage` is a warning shown to ezexe.
"""

import json
import os
import re
import sys
import time

# subprocess, hashlib and tempfile are imported where they are used, so a hook that does not need them does not pay
# for them

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

SEED_MARKER = "# seeded by p4-recall"
# a seed marker: the GITIGNORE header, SEED_MARKER, or the header that the vlds plugin's layout hook wrote in the
# stores this plugin inherits
SEED_MARKER_RE = re.compile(r"(?i)^#\s*seeded (once )?by (p4-recall|the vlds plugin)\b")
GITIGNORE = """# seeded once by p4-recall; your edits win
temportal/notebook/.out/
phi/served/
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
.venv/
__pycache__/
*.pyc
*.png
*.jpg
*.zip
*.gz
"""
# .venv/ is a Python environment of the store's, which git never tracks: Python's venv page says an environment is
# "Not checked into source control systems such as Git".


def project_of(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def p4_of(payload):
    return os.path.join(project_of(payload), ".claude", "p4")


def ready(payload):
    """The .claude/p4 directory where it holds its p4.json, which the layout hook writes; None otherwise."""
    p4 = p4_of(payload)
    p4conf.migrate_layout(p4)             # a store in an older layout is moved first
    return p4 if os.path.isfile(os.path.join(p4, p4conf.FILE)) else None


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
    """Make .claude/p4/ with its .gitignore, p4.json and its git repository where they are missing, and add its
    line to the project's .git/info/exclude. Returns the lines p4conf.migrate_layout printed for a store of an older
    layout, none where there was nothing to move: the layout hook shows them."""
    import subprocess
    p4 = os.path.join(project, ".claude", "p4")
    os.makedirs(p4, exist_ok=True)
    moved = p4conf.migrate_layout(p4)     # a store in an older layout is moved first
    seed_gitignore(os.path.join(p4, ".gitignore"))
    p4conf.load(p4)                       # p4.json: every plugin's settings, written when missing
    if not os.path.exists(os.path.join(p4, ".git")):
        try:
            git("init", "-q", cwd=p4)
        except (OSError, subprocess.SubprocessError):
            pass
    exclude_line(project)
    return list(moved or [])


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


def served_dir(p4):
    """The folder a launch's text waits in, and the origin of a prompt: phi/served of the store."""
    return p4conf.sub(p4, "phi", "served")


SERVED_MAX_S = 86400            # a served record no Stop or SubagentStop took: swept at a layout hook once this old


def sweep_served(p4, now_s=None):
    """Remove the served records older than SERVED_MAX_S: a Stop or a SubagentStop removes the one it reads, and one
    whose session never got there, as one a crash ended, is left; returns how many went."""
    d = served_dir(p4)
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
    asks = init_layout(project) + settings_watch(project, payload)
    sweep_served(os.path.join(project, ".claude", "p4"))
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


# --- `watch`, on UserPromptSubmit ------------------------------------------------------------------------

def h_watch(payload):
    """A line for each change the read of Claude Code's cached changelog found, taken once, as additionalContext."""
    p4 = p4_of(payload)
    if not os.path.exists(os.path.join(p4, "phi", "claude-code-watch.pending.json")):
        return None
    watch = p4conf.claim_watch(p4)
    if not watch:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(watch)}}


# --- `agent`, on PreToolUse for the Agent tool ---------------------------------------------------------

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


PENDING_S = 600                  # a launch's text no subagent start took within this long is dropped


def pending_dir(payload):
    """Where a launch's text waits for its subagent's start: the store's served folder, which git ignores and the
    layout hook sweeps, or a folder of the temp directory in a project with no store. The plugin's hooks module
    writes into the store's one too: a subagent's binding to its launch, and the origin of the session's latest
    prompt, origin.json, which rows.origin_of reads."""
    import tempfile
    p4 = p4_of(payload)
    base = served_dir(p4) if os.path.isfile(os.path.join(p4, p4conf.FILE)) else os.path.join(
        tempfile.gettempdir(), "p4-phi-subagent-start", sha8(os.path.normcase(os.path.abspath(project_of(payload)))))
    return os.path.join(base, "start-" + re.sub(r"[^\w-]", "_", payload.get("session_id") or "none"))


def hold_for_start(payload, kind, text, key):
    """The launch's text, kept for its SubagentStart under the Agent call's tool_use_id, which is how launch_of's
    answer finds it. A launch whose call was denied or failed starts no subagent, so no start is bound to it, and
    its text goes at PENDING_S. phi.py binds its own record of the subagent by the `agent_id` alone."""
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
    project with no store, where no text is kept either."""
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
    """The Agent call runs with its prompt as written. phi.py's text for the subagent waits in pending_dir for its
    SubagentStart, which adds it as context, ezexe/p4#243 row D2."""
    inp = payload.get("tool_input")
    if not isinstance(inp, dict) or not isinstance(inp.get("prompt"), str):
        return None
    kind = str(inp.get("subagent_type") or "general-purpose")
    # phi.py's text for the subagent: the plan step it serves, and what this session's parent holds for its paths
    node = phi_text("agent-launch", payload)
    text = node if node and node not in inp["prompt"] else ""
    key = sha8(inp["prompt"].rstrip())
    if text or ready(payload):
        hold_for_start(payload, kind, text, key)
    return agent_input(inp)


def h_subagent_start(payload):
    """SubagentStart: phi.py binds the subagent by the `agent_id` the input carries. Then the launch launch_of
    names for it gives its text as `additionalContext`. A start no launch is bound to gets none."""
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
        if not row.get("text"):
            return None
        return {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": row["text"]}}
    return None


def h_subagent_stop(payload):
    phi_text("agent-stop", payload)               # phi.py: the subagent's record closed with its last message
    return None


# --- `lookup-check` before a checked tool call, and `lookup-record` after every tool call ---------------

PHI_CHECK = {"mcp__ccd_session__start_session": "start-advice",
             "mcp__ccd_session_mgmt__archive_session": "self-archive",
             "SendMessage": "go-guard", "mcp__ccd_session_mgmt__send_message": "go-guard",
             "Bash": ("cards-guard", "issue-guard", "store-guard", "force-guard", "branch-guard", "restart-check",
                      "nudge", "puppeteer-tool"),
             "PowerShell": ("cards-guard", "issue-guard", "store-guard", "force-guard", "branch-guard",
                            "restart-check", "nudge", "puppeteer-tool"),
             "Edit": ("nudge", "puppeteer-tool"), "Write": ("nudge", "puppeteer-tool"),
             "NotebookEdit": ("nudge", "puppeteer-tool")}
PHI_RECORD = {"mcp__ccd_turn__update_plan": "plan", "mcp__ccd_turn__wrap_up": "wrap-up", "Write": "memory-gap",
              "Edit": "memory-gap", "TaskStop": "task-stop", "EnterPlanMode": "plan-mode",
              "ExitPlanMode": "plan-mode"}


# The tools whose PostToolUse entry a call waits on, as the first matcher of hooks.json lists them: a record of
# phi.py can answer for a tool of PHI_RECORD, and a shell tool's call can end in the tie of PHI_TIE or the yes of
# PHI_YES. A call that failed has the PostToolUseFailure entry whatever its tool.
WAITED = ("Bash", "PowerShell", "Write", "Edit", "TaskStop", "mcp__ccd_turn__update_plan",
          "mcp__ccd_turn__wrap_up", "EnterPlanMode", "ExitPlanMode")

# After a shell call: phi.py's tie of a behaviour memory to the issue a `gh issue create` filed for it. It answers
# nothing, so it runs in the batch's entry behind a clean call and beside a failed one, and needs no gate of its own.
PHI_TIE = {"Bash": "issue-tie", "PowerShell": "issue-tie"}
# After a shell call that worked: phi.py keeps ezexe's yes to the set of what p4-phi settles with no approval card,
# for the call its `cards-guard` raised the card for, and says how the set stands. It runs in the entry the call
# waits on, so the next call reads the set as it stands, and for no call that failed.
PHI_YES = {"Bash": "cards-yes", "PowerShell": "cards-yes"}

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
    needs no hook of its own in hooks.json, only its tool in WAITED, in the PostToolUse matcher there and, for a call
    that prints no word of an error, in an arm of hooks/recall-hook.sh. A check added to phi.py
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
    """Before a tool runs. The first answer of phi.py's checks that PHI_CHECK names for the tool. A subagent's call
    also gets phi.py's word of what changed since its launch, when there is one, as additionalContext beside that
    answer."""
    out = phi_route(payload, PHI_CHECK)
    news = phi_text("agent-pre", payload) if payload.get("agent_id") else ""
    if not news:
        return out
    out = dict(out or {})
    hso = dict(out.get("hookSpecificOutput") or {"hookEventName": "PreToolUse"})
    hso["additionalContext"] = "\n\n".join(x for x in (hso.get("additionalContext"), news) if x)
    out["hookSpecificOutput"] = hso
    return out


def h_lookup_phi(payload):
    """After a clean call: phi.py's records, which must be in place before the next call, run here in the entry the
    call waits on. Its answer is returned for a Write or an Edit, as h_lookup_record returns it."""
    if plugins_own(payload):
        return None
    out = phi_route(payload, PHI_RECORD)
    if out and str(payload.get("tool_name") or "") in ("Write", "Edit"):
        return out
    return None


# The field of a PostToolBatch hook's input under which the plugin's hooks module names the calls of the batch that
# failed, by their ids: it hears each at `classic.PostToolUseFailure`. hooks.md, "PostToolBatch input", gives a call
# of `tool_calls` four fields, the tool's name, its input, its id and its response, and seen on Claude Code 2.1.328
# and 2.1.330 a call that failed stands there with its error's text as the response and nothing that marks it.
FAILED_KEY = "p4_failed"


def h_lookup_batch(payload):
    """PostToolBatch, async: phi.py's tie of a memory to the issue a `gh issue create` filed, for every call of a
    batch that worked, in the background by one start, and nothing printed. Seen on Claude Code 2.1.328 and 2.1.330
    in a scripted run: the event comes once a batch, for a batch of one call too and for a subagent's batch with its
    `agent_id`, after every PostToolUse and PostToolUseFailure entry a call waits on has answered.
    A call that failed is left to its PostToolUseFailure entry: the module names such a call under FAILED_KEY.
    A call a plugin's hooks module made itself gets none of it."""
    calls = payload.get("tool_calls")
    if not isinstance(calls, list):
        return None
    marked = payload.get(FAILED_KEY)
    failed = {str(x) for x in marked} if isinstance(marked, list) else set()
    common = {k: v for k, v in payload.items() if k not in ("tool_calls", FAILED_KEY)}
    for call in calls:
        if not isinstance(call, dict):
            continue
        one = {**common, **call, "hook_event_name": "PostToolUse"}
        if plugins_own(one) or str(one.get("tool_use_id") or "") in failed:
            continue
        phi_route(one, PHI_TIE)                    # a `gh issue create` that filed a memory's finding ties it, once
    return None


def h_lookup_record(payload):
    """After a tool ran or failed, phi.py's records that PHI_RECORD names for the tool run, such as the task list
    with its step boundary and a background task under its step; their answer is returned for `update_plan`,
    `wrap_up`, Write, Edit and `ExitPlanMode`. Then the yes to the set of what p4-phi settles with no approval card,
    for the one command it is kept for. A call a plugin's hooks module made itself gets none of it."""
    if plugins_own(payload):
        return None
    phi_route(payload, PHI_TIE)                    # as h_lookup_batch does behind a clean call, and a tie is made once
    out = phi_route(payload, PHI_RECORD)
    if out and str(payload.get("tool_name") or "") in ("mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up",
                                                       "Write", "Edit", "ExitPlanMode"):
        return out
    inp = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    cmd = str(inp.get("command") or "")                 # the one command the yes is kept for, read before any route
    asks = payload.get("hook_event_name") == "PostToolUse" and "phi.py" in cmd and "cards" in cmd
    yes = phi_route(payload, PHI_YES) if asks else None
    said = ((yes or {}).get("hookSpecificOutput") or {}).get("additionalContext") or ""
    if not said:
        return None
    return {"hookSpecificOutput": {"hookEventName": payload.get("hook_event_name") or "PostToolUse",
                                   "additionalContext": said}}


HANDLERS = {"settings": h_settings, "layout": h_layout, "watch": h_watch, "agent": h_agent,
            "subagent-start": h_subagent_start, "subagent-stop": h_subagent_stop, "lookup-check": h_lookup_check,
            "lookup-record": h_lookup_record, "lookup-phi": h_lookup_phi, "lookup-batch": h_lookup_batch}


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
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
