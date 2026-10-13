---
name: acts-widget
description: "The session's acts page — one self-contained HTML page per session, recycled at every closing: each closing's pending acts are appended as a new round, the owner ticks acts and copies the Markdown prompt the page assembles, and when that prompt arrives the reply records the pick into the same page before acting, so the page reads as the session's log of closings — what was offered, what was picked, what was left — oldest first, with the open closing at the bottom."
when_to_use: "At every closing with pending acts: the round is appended whichever form serves it — the native question panel by default, the page itself in chat once the owner asked for the visual page; when the panel's answer lands, to record the pick; and on a message carrying an `<!-- acts-widget round=N picked=... -->` line, which is a pick from that page to record before running the acts it names."
argument-hint: "[append ACTS.json | pick --acts ID,ID | show]"
---

# Acts widget

One page per session, at `<working dir>/.claude/scratchpad/acts-widget/<session short id>.html` — the git-ignored notebook, since the page is the session's own working surface and nothing reads it after the session.
The page is its own state: the rounds live in a JSON block inside it, `build_acts_widget.py` reads that block back on every call and rewrites the page whole, so there is never a second file to keep in step.
A path that already holds something other than an acts page is refused, never overwritten.

## At a closing

1. Write the closing's acts as JSON to the notebook — one object per act: `id`, `title`, `goal` required; `summary`, `files`, `constraints`, `done`, `recommended`, `briefs` optional; `title`, `repo`, `branch` at the top.
The `goal` is the instruction the prompt carries, so write it as the act exactly as it should run.
`briefs` is `{label: text}`, one line per standing brief label of the store's `briefs.md` (`changes`, `scope`, …): the pre-ask gate reads the acts out of the served page and bounces a closing whose acts lack one.
2. Append it as the next round:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/acts-widget/build_acts_widget.py" append <acts.json> --session <short id> --now "<the latest now:>"
```

A round still open when the next one is appended is marked superseded — the owner never answered it — so only one closing is ever open.
3. Serve the closing as the turn's last tool call. By default that is the native question panel (`AskUserQuestion`, multiSelect): one option per act of the round, the recommended act first, each description the act's summary plus its `briefs` lines, at most four options to a question and four questions to a panel. Its answer returns in place: record it with `pick` (below), an Other note with `--note`, and open the final message, after the Deviations block, with the `## Picked acts` prompt the page would have assembled.
Serve the page itself in chat only once the owner has asked for the visual page in words, for the rest of that session: print its widget code and pass it whole as `show_widget`'s `widget_code`, with a `title` naming the closing.

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/acts-widget/build_acts_widget.py" widget --session <short id> --out <notebook>/acts-widget/<short id>.widget.html
```

The fragment is the same page without its document skeleton — the widget host supplies one — and with a transparent background.
In the widget frame the host defines `sendPrompt`, so the page shows a Send button that posts the assembled prompt as the next message: no copy, no paste.
Copy stays beside it, and runs the copy itself in the click — `execCommand("copy")` first, which needs no clipboard permission, then the clipboard API, and only when both are blocked does it select the prompt for a manual copy.
The same page file also opens in the built-in browser (`mcp__Claude_Browser__preview_start` with its `file:///` URL) as a read view of the session's closings; there Send is absent, since a page in the pane has no channel to the chat.
In a session shown in a pop-out window the widget never renders, so the native question panel serves the closing there, as the contract says.
4. In the final message, say what the closing asks in one line, so a widget that does not render still leaves a readable question.

## When the pick arrives

The prompt the page assembles ends with `<!-- acts-widget round=N picked=ID,ID -->`.
Before running any act it names, record the pick into the page, carrying any per-act context the owner added:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/acts-widget/build_acts_widget.py" pick --session <short id> --round N --acts ID,ID --note "ID=context" --now "<the latest now:>"
```

Then run exactly the picked acts, in the order the prompt lists them, and report as its "How to report" section says.
A message that answers the closing some other way — a skip, a typed reply — is recorded with `pick --skipped`, so the round does not stay open.

## After the close of a turn that ran picked acts

When `scripts/record.py` has applied the turn's record, attach what it wrote to the acts that wrote it, so the page's log lists each finished act's VLDS store entries as links that open the store file at that entry's line in VS Code:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/acts-widget/build_acts_widget.py" stored --session <short id> --store <working dir>/.claude/p4/sessions/<s8>/vlds --record <the turn record> --act ID
```

Leave `--act` off when the round picked several acts and the record's entries are the turn's as a whole: they are listed under the closing instead of under one act; a round with one picked act takes them under that act on its own.
`--entry FILE:HEAD` attaches an entry the record did not carry, by its head line.
The page keeps each entry by its file and head, never by its line: every build finds it again — in its hot file, or in the keyspace run a pour moved it to — so a link always points at where the entry is now, and an entry found nowhere is shown as no longer found.

`show --session <short id>` prints the rounds and their state without touching the page.

## Files

- `build_acts_widget.py` — the `append`, `pick` and `show` commands, and the page build.
- `template.html` — the page: earlier closings as a log, the open closing's acts beside the prompt they assemble.
- `assemble.js` — the prompt builder, inlined into the page and required by the test.
- `test_acts_widget.py` — acceptance tests: the build, the session round trip, the prompt, and the page's script run under node.
