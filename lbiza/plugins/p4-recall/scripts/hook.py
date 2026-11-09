#!/usr/bin/env python3
"""hook.py <name>: the p4-recall hooks (fresh-marketplace.md 3.3), run by hooks/run-hook.sh with the harness's JSON
payload on stdin. Every hook resolves `.claude/p4/` from CLAUDE_PROJECT_DIR or the payload's `cwd`, prints only what
its row of 3.3 allows, and on any failure exits 0 with one notice for the user (`systemMessage`), never for the model.

  layout         SessionStart startup|resume|clear|compact  silent; .claude/p4/ and its git repository once, the
                 `.git/info/exclude` line, the index when owed; only when the owner pinned rules, the block
                 `Standing rules from the owner:` (<= 1,500 characters). The store's .gitignore is seeded whole
                 when there is none; later, any seeded line the file lacks is appended under its own marker line
                 (`# seeded by p4-recall <date>`), nothing else touched or reordered. A line the owner deleted on
                 purpose is indistinguishable from one a newer plugin added, so the marker decides: with no seed
                 marker in the file (the owner deleted the marker block) and some seeded line present, nothing is
                 added; with no marker and no seeded line (the owner's own file), the whole block is appended.
  recall         UserPromptSubmit   additionalContext: 0-5 lines; opens the message row; logs what it served
  agent          PreToolUse Agent   updatedInput: the Agent call's input as received, its `prompt` with the lines
                 appended under "Notes from this repo's memory:"; nothing when no line clears the threshold
  subagent-start SubagentStart      (the fallback of 4.7; registered only if the PreToolUse road fails its test)
  close          Stop               nothing; completes the row, writes the turn's usage and repo labels and the
                 dictionary's signals, rebuilds the index when owed
  subagent-stop  SubagentStop       nothing; usage and repo labels for what was served to that subagent
  train          Stop, async        nothing; `train --if-owed`, never a paid step

The output shapes, from https://code.claude.com/docs/en/hooks (read 2026-11-01):
- UserPromptSubmit: `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}`,
  "String added to Claude's context alongside the submitted prompt"; it "can't replace the prompt".
- SessionStart: `hookSpecificOutput.additionalContext` "adds context for Claude"; plain stdout is added as context
  too, so a silent hook prints nothing at all.
- PreToolUse: `updatedInput` "Modifies the tool's input parameters before execution. Replaces the entire input
  object, so include unchanged fields alongside modified ones." and "Combine with "allow" to auto-approve, or "ask"
  to show the modified input to the user." The Agent tool's input: `prompt`, `description`, `subagent_type`,
  `model`. Whether the rewritten `prompt` reaches the subagent is not stated in words; hooks/test_live_subagent.py
  measured it on 2026-11-01 (CLI 2.1.309, haiku): with `updatedInput` alone, no `permissionDecision`, the subagent's
  first user message carried the appended lines, so the hook sets no permission decision (P4_AGENT_ALLOW=1 adds
  "allow" for a harness that would want one) and the SubagentStart fallback stays unregistered.
- SubagentStart: input `agent_id`, `agent_type`; output `additionalContext`, "String added to the subagent's context
  at the start of its conversation, before its first prompt."
- Stop: input `stop_hook_active`, `last_assistant_message` ("use this field rather than reading transcript_path: the
  transcript file isn't guaranteed to include the final message at Stop time"); stdout without `decision` blocks
  nothing; `transcript_path` "may lag the in-memory conversation".
- SubagentStop: input `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`.
- async: "Async hooks can't block or control Claude's behavior" and their output "is delivered on the next
  conversation turn", so the train hook prints nothing; with `-p` an async hook still running at teardown is killed.
- `systemMessage` (a common JSON field) is shown to the user; the 10,000-character cap applies per string.
"""

import json
import os
import re
import sys
import time

# subprocess, hashlib, contextlib and io are imported where they are used: the recall hook runs on every message
# and its whole budget is 300 ms (fresh-marketplace.md 4.5)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

PINNED_CHARS = 1500
NOTES_HEAD = "Notes from this repo's memory:"
REPO_DEADLINE_S = 8.0
SEED_MARKER = "# seeded by p4-recall"
# a seed marker of this plugin (either header) or of the vlds plugin's layout hook, whose stores this one inherits
SEED_MARKER_RE = re.compile(r"(?i)^#\s*seeded (once )?by (p4-recall|the vlds plugin)\b")
GITIGNORE = """# seeded once by p4-recall; your edits win
scratchpad/.out/
models/served/
models/index.json
models/repo.json
models/*.tmp
__pycache__/
*.pyc
*.png
*.jpg
*.zip
*.gz
*.pt
*.phid
"""
# inject: "rules-facts" is the measured default. The paid validation of 2026-11-01 (Opus 5.5, two seeds, Haiku judge):
# - every line (inject: true): never better than the built-in on the general tasks, the same lesson task worse on
#   both seeds, and held-out short turns 0.373/0.360 against 0.393/0.373; it gains on newer-than-the-model tasks
#   (0.75 against 0.50), but section 0's rule keeps it off
# - only the rule and fact lines: silent wherever every line cost (identical to the built-in there), and on the
#   newer-than-the-model tasks 0.667 against 0.50 on both seeds with nothing lost
# With the other lines held back, the query still runs and what it would have shown is logged, so usage labels keep
# teaching the model. inject: false turns it off entirely.
CONFIG = {"teacher-model": "claude-fable-5-1", "inject": "rules-facts"}


