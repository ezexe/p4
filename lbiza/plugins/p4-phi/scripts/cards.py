"""cards.py: the approval cards that can stop a session another session started, and what p4-phi settles before the
start so that none does.

desktop.md names the prompt an approval card, and permission-modes.md, "Actions no mode auto-approves", lists what
prompts in every permission mode. KINDS holds every kind of card met in this project's session trees, what raises
each and how it is settled before a start, or why it stays. What p4-phi settles with no card is p4conf.CARD_SET, the
one place the set is kept, in force for a store only while ezexe's yes to that set stands, p4conf.cards_on.

The step before a start is `before_start`, which the hook on `mcp__ccd_session__start_session` runs: a start that
would leave its session cut off or waiting on a card is refused with what to change, or with the session that brings
it to ezexe. The guards of phi.py answer through `raised`: Claude Code's approval card where the set is off or the
session is ezexe's own, and a refusal that names the session to ask where the set is in force and another session
started this one.
"""

import re

import p4conf

# Every kind of card, as (its name, what raises it, how it is settled before a start or why it stays). The page
# docs/claude-settings.html, "Approval cards and a session's start", carries the same list with the count of each on
# 2026-11-19, read from the transcripts' `permissionDecision` rows and the desktop app's log.
KINDS = (
    ("a guard of p4-phi",
     "A hook's `ask` is put to a person in every permission mode. p4-phi's branch guard answered it for `git push`, "
     "`git merge`, `git rebase` and `git pull` in every session another session started, the store guard for a hand "
     "push or pull in a store, and the start hook for a start it advised another way.",
     "Settled by the set: a worktree's own branch moves unasked, a push runs unasked where the brief tells the "
     "session to push, and every other such call is refused with the session to ask."),
    ("the ask rule on the archive tool",
     "`mcp__ccd_session_mgmt__archive_session` under `permissions.ask` of the project's local settings file, which "
     "prompts in every mode. p4's keeper writes it where `phi.upkeep` is off.",
     "Settled by `phi.upkeep`: with it on the keeper writes none, and by the set it also takes out an entry of that "
     "exact text which its record no longer holds. With `phi.upkeep` off the card stays, as ezexe's check on an "
     "archive."),
    ("a tool a p4 hooks module declares",
     "Claude Code asks about the first call of an MCP tool that no rule allows, in a mode that asks. The tools are "
     "those of p4conf.CARD_TOOLS. A session that bypasses permission prompts is asked nothing.",
     "Settled by the set: the keeper writes an allow rule for each."),
    ("a message between two sessions held",
     "cross-session-messaging.md, \"Control inbound messages\": sessions that bypass permission prompts are one "
     "class and every other session the other, and a message across the two is held for approval. The desktop app "
     "cannot show that dialog: it draws the message in the receiving session as a card that reads \"held\" with no "
     "button, and the message expires after five minutes.",
     "Settled by the start call's own field: `permission_mode` left out, which inherits the starter's mode, or one "
     "of the starter's class. By the set a start of another class is refused before it runs."),
    ("the question about mods",
     "plugins/mods/create.md: when a session saves the first file of a mod, \"Claude Code asks whether to enable hot "
     "reloading for the session\", and no rule or hook answers it. It is not asked in auto mode or with permission "
     "prompts bypassed.",
     "It stays in a mode that asks. A session that writes a mod is started in its starter's mode where that is auto "
     "or bypass, and in any other mode the top session brings it to ezexe before the start."),
    ("the trust dialog",
     "security.md: Claude Code asks once for a folder it holds no trust for, keyed on the repository's root, and a "
     "worktree uses its main checkout's. The desktop app answers a start there with a Trust repository button.",
     "A start in the project never raises it. For a folder never opened it stays: the button is ezexe's to press, "
     "and the top session brings it to ezexe before the start."),
    ("a start the app does not make",
     "The app starts a session only on ezexe's own words in the session that asks: a start from a turn another "
     "session or an event began is refused, one in another folder, on another host or in the cloud may raise the "
     "app's own card, and one in a worktree of a repository ezexe never opened in the app is refused with no card "
     "to press.",
     "It stays. In the project the session shows a suggested task card, which ezexe presses. By the set a start "
     "elsewhere made by a session another session started is refused with the top session to send it to, which "
     "makes it in a turn of ezexe's."),
    ("a question to ezexe",
     "`AskUserQuestion` needs a person in every mode, and so does an MCP tool marked `requiresUserInteraction`.",
     "It stays. A session another session started asks its parent with SendMessage, by the rule built into p4-phi, "
     "and what only ezexe can answer is asked by the top session before the start."),
    ("a plan's approval",
     "In plan mode `ExitPlanMode` raises the plan's approval, and a call not shown to be a read is asked about.",
     "It stays, as docs/plugin-development.html, \"Plan mode for a worker\", says: a worker is started in its "
     "starter's mode, and a plan a person is to approve is made in a session ezexe has on screen."),
    ("a raise of a session's permission mode",
     "`mcp__ccd_session_mgmt__set_session_permission_mode` to a mode that does more without asking shows its "
     "approval card in every mode, by the tool's own text.",
     "It stays: a higher mode is ezexe's to give, so a session starts in the mode its work needs."),
    ("what no mode approves",
     "permission-modes.md: a connector tool an organization set to ask, a removal of a critical path, and in the "
     "desktop app an action such as deleting a session.",
     "It stays: a brief asks a started session for none of them, and the top session does them in a turn of "
     "ezexe's."),
    ("a mode that asks",
     "A session in default or accept-edits mode is asked before each shell command that no allow rule covers, and "
     "auto mode's classifier can pause for a person.",
     "It stays: a wider allow rule is ezexe's to write. A session is started in its starter's mode, and a starter "
     "in a mode that asks says so to the top session before the start."),
    ("computer use on the app's own window",
     "`mcp__computer-use__request_access` raises an approval card for each application a session asks to see or "
     "control. Asked for the desktop app itself it raises none and refuses, in the tool's own words: \"Claude cannot "
     "be granted control of its own window: doing so would let you operate Claude's own interface and change your "
     "own permissions, settings, and allowed behaviors. This can never be granted\".",
     "It stays, and no card lifts it: a look at the app's own window is ezexe's, or a capture of that window by a "
     "script ezexe has said yes to, and a brief asks a started session for neither."),
)

