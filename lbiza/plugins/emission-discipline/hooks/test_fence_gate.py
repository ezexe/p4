#!/usr/bin/env python3
"""test_fence_gate.py — acceptance tests for the fence gate: the incident fence asks on its hedged minute, the
corrected fence passes, and the exemptions hold (a quoted verbatim ellipsis, a runtime placeholder, a header
template). Run from anywhere: python hooks/test_fence_gate.py — exit 0 = green."""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "fence_gate.py")

INCIDENT = (
    'cd "E:/gritz/juce-8.0.12-windows/juser/AudioPlugin" && python - <<\'EOF\'\n'
    'print("the by-value fix")\n'
    'EOF\n'
    'cat >> .claude/p4/sessions/<s8>/vlds/dispatch.md <<\'EOF\'\n'
    '  addressed: the by-value fix landed\n'
    'EOF\n'
    'cat >> ledger.md <<\'EOF\'\n'
    '\n'
    '- correction: the first build after the handoff carried a dangling callback reference; two runs were read as a window cause\n'
    '  time: 2026-09-02 12:4x\n'
    'EOF\n'
)


def run(payload):
    r = subprocess.run([sys.executable, GATE, "fence-gate"], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, timeout=60)
    out = r.stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        if line.startswith("{"):
            return json.loads(line)["hookSpecificOutput"]
    assert out.strip() == "", f"unexpected non-JSON output: {out}"
    return None


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


def write(content):
    return {"tool_name": "Write", "tool_input": {"file_path": "x.md", "content": content}}


def main():
    d = run(bash(INCIDENT))
    assert d and d["permissionDecision"] == "ask" and "12:4x" in d["permissionDecisionReason"], d
    assert d["permissionDecisionReason"].startswith("R2/R6"), d
    assert run(bash(INCIDENT.replace("12:4x", "11:27"))) is None, "corrected fence asked"
    # a bare `...` on its own line, and inside an unquoted yaml value
    assert run(write("- swept: [a, b]\n  lesson: x\n...\n")) is not None, "bare ... passed"
    assert run(write("- addressed: landed the fix, ...\n")) is not None, "... in a yaml value passed"
    # placeholders in yaml fields
    assert run(write("- sha: TBD\n")) is not None, "TBD passed"
    assert run(write("- key: x\n  outcome: TODO: fill\n")) is not None, "TODO: fill passed"
    assert run(write("- verified: 2026-09-03\n  sha: 5c57fc7?\n")) is not None, "hedged sha passed"
    assert run(write("- date: 2026-09-0x\n")) is not None, "hedged date passed"
    # exemptions: a quoted verbatim ellipsis, a runtime placeholder, a header template, a clean stamp
    assert run(write('- owner-words: "delete everything... start fresh"\n')) is None, "quoted ellipsis flagged"
    assert run(bash('python - <<\'EOF\'\nprint(f"  time: {now:%Y-%m-%d %H:%M}")\nEOF\n')) is None, "runtime placeholder flagged"
    assert run(write("```yaml\n- ruling: [x]\n  time: [YYYY-MM-DD HH:MM]\n```\n")) is None, "header template flagged"
    assert run(write("- time: 2026-09-03 11:05\n  sha: 5c57fc73769d\n")) is None, "clean stamps flagged"
    # a PowerShell here-string and a content cmdlet are read
    ps = {"tool_name": "PowerShell", "tool_input": {"command": "Add-Content -Path x.md -Value @'\n  time: 03:xx\n'@"}}
    assert run(ps) is not None, "here-string placeholder passed"
    ps = {"tool_name": "PowerShell", "tool_input": {"command": 'Add-Content -Path x.md -Value "  time: 12:4x"'}}
    assert run(ps) is not None, "cmdlet value placeholder passed"
    # tools the gate does not cover stay silent
    assert run({"tool_name": "Read", "tool_input": {"file_path": "x"}}) is None
    print("test_fence_gate.py: all green")


if __name__ == "__main__":
    main()
