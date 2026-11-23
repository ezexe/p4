#!/usr/bin/env python3
"""store.py <command>: p4-temportal's one maker of the project's store, `<project>/.claude/p4/`. The functions here
moved from p4-phi's scripts/hook.py as they were, so the store a new project gets is the one it got from p4-phi.

  make    at SessionStart, reads the hook's input from stdin as hookio does, takes the project from CLAUDE_PROJECT_DIR
          and then the input's cwd, and runs init_layout: moves a store of an older layout, and makes `.claude/p4/`
          with its .gitignore, p4.json and its git repository where they are missing, and adds the
          `.git/info/exclude` line. It prints one systemMessage that opens "p4-temportal: " with the lines
          p4conf.migrate_layout returned, and nothing where there were none.

Every failure exits 0, so a broken maker blocks no session.
"""

import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
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
phi/claude-code-watch.pending.json*
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
    if not os.path.exists(os.path.join(p4, ".git")):
        try:
            git("init", "-q", cwd=p4)
        except (OSError, subprocess.SubprocessError):
            pass
    exclude_line(project)
    return list(moved or [])


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


def cmd_make():
    payload = hookio.payload_from_stdin()
    moved = init_layout(hookio.project_root(payload))
    if moved:
        print(json.dumps({"systemMessage": "p4-temportal: " + "; ".join(moved) + "."}))
    return 0


COMMANDS = {"make": cmd_make}


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
