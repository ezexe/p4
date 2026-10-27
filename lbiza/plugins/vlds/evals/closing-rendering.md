# Eval — the closing's delivery surface in the desktop app's Code tab

A manual eval, run in the Claude desktop app's Code tab, that pins the rendering cause behind the delivery rule instead of guessing it. The rule it verifies: the final message after the turn's last tool call is the delivery surface; a fence or a widget placed before or beside the closing tool calls may not be seen.

## The observation that produced the rule

In one owner's session a closing picker (the `show_widget` elicitation form) served after the reply text drew "what picker?"; a fenced settings snippet and a fenced command that sat in the reply text before the turn's `record.py` call and the picker widget, with a one-line coda after, drew "theres no laid out fence"; a prose derivation line placed before the same kind of tool calls was quoted back. The loss is of fenced blocks and at least one widget positioned before or beside the closing tool calls, not of all pre-tool text. The cause in the app was not established.

## The turn to run

1. Ask for anything that yields a short fenced block — a one-line shell command is enough.
2. Have the reply emit, in this order: the fenced block in prose; then a tool call (the record script, or any harmless read); then a `show_widget` elicitation form with one option; then a one-line coda.
3. Read the turn in the Code tab without expanding any tool output.

## What to record

| placement | seen in the Code tab? |
| --- | --- |
| the fence before the tool call | |
| the widget after the tool call | |
| the one-line coda after the widget | |
| the same fence repeated in the final message, after the last tool call | |

Run it twice: once in the main window, once with the session in its own pop-out window (a pop-out never renders the widget; the native question panel is the closing's form there).

## Acceptance

An owner reading only the turn's final message sees the deliverable, the question the popup asks, and the bookkeeping line without scrolling into tool output. A fence lost before the tool call and seen in the final message pins the cause on placement; a fence lost in both places is a different defect and is reported as one.
