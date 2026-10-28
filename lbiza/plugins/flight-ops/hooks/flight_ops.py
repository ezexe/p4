#!/usr/bin/env python3
"""flight_ops.py — the flight-ops plugin's mechanical half: each launch of a p4 operator is checked at takeoff
against that operator's own checklist, recorded, and checked again at landing against the return shape its brief
promises. Launches of anything else pass untouched: this is no plan system.

The flights (skills/flight-ops/references/flights.md has each one's full checklist):

  vlds-operator              a brief that says to read the vlds plugin's hooks/operator-prompt.md
  roboto-conductor           the same brief sent to mister:roboto with its `conductor: launch the operator` line
  vlds-pick-reader           a brief that says to read hooks/pool-child-prompt.md
  vlds-inspector-perspective a brief carrying the line `flight: vlds-inspector-perspective`
  orchestration-branch       a brief carrying the line `flight: orchestration-branch`

Subcommands, reading the harness's JSON payload on stdin:

  takeoff (PreToolUse on Agent|Task)   runs the flight's takeoff checklist; a failed one is bounced ONCE — the
                                       same call re-issued passes, the way the vlds pre-ask gate bounces — so a
                                       check that is wrong costs one re-issue, never a blocked session
  landing (PostToolUse on Agent|Task)  a foreground flight's return is checked against its promised shape; a return
                                       that is not it is a go-around, said in one line with that operator's own
                                       go-around rule; an asynchronous launch — the harness's {isAsync,
                                       async_launched, agentId} acknowledgment, or run_in_background — is recorded
                                       airborne with its agent id, never judged as a return
  handback (UserPromptSubmit)          an asynchronous flight's return reaches the session as an agent-message
                                       hand-back; it is matched to its airborne line by agent id and checked there
                                       (a flight a subagent launched hands back to that subagent, where no prompt
                                       hook runs: it stays airborne in the record)

Every flight is one line in `.claude/p4/sessions/<name>/flights.tsv` — time, flight, phase, pilot, fingerprint,
note — tracked by the p4 repo beside the session's vlds/ and src/. Every failure inside this script passes the
call and prints nothing: the checklist is a safeguard on the operators, never a gate on the work.
"""

import hashlib
import json
import os
import re
import sys
import time

TSV_HEAD = "# flights — time\tflight\tphase\tpilot\tfingerprint\tnote\n"
OPERATOR_BRIEF = "hooks/operator-prompt.md"
CHILD_BRIEF = "hooks/pool-child-prompt.md"
CONDUCTOR_LINE = re.compile(r"(?m)^\s*conductor:\s*launch the operator\b")
TAG_LINE = re.compile(r"(?m)^\s*flight:\s*(vlds-inspector-perspective|orchestration-branch)\s*$")
OPERATOR_FIELDS = ("store:", "session:", "now:", "moment:")
PLACEHOLDER_NOW = re.compile(r"now:\s*<")
RETURNS = {"vlds-operator": "derivation —", "roboto-conductor": "derived understanding —"}
GO_AROUND = {
    "vlds-operator": "relaunch it once, fresh — under roboto with a `conductor fact:` line naming what the first "
                     "launch reported and left behind; from the session, say the continuation failed and launch "
                     "fresh (the vlds contract)",
    "roboto-conductor": "the conductor returned no derived understanding: read its hand-back for the operator's "
                        "failure, and relaunch the hand-off once, saying so",
}


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def sessions_dir(root):
    return os.path.join(root, ".claude", "p4", "sessions")


def session_name(root, sid):
    s8 = (sid or "unknown")[:8]
    try:
        return next((n for n in os.listdir(sessions_dir(root)) if n == s8 or n.endswith("--" + s8)), s8)
    except OSError:
        return s8


def tsv_path(root, name):
    return os.path.join(sessions_dir(root), name, "flights.tsv")


def now_str():
    return os.environ.get("FLIGHT_OPS_NOW") or time.strftime("%Y-%m-%d %H:%M")


def text_of(inp, key):
    v = inp.get(key) if isinstance(inp, dict) else None
    return v if isinstance(v, str) else ""