RULES_FACTS = re.compile(r"^- \S+ (rule|fact): ")


def inject_mode(p4):
    """"off", "rules-facts" or "all": what reaches the main agent or a subagent. P4_RECALL_INJECT (0, 1 or
    rules-facts) overrides p4.json's recall.inject (false, "rules-facts" or true)."""
    env = os.environ.get("P4_RECALL_INJECT")
    if env in ("0", "1", "rules-facts"):
        return {"0": "off", "1": "all"}.get(env, env)
    v = p4conf.section(p4, "recall", write=False).get("inject", CONFIG["inject"])
    return "rules-facts" if v == "rules-facts" else ("all" if v is True else "off")


def inject_on(p4):
    return inject_mode(p4) != "off"


def injected(p4, lines):
    """The lines that may reach the model under the repo's mode: all of them, only the rule and fact lines (the
    kind that read right on the newer-than-the-model tasks), or none."""
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
    """The .claude/p4 directory when it holds a store (the layout hook made it); None otherwise."""
    p4 = p4_of(payload)
    if not (os.path.isdir(os.path.join(p4, "store")) or os.path.isdir(os.path.join(p4, "models"))):
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


# --- layout (SessionStart) -------------------------------------------------------------------------------

def init_layout(project):
    """Create .claude/p4/ with its folders, .gitignore, config and git repository once; add its line to the
    project's .git/info/exclude. Returns the p4 path."""
    import subprocess
    p4 = os.path.join(project, ".claude", "p4")
    for sub in ("store", "store/messages", "memory", "scratchpad", "models"):
        os.makedirs(os.path.join(p4, sub), exist_ok=True)
    seed_gitignore(os.path.join(p4, ".gitignore"))
    p4conf.load(p4)                       # p4.json: every plugin's settings, written when missing
    if not os.path.exists(os.path.join(p4, ".git")):
        try:
            git("init", "-q", cwd=p4)
        except (OSError, subprocess.SubprocessError):
            pass
    exclude_line(project)
    return p4


def seeded_lines():
    return [l for l in GITIGNORE.splitlines() if l and not l.startswith("#")]


def seed_gitignore(gi, today=None):
    """The store's .gitignore: written whole when absent; otherwise the seeded lines it lacks are appended under
    `# seeded by p4-recall <date>`, when the file carries a seed marker or none of the seeded lines (module
    docstring, layout). Returns the lines added."""
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
        return []                          # the owner removed the marker block: their edits win
    today = today or time.strftime("%Y-%m-%d")
    with open(gi, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + f"{SEED_MARKER} {today}\n"
                + "".join(l + "\n" for l in missing))
    return missing


def exclude_line(project):
    """The one line `.claude/p4/` in the project's info/exclude (a worktree's common git dir), added once."""
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
    """The repository's entries brought up to date (incrementally, within the deadline), then the index rebuilt
    when any source is newer."""
    deadline_s = REPO_DEADLINE_S if deadline_s is None else deadline_s
    import subprocess
    import repo
    import store as st
    if project and repo.is_repo(project):
        try:
            repo.build(p4, project, deadline_s=deadline_s)
        except (RuntimeError, OSError, subprocess.SubprocessError):
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
    out = "Standing rules from the owner:"
    for e in rules:
        line = "\n- " + st.collapse(e.fields.get("plain") or e.value)
        if len(out) + len(line) > PINNED_CHARS:
            break
        out += line
    return out if out.count("\n") else ""


def h_layout(payload):
    project = project_of(payload)
    p4 = init_layout(project)
    refresh_index(p4, project)
    block = pinned_block(p4)
    if block:
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": block}}
    return None


# --- recall (UserPromptSubmit) ---------------------------------------------------------------------------

def h_recall(payload):
    import labels as lb
    import p4 as cli
    import rows
    p4 = ready(payload)
    if not p4:
        return None
    prompt = payload.get("prompt") or ""
    session = payload.get("session_id") or ""
    if rows.HARNESS_RE.match(prompt):
        rows.row_open(p4, session, prompt, now())     # a notification: its row, complete on arrival, and no recall
        return None
    r = cli.query(p4, prompt, session[:8] if session else None, now())
    rid = rows.row_open(p4, session, prompt, now())
    ids = [i for i in r["ids"] if not i.startswith(("history:", "repeat"))]
    shown = injected(p4, r["lines"])
    shadow = not shown
    lb.write_served(p4, f"turn-{session}", {"ids": ids, "text": prompt[:2000], "task": rid, "session": session,
                                            "time": now(), "lines": len(r["lines"]), "shown": len(shown),
                                            "shadow": shadow})
    if shadow:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(shown)}}


