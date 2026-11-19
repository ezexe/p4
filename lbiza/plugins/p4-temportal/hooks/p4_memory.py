#!/usr/bin/env python3
"""p4_memory.py: p4-temportal's memory part. Claude Code writes and loads the project's auto memory itself, in the
store's `<project>/.claude/p4/temportal/memory/` once `autoMemoryDirectory` in the project's
`.claude/settings.local.json` names that folder, by https://code.claude.com/docs/en/memory, section Storage location.
p4-phi's settings writer, ezexe/p4#246, writes that key. Until it is there, Claude Code keeps the memory in its own folder,
`~/.claude/projects/<project>/memory/`, and this part moves no file out of it and writes nothing into it.

  migrate    at SessionStart, moves files left in an earlier place of the store's layout and prints that move's line
             when this hook made it. In a worktree or a subdirectory whose autoMemoryDirectory names the main
             checkout's store, it prints one line when blockWritesOutsideWorkingDirectories may keep Claude Code from
             saving memory there: the store lies outside the working directory, no user or managed additionalDirectories
             entry holds it, and a repository settings file chose the folder.

Every failure prints a one-line notice and exits 0. `migrate` is the script's one command: `mirror` and `sweep`, the
PostToolUse and Stop commands that moved memory into the store, are gone, since Claude Code writes the memory there
itself, and an installed version runs the scripts of its own folder in Claude Code's plugin cache.
"""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import p4conf  # noqa: E402 - the settings file, .claude/p4/p4.json
import hookio  # noqa: E402 - the hook input and link helpers p4-temportal's scripts share

MEMORY = "memory"


payload_from_stdin = hookio.payload_from_stdin


def layout(payload):
    """Files in an earlier place of the store's layout are moved into each plugin's folder first. -> the line saying
    so, which cmd_migrate prints first."""
    lines = p4conf.migrate_layout(os.path.join(project_root(payload), ".claude", "p4"))
    return ("p4-temportal: " + "; ".join(lines) + ".\n") if lines else ""


project_root = hookio.project_root


def project_slug(root):
    """Claude Code's folder name for a project under `projects/`: every character outside [A-Za-z0-9] is a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.normpath(root))


def repo_root(root):
    """The main checkout of the git repository holding root, read from the `.git` files without running git: a
    worktree's `.git` file names its gitdir, whose `commondir` leads to the main `.git`. Outside a repository, root."""
    d = os.path.abspath(root)
    while True:
        dot = os.path.join(d, ".git")
        if os.path.isdir(dot):
            return d
        if os.path.isfile(dot):
            try:
                with open(dot, encoding="utf-8", errors="replace") as f:
                    gitdir = f.read().strip().split("gitdir:", 1)[1].strip()
                gitdir = os.path.normpath(os.path.join(d, gitdir))
                with open(os.path.join(gitdir, "commondir"), encoding="utf-8", errors="replace") as f:
                    common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
                return os.path.dirname(common)
            except (OSError, IndexError):
                return d
        up = os.path.dirname(d)
        if up == d:
            return os.path.abspath(root)
        d = up


def sources(root):
    """[(source, settings)] of a session started in `root`, in Claude Code's order of precedence: `policy`, the
    managed settings, then `local`, `project` and `user`. Where p4-temportal's hooks module added the settings to
    the hook's input, they are the ones it read by `$.settings.read`, each source as Claude Code loaded it and
    `policy` with every managed tier merged, by p4conf.handed. Where it added none, each file is read: a file that is
    not there is left out, and one that holds no JSON object gives None."""
    got = p4conf.handed(p4conf.settings_file(root))
    if got is not None:
        return [(source, got[source]) for source in ("policy", "local", "project", "user")]
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    out = []
    for source, path in (("policy", managed_settings()),
                         ("local", os.path.join(root, ".claude", "settings.local.json")),
                         ("project", os.path.join(root, ".claude", "settings.json")),
                         ("user", os.path.join(home, "settings.json"))):
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
        out.append((source, data if isinstance(data, dict) else None))
    return out


def setting(root, name):
    """A key of Claude Code's settings by its precedence, local over project over user, or None."""
    for source, data in sources(root):
        if source != "policy" and data is not None and name in data:
            return data[name]
    return None


def managed_settings():
    """The managed settings file's path for this platform, by https://code.claude.com/docs/en/managed-settings."""
    if os.environ.get("P4_MANAGED_SETTINGS"):          # tests point it at a fixture
        return os.environ["P4_MANAGED_SETTINGS"]
    if os.name == "nt":
        return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "ClaudeCode", "managed-settings.json")
    if sys.platform == "darwin":
        return "/Library/Application Support/ClaudeCode/managed-settings.json"
    return "/etc/claude-code/managed-settings.json"


def write_block(root):
    """-> (blocked, additional directories). By the settings reference, key blockWritesOutsideWorkingDirectories, a
    true in any loaded source turns the block on, and so do managed settings whose permissions object cannot be
    read. Only user and managed additionalDirectories are counted, since repository settings may not add a directory
    to the block's working directories."""
    blocked, extra = False, []
    for source, data in sources(root):
        perms = data.get("permissions", {}) if data is not None else None
        if not isinstance(perms, dict):
            blocked = blocked or source == "policy"     # an unreadable managed permissions object fails closed
            continue
        blocked = blocked or perms.get("blockWritesOutsideWorkingDirectories") is True
        if source in ("user", "policy"):
            extra += [os.path.normpath(os.path.join(root, os.path.expanduser(d)))
                      for d in perms.get("additionalDirectories") or [] if isinstance(d, str)]
    return blocked, extra


