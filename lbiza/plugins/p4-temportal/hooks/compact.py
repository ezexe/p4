#!/usr/bin/env python3
"""compact.py: p4-temportal's command hook at PreCompact, for a session where the hooks module does not load.

  keep   at PreCompact, prints the keep list, which Claude Code uses as instructions for the compaction summary:
         https://code.claude.com/docs/en/hooks.md, "PreCompact output", "Claude Code uses its stdout as instructions
         for the compaction summary." It prints nothing when the instructions the hook is handed already hold the
         list, so a summary is told it once.

The hooks module, register.ts, adds the same list at `session.compact`, and Claude Code runs the PreCompact hooks
beneath that event with what the module left: seen on Claude Code 2.1.328 in a `claude -p` run, a `/compact` with no
words after it handed a PreCompact hook the module's list as `custom_instructions`. So where the module loads, the
list is in the hook's input and this hook is silent, and where no module loads, the list comes from here. The list
is register.ts's KEEP word for word, held so by test_hooks_json.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # the runner starts python with -I
from hookio import payload_from_stdin  # noqa: E402 - the hook input p4-temportal's scripts share

KEEP = ("Keep each of these verbatim in the summary, one to a line: every session id, every file path, every branch, "
        "every commit hash, every decision with its source, every open item, and the path of every state page and "
        "hand-over note.")


def kept(payload):
    """What the hook prints for its input: the keep list, or '' when the instructions already hold it."""
    told = payload.get("custom_instructions")
    return "" if isinstance(told, str) and KEEP in told else KEEP


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub != "keep":
        print(f"compact.py: unknown subcommand {sub!r}", file=sys.stderr)   # stdout would be read as instructions
        return 0
    text = kept(payload_from_stdin())
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