# --- subagent recall (PreToolUse Agent; SubagentStart fallback) ------------------------------------------

def agent_lines(p4, prompt, model_id=""):
    import p4 as cli
    r = cli.query(p4, prompt, None, now())
    return r


def h_agent(payload):
    import labels as lb
    p4 = ready(payload)
    if not p4:
        return None
    inp = payload.get("tool_input")
    if not isinstance(inp, dict) or not isinstance(inp.get("prompt"), str):
        return None
    prompt = inp["prompt"]
    if NOTES_HEAD in prompt:
        return None                       # already carries notes (a retried call)
    r = agent_lines(p4, prompt)
    if not r["lines"]:
        return None
    shown = injected(p4, r["lines"])
    shadow = not shown
    lb.write_served(p4, f"agent-{sha8(prompt)}", {"ids": [i for i in r["ids"] if ":" in i], "text": prompt[:2000],
                                                  "task": f"agent:{sha8(prompt)}", "time": now(),
                                                  "tool_use_id": payload.get("tool_use_id", ""), "shadow": shadow})
    if shadow:
        return None
    updated = dict(inp)                   # every original field, unchanged, as updatedInput requires
    updated["prompt"] = prompt.rstrip() + "\n\n" + NOTES_HEAD + "\n" + "\n".join(shown)
    out = {"hookEventName": "PreToolUse", "updatedInput": updated}
    if os.environ.get("P4_AGENT_ALLOW") == "1":
        out["permissionDecision"] = "allow"
    return {"hookSpecificOutput": out}


def last_agent_prompt(transcript_path, agent_type):
    """The prompt of the last Agent tool_use in the parent transcript whose subagent_type is agent_type (4.7's
    fallback: a guess when several agents of one type launch at once)."""
    import transcript as tr
    for d in reversed(tr.read_lines(transcript_path)):
        if d.get("type") != "assistant":
            continue
        for b in reversed((d.get("message") or {}).get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                inp = b.get("input") or {}
                if (inp.get("subagent_type") or "general-purpose") == (agent_type or "general-purpose"):
                    return inp.get("prompt") or ""
    return ""


def h_subagent_start(payload):
    import labels as lb
    p4 = ready(payload)
    if not p4:
        return None
    prompt = last_agent_prompt(payload.get("transcript_path") or "", payload.get("agent_type") or "")
    if not prompt or NOTES_HEAD in prompt:
        return None
    r = agent_lines(p4, prompt)
    if not r["lines"]:
        return None
    lb.write_served(p4, f"agent-{sha8(prompt)}", {"ids": [i for i in r["ids"] if ":" in i], "text": prompt[:2000],
                                                  "task": f"agent:{sha8(prompt)}", "time": now()})
    return {"hookSpecificOutput": {"hookEventName": "SubagentStart",
                                   "additionalContext": NOTES_HEAD + "\n" + "\n".join(r["lines"])}}


# --- close (Stop, SubagentStop) --------------------------------------------------------------------------

def turn_for(transcript_path, prompt, sidechain=False):
    """The transcript's turn for this prompt (the last one whose prompt starts like it), or the last turn."""
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
            got, _ = lb.turn_repo_labels(turn, project, ri, task_id, reply, when)
            rows_out += got
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
    lb.signals(p4, session=session, now=when)
    refresh_index(p4, project)
    return None


def h_subagent_stop(payload):
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


def h_train(payload):
    import contextlib
    import io
    import train
    p4 = ready(payload)
    if not p4:
        return None
    if not p4conf.section(p4, "recall", write=False).get("learn", True):
        return None             # mode off (phi_model mode off): the models stay on disk, untouched

    class A:
        pass
    a = A()
    a.p4, a.if_owed, a.now, a.sources = p4, True, "", ""
    with contextlib.redirect_stdout(io.StringIO()):
        train.cmd_train(a)
    return None


HANDLERS = {"layout": h_layout, "recall": h_recall, "agent": h_agent, "subagent-start": h_subagent_start,
            "close": h_close, "subagent-stop": h_subagent_stop, "train": h_train}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    name = argv[0] if argv else ""
    payload = {}
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        out = HANDLERS[name](payload)
    except Exception as e:  # noqa: BLE001 — a broken hook never blocks a call
        out = {"systemMessage": f"p4-recall ({name or '?'}): {type(e).__name__}: {str(e)[:200]}; nothing was added"}
        try:                # one retrain notice for the p4-model skill (notices.py), never a second failure here
            import notices
            p4 = p4_of(payload if isinstance(payload, dict) else {})
            if os.path.isdir(os.path.join(p4, "store")) or os.path.isdir(os.path.join(p4, "models")):
                notices.notify(p4, f"hook {name or '?'}", e, (payload.get("session_id") or "") if isinstance(payload, dict) else "")
        except Exception:  # noqa: BLE001
            pass
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
