#!/usr/bin/env python3
"""test_live_memory_limit.py — measures how much of MEMORY.md the built-in loads, against p4_memory's constants.

The docs (https://code.claude.com/docs/en/memory) say "The first 200 lines of `MEMORY.md`, or the first 25KB, whichever
comes first", but not whether 25KB is 25,000 or 25,600 bytes. This test asks a real `claude -p` session. Its auto
memory points at a temporary directory (`autoMemoryDirectory` through `--settings`, which the same page documents),
whose MEMORY.md has 200 numbered lines of 150 bytes each. A 25,000-byte cut ends after line 166, a 25,600-byte cut
after line 170, and no byte cut at all after line 200. The session is asked for the highest line number it can see.

Live and opt-in: it runs a real session on the account this machine is signed in with (Haiku, one short answer).
  P4_LIVE=1 python3 lbiza/plugins/p4-memory/hooks/test_live_memory_limit.py
Without P4_LIVE=1, or without a claude binary, it skips and says so.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4_memory  # noqa: E402

LINE_BYTES = 150


def claude_bin():
    found = shutil.which("claude")
    if found:
        return found
    apps = sorted(glob.glob(os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")))
    return apps[-1] if apps else None


def memory_index():
    lines = []
    for i in range(1, 201):
        head = f"- line {i:03d} of the measurement index, marker M{i:03d} "
        lines.append(head + "x" * (LINE_BYTES - len(head) - 1) + "\n")
    assert all(len(l.encode()) == LINE_BYTES for l in lines)
    return "".join(lines)


def expected_last(byte_cap):
    return min(200, byte_cap // LINE_BYTES)


def main():
    if os.environ.get("P4_LIVE") != "1":
        print("test_live_memory_limit.py: skipped (set P4_LIVE=1 to run a live session)")
        return 0
    binary = claude_bin()
    if not binary:
        print("test_live_memory_limit.py: skipped (no claude binary found)")
        return 0
    base = tempfile.mkdtemp(prefix="p4-live-memory-")
    try:
        mem = os.path.join(base, "memory")
        proj = os.path.join(base, "proj")
        os.makedirs(mem)
        os.makedirs(proj)
        with open(os.path.join(mem, "MEMORY.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(memory_index())
        settings = os.path.join(base, "settings.json")
        with open(settings, "w", encoding="utf-8") as f:
            json.dump({"autoMemoryDirectory": mem, "autoMemoryEnabled": True}, f)
        prompt = ("Your auto memory index (MEMORY.md) was loaded at the start of this session; its lines carry markers "
                  "M001, M002 and so on. Without reading any file, reply with only the highest marker number you can "
                  "see in it, as digits.")
        r = subprocess.run([binary, "-p", prompt, "--settings", settings, "--model", "haiku",
                            "--disallowedTools", "Read,Bash,Glob,Grep"],
                           cwd=proj, capture_output=True, text=True, timeout=300)
        got = re.findall(r"\d+", r.stdout)
        if r.returncode != 0 or not got:
            print("test_live_memory_limit.py: the session did not answer:", (r.stdout + r.stderr)[-400:])
            return 1
        seen = int(got[-1])
        readings = {25_000: expected_last(25_000), 25_600: expected_last(25_600), "no byte cap": 200}
        match = [k for k, v in readings.items() if v == seen]
        ours = expected_last(p4_memory.BUILTIN_BYTES)
        print(f"test_live_memory_limit.py: the session saw up to M{seen:03d}; readings {readings}; "
              f"p4_memory.BUILTIN_BYTES = {p4_memory.BUILTIN_BYTES} expects M{ours:03d}; matches {match or 'none'}")
        assert seen == ours, (f"p4_memory.BUILTIN_BYTES expects M{ours:03d}, the built-in showed M{seen:03d}: set "
                              f"BUILTIN_BYTES (and the test copy in test_p4_memory.py) to match")
        print("test_live_memory_limit.py: green")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
