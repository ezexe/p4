#!/usr/bin/env python3
"""store.py <command>: p4-temportal's one maker of the project's store, `<project>/.claude/p4/`. The functions here
moved from p4-phi's scripts/hook.py as they were, so the store a new project gets is the one it got from p4-phi.

  make    at SessionStart, reads the hook's input from stdin as hookio does, takes the project from CLAUDE_PROJECT_DIR
          and then the input's cwd, and runs init_layout: moves a store of an older layout, and makes `.claude/p4/`
          with its .gitignore, p4.json and its git repository where they are missing, and adds the
          `.git/info/exclude` line. It then runs the settings watch, which p4-phi's layout hook ran before: the cheap
          comparison of p4conf.watch, which on any change runs the keeper, and the read of Claude Code's cached
          changelog. It prints one systemMessage that opens "p4-temportal: " with the lines p4conf.migrate_layout
          returned and the watch's asks, and nothing where there were none.
  settings  at ConfigChange of a local, project or user settings file: p4conf.watch checks the keys the record owns,
          never a block. Prints nothing.
  prompt  at UserPromptSubmit: where what p4-phi asks in the store's settings.local.json moved, and the last whole check
          knows whether p4-phi runs, the keeper copies the rules (asks_only), and then a line for each change of Claude
          Code the changelog read found, once, as additionalContext. Nothing when there is none.
  asks    at FileChanged: where the changed file is the store's settings.local.json and its asks moved, the keeper
          copies the rules, as at a prompt. Prints nothing. scratchpad.py's notebook-out hands the path to Claude Code
          as watchPaths.

  unkeep  takes out everything the settings keeper wrote, the keys and rules of a settings file and the import line of
          CLAUDE.local.md, deletes a file the keeper made and emptied, and sets `claude.keep` false in p4.json, so no
          later start writes them again. It prints one line for each thing taken out and each thing left.
  keep    sets `claude.keep` true and runs the keeper once, which writes them again.

Every failure exits 0, so a broken maker blocks no session.
"""

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIMITS = os.path.join(HERE, "claude_code_limits.json")   # the terms the changelog read looks for
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the store's p4.json and its layout
import hookio  # noqa: E402 - the hook input p4-temportal's scripts share

SEED_MARKER = "# seeded by p4-recall"
# a seed marker: the GITIGNORE header, SEED_MARKER, or the header that the vlds plugin's layout hook wrote in the
# stores this plugin inherits
SEED_MARKER_RE = re.compile(r"(?i)^#\s*seeded (once )?by (p4-recall|the vlds plugin)\b")
GITIGNORE = """# seeded once by p4-recall; your edits win
temportal/notebook/.out/
phi/served/
.layout.lock
.settings.lock
claude-settings.json
phi/cards.json
settings.local.json
phi/claude-code-watch.pending.json*
temportal/claude-code-watch.pending.json*
phi/sessions/*/log.jsonl
phi/sessions/*/session.md
phi/sessions.md
phi/rules.md
phi/catchup.json
phi/**/*.tmp
phi/**/*.lock
phi/sessions/*/.calls/
phi/.agents/
phi/.nudge/
.venv/
__pycache__/
*.pyc
*.png
*.jpg
*.zip
*.gz
"""
# .venv/ is a Python environment of the store's, which git never tracks: Python's venv page says an environment is
# "Not checked into source control systems such as Git".


def git(*args, cwd, timeout=10):
    import subprocess
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)


def init_layout(project):
    """Make .claude/p4/ with its .gitignore, p4.json and its git repository where they are missing, and add its
    line to the project's .git/info/exclude. Returns the lines p4conf.migrate_layout printed for a store of an older
    layout, none where there was nothing to move: the layout hook shows them."""
    import subprocess
    p4 = os.path.join(project, ".claude", "p4")
    os.makedirs(p4, exist_ok=True)
    moved = p4conf.migrate_layout(p4)     # a store in an older layout is moved first
    seed_gitignore(os.path.join(p4, ".gitignore"))
    p4conf.load(p4)                       # p4.json: every plugin's settings, written when missing
    seed_claude_md(os.path.join(p4, "CLAUDE.md"))
    if not os.path.exists(os.path.join(p4, ".git")):
        try:
            git("init", "-q", cwd=p4)
        except (OSError, subprocess.SubprocessError):
            pass
    exclude_line(project)
    return list(moved or [])


CLAUDE_MD = """# p4

This is the p4 plugins' text for this project. It holds no ruling yet.

See more: https://code.claude.com/docs/en/memory.md
"""


def seed_claude_md(path):
    """The store's CLAUDE.md, which the line in the project's CLAUDE.local.md imports: written where it is missing, and a
    file that is there is never touched."""
    if os.path.exists(path):
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(CLAUDE_MD)
    return True


def seeded_lines():
    return [l for l in GITIGNORE.splitlines() if l and not l.startswith("#")]


