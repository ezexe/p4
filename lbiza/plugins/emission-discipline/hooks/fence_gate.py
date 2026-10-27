#!/usr/bin/env python3
"""fence_gate.py — the emission gate's one mechanical arm: a PreToolUse check on persisted fences.

Subcommand `fence-gate`, reading the harness's JSON payload on stdin (decoded as UTF-8): for a Bash or
PowerShell command, every heredoc body, every PowerShell here-string, and every quoted string handed to
Set-Content / Add-Content / Out-File; for a Write, the content. Any of these is text that will EXIST after the
call — a fence that persists — and the gate asks (never denies) when it carries a hedged literal:

  R2 / R6   a `time:`, `date:`, or `sha:` field with a non-digit in a digit position (`12:4x`, `03:xx`,
            `5c57fc7?`) — a stamp the writer did not know and hedged instead of resolving
  R2        a bare `...` on its own line, or `...` inside a yaml field's unquoted value — an abbreviation
            that survives the paste as three dots
  R2        `TBD`, or a value that opens with `TODO`, in a yaml field — a placeholder that greps as valid

Exempt, because they do not survive as literals or are not the writer's hedge: a bracketed template value
(`[YYYY-MM-DD HH:MM]` in a header shape); a value holding a runtime placeholder (`{now:...}`, `$stamp`,
`%H`); and anything inside double or single quotes on the line — a verbatim quotation carries the speaker's
own ellipsis, which is not a shortening (`owner-words: "delete everything... start fresh"`).

This is deliberately the whole of the mechanical arm. R1 and R4 (identifier binding, label truth) need the
user's world and stay prose rules; the one binding that matters for a store — where its file lives — is the
vlds plugin's own `pre-write` hook. Every failure prints a one-line notice and exits 0: a gate that crashes
the call it guards is worse than no gate.
"""

import json
import re
import sys

HEREDOC_RE = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?=\r?\n|$)", re.S)
PS_HERE_RE = re.compile(r"@(['\"])\r?\n(.*?)\r?\n\1@", re.S)
PS_CONTENT_RE = re.compile(r"\b(?:Set-Content|Add-Content|Out-File)\b[^\n]*?(?:\"((?:[^\"`]|`.)*)\"|'((?:[^']|'')*)')")
QUOTED_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"", re.S)
FIELD_RE = re.compile(r"^[ \t]*(?:- )?([a-z][a-z0-9_-]*):[ \t]*(.*?)[ \t]*$")
STAMP_FIELDS = ("time", "date", "sha")
DIGIT_OK = {"time": re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$|^\d{2}:\d{2}(?::\d{2})?$"),
            "date": re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$"),
            "sha": re.compile(r"^[0-9a-f]{6,64}$")}
# the shape a hedged stamp takes: the stamp's punctuation intact, a digit position holding a non-digit
DIGIT_LOOSE = {"time": re.compile(r"^(?:[\dxX?*_#]{4}-[\dxX?*_#]{2}-[\dxX?*_#]{2})?[ T]?(?:[\dxX?*_#]{1,2}:[\dxX?*_#]{1,2}(?::[\dxX?*_#]{1,2})?)?$"),
               "date": re.compile(r"^[\dxX?*_#]{4}-[\dxX?*_#]{2}-[\dxX?*_#]{2}(?:[ T][\dxX?*_#]{2}:[\dxX?*_#]{2})?$"),
               "sha": re.compile(r"^[0-9a-fA-FxX?*_#]{6,64}$")}
TBD_RE = re.compile(r"\bTBD\b|^TODO\b", re.I)
RULE = "R2/R6: a hedged literal in a persisted fence — emit the declarative or a non-surviving placeholder"


def payload_from_stdin():
    try:
        return json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except Exception:
        return {}


def persisted_bodies(payload):
    """The texts this call persists, each with a label for the finding."""
    tool = str(payload.get("tool_name") or "")
    inp = payload.get("tool_input") or {}
    if not isinstance(inp, dict):
        return []
    if tool == "Write":
        return [("content", str(inp.get("content") or ""))]
    if tool not in ("Bash", "PowerShell"):
        return []
    cmd = str(inp.get("command") or "")
    out = [("heredoc", m.group(3)) for m in HEREDOC_RE.finditer(cmd)]
    out += [("here-string", m.group(2)) for m in PS_HERE_RE.finditer(cmd)]
    for m in PS_CONTENT_RE.finditer(cmd):
        v = m.group(1) if m.group(1) is not None else m.group(2)
        if v and "\n" not in v:
            out.append(("cmdlet value", v.replace("`n", "\n")))
    return out


def unquoted(line):
    """The line with its quoted spans blanked — a verbatim quotation is the speaker's text, not the writer's."""
    return QUOTED_RE.sub(lambda m: '"' + " " * (len(m.group(0)) - 2) + '"', line)


def hedged_stamp(field, value):
    """The value when it is a stamp with a non-digit in a digit position; None when it is clean or exempt."""
    v = value.strip().strip("\"'")
    if not v or v.startswith("[") or any(c in v for c in "{$%"):
        return None
    if DIGIT_OK[field].match(v):
        return None
    if DIGIT_LOOSE[field].match(v):
        return v
    return None


def findings(label, text):
    found = []
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.rstrip("\r")
        bare = unquoted(line)
        stripped = bare.strip()
        if re.match(r"^(?:- )?\.\.\.,?$", stripped):
            found.append(f"{label} line {n}: bare `...`")
            continue
        m = FIELD_RE.match(bare)
        if not m:
            continue
        field, value = m.group(1), m.group(2)
        value_nocomment = re.sub(r"\s+#.*$", "", value)
        if field in STAMP_FIELDS:
            h = hedged_stamp(field, value_nocomment)
            if h is not None:
                found.append(f"{label} line {n}: `{field}: {h}` has a non-digit in a digit position")
                continue
        if "..." in value_nocomment:
            found.append(f"{label} line {n}: `...` inside the `{field}:` value")
        elif TBD_RE.search(value_nocomment.strip()):
            found.append(f"{label} line {n}: placeholder in the `{field}:` value ({value_nocomment.strip()[:40]})")
    return found


def cmd_fence_gate(payload):
    bodies = persisted_bodies(payload)
    if not bodies:
        return 0
    found = []
    for label, text in bodies:
        for f in findings(label, text):
            if f not in found:
                found.append(f)
    if not found:
        return 0
    reason = RULE + " — " + "; ".join(found[:6]) + (f" (+{len(found) - 6} more)" if len(found) > 6 else "")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                             "permissionDecisionReason": reason}}))
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        if sub == "fence-gate":
            return cmd_fence_gate(payload)
        print(f"fence_gate.py: unknown subcommand {sub!r}")
        return 0
    except Exception as e:  # noqa: BLE001 — a gate degrades, never raises
        print(f"emission gate ({sub}) degraded: {type(e).__name__}: {e}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
