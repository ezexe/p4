#!/usr/bin/env python3
"""test_flight_ops.py — acceptance tests for the flight-ops hooks over a fixture p4 store: each p4 operator launch
is classified by its own brief, its takeoff checklist bounces a faulty launch once and passes the re-issue, every
flight is recorded in the session's flights.tsv, a foreground return without its promised shape is a go-around,
a background launch is recorded airborne, and a launch that is no p4 operator's passes untouched and unrecorded.
Run from anywhere: python hooks/test_flight_ops.py — exit 0 = green."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "flight_ops.py")
OP = ("Read E:/x/lbiza/plugins/vlds/hooks/operator-prompt.md and do what it says. store: S | session: abc | "
      "now: 2026-10-23 02:50 | moment: open | task")
CHILD = "read the plugin's hooks/pool-child-prompt.md (beside this file) and do what it says. store: S file: index.md"


def run(root, sub, payload):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root, FLIGHT_OPS_NOW="2026-10-23 03:00")
    r = subprocess.run([sys.executable, HOOK, sub], env=env, capture_output=True, timeout=60,
                       input=json.dumps(payload).encode("utf-8"))
    out = r.stdout.decode("utf-8", "replace").strip()
    return json.loads(out)["hookSpecificOutput"] if out else None


def call(prompt, sid="abcd1234-x", resp=None, **inp):
    p = {"session_id": sid, "tool_name": "Agent", "tool_input": {"description": "d", "prompt": prompt, **inp}}
    if resp is not None:
        p["tool_response"] = resp
    return p


def rows(root):
    path = os.path.join(root, ".claude", "p4", "sessions", "t--abcd1234", "flights.tsv")
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\n").split("\t") for ln in f if not ln.startswith("#")]


def main():
    root = tempfile.mkdtemp(prefix="flight-ops-")
    assert run(root, "takeoff", call(OP)) is None, "a project with no p4 store spoke"
    os.makedirs(os.path.join(root, ".claude", "p4", "sessions", "t--abcd1234"))
    # the operator: a well-formed launch takes off and lands on its derivation
    assert run(root, "takeoff", call(OP)) is None, "a good operator launch was bounced"
    assert run(root, "landing", call(OP, resp={"content": [{"type": "text", "text": "derivation — open, x"}]})) is None
    assert [r[1:3] for r in rows(root)] == [["vlds-operator", "takeoff"], ["vlds-operator", "landed"]], rows(root)
    # a placeholder now: bounces once, the re-issue passes
    bad = OP.replace("now: 2026-10-23 02:50", "now: <the latest now:>")
    d = run(root, "takeoff", call(bad))
    assert d and d["permissionDecision"] == "deny" and "placeholder" in d["permissionDecisionReason"], d
    assert run(root, "takeoff", call(bad)) is None, "the re-issued launch was bounced twice"
    assert rows(root)[-1][2:3] == ["takeoff"] and "re-issued" in rows(root)[-1][5], rows(root)[-1]
    # the operator as the wrong type is bounced; with the conductor line it is roboto's flight
    d = run(root, "takeoff", call(OP, subagent_type="Explore"))
    assert d and "general-purpose" in d["permissionDecisionReason"], d
    cond = OP + "\nconductor: launch the operator with this message on sonnet, and return a derived understanding"
    d = run(root, "takeoff", call(cond))
    assert d and "mister:roboto" in d["permissionDecisionReason"], "a conductor hand-off to the wrong type passed"
    assert run(root, "takeoff", call(cond, subagent_type="mister:roboto")) is None
    # roboto landing without a derived understanding is a go-around, said with its rule
    d = run(root, "landing", call(cond, subagent_type="mister:roboto", resp="still running children"))
    assert d and "go-around" in d["additionalContext"] and "derived understanding" in d["additionalContext"], d
    assert rows(root)[-1][1:3] == ["roboto-conductor", "go-around"], rows(root)[-1]
    # an operator return that is a progress note is a go-around
    d = run(root, "landing", call(OP, resp="three children are still running"))
    assert d and "relaunch it once" in d["additionalContext"], d
    # pick-readers fly in the background; an explicit foreground one is bounced, and a launch without the parameter
    # (a harness whose Agent tool has none) passes
    d = run(root, "takeoff", call(CHILD, subagent_type="vlds:pick-reader", run_in_background=False))
    assert d and "background" in d["permissionDecisionReason"], d
    assert run(root, "takeoff", call(CHILD + " ", subagent_type="vlds:pick-reader")) is None
    assert run(root, "takeoff", call(CHILD, subagent_type="vlds:pick-reader", run_in_background=True)) is None
    assert run(root, "landing", call(CHILD, subagent_type="vlds:pick-reader", run_in_background=True,
                                     resp="Async agent launched")) is None
    assert rows(root)[-1][1:3] == ["vlds-pick-reader", "airborne"], rows(root)[-1]
    # tagged inspector perspectives and branches are recorded; nothing is enforced on them
    n = len(rows(root))
    assert run(root, "takeoff", call("refute it\nflight: vlds-inspector-perspective", subagent_type="Explore")) is None
    assert run(root, "landing", call("refute it\nflight: vlds-inspector-perspective", resp="against: …")) is None
    assert [r[1:3] for r in rows(root)[n:]] == [["vlds-inspector-perspective", "takeoff"],
                                                 ["vlds-inspector-perspective", "landed"]], rows(root)[n:]
    # any other launch passes untouched and unrecorded
    n = len(rows(root))
    assert run(root, "takeoff", call("Do the work.", subagent_type="Explore")) is None
    assert run(root, "landing", call("Do the work.", resp="done")) is None
    assert len(rows(root)) == n, "a non-operator launch was recorded"
    # the incident of 2026-10-23 03:03: the harness launches an Agent asynchronously and answers PostToolUse with
    # {isAsync, status: async_launched, agentId} — that acknowledgment is no return, so it is recorded airborne,
    # never a go-around; the flight lands on its hand-back, matched by agent id
    ack = {"isAsync": True, "status": "async_launched", "agentId": "aec3c7cf", "description": "d", "prompt": cond}
    assert run(root, "landing", call(cond, subagent_type="mister:roboto", resp=ack)) is None, "an async ack was judged"
    assert rows(root)[-1][2] == "airborne" and rows(root)[-1][5].startswith("agent aec3c7cf "), rows(root)[-1]
    # and the foreground return that is only the delivery frame of a SubagentHandback (the operator under roboto)
    frame = [{"type": "text", "text": "This agent's report was delivered to you as a message from \"a3da6c07\" (its "
                                       "SubagentHandback call). Read it there; it is not repeated here."}]
    assert run(root, "landing", call(OP, resp=frame)) is None, "a delivery frame was judged a return"
    assert rows(root)[-1][2] == "airborne" and rows(root)[-1][5].startswith("agent a3da6c07 "), rows(root)[-1]
    acks = "Async agent launched successfully.\nagentId: b1b2b3 (internal ID)"
    assert run(root, "landing", call(OP, resp=acks)) is None and rows(root)[-1][2] == "airborne", rows(root)[-1]

    def handback(agent, report):
        body = "\n".join("  " + ln for ln in report.split("\n"))
        return {"session_id": "abcd1234-x", "prompt": f"<agent-message from='{agent}'>\n[Subagent hand-back] The text "
                f"below is the final report. The report follows:\n{body}\n</agent-message>"}
    assert run(root, "handback", handback("aec3c7cf", "derived understanding — open, session x, conducted by roboto")) \
        is None
    assert rows(root)[-1][1:3] == ["roboto-conductor", "landed"] and "aec3c7cf" in rows(root)[-1][5], rows(root)[-1]
    n = len(rows(root))
    assert run(root, "handback", handback("aec3c7cf", "derived understanding — again")) is None
    assert len(rows(root)) == n, "a flight landed twice"
    d = run(root, "handback", handback("b1b2b3", "children still running"))
    assert d and d["hookEventName"] == "UserPromptSubmit" and "go-around" in d["additionalContext"], d
    assert rows(root)[-1][1:3] == ["vlds-operator", "go-around"], rows(root)[-1]
    n = len(rows(root))
    assert run(root, "handback", handback("ffffff", "derivation — open")) is None and len(rows(root)) == n, \
        "a hand-back from an unknown agent was recorded"
    assert run(root, "handback", {"session_id": "abcd1234-x", "prompt": "commit"}) is None and len(rows(root)) == n
    # garbage on stdin passes silently
    r = subprocess.run([sys.executable, HOOK, "takeoff"], input=b"not json", capture_output=True, timeout=60,
                       env=dict(os.environ, CLAUDE_PROJECT_DIR=root))
    assert r.returncode == 0 and r.stdout == b"", r.stdout
    shutil.rmtree(root, ignore_errors=True)
    print("test_flight_ops.py: all green")


if __name__ == "__main__":
    main()