def seed_gitignore(gi, today=None):
    """The store's .gitignore: written whole when there is none. Otherwise each seeded line the file lacks is appended
    under a marker line, `# seeded by p4-recall <date>`, and nothing else is touched or reordered. A line ezexe
    deleted on purpose cannot be told from one a newer plugin added, so the marker decides. A file with a seed marker
    gets the lines it lacks. A file with no marker and some seeded line is one where ezexe deleted the marker block,
    and gets nothing. A file with no marker and no seeded line is ezexe's own, and gets the whole block. Returns the
    lines added."""
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8", newline="\n") as f:
            f.write(GITIGNORE)
        return seeded_lines()
    try:
        text = open(gi, encoding="utf-8").read()
    except OSError:
        return []
    have = {l.strip() for l in text.splitlines()}
    missing = [l for l in seeded_lines() if l not in have]
    if not missing:
        return []
    marked = any(SEED_MARKER_RE.match(l.strip()) for l in text.splitlines())
    if not marked and len(missing) < len(seeded_lines()):
        return []                          # ezexe removed the marker block: their edits win
    today = today or time.strftime("%Y-%m-%d")
    with open(gi, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + f"{SEED_MARKER} {today}\n"
                + "".join(l + "\n" for l in missing))
    return missing


def exclude_line(project):
    """Add the line `.claude/p4/` to the project's info/exclude unless a line there already names `.claude/p4`. In a
    worktree, `git rev-parse --git-path` names the common git dir's file. Returns whether the line was added."""
    import subprocess
    try:
        r = git("rev-parse", "--git-path", "info/exclude", cwd=project)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0 or not r.stdout.strip():
        return False
    path = r.stdout.strip()
    path = path if os.path.isabs(path) else os.path.join(project, path)
    try:
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    except OSError:
        return False
    if any(l.strip() in (".claude/p4/", ".claude/p4", "/.claude/p4/", "/.claude/p4") for l in text.splitlines()):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if not text or text.endswith("\n") else "\n") + ".claude/p4/\n")
    return True


def _store_of(project):
    return os.path.join(p4conf.main_root(project)[0], ".claude", "p4")


def _watch(project, payload):
    """p4conf.watch at a start or a settings change: the asks to show ezexe. At a start it then reads the versions the
    record owes from Claude Code's own cached changelog, a local file read in the hook's own time, with no web call and
    no process of its own. A failure of any kind is one line among the asks, never the hook's own failure, so the rest
    of the command runs."""
    try:
        got = p4conf.watch(project, payload)
        if payload.get("hook_event_name") != "ConfigChange":
            p4conf.read_changelog(_store_of(project), limits=LIMITS)
    except Exception as e:  # noqa: BLE001
        return [f"the settings watcher failed: {type(e).__name__}: {e}"]
    return got["asks"]


def cmd_make():
    payload = hookio.payload_from_stdin()
    project = hookio.project_root(payload)
    lines = init_layout(project) + _watch(project, payload)
    if lines:
        print(json.dumps({"systemMessage": "p4-temportal: " + "; ".join(lines) + "."}))
    return 0


def cmd_settings():
    """ConfigChange of the local, project or user settings file: the keys the record owns checked, never a block."""
    payload = hookio.payload_from_stdin()
    _watch(hookio.project_root(payload), payload)
    return 0


def cmd_prompt():
    """UserPromptSubmit: the keeper copies what p4-phi asks where Claude Code raised no FileChanged for the file, then
    the pending watch lines are taken once as additionalContext."""
    payload = hookio.payload_from_stdin()
    project = hookio.project_root(payload)
    p4 = _store_of(project)
    if not os.path.isdir(p4):
        return 0
    if p4conf.asks_due(p4, project):
        p4conf.keep_settings(project, p4=p4, asks_only=True)
    lines = p4conf.claim_watch(p4)
    if lines:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": "\n".join(lines)}}))
    return 0


def cmd_asks():
    """FileChanged: the keeper copies what p4-phi asks when the changed file is the one p4-phi writes in the store."""
    payload = hookio.payload_from_stdin()
    path = payload.get("file_path")
    project = hookio.project_root(payload)
    p4 = _store_of(project)
    if not isinstance(path, str) or not path or not os.path.isdir(p4):
        return 0
    if hookio.same(path, p4conf.asks_file(p4)) and p4conf.asks_due(p4, project):
        p4conf.keep_settings(project, p4=p4, asks_only=True)
    return 0


def _project_and_store():
    payload = {} if sys.stdin is None or sys.stdin.isatty() else hookio.payload_from_stdin()
    project = hookio.project_root(payload)
    return project, os.path.join(p4conf.main_root(project)[0], ".claude", "p4")


def cmd_unkeep():
    project, p4 = _project_and_store()
    lines = p4conf.unkeep(project, p4=p4)
    for line in lines or ["nothing to take out"]:
        print("p4-temportal: " + line)
    print("p4-temportal: the keeper stays out until `store.py keep` turns it on")
    return 0


def cmd_keep():
    project, p4 = _project_and_store()
    if not os.path.isdir(p4):
        print("p4-temportal: no store at " + p4 + "; `store.py make` makes one")
        return 0
    p4conf.set_key(p4, "claude.keep", True)
    got = p4conf.keep_settings(project, p4=p4)
    print("p4-temportal: the keeper is on" + (f"; wrote {got['file']}" if got.get("wrote") else ""))
    return 0


COMMANDS = {"make": cmd_make, "settings": cmd_settings, "prompt": cmd_prompt, "asks": cmd_asks,
            "unkeep": cmd_unkeep, "keep": cmd_keep}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    fn = COMMANDS.get(argv[0] if argv else "")
    if fn is None:
        print(json.dumps({"systemMessage": "p4-temportal store: unknown command; nothing was done"}))
        return 0
    try:
        return fn()
    except Exception as e:  # a broken maker blocks no session
        print(json.dumps({"systemMessage": f"p4-temportal store {argv[0]}: {type(e).__name__}: {e}".replace('"', "'")}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
