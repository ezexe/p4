#!/usr/bin/env python3
"""rows.py: whose words a prompt is. Claude Code stamps each prompt with where it came from, the plugin's hooks module
keeps that origin where the UserPromptSubmit hooks read it, and origin_of reads it back. whose() names whose words the
prompt is by that origin, sender_of names the session that sent a cross-session message by its wrapper, and
origin_dir is the folder of the store that holds the origin, which is the folder hook.pending_dir names for a
session. The marks at the head of a text that tell a prompt that the origin does not say are HARNESS_RE, PEER_RE and
WAKE_RE.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402

FP_CHARS = 300
ADDRESSED_CHARS = 300
RECOMMENDED_CHARS = 300
HARNESS_RE = re.compile(r"^\s*(?:<(task-notification|system-reminder|local-command|command-name|command-message|"
                        r"bash-input|bash-stdout|user-prompt-submit-hook)|"
                        # the app's notice about a message this session sent, as plans.APP_NOTICE spells it
                        r"(?:\[MESSAGE FROM NON-USER SOURCE\b[^\]\n]*\]\s*)?\[Cross-session (?:delivery|idle) notice\])",
                        re.I)
PEER_RE = re.compile(r"^\s*(Another Claude session sent a message:\s*)?<cross-session-message\b", re.I)
# the prompt of a turn p4-phi's hooks module started: it opens with plans.WAKE_MARK, and its words are not ezexe's.
# Nor are those of the sweep's own prompt, which a schedule fires and which opens with plans.SWEEP_MARK.
WAKE_RE = re.compile(r"^\s*(?:phi \(p4-phi\): the turn before this one ended on\b"
                     r"|Sweep the sessions this one started, as p4-phi's upkeep has it\.)")
# a sentence that hands ezexe a recommendation: recommendation phrasing only, not every `should`
RECOMMEND_RE = re.compile(r"(?i)\b(recommend|suggest|better to|prefer(red|able)?|the right way|instead of|rather than|"
                          r"go with|best (way|option|practice)|i'?d (use|go|pick|keep|pin|set)|the fix is|"
                          r"(you|we) should|should (use|pin|keep|move|set|run|switch|avoid|not|stay|be))\b")
FENCE_RE = re.compile(r"```.*?```", re.S)
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[`])|\n+")


# --- whose message a prompt is ----------------------------------------------------------------------------------------
# Claude Code stamps each prompt with where it came from, and hands that origin to a hooks module at `prompt.submit`:
# the types of `claude-code` say of PromptOrigin "A hooks module reads `e.origin.kind` to tell the user's own Enter
# from a notification, a peer session, a schedule or another plugin", and "a closed set, never a text prefix". A
# UserPromptSubmit command hook is given the prompt's text and no origin, so p4-phi's hooks module writes the origin
# of each prompt to ORIGIN_FILE, with the prompt's `prompt_id`, before the UserPromptSubmit hooks of that prompt
# run, and origin_of reads it back for the hook input that carries the same id. whose() names whose words the
# prompt is, and names nobody for a kind that does not say: those are told by the marks at the head of the text,
# as every prompt was before the origin was read.
ORIGIN_FILE = "origin.json"
# ezexe's own: Enter in a terminal, a Remote Control client, a ping from Slack
OWN_KINDS = frozenset(("composer", "bridge", "slack-ping"))
# another session's model, or a session coordinating this one
SESSION_KINDS = frozenset(("peer", "peer-send-message", "coordinator", "projects-relay"))
# The kinds whose() names nobody for, and why each is left to the marks. `sdk` is "The SDK host's own turn", and
# the desktop app is such a host: its unstamped deliveries, as a handed-over brief, a `<side-sessions-event>` and a
# Stop hook's feedback, share the kind with a scripted run's prompt. `unclassified` is "A turn with no provenance
# the engine can name", which the app's own notice about a sent message is. `scheduled-trigger` fires ezexe's
# `auto-continuation` follows ezexe's click, and `channel`, `observer` and `observer-activity` carry words of a
# third party: none of them was told from ezexe's words by a mark before, and none is now.
# `scheduled-trigger` is named: the types give it as "A scheduled task or /loop firing its stored prompt", so
# nobody typed it when it came, whoever stored it. Seen in the desktop app on Claude Code 2.1.326, for a one-shot
# `CronCreate` of a session's own: the module was handed the kind `scheduled-trigger`, and the transcript's row of
# the prompt reads `promptSource` "system", `turnOrigin` "scheduled" and `wakeupSource` "schedule_wakeup". Left to
# the marks, that prompt read as ezexe's own, and the sweep's prompt, which p4-phi hands a session to schedule,
# was routed as a message of ezexe's and drafted a session of its own.
REMINDER = re.compile(r"\A\s*<system-reminder>.*?</system-reminder>\s*", re.S)
SESSION_ATTR = re.compile(r"\A\s*(?:Another Claude session sent a message:\s*)?<cross-session-message\b([^>]*)>", re.I)


def origin_dir(project, session):
    """Where the hooks module keeps a prompt's origin for a project that has a store: the session's folder under
    the store's served folder, hook.pending_dir, which git ignores and the layout hook sweeps. '' for a project
    with no store, where the module writes it into the session's folder in the tree's store instead."""
    p4 = os.path.join(project or "", ".claude", "p4")
    if not project or not os.path.isfile(os.path.join(p4, p4conf.FILE)):
        return ""
    return os.path.join(p4conf.sub(p4, "phi", "served"), "start-" + re.sub(r"[^\w-]", "_", session or "none"))


def origin_of(payload, folder=""):
    """The origin Claude Code stamped on the prompt of a UserPromptSubmit hook's input, as the plugin's hooks module
    wrote it: `{"promptId": .., "kind": ..}` and what else the kind carries. It is read from the project's store,
    and from `folder`, the session's folder in the tree's store, for a project that has none. {} where no record
    names this prompt's id: a session whose Claude Code loads no hooks module, a hook input with no `prompt_id`, or
    a prompt submitted before the module learnt the session's folder."""
    pid = str((payload or {}).get("prompt_id") or "")
    if not pid:
        return {}
    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    for d in (origin_dir(project, str(payload.get("session_id") or "")), folder):
        if not d:
            continue
        try:
            with open(os.path.join(d, ORIGIN_FILE), encoding="utf-8") as f:
                kept = json.loads(f.read())
        except (OSError, ValueError):
            continue
        if isinstance(kept, dict) and kept.get("promptId") == pid and isinstance(kept.get("kind"), str):
            return kept
    return {}


