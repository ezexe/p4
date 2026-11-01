#!/usr/bin/env python3
"""The live test of 4.7 (build step 6): does the PreToolUse `Agent` hook's `updatedInput` reach the subagent?

Opt-in: P4_LIVE=1 python3 hooks/test_live_subagent.py   (it spends the signed-in account's subscription: one or two
`claude -p` runs on haiku). P4_CLAUDE names the CLI (default: the desktop app's bundled one); ANTHROPIC_API_KEY is
removed from its environment, since the CLI is signed in to a claude.ai account and a key in the environment breaks
that. `--setting-sources project,local` keeps the user's own settings (their hooks and installed plugins) out, so
only this plugin (`--plugin-dir`) runs, on a fixture git project in a temp directory.

The run: a prompt that makes the main agent launch exactly one subagent on a task the fixture store has lines for.
Evidence read afterwards:
  - the hook fired: an `agent:` task in the fixture's models/tasks.tsv, with its usage labels in labels.tsv (the
    SubagentStop hook consumes models/served/agent-*.json when it writes them);
  - the subagent saw the lines: its transcript (~/.claude/projects/<slug>/<session>/subagents/*.jsonl) holds
    "Notes from this repo's memory:" in its first user message.
P4_LIVE_ROAD=subagentstart runs the fallback instead: a copy of the plugin whose hooks.json registers SubagentStart
(and not the PreToolUse road), the same evidence required, the notes then arriving as additional context.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from test_hooks import make_project  # noqa: E402

CLI = os.environ.get("P4_CLAUDE", "/Users/ez/Library/Application Support/Claude/claude-code/2.1.309/300ae7409767/"
                                  "claude.app/Contents/MacOS/claude")
NOTES = "Notes from this repo's memory:"
PROMPT = ("Launch exactly one subagent with the Agent tool (subagent_type general-purpose). Its prompt must be exactly: "
          "\"check whether the quokka harness runs the zebrafish plotter golden images on every push. Use no tools; "
          "answer in one sentence from what your prompt and context tell you.\" Then reply with its answer in one "
          "line. Do not use any other tool.")


def plugin_for(road, tmp):
    if road == "pretooluse":
        return ROOT
    dst = os.path.join(tmp, "plugin")
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns("__pycache__"))
    path = os.path.join(dst, "hooks", "hooks.json")
    with open(path, encoding="utf-8") as f:
        h = json.load(f)
    h["hooks"].pop("PreToolUse", None)
    h["hooks"]["SubagentStart"] = [{"matcher": ".*", "hooks": [
        {"type": "command", "command": "sh \"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.sh\" subagent-start",
         "timeout": 10}]}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2)
    return dst


def first_user_text(path):
    with open(path, encoding="utf-8") as f:
        for l in f:
            d = json.loads(l)
            if d.get("type") != "user":
                continue
            c = (d.get("message") or {}).get("content")
            if isinstance(c, list):
                c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
            if isinstance(c, str) and c.strip():
                return c
    return ""


def whole_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run(road):
    tmp = tempfile.mkdtemp(prefix="p4-live-")
    proj = make_project(tmp)
    plugin = plugin_for(road, tmp)
    sid = str(uuid.uuid4())
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDE_PROJECT_DIR",
                                                            "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    cmd = [CLI, "-p", PROMPT, "--plugin-dir", plugin, "--model", "haiku", "--setting-sources", "project,local",
           "--session-id", sid, "--output-format", "json"]
    r = subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True, timeout=600)
    served = glob.glob(os.path.join(proj, ".claude", "p4", "models", "served", "agent-*.json"))
    try:
        with open(os.path.join(proj, ".claude", "p4", "models", "labels.tsv"), encoding="utf-8") as f:
            agent_labels = [l.rstrip("\n") for l in f if l.startswith("agent:")]
    except OSError:
        agent_labels = []
    subs = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}/subagents/*.jsonl"))
    mains = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{sid}.jsonl"))
    ev = {"road": road, "returncode": r.returncode, "session": sid, "project": proj,
          "stdout": r.stdout[-1500:], "stderr": r.stderr[-1500:], "served_files": served,
          "agent_labels": agent_labels,
          "subagent_transcripts": subs, "main_transcripts": mains}
    if subs:
        first = first_user_text(subs[0])
        ev["subagent_first_user_message"] = first[:3000]
        ev["notes_in_first_message"] = NOTES in first
        ev["notes_anywhere_in_subagent_transcript"] = NOTES in whole_text(subs[0])
    if mains:
        ev["notes_in_main_transcript"] = NOTES in whole_text(mains[0])
    return ev


@unittest.skipUnless(os.environ.get("P4_LIVE") == "1", "live: set P4_LIVE=1 (spends subscription usage)")
class LiveSubagent(unittest.TestCase):
    def test_road(self):
        road = os.environ.get("P4_LIVE_ROAD", "pretooluse")
        ev = run(road)
        out = os.environ.get("P4_LIVE_OUT")
        if out:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(ev, f, indent=1)
        print(json.dumps({k: v for k, v in ev.items() if k not in ("stdout", "stderr")}, indent=1)[:4000])
        self.assertEqual(ev["returncode"], 0, ev["stderr"])
        self.assertTrue(ev["subagent_transcripts"], "no subagent was launched")
        if road == "pretooluse":
            self.assertTrue(ev["served_files"] or ev["agent_labels"], "the PreToolUse hook did not serve lines")
            self.assertTrue(ev.get("notes_in_first_message"), "updatedInput's prompt did not reach the subagent")
        else:
            self.assertTrue(ev.get("notes_anywhere_in_subagent_transcript"),
                            "SubagentStart's additionalContext is not in the subagent's transcript")


if __name__ == "__main__":
    unittest.main(verbosity=2)