# A brief that tells its session to push. The word alone is not enough: "do not push", "push nothing" and "the
# orchestrator pushes" tell it the opposite. A clause counts when it holds the word, no word of refusal within the
# four words before it or the one after, and names no other session as the one that pushes.
PUSH = re.compile(r"\bpush(?:es|ed|ing)?\b", re.I)
NO_PUSH = re.compile(r"(?:\b(?:not|never|no|nothing|none|nobody|without|neither|nor)\b|n['’]t\b)(?:\W+\w+){0,3}?"
                     r"\W+push(?:es|ed|ing)?\b|\bpush(?:es|ed|ing)?\W+(?:nothing|none|no\b)", re.I)
OTHERS_PUSH = re.compile(r"\b(?:orchestrator|parent|starter|puppeteer|top session)\b(?:\W+\w+){0,3}?\W+push", re.I)
CLAUSE = re.compile(r"(?<=[.!?;:])\s+|\n+")


def brief_pushes(text):
    """True when a brief tells its session to push its work, by one clause of it."""
    for clause in CLAUSE.split(str(text or "")):
        if PUSH.search(clause) and not NO_PUSH.search(clause) and not OTHERS_PUSH.search(clause):
            return True
    return False


OWN_BRANCH = ("git rebase", "git merge", "git pull")   # what moves a worktree's own branch and nothing else


