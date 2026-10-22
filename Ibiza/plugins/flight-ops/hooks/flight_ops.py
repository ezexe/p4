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
                                       go-around rule; a background flight is recorded airborne (its landing is
                                       the completion that reaches its tower)

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
    bg = inp.get("run_in_background") is True
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
        if not bg:
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


def cmd_landing(payload):
    inp = payload.get("tool_input") or {}
    kind = classify(inp)
    root = project_root(payload)
    if not kind or not os.path.isdir(sessions_dir(root)):
        return 0
    name = session_name(root, str(payload.get("session_id") or ""))
    fp, who = fingerprint(inp), pilot(inp)
    if inp.get("run_in_background") is True:
        record(root, name, kind, "airborne", who, fp, "background — lands as a completion to its tower")
        return 0
    text = response_text(payload.get("tool_response")).lstrip()
    want = RETURNS.get(kind)
    if want and not text.startswith(want) and f"\n{want}" not in text[:4000]:
        head = " ".join(text.split())[:100]
        record(root, name, kind, "go-around", who, fp, f"returned {head!r}")
        msg = (f"flight-ops: the {kind} landed without its `{want}` return (it opened {head!r}) — a go-around: "
               f"{GO_AROUND[kind]}.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}))
        return 0
    record(root, name, kind, "landed", who, fp)
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
    except Exception:  # noqa: BLE001 — a safeguard on the operators never stops the work
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