def classify(inp):
    """The flight a launch is, or None for any launch that is not a p4 operator's."""
    prompt = text_of(inp, "prompt").replace("\\", "/")
    if CHILD_BRIEF in prompt:
        return "vlds-pick-reader"
    if OPERATOR_BRIEF in prompt:
        return "roboto-conductor" if CONDUCTOR_LINE.search(prompt) else "vlds-operator"
    m = TAG_LINE.search(prompt)
    return m.group(1) if m else None


def pilot(inp):
    return f"{text_of(inp, 'subagent_type') or 'general-purpose'}/{text_of(inp, 'model') or '-'}"


def fingerprint(inp):
    raw = json.dumps({k: inp.get(k) for k in ("subagent_type", "model", "prompt", "run_in_background")},
                     sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def takeoff_reasons(kind, inp):
    """The takeoff checklist of each flight; [] when it holds."""
    prompt, typ = text_of(inp, "prompt"), text_of(inp, "subagent_type") or "general-purpose"
    # only an explicit foreground launch fails: a harness whose Agent tool has no run_in_background parameter runs
    # every launch in the background and sends the key not at all (2026-10-28, the bounce cost a re-issue per child)
    foreground = inp.get("run_in_background") is False
    reasons = []
    if kind in ("vlds-operator", "roboto-conductor"):
        missing = [f for f in OPERATOR_FIELDS if f not in prompt]
        if missing:
            reasons.append(f"the operator line lacks {', '.join(missing)} (store, session, now, moment)")
        if PLACEHOLDER_NOW.search(prompt):
            reasons.append("`now:` is the template's placeholder — copy the latest `now:` from the hook stream")
    if kind == "vlds-operator" and typ != "general-purpose":
        reasons.append(f"the operator flies as general-purpose, not {typ} (to hand it to a conductor, add the "
                       "`conductor: launch the operator …` line)")
    if kind == "roboto-conductor" and typ != "mister:roboto":
        reasons.append(f"the conductor line hands the operator to roboto, but the launch is {typ} — launch "
                       "mister:roboto, or drop the conductor line and launch the operator itself")
    if kind == "vlds-pick-reader":
        if typ not in ("vlds:pick-reader", "general-purpose"):
            reasons.append(f"a pick-reader flies as vlds:pick-reader (general-purpose where that type is absent), "
                           f"not {typ}")
        if foreground:
            reasons.append("pick-readers fly in the background, all in one message (run_in_background true), so "
                           "the operator folds each as it lands")
    return reasons


def records(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [ln.rstrip("\n").split("\t") for ln in f if not ln.startswith("#")]
    except OSError:
        return []


def record(root, name, kind, phase, who, fp, note=""):
    path = tsv_path(root, name)
    if not os.path.isdir(os.path.dirname(path)):
        return
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write(TSV_HEAD)
        f.write("\t".join([now_str(), kind, phase, who, fp, " ".join(note.split())[:200]]) + "\n")


def cmd_takeoff(payload):
    inp = payload.get("tool_input") or {}
    kind = classify(inp)
    root = project_root(payload)
    if not kind or not os.path.isdir(sessions_dir(root)):
        return 0
    name = session_name(root, str(payload.get("session_id") or ""))
    fp, who = fingerprint(inp), pilot(inp)
    reasons = takeoff_reasons(kind, inp)
    bounced = any(r[1:2] == [kind] and r[2:3] == ["bounced"] and r[4:5] == [fp] for r in records(tsv_path(root, name)))
    if reasons and not bounced:
        record(root, name, kind, "bounced", who, fp, "; ".join(reasons))
        why = (f"flight-ops: the {kind} takeoff checklist failed — " + "; ".join(reasons)
               + ". Fix the launch and re-issue it; the same call re-issued passes once (the check may be wrong).")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
        return 0
    record(root, name, kind, "takeoff", who, fp, "re-issued past a bounce" if reasons else "")
    return 0


def response_text(resp):
    """The returned report's text, from a string or the content blocks a tool response carries."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for k in ("content", "result", "output", "text"):
            if k in resp:
                return response_text(resp[k])
        return ""
    if isinstance(resp, list):
        return "\n".join(response_text(x) for x in resp)
    return ""


def async_agent(resp):
    """The agent id of an asynchronous launch's acknowledgment — the harness answers every Agent call it runs in
    the background with {isAsync, status: async_launched, agentId}, and the flight's return reaches the tower later
    as a hand-back — or None for a foreground return."""
    if isinstance(resp, dict) and (resp.get("isAsync") is True or resp.get("status") == "async_launched"):
        return str(resp.get("agentId") or "?")
    text = response_text(resp)
    m = (re.search(r"Async agent launched[\s\S]*?agentId:\s*([0-9a-z]+)", text)
         # a foreground return that only says the report went elsewhere: the agent called SubagentHandback, and its
         # report reaches the tower as an agent-message (2026-10-23 03:04, the operator under roboto)
         or re.search(r"report was delivered to you as a message from \\?[\"']?([0-9a-z]+)", text))
    return m.group(1) if m else None


def landing_check(root, name, kind, who, fp, text, event, agent=None):
    """Record a return as landed, or as a go-around said in one line for the tower; event is the hook's, agent the
    id an asynchronous flight handed back under."""
    want = RETURNS.get(kind)
    text = text.lstrip()
    tag = f"agent {agent} " if agent else ""
    if want and not text.startswith(want) and f"\n{want}" not in text[:4000]:
        head = " ".join(text.split())[:100]
        record(root, name, kind, "go-around", who, fp, f"{tag}returned {head!r}")
        msg = (f"flight-ops: the {kind} {('(' + tag.strip() + ') ') if agent else ''}landed without its `{want}` "
               f"return (it opened {head!r}) — a go-around: {GO_AROUND[kind]}.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": msg}}))
        return
    record(root, name, kind, "landed", who, fp, f"{tag}— on its hand-back" if agent else "")


def cmd_landing(payload):
    inp = payload.get("tool_input") or {}
    kind = classify(inp)
    root = project_root(payload)
    if not kind or not os.path.isdir(sessions_dir(root)):
        return 0
    name = session_name(root, str(payload.get("session_id") or ""))
    fp, who = fingerprint(inp), pilot(inp)
    resp = payload.get("tool_response")
    agent = async_agent(resp)
    if agent or inp.get("run_in_background") is True:
        record(root, name, kind, "airborne", who, fp, f"agent {agent or '?'} — lands on its hand-back to the tower")
        return 0
    landing_check(root, name, kind, who, fp, response_text(resp), "PostToolUse")
    return 0


HANDBACK = re.compile(r"""<agent-message from=["']([0-9a-z]+)["']>""")
REPORT_START = re.compile(r"The report follows:\s*\n")


def cmd_handback(payload):
    """UserPromptSubmit: an asynchronous flight's return reaches the session as an agent-message hand-back; the
    flight it belongs to is the airborne line that names its agent id, and its landing is checked here."""
    prompt = str(payload.get("prompt") or "")
    m = HANDBACK.search(prompt[:400])
    root = project_root(payload)
    if not m or not os.path.isdir(sessions_dir(root)):
        return 0
    agent = m.group(1)
    name = session_name(root, str(payload.get("session_id") or ""))
    rows = records(tsv_path(root, name))
    flight = next((r for r in reversed(rows) if len(r) > 5 and r[2] == "airborne" and r[5].startswith(f"agent {agent} ")),
                  None)
    if not flight or any(r[2] in ("landed", "go-around") and r[4] == flight[4] and r[5].startswith(f"agent {agent}")
                         for r in rows):
        return 0
    s = REPORT_START.search(prompt)
    report = "\n".join(ln[2:] if ln.startswith("  ") else ln for ln in (prompt[s.end():] if s else prompt).split("\n"))
    landing_check(root, name, flight[1], flight[3], flight[4], report, "UserPromptSubmit", agent)
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = payload_from_stdin()
        if sub == "takeoff":
            return cmd_takeoff(payload)
        if sub == "landing":
            return cmd_landing(payload)
        if sub == "handback":
            return cmd_handback(payload)
    except Exception:  # noqa: BLE001 — a safeguard on the operators never stops the work
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