def whose(origin):
    """Whose words a prompt is, by its origin: `user` for ezexe's own, `session` for another session's, `plugin`
    for a prompt a plugin's hooks module submitted, p4-phi's own wake among them, `event` for a background task's
    notification, `schedule` for a prompt a scheduled task or a `/loop` fired, and '' for a kind that does not
    say, which the marks at the head of the text tell."""
    kind = (origin or {}).get("kind")
    if kind in OWN_KINDS:
        return "user"
    if kind in SESSION_KINDS:
        return "session"
    if kind == "plugin":
        return "user" if origin.get("asUser") is True else "plugin"
    if kind == "scheduled-trigger":
        return "schedule"
    return "event" if kind == "task-notification" else ""


def sender_of(prompt):
    """The session that sent a cross-session message, by the wrapper Claude Code puts around it: `from-session`
    where the wrapper has one, as on a message a hooks module sent with `$.session.send`, whose `from` is the
    sender's socket, and `from` otherwise. The origin names no sender, so this attribute is the one place the id
    is. '' for a prompt with no such wrapper at its head."""
    text = str(prompt or "")
    while REMINDER.match(text):                    # the reminders Claude Code puts ahead of a message
        text = REMINDER.sub("", text, count=1)
    m = SESSION_ATTR.match(text)
    if not m:
        return ""
    attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
    return attrs.get("from-session") or attrs.get("from") or ""