def _answer(decision, reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def raised(on, parent, reason):
    """A guard's answer for a call it questions. With the set off, or in a session no session started, it is a
    PreToolUse `ask`, which Claude Code puts to ezexe as an approval card. With the set in force in a session that
    `parent` started it is a refusal: the reason, and the session to ask instead."""
    if on and parent:
        return _answer("deny", f"{reason} p4-phi raises no approval card in a session another session started, so "
                               f"this call is refused: if the work needs it, ask `{parent}` with SendMessage, which "
                               f"does it or brings it to ezexe.")
    return _answer("ask", reason)


def mode_class(mode):
    """The class cross-session-messaging.md sorts a permission mode into: `bypass` for a session that bypasses
    permission prompts, `asks` for every other, and '' for a mode not known."""
    mode = str(mode or "")
    return "" if not mode else "bypass" if mode == "bypassPermissions" else "asks"


ELSEWHERE = ("cwd", "host", "preset", "environment", "repository")


def before_start(inp, own_mode, parent, top, here=""):
    """The step before a start, for a session that `parent` started and with the set in force: why this start is
    refused, or '' for a start that leaves nothing to ask. `inp` is the start call's input, `own_mode` the starter's
    permission mode, '' where nothing says what it is, and `top` the tree's top session, as (its id, its title). A
    start that names a mode is judged against the starter's own, so where that is not known it is refused too: a
    start that leaves the mode out inherits the starter's and needs no judging."""
    if not parent:
        return ""
    asked = str(inp.get("permission_mode") or "")
    if asked and not mode_class(own_mode):
        return (f"phi (p4-phi): this start is refused before it runs: it names `permission_mode` `{asked}`, and this "
                f"session's own mode is not known, from the hook's input, the app's record or the session's last "
                f"prompt, so whether the two are of one class is not either. cross-session-messaging.md holds every "
                f"message between two sessions of different classes for an approval the desktop app cannot show. "
                f"Leave `permission_mode` out, so the session inherits this one's.")
    if asked and mode_class(asked) != mode_class(own_mode):
        return (f"phi (p4-phi): this start is refused before it runs: `permission_mode` `{asked}` is of another "
                f"class than this session's own `{own_mode}`, and cross-session-messaging.md holds every message "
                f"between two such sessions for an approval the desktop app cannot show. Leave `permission_mode` "
                f"out, so the session inherits this one's.")
    there = [k for k in ELSEWHERE if inp.get(k)] + (["target"] if str(inp.get("target") or "local") != "local"
                                                    else [])
    if there == ["cwd"] and here and _same(inp.get("cwd"), here):
        there = []                                 # the project's own folder, named: no start elsewhere
    if there:
        tid, title = top
        return (f"phi (p4-phi): this start is refused before it runs: it names {' and '.join(f'`{k}`' for k in there)}"
                f", and a start outside this project can raise the app's own card or the trust dialog, which no "
                f"session settles. Send the exact call to the top session \"{title}\" `{tid}` with SendMessage: it "
                f"makes the start in a turn of ezexe's.")
    return ""


def _same(a, b):
    """Whether two paths name one folder, by their normal form without case on a machine that has none."""
    import os
    one, two = (os.path.normcase(os.path.normpath(str(x))) for x in (a, b))
    return one == two


# `phi.py cards on <id>` as a shell line holds it: the script's name, past its closing quote the word `cards`, then
# `on`. The hooks module passes such a call to python's check by the same words.
CARDS_ON = re.compile(r"phi\.py[\"']?\s+cards\s+on\b")


def approval(store):
    """The reason of the one approval card the set has: what a yes puts in force, whole."""
    lines = [f"{n}. {text}" for n, (_, text) in enumerate(p4conf.CARD_SET, 1)]
    return (f"phi (p4-phi): this puts in force, for the store {p4conf.fwd(store)}, the set {p4conf.card_set_id()} of "
            f"what p4-phi settles with no approval card. A yes here is ezexe's yes to all of it, kept when this "
            f"call has ended:\n" + "\n".join(lines) + "\n`phi.py cards off` takes it out of force again.")


# What the command says once it has written the key: the key asks, and the yes is the hook's to keep.
ASKED = ("The set is not in force yet. It comes in force when p4-phi's hook keeps ezexe's yes, at the end of the "
         "shell call that ran this command and whose approval card ezexe pressed. A line run where no hook of "
         "p4-phi runs, such as the app's Terminal panel, keeps no yes, and neither does a write of the key.")


def text(store):
    """What `phi.py cards` prints: whether the set is in force for the store, the set, and every kind of card."""
    sid = p4conf.card_set_id()
    held = p4conf.cards_asked(store)
    stands = ("in force" if p4conf.cards_on(store) else
              "not in force: `phi.cards` names it and no yes of ezexe's is kept for it, so the key was written "
              "another way than by the command behind its approval card" if held == sid else
              f"not in force: the store names an earlier set, {held}" if held else
              "not in force: ezexe has not said yes to it")
    out = [f"The set {sid} of what p4-phi settles with no approval card is {stands}, for the store "
           f"{p4conf.fwd(store) or 'of no project'}.", ""]
    out += [f"{n}. {name}: {words}" for n, (name, words) in enumerate(p4conf.CARD_SET, 1)]
    out += ["", f"`phi.py cards on {sid}` puts it in force and `phi.py cards off` takes it out. The first raises "
                f"one approval card in every permission mode, which is ezexe's yes to the set as a whole and is "
                f"kept at the end of that call, and it is refused in a session another session started.", "",
            "Every kind of approval card:"]
    for name, why, how in KINDS:
        out += [f"- {name}. {why} {how}"]
    return out


def held_line(store):
    """One line on what the local settings file of the store's project holds of the set, after the keeper ran for
    it: how many of the allow rules for p4's tools, and whether the ask rule on the archive tool. '' for a store
    that sits in no project's `.claude`."""
    import os
    project = os.path.dirname(os.path.dirname(os.path.abspath(store)))
    if os.path.basename(os.path.dirname(os.path.abspath(store))) != ".claude":
        return ""
    kept = p4conf.keep_settings(project, p4=store)
    data = p4conf.read_json(kept["file"]) or {}
    allow = p4conf._get(data, p4conf.ALLOW_KEY)
    ask = p4conf._get(data, p4conf.ASK_KEY)
    have = [t for t in p4conf.CARD_TOOLS if isinstance(allow, list) and t in allow]
    return (f"{p4conf.fwd(kept['file'])} holds {len(have)} of the {len(p4conf.CARD_TOOLS)} allow rules for p4's "
            f"tools and " + ("an" if isinstance(ask, list) and p4conf.ASK_RULES[0] in ask else "no")
            + f" ask rule on `{p4conf.ASK_RULES[0]}`.")


def switch(store, on, given=""):
    """`phi.py cards on <id>` and `cards off`. `on` writes `phi.cards` to the store's p4.json and takes out a yes
    kept before, so the key asks for the set and one press of ezexe's answers one writing of it: the set comes in
    force only when `kept` runs for the call that ran the command. `off` takes the key and the kept yes out. Either
    way the settings keeper runs for the project the store sits in, so the allow rules of the set go at once. `on`
    with an id that is not this copy's set writes nothing. Returns (the exit status, the lines to print)."""
    sid = p4conf.card_set_id()
    if on and given != sid:
        return 2, [f"phi: the set as this copy of p4-phi has it is {sid}, not {given or 'named'}: nothing is "
                   f"written. `phi.py cards` prints the set."]
    p4conf.cards_no(store)
    p4conf.set_key(store, p4conf.CARDS_KEY, sid if on else None)
    out = [f"phi.cards is {sid if on else 'off'} in {p4conf.fwd(p4conf.path(store))}."
           + (f" {ASKED}" if on else " The set is not in force.")]
    line = held_line(store)
    return 0, out + ([line] if line else [])


def kept(store, session, call):
    """ezexe's yes kept, for the call whose approval card p4-phi raised and that then ran: p4conf.cards_yes for the
    store the card named, and the settings keeper for its project, so the allow rules of the set come at once.
    Returns the lines that say so, or [] where the key does not name this copy's set, as after a command that
    wrote nothing."""
    if not p4conf.cards_yes(store, session=session, call=call):
        return []
    out = [f"ezexe's yes to the set {p4conf.card_set_id()} is kept for the store {p4conf.fwd(store)}: the set is "
           f"{'in force' if p4conf.cards_on(store) else 'not in force'}."]
    line = held_line(store)
    return out + ([line] if line else [])