def chosen_by_user(root):
    """autoMemoryDirectory takes effect from a source of the user's own: by the settings reference, the write block
    leaves auto memory .md files writable, but not in a directory the repository chose. The source that sets it is
    the first holding the key in Claude Code's order, managed, local, project, user. Managed and user settings are
    the user's, the project file is the repository's, and the local file is the user's only while local_is_users."""
    for source, data in sources(root):
        if data is not None and isinstance(data.get("autoMemoryDirectory"), str):
            return source in ("policy", "user") or (source == "local" and local_is_users(root))
    return False


def local_is_users(root):
    """By https://code.claude.com/docs/en/permissions, a `.claude/settings.local.json` git tracks, or one under a
    `.claude` that is a link, is repository-supplied. So it is the user's own only inside a git work tree, untracked,
    under a real `.claude`; when git cannot tell, it is the repository's."""
    if is_link(os.path.join(root, ".claude")):
        return False

    def git(*args):
        try:
            return subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
    inside = git("rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != b"true":
        return False
    tracked = git("ls-files", "--error-unmatch", "--", ".claude/settings.local.json")
    return tracked is not None and tracked.returncode == 1


def auto_memory_off(root):
    """Auto memory is off by CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 or
    `autoMemoryEnabled: false`, and CLAUDE_CODE_DISABLE_AUTO_MEMORY=0 forces it on over the setting, as the env-vars
    page and the settings reference, key autoMemoryEnabled, of https://code.claude.com/docs say."""
    if switch("CLAUDE_CODE_DISABLE_CLAUDE_MDS") is True:
        return True
    env = switch("CLAUDE_CODE_DISABLE_AUTO_MEMORY")
    if env is not None:
        return env
    return setting(root, "autoMemoryEnabled") is False


def switch(name):
    """An on/off variable as the env-vars page reads it: 1, true, yes or on, and 0, false, no or off, in any casing;
    None when unset or anything else."""
    v = os.environ.get(name, "").strip().lower()
    return True if v in ("1", "true", "yes", "on") else False if v in ("0", "false", "no", "off") else None


def appdata_memory(payload, root):
    """The auto memory directory as https://code.claude.com/docs/en/memory sets it: `autoMemoryDirectory` when it is
    an absolute or `~/` path, else `<config>/projects/<project>/memory`, where <project> is
    CLAUDE_CODE_PROJECT_DIR_NAME or the slug of the git repository's main checkout, so worktrees and subdirectories
    share one."""
    if os.environ.get("P4_MEMORY_APPDATA"):          # tests point it at a fixture
        return os.environ["P4_MEMORY_APPDATA"]
    moved = setting(root, "autoMemoryDirectory")
    if isinstance(moved, str) and (moved.startswith("~/") or os.path.isabs(moved)):
        return os.path.normpath(os.path.expanduser(moved))
    home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    named = os.environ.get("CLAUDE_CODE_PROJECT_DIR_NAME") if os.environ.get("CLAUDE_CONFIG_DIR") else None
    name = named or project_slug(repo_root(root))      # the env-vars page: ignored without CLAUDE_CONFIG_DIR
    return os.path.join(home, "projects", name, MEMORY)


def p4_memory(root):
    return p4conf.sub(os.path.join(root, ".claude", "p4"), "memory")


is_link = p4conf.is_link


def notice(parts):
    return ("p4-temportal: " + "; ".join(parts) + ".") if parts else ""


def block_notice(root, app):
    """-> the line saying that blockWritesOutsideWorkingDirectories keeps Claude Code from saving memory in the main
    checkout's store, or nothing. Only a worktree or a subdirectory whose autoMemoryDirectory names that store can
    meet it: Claude Code's own folder and the store seen from its own checkout are writable under the block."""
    if norm(repo_root(root)) == norm(root):
        return []
    mem = p4_memory(repo_root(root))
    n = norm(mem)
    if norm(app) != n:
        return []
    blocked, extra = write_block(root)
    if not blocked or chosen_by_user(root):
        return []                       # .md files of auto memory stay writable unless the repository chose the folder
    if any(n == norm(d) or n.startswith(norm(d).rstrip(os.sep) + os.sep) for d in [root] + extra):
        return []
    where = "this working directory" if norm(root).startswith(norm(repo_root(root)) + os.sep) else "this checkout"
    return [f"memory is written to {os.path.normpath(mem)}, outside {where}, and "
            "blockWritesOutsideWorkingDirectories may refuse those writes"]


def cmd_migrate(payload, first=""):
    """SessionStart: the line of a layout move made at this start, then the write block's line when it applies."""
    root = project_root(payload)
    out = notice(block_notice(root, appdata_memory(payload, root)))
    text = first + (out + "\n" if out else "")
    sys.stdout.flush()                  # LF as written, never the CRLF Windows text mode would write
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()
    return 0


def norm(path):
    return os.path.normcase(os.path.normpath(path.replace("/", os.sep)))


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = payload_from_stdin()
    try:
        # the settings the hooks module read, where it added them to this hook's input
        p4conf.hand_settings(payload, p4conf.settings_file(project_root(payload)))
        if sub == "migrate":
            if auto_memory_off(project_root(payload)):
                return 0                # auto memory is off: Claude Code saves none, so no block keeps it from saving
            return cmd_migrate(payload, layout(payload))
        print(json.dumps({"systemMessage": f"p4_memory.py: unknown subcommand {sub!r}"}))
        return 0
    except Exception as e:  # noqa: BLE001 — a hook degrades, never raises
        # a systemMessage reaches ezexe whatever the event, and a start's plain stdout reaches only the model
        print(json.dumps({"systemMessage": f"p4-temportal memory {sub} degraded: {type(e).__name__}: {e}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
