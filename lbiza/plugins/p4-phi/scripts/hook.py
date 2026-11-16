#!/usr/bin/env python3
"""hook.py <name>: the p4-phi hooks that hooks/recall-hook.sh runs with Claude Code's JSON payload on stdin: the
store's layout and catch-up, retrieval, the lookups around every tool call, and training. Every handler resolves
`.claude/p4/` from CLAUDE_PROJECT_DIR or the payload's `cwd`, prints only what its row below names, and on any failure
exits 0 with one `systemMessage` for ezexe, never context for the model. Each row gives the handler's name, the
event and matcher hooks/hooks.json runs it on, and what it does.

  catch-up       SessionStart, matcher `startup`. One `systemMessage` from catchup.py when something fell behind on
                 this machine, such as the store's layout, its branch or the marketplace's plugins; nothing otherwise.
  layout         SessionStart, matcher `startup|resume|clear|compact`. Moves a store of an older layout through
                 p4conf.migrate_layout; makes `.claude/p4/` with its folders, its .gitignore, p4.json and its git
                 repository where they are missing; adds the `.git/info/exclude` line; seeds the store's sync
                 workflow once the store has an origin; on the `compact` source, marks the compaction in the
                 session's view record; and brings the repository's and the dependencies' documents and the
                 index up to date.
                 It prints nothing unless ezexe pinned rules, and then the block `Standing rules from ezexe:` of
                 at most PINNED_CHARS characters as `additionalContext`.
  recall         UserPromptSubmit. The retrieval lines that `injected` lets through as `additionalContext`, with
                 said.py's handles and instruction unless `recall.said.mode` is off, and nothing when it lets none
                 through. It opens the message's row and logs what retrieval found, shown or held back.
  agent          PreToolUse, matcher `Agent`. `updatedInput`: the Agent call's input with its `prompt` extended by
                 phi.py's text for the subagent and by the retrieval lines under "Notes from this repo's memory:";
                 nothing when neither adds a line.
  lookup-check   PreToolUse, matcher `.*`. The first answer of phi.py's checks that PHI_CHECK names for the tool,
                 or else lookups.py's check: an earlier finding in place of a web call, an earlier failure before a
                 command expected to fail. A subagent's call also gets phi.py's word of what changed since its
                 launch beside that answer, when there is one.
  lookup-record  PostToolUse and PostToolUseFailure, matcher `.*`. For a subagent's call, its id bound to phi.py's
                 record of the subagent. Then phi.py's records that PHI_RECORD names for the tool, whose answer is
                 returned for `update_plan`, Write and Edit; otherwise lookups.py writes the call's row and tells a
                 failure what other sessions did about it.
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
  silent hook prints nothing at all.
- PreToolUse: `updatedInput` replaces the whole input object, so the agent hook carries every field of the Agent
  call unchanged beside the `prompt`; that input is `prompt`, `description`, `subagent_type` and `model`. The hook
  sets no `permissionDecision` unless P4_AGENT_ALLOW=1 adds "allow", and in auto mode an `updatedInput` without a
  `permissionDecision` can be denied. The live test experiments/p4-suite/test_live_subagent.py of ezexe/p4-phi, which
  runs `claude -p`, checks that the subagent's first user message carries the appended lines. SubagentStart can add
  context to a subagent before its first prompt without rewriting the Agent call, and hooks.json registers no handler
  of this file on it.
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

PINNED_CHARS = 1500
NOTES_HEAD = "Notes from this repo's memory:"
REPO_DEADLINE_S = 8.0
HOOK_BUDGET_S = 11.0             # the layout hook's 15 s, less the index build: what the two reads share
SEED_MARKER = "# seeded by p4-recall"
# a seed marker: the GITIGNORE header, SEED_MARKER, or the header that the vlds plugin's layout hook wrote in the
# stores this plugin inherits
SEED_MARKER_RE = re.compile(r"(?i)^#\s*seeded (once )?by (p4-recall|the vlds plugin)\b")
GITIGNORE = """# seeded once by p4-recall; your edits win
temportal/scratchpad/.out/
phi/models/served/
phi/models/index.json
phi/models/repo.json
phi/models/deps.json
phi/models/near.json
phi/models/lookups.db*
phi/models/view/
phi/models/*.tmp
.layout.lock
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
    """"off", "rules-facts" or "all": which retrieval lines reach the main agent or a subagent. P4_RECALL_INJECT set
    to 0, 1 or rules-facts overrides p4.json's recall.inject, which is false, "rules-facts" or true."""
    env = os.environ.get("P4_RECALL_INJECT")
    if env in ("0", "1", "rules-facts"):
        return {"0": "off", "1": "all"}.get(env, env)
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
    """The .claude/p4 directory, with PINNED_CHARS and REPO_DEADLINE_S set from its p4.json, when the layout hook has
    made its corpus or models folder; None otherwise."""
    p4 = p4_of(payload)
    p4conf.migrate_layout(p4)             # a store in an older layout is moved first
    if not (os.path.isdir(p4conf.sub(p4, "store")) or os.path.isdir(p4conf.sub(p4, "models"))):
        return None
    p4conf.configure(globals(), p4, "recall", {"pinned_chars": "PINNED_CHARS",
                                                          "repo_deadline_s": "REPO_DEADLINE_S"})
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


def pinned_block(p4):
    import store as st
    rules = [e for e in st.load_store(p4).get("rules.md", [])
             if e.state == "LIVE" and (e.fields.get("pinned", "").strip().lower() in ("yes", "true", "1"))]
    if not rules:
        return ""
    rules.sort(key=lambda e: e.time, reverse=True)
    out = "Standing rules from ezexe:"
    for e in rules:
        line = "\n- " + st.collapse(e.fields.get("plain") or e.value)
        if len(out) + len(line) > PINNED_CHARS:
            break
        out += line
    return out if out.count("\n") else ""


def h_layout(payload):
    project = project_of(payload)
    p4 = init_layout(project)
    if payload.get("source") == "compact" and payload.get("session_id"):
        try:                    # view.py: the compaction marked where it happened, not guessed from the transcript
            import view
            view.compacted(p4, project, payload["session_id"], payload.get("transcript_path") or "")
        except (OSError, ValueError, KeyError, ImportError):
            pass
    refresh_index(p4, project)
    block = pinned_block(p4)
    if block:
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": block}}
    return None


# --- `recall`, on UserPromptSubmit -----------------------------------------------------------------------

def h_recall(payload):
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
    if rows.HARNESS_RE.match(prompt):
        rows.row_open(p4, session, prompt, now())     # a notification: its row, complete on arrival, no retrieval
        return None
    node, node_ids = cli.live_node(p4, session)
    r = cli.query(p4, prompt, session[:8] if session else None, now(), node=node, node_ids=node_ids)
    rid = rows.row_open(p4, session, prompt, now())
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
    out = {"hookEventName": "PreToolUse", "updatedInput": inp}
    if os.environ.get("P4_AGENT_ALLOW") == "1":
        out["permissionDecision"] = "allow"
    return {"hookSpecificOutput": out}


def phi_text(name, payload):
    """The text of phi.py's routed handler `name`, '' when it has none or fails."""
    try:
        import phi
        out = phi.routed(name, payload)
    except Exception:  # noqa: BLE001
        return ""
    return str(((out or {}).get("hookSpecificOutput") or {}).get("additionalContext") or "")


def h_agent(payload):
    import labels as lb
    inp = payload.get("tool_input")
    if not isinstance(inp, dict) or not isinstance(inp.get("prompt"), str):
        return None
    # phi.py's text for the subagent: the plan step it serves, and what this session's parent holds for its paths
    node = phi_text("agent-launch", payload)
    if node and node not in inp["prompt"]:
        inp = dict(inp, prompt=inp["prompt"].rstrip() + "\n\n" + node)
    else:
        node = ""
    p4 = ready(payload)
    if not p4:
        return agent_input(inp) if node else None
    prompt = inp["prompt"]
    if NOTES_HEAD in prompt:
        return agent_input(inp) if node else None   # a retried call that already carries the notes
    r = agent_lines(p4, prompt)
    if not r["lines"]:
        return agent_input(inp) if node else None
    shown = injected(p4, r["lines"])
    shadow = not shown
    key = sha8(prompt.rstrip())           # the prompt before the notes, as h_subagent_stop rebuilds it
    lb.write_served(p4, f"agent-{key}", {"ids": [i for i in r["ids"] if ":" in i], "text": prompt[:2000],
                                         "task": f"agent:{key}", "time": now(),
                                         "tool_use_id": payload.get("tool_use_id", ""), "shadow": shadow})
    if shadow:
        return agent_input(inp) if node else None
    updated = dict(inp)                   # every original field unchanged: updatedInput replaces the whole input
    updated["prompt"] = prompt.rstrip() + "\n\n" + NOTES_HEAD + "\n" + "\n".join(shown)
    out = {"hookEventName": "PreToolUse", "updatedInput": updated}
    if os.environ.get("P4_AGENT_ALLOW") == "1":
        out["permissionDecision"] = "allow"
    return {"hookSpecificOutput": out}


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
    key = f"agent-{sha8(original)}"
    served = lb.read_served(p4, key)
    if not served:
        return None
    idx, _ = st.ensure_index(p4)
    task_id = served.get("task") or f"agent:{payload.get('agent_id', '')}"
    turn = turn_for(path, first, sidechain=True)
    when = now()
    labels_for_turn(p4, project, idx, task_id, served, reply, turn, when)
    lb.add_tasks(p4, [{"id": task_id, "session": (payload.get("session_id") or "")[:8], "time": when,
                       "text": st.collapse(original)[:2000], "kind": "agent"}])
    try:
        os.remove(lb.served_path(p4, key))
    except OSError:
        pass
    return None


# --- `lookup-check` and `lookup-record`, before and after every tool call -------------------------------

PHI_CHECK = {"mcp__ccd_session__start_session": "start-advice", "EnterWorktree": "branch-guard",
             "mcp__ccd_session_mgmt__archive_session": "self-archive",
             "SendMessage": "go-guard", "mcp__ccd_session_mgmt__send_message": "go-guard",
             "Bash": ("branch-guard", "store-guard", "restart-check", "level", "nudge"),
             "PowerShell": ("branch-guard", "store-guard", "restart-check", "level", "nudge"), "Edit": "nudge",
             "Write": "nudge", "MultiEdit": "nudge", "NotebookEdit": "nudge"}
PHI_RECORD = {"mcp__ccd_turn__update_plan": "plan", "Bash": "task", "PowerShell": "task", "Monitor": "task",
              "Agent": "task",
              "Workflow": "task", "TaskStop": "task", "KillShell": "task", "Write": "memory-gap", "Edit": "memory-gap",
              "MultiEdit": "memory-gap"}


def phi_route(payload, table):
    """phi.py's handlers that `table` names for this tool, run in this process in their order until one answers:
    that answer, or None. A failure in phi.py is swallowed and never touches the lookup hooks. A session registers a
    plugin's hooks when it loads the plugin, at its start or at `/reload-plugins`, and the lookup hooks already run
    on every tool, so a check added to phi.py needs no hook of its own in hooks.json."""
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
    lookups.py's check: an earlier finding in place of a web call, an earlier failure before a command expected to
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


def h_lookup_record(payload):
    """After a tool ran or failed. A subagent's call binds its id to phi.py's record of the subagent. Then phi.py's
    records that PHI_RECORD names for the tool run, such as the task list with its step boundary and a background
    task under its step; their answer is returned for `update_plan`, Write and Edit. Otherwise lookups.py writes the
    call's row, and a failure other sessions already met is told what they did about it."""
    if payload.get("agent_id"):
        phi_text("agent-post", payload)            # phi.py: the subagent's id bound to its record
    out = phi_route(payload, PHI_RECORD)
    if out and str(payload.get("tool_name") or "") in ("mcp__ccd_turn__update_plan", "Write", "Edit", "MultiEdit"):
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


HANDLERS = {"catch-up": h_catch_up, "layout": h_layout, "recall": h_recall, "agent": h_agent,
            "close": h_close, "subagent-stop": h_subagent_stop, "train": h_train,
            "lookup-check": h_lookup_check, "lookup-record": h_lookup_record}


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
