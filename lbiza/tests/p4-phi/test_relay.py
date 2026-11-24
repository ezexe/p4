#!/usr/bin/env python3
"""relay.py: owned paths, deltas, anchors, the rebase check and routing, on a tree of three sessions run through
phi.py's hooks, with fork or fresh, tracking in the store and a shared store beside them.

    python -m pytest tests/p4-phi/test_relay.py

The tree: an orchestrator and two workers. One of them deprecates a path the other has uncommitted edits
in; the other is warned on its next message, before any tool runs.
"""

import json
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import pathfilter  # noqa: E402
import relay  # noqa: E402
import starts  # noqa: E402
from test_phi import CLI, GRAND, KID, KID2, START, TOP, Tree, context, write  # noqa: E402
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # tests/, which holds inproc.py
import inproc  # noqa: E402

A, B = KID, KID2
# The letter of a drive this machine has, the one this checkout is on, and E on a machine without drive letters:
# relay.paths_in drops a path on a drive the machine lacks, and a GitHub runner has C: and D: and no E:.
DRIVE = os.path.splitdrive(SRC)[0][:1].upper() if os.path.splitdrive(SRC)[0].endswith(":") else "E"


class Paths(unittest.TestCase):
    def test_globs_and_dirs_cover_and_overlap(self):
        self.assertTrue(relay.covers("e:/w/lib", "e:/w/lib/x.py"))
        self.assertFalse(relay.covers("e:/w/lib", "e:/w/library/x.py"))
        self.assertTrue(relay.covers("e:/w/lib/*.py", "e:/w/lib/x.py"))
        self.assertTrue(relay.overlap("e:/w/lib/**", "e:/w/lib/x.py"))
        self.assertFalse(relay.overlap("e:/w/lib", "e:/w/docs"))
        with mock.patch.object(relay, "DRIVES", True):     # Git Bash's spelling, which a machine with drive letters has
            self.assertEqual(relay.norm("/e/projects/x/", ""), relay.norm("E:/projects/x", ""))

    def test_a_one_letter_folder_is_a_drive_only_where_the_machine_has_drive_letters(self):
        """https://docs.python.org/3/library/os.path.html, os.path.splitdrive: "On systems which do not use drive
        specifications, drive will always be the empty string." Git Bash writes E:/x as /e/x and runs on Windows
        alone, so relay.norm reads /w/lib as the drive W: only on a machine that has drive letters. On macOS and
        Linux it is the folder lib in /w and stays that path, where it was read as a drive the machine lacks and
        relay.paths_in dropped it. WSL's /mnt/e/x names a drive on every system, as it did. Each rule is held on
        every system by setting relay.DRIVES, and the machine's own rule by what relay.DRIVES is."""
        self.assertEqual(relay.DRIVES, bool(os.path.splitdrive("C:/x")[0]))
        self.assertEqual(relay.DRIVES, os.name == "nt")
        with mock.patch.object(relay, "DRIVES", False):     # macOS and Linux: no drive letters
            for path in ("/w/lib/x.py", "/w/lib/", "/w", "/e/projects/x", "/W/Lib"):
                self.assertEqual(relay.norm(path).lower(), path.rstrip("/").lower(), path)
            self.assertEqual(relay.paths_in("see /w/lib/x.py and `/e/notes.md`"),
                             [relay.norm("/w/lib/x.py"), relay.norm("/e/notes.md")], "neither is dropped as a drive")
            self.assertTrue(relay.covers(relay.norm("/w/lib"), relay.norm("/w/lib/x.py")))
            self.assertEqual(relay.norm("/mnt/e/projects/x"), relay.norm("E:/projects/x"), "WSL's spelling of a drive")
            self.assertNotEqual(relay.norm("/e/projects/x"), relay.norm("E:/projects/x"))
        with mock.patch.object(relay, "DRIVES", True):      # Windows: what it did
            self.assertEqual(relay.norm("/w/lib/x.py").lower(), "w:/lib/x.py")
            self.assertEqual(relay.norm("/w").lower(), "w:")
            self.assertEqual(relay.norm("/e/projects/x/"), relay.norm("E:/projects/x"))
            self.assertEqual(relay.norm("/mnt/e/projects/x"), relay.norm("E:/projects/x"))
            for path in ("/work/lib", "/wsl/lib", "/1/lib"):
                self.assertEqual(relay.norm(path), path, "a first part that is no single letter was never a drive")
        native = relay.norm("/w/lib/x.py")                  # this machine's own rule, with nothing set
        self.assertEqual(native, "w:/lib/x.py" if os.name == "nt" else "/w/lib/x.py")

    def test_a_git_ref_and_a_repositorys_name_are_no_path(self):
        """`origin/main` and `ezexe/p4` in a message are a remote-tracking branch, gitrevisions, and a repository as
        GitHub names one, `owner/name`. Each is written as a relative path is, and a start draft named both as its
        area, joined to the project's folder. They are told by what the project's repository knows: the names of
        its remotes, the owner and name in their addresses, its branches, and git's own `refs`. A folder that is
        there stays a path. The config is read with no process started, a worktree's through its `commondir`, and
        read again when it changed."""
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "proj").replace("\\", "/")
            os.makedirs(os.path.join(base, "lib", "sub"))
            subprocess.run(["git", "init", "-q", "-b", "main", base], check=True)
            for name, url in (("origin", "https://github.com/ezexe/p4.git"), ("fork", "git@github.com:Other/P4-fork")):
                subprocess.run(["git", "-C", base, "remote", "add", name, url], check=True)
            self.assertEqual(relay.remotes(base), ("origin", "fork"))
            said = ("Rebase onto origin/main of ezexe/p4, as `origin/main` and `ezexe/p4.git` and other/p4-fork say, "
                    "see refs/heads/main and fork/release/2, then fix lib/sub and lib/new.py and docs/guide/intro.")
            want = [relay.norm(x, base) for x in ("lib/sub", "lib/new.py", "docs/guide/intro")]
            self.assertEqual(relay.paths_in(said, base), want)
            for word in ("origin/main", "ezexe/p4", "EZEXE/P4.git", "other/p4-fork", "refs/heads/main",
                         "refs/remotes/origin/main", "fork/release/2"):
                self.assertTrue(relay.ref_word(word, relay.norm(word, base), base), word)
            for word in ("lib/sub", "lib/new.py", "docs/guide/intro", "/origin/main", "./origin/main", "main",
                         "lib/*", "origin/", "upstream/main", "anthropics/claude-code"):
                self.assertFalse(relay.ref_word(word, relay.norm(word, base), base), word)
            # a remote added later is known once the config changed
            subprocess.run(["git", "-C", base, "remote", "add", "upstream", "https://example.invalid/u/r.git"],
                           check=True)
            config = os.path.join(base, ".git", "config")
            os.utime(config, (time.time() + 5, time.time() + 5))       # a later time, whatever the clock's grain
            self.assertEqual(relay.remotes(base), ("origin", "fork", "upstream"), "read again once it changed")
            self.assertTrue(relay.ref_word("upstream/main", relay.norm("upstream/main", base), base))
            self.assertTrue(relay.ref_word("u/r", relay.norm("u/r", base), base))
            os.makedirs(os.path.join(base, "upstream", "main"))
            self.assertEqual(relay.paths_in("read upstream/main", base), [relay.norm("upstream/main", base)],
                             "a folder that is there")
            # the repository's own branches, as files under refs/heads and as lines of packed-refs
            subprocess.run(["git", "-C", base, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                            "--allow-empty", "-m", "one"], check=True)
            for name in ("claude/loose-one", "claude/packed-one"):
                subprocess.run(["git", "-C", base, "branch", name], check=True)
            subprocess.run(["git", "-C", base, "pack-refs", "--all"], check=True)
            subprocess.run(["git", "-C", base, "branch", "claude/loose-two"], check=True)
            for name in ("claude/loose-two", "claude/packed-one"):
                self.assertTrue(relay.branch(base, name), name)
                self.assertEqual(relay.paths_in(f"merge {name} into lib/sub", base), [relay.norm("lib/sub", base)])
            self.assertFalse(relay.branch(base, "claude/none"))
            self.assertFalse(relay.branch(base, "../config"))
            # a worktree's `.git` is a file, and what the repository knows is in the folder its commondir names
            tree = os.path.join(tmp, "tree").replace("\\", "/")
            subprocess.run(["git", "-C", base, "worktree", "add", "-q", tree], check=True)
            self.assertTrue(os.path.isfile(os.path.join(tree, ".git")))
            self.assertEqual(relay.remotes(tree), ("origin", "fork", "upstream"))
            self.assertTrue(relay.branch(tree, "claude/packed-one"))
            self.assertEqual(relay.paths_in("rebase onto origin/main of ezexe/p4", tree), [])
            self.assertEqual(relay.remotes(""), ())
            self.assertEqual(relay.remotes(os.path.join(tmp, "no-repository")), ())

    def test_a_folder_still_to_be_made_is_a_path_whatever_its_shape(self):
        """Row 12 told a ref and a repository's name by their shape, two parts with no file extension and nothing on
        disk, so a folder still to be made, such as `docs/guides`, was read as no path, which it was before. A word
        the repository knows nothing of is a path: in a project with the remote `origin` at ezexe/p4, in one with no
        remote, and in a folder that is no repository."""
        with tempfile.TemporaryDirectory() as tmp:
            said = "Make the folder docs/guides and `notes/drafts`, rebased onto origin/main of ezexe/p4."
            repo = os.path.join(tmp, "repo").replace("\\", "/")
            subprocess.run(["git", "init", "-q", repo], check=True)
            subprocess.run(["git", "-C", repo, "remote", "add", "origin", "https://github.com/ezexe/p4"], check=True)
            self.assertEqual(relay.paths_in(said, repo), [relay.norm("docs/guides", repo),
                                                          relay.norm("notes/drafts", repo)])
            for word in ("docs/guides", "notes/drafts", "src/new", "anthropics/claude-code"):
                self.assertFalse(relay.ref_word(word, relay.norm(word, repo), repo), word)
            bare = os.path.join(tmp, "bare").replace("\\", "/")
            subprocess.run(["git", "init", "-q", bare], check=True)
            plain = os.path.join(tmp, "plain").replace("\\", "/")
            os.makedirs(plain)
            for base in (bare, plain):             # nothing known: every word with a slash is a path, as before
                self.assertEqual(relay.paths_in(said, base),
                                 [relay.norm(x, base) for x in ("docs/guides", "notes/drafts", "origin/main",
                                                                "ezexe/p4")])

    def test_a_repository_the_message_names_as_one_is_no_path(self):
        """`anthropics/claude-code` is a repository the project's repository knows nothing of, and by its shape it
        is a folder still to be made, so a message that named it got a draft with that path under the project. The
        message's own words tell it: the word repository or repo directly before or behind the name, `-R` and
        `--repo` of the gh manual, a host before it, and GitHub's autolinked references `owner/name#26` and
        `owner/name@SHA`. A second repository of an owner in a remote's address, such as `ezexe/phi` beside
        ezexe/p4, is known by that owner. A folder still to be made stays a path, and so does a name the message
        only puts behind a word such as "in"."""
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "proj").replace("\\", "/")
            os.makedirs(os.path.join(base, "lib", "sub"))
            os.makedirs(os.path.join(base, "docs"))
            subprocess.run(["git", "init", "-q", base], check=True)
            subprocess.run(["git", "-C", base, "remote", "add", "origin", "https://github.com/ezexe/p4.git"],
                           check=True)
            guides = [relay.norm("docs/guides", base)]
            for said in ("Read the repository anthropics/claude-code for it, then make docs/guides.",
                         "Read the repo `anthropics/claude-code`, then make docs/guides.",
                         "Read the anthropics/claude-code repository, then make docs/guides.",
                         "As anthropics/claude-code#110694 says, make docs/guides.",
                         "As `anthropics/claude-code#110694` says, make docs/guides.",
                         "As anthropics/claude-code@1efb487 has it, make docs/guides.",
                         "Run gh issue list -R anthropics/claude-code, then make docs/guides.",
                         "Run gh issue list --repo=anthropics/claude-code.git and make docs/guides.",
                         "See github.com/anthropics/claude-code, then make docs/guides.",
                         "The repositories anthropics/claude-code, `ezexe/phi` and astral-sh/uv: make docs/guides.",
                         "Make docs/guides as ezexe/phi and ezexe/p4-phi-experiments have it."):
                self.assertEqual(relay.paths_in(said, base), guides, said)
            self.assertEqual(relay.repos_said("the repos Anthropics/Claude-Code and astral-sh/uv.", base),
                             ["anthropics/claude-code", "astral-sh/uv"])
            # no word of the message says it is a repository: a path, as a folder still to be made is
            for said, want in (("Work in anthropics/claude-code and docs/guides.",
                                ["anthropics/claude-code", "docs/guides"]),
                               ("Make the folder notes/drafts in the repository.", ["notes/drafts"]),
                               ("In the repo lib/sub is wrong, and the repo docs/new is to be made.",
                                ["lib/sub", "docs/new"]),
                               ("Fix lib/new.py#L12 of the repository.", ["lib/new.py"])):
                self.assertEqual(relay.paths_in(said, base), [relay.norm(x, base) for x in want], said)
            # the owner of a remote's address, and a folder of the owner's name that is there
            self.assertTrue(relay.ref_word("ezexe/phi", relay.norm("ezexe/phi", base), base))
            self.assertFalse(relay.ref_word("ezexe/phi/src", relay.norm("ezexe/phi/src", base), base))
            os.makedirs(os.path.join(base, "ezexe"))
            self.assertFalse(relay.ref_word("ezexe/phi", relay.norm("ezexe/phi", base), base), "a folder is there")
            plain = os.path.join(tmp, "plain").replace("\\", "/")
            os.makedirs(plain)
            self.assertEqual(relay.paths_in("Read the repository anthropics/claude-code for ezexe/phi.", plain),
                             [relay.norm("ezexe/phi", plain)], "said in a folder that is no repository")

    def test_a_slash_command_is_no_path(self):
        """`/goal` and `/plan` in a message are Claude Code's commands, commands.md, and a plugin's is written
        `/plugin-name:skill-name`, skills.md. Joined to a base on a machine with drive letters each read as a folder
        at the drive's root, `e:/goal`, and a start draft named it as its area and its files. One slash and one name
        with nothing on disk there is a command; a folder that is there, and every path with a second part, stays."""
        with tempfile.TemporaryDirectory() as base:
            base = base.replace("\\", "/")
            said = ("Give this session a /goal of its own, like `/plan` and /p4-phi:readings and "
                    "`/mcp__github__list_prs`, then fix lib/x.py and /goal/notes.md.")
            got = relay.paths_in(said, base)
            self.assertEqual(got, [relay.norm("lib/x.py", base), relay.norm("/goal/notes.md", base)])
            for word in ("/goal", "/plan", "/p4-phi:readings", "/p4-phi", "/mcp__github__list_prs"):
                self.assertTrue(relay.command_word(word, relay.norm(word, base)), word)
            for word in ("lib/goal", "/goal/x", "/goal.md", "./goal", "goal"):
                self.assertFalse(relay.command_word(word, relay.norm(word, base)), word)
            self.assertEqual(relay.paths_in("/goal", ""), [], "with no base too")
            with mock.patch.object(relay.os.path, "lexists", lambda p: True):   # a folder of that name is there
                self.assertEqual(relay.paths_in("look in /goal", base), [relay.norm("/goal", base)])

    def test_a_childs_slice_names_its_paths_relative_and_no_scratchpad_in_the_store(self):
        """The slice's paths as the project names them. No line names a scratchpad under .claude: the app names each
        session's scratchpad itself, and every write under .claude asks ezexe."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, ".claude", "p4")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"),
                  json.dumps({"sessionId": "top", "cwd": tmp, "task": "t"}))
            kid = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "cwd": tmp,
                   "task": f"fix {tmp}/src/a.py"}
            text = relay.slice_text(home, kid)
            self.assertIn("paths, src/a.py, from", text)
            self.assertNotIn(relay.norm(tmp), text)
            self.assertEqual(relay.slice_text(home, dict(kid, task="no path here")), "", "no empty paths line")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_childs_slice_hands_on_no_run_of_its_parents_prompt(self):
        """A session is handed what its parent wrote for it, never a run of eight words of the prompt the parent was
        sent: the slice names the parent by its title alone."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, ".claude", "p4")
            prompt = ("Resolve the open issues on the plugin repository and land each one with its deciding "
                      "test before the weekly limit comes round again")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"),
                  json.dumps({"sessionId": "top", "cwd": tmp, "task": prompt, "title": "the issues run"}))
            kid = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "cwd": tmp,
                   "task": f"fix {tmp}/src/a.py"}
            text = relay.slice_text(home, kid)
            self.assertIn("\"the issues run\"", text)
            words = prompt.split()
            runs = [" ".join(words[k:k + 8]) for k in range(len(words) - 7)]
            self.assertEqual([r for r in runs if r in text], [], "no eight-word run of the parent's prompt")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_same_words_are_queued_once_and_no_cli_id_gets_no_background(self):
        """The same words under two keys are queued once, and a call with no CLI session id is not given the
        background again."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"), json.dumps({"sessionId": "kid"}))
            self.assertTrue(relay.warn(home, "kid", "turn:top:aaa", "the same quote"))
            self.assertFalse(relay.warn(home, "kid", "turn:top:bbb", "the same quote"))
            self.assertEqual(len(relay._session(home, "kid")["relayPending"]), 1)
            import phi
            s = {"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "forked": True,
                 "backgroundGivenFor": {"": "top"}}
            me = type("Me", (), {"cli": ""})()
            self.assertEqual(phi.given(s, me, home), "")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"),
                  json.dumps({"sessionId": "kid", "backgroundGivenFor": {"": "top", "c1": "top"}}))
            self.assertEqual(phi.load_session(home, "kid")["backgroundGivenFor"], {"c1": "top"}, "dropped on load")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_first_look_hands_on_no_backlog_and_revisions_collapse(self):
        """A first look hands on none of what was there before it, and a child's revisions since the last look
        collapse into one line."""
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"),
                  json.dumps({"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}}))
            write(os.path.join(home, "phi", "sessions", "top", "anchor.json"), json.dumps({
                "version": 9, "changedAt": {"sib": 9}, "parent": {},
                "nodes": {"sib": {"title": "sib", "marks": [{"claim": "replaces: old news", "time": "2026-11-12 09:00",
                                                             "paths": []}]}}}))
            text, _ = relay.rebase(home, "kid", 9000, lambda xs, n: xs)
            self.assertNotIn("old news", text, "what was there at the first look is taken as seen")
            write(os.path.join(home, "phi", "sessions", "top", "session.json"), json.dumps({"sessionId": "top"}))
            for k in range(5):
                relay.warn(home, "top", f"plan:kid:{k:04d}:up", f"\"kid\", started for a step not in your task list, "
                                                                 f"revised its plan: {k}.1 changed.")
            pend = relay._session(home, "top")["relayPending"]
            self.assertEqual(len(pend), 1)
            self.assertIn("revised its plan 5 times since you last looked; now: 4.1 changed.", pend[0]["text"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_title_is_cut_at_a_clause_never_mid_phrase(self):
        """A cut ends where a clause ends, never mid-phrase as "count only the sessions that the command" would."""
        self.assertEqual(relay.clause_cut("count only the sessions that the command python -I phi.py tree prints", 46),
                         "count only the sessions")
        self.assertEqual(relay.clause_cut("count every session folder under E:/projects/p4-phi/.claude/p4/phi", 46),
                         "count every session folder")
        self.assertEqual(relay.clause_cut("Cap the hook text. Then hand each note to a session only once, by page", 40),
                         "Cap the hook text")
        self.assertEqual(relay.clause_cut("the issue loop files on the plugin repo, keeps whole titles, and more", 60),
                         "the issue loop files on the plugin repo, keeps whole titles")
        self.assertEqual(relay.clause_cut("a short title", 46), "a short title")

    def test_git_bash_and_wsl_paths_are_absolute(self):
        """/e/x as Git Bash writes it is E:/x, not a path under the base."""
        self.assertEqual(relay.norm("/mnt/e/projects/x"), relay.norm("E:/projects/x"))
        if os.name != "nt":
            self.skipTest("a letter names a drive only on Windows, and paths_in drops a path on a drive it lacks")
        d = DRIVE
        self.assertEqual(relay.paths_in(f"cat /{d.lower()}/projects/p4-phi/x/a1.txt", f"{d}:/projects/p4-phi"),
                         [relay.norm(f"{d}:/projects/p4-phi/x/a1.txt")])

    def test_a_path_on_a_missing_drive_never_hangs(self):
        """A mark's path on a drive this machine lacks gets no repository at once, and that mark is still handed
        on."""
        import time
        t0 = time.time()
        self.assertEqual(relay.repo_of("s:/replaces"), "")
        self.assertFalse(relay.drive_ok("s:/replaces"))
        self.assertLess(time.time() - t0, 5)
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            write(os.path.join(home, "phi", "sessions", "kid", "session.json"),
                  json.dumps({"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}, "anchorSeen": 0}))
            write(os.path.join(home, "phi", "sessions", "top", "anchor.json"), json.dumps({
                "version": 3, "changedAt": {"sib": 3}, "parent": {},
                "nodes": {"sib": {"title": "sib", "marks": [{"claim": "replaces: x", "time": "2026-11-12 14:00",
                                                             "paths": ["s:/replaces"]}]}}}))
            text, _ = relay.rebase(home, "kid", 9000, lambda xs, n: xs)
            self.assertIn("replaces: x", text, "the mark is still handed on")
            self.assertNotIn("stop before any tool", text)
            self.assertLess(time.time() - t0, 10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_paths_a_note_names(self):
        # a folder this machine takes as absolute; /w alone would read as the drive W: in Git Bash's spelling
        base = f"{DRIVE}:/w" if os.name == "nt" else "/work"
        got = relay.paths_in("deprecates: `lib/x.py` and docs/old.md, see https://example.com/a", base)
        self.assertEqual(got, [relay.norm(f"{base}/lib/x.py"), relay.norm(f"{base}/docs/old.md")])

    def test_a_repository_is_found_without_starting_git(self):
        """A path's repository is found from the `.git` folders above it, with no git process started."""
        if not shutil.which("git"):
            self.skipTest("no git")
        tmp = os.path.realpath(tempfile.mkdtemp())
        real, asked = relay._git, []
        try:
            repo = os.path.join(tmp, "r")
            os.makedirs(os.path.join(repo, "lib", "deep"))
            subprocess.run(["git", "init", "-q", repo], check=True)
            says = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            relay._git = lambda *a: asked.append(a) or real(*a)
            relay._ABOVE.clear()
            for p in (repo, os.path.join(repo, "lib"), os.path.join(repo, "lib", "deep", "x.py"),
                      os.path.join(repo, "lib", "not", "made", "y.py")):
                self.assertEqual(relay.repo_of(p), relay.norm(says.stdout.strip()), p)
            self.assertEqual(asked, [], "no git process for a path under a .git")
        finally:
            relay._git = real
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_repository_is_named_as_git_names_it(self):
        """A stray `.git` is passed over as git passes over it, a linked path gives the resolved top as git does, and
        what was found is believed only for ABOVE_S, so a later `git init` is seen."""
        if not shutil.which("git"):
            self.skipTest("no git")
        tmp = os.path.realpath(tempfile.mkdtemp())

        def says(path):
            r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
            return relay.norm(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else ""
        try:
            repo = os.path.join(tmp, "r")
            inner = os.path.join(repo, "pkg", "sub")
            os.makedirs(os.path.join(inner, ".git"))             # an empty .git folder inside a real repository
            os.makedirs(os.path.join(repo, "docs"))
            with open(os.path.join(repo, "docs", ".git"), "w", encoding="utf-8") as f:
                f.write("not a gitdir line\n")                   # and a stray file by that name
            subprocess.run(["git", "init", "-q", repo], check=True)
            relay._ABOVE.clear()
            for p in (inner, os.path.join(repo, "docs")):
                self.assertEqual(relay.repo_of(p), relay.norm(repo), p)
            self.assertEqual(says(inner), relay.norm(repo), "git passes over the empty folder too")
            self.assertEqual(relay.repo_of(os.path.join(inner, "x.py")), relay.norm(repo))
            bare = os.path.join(tmp, "none", "deep")
            os.makedirs(os.path.join(tmp, "none", ".git"))       # a stray .git with no repository above it
            os.makedirs(bare)
            relay._ABOVE.clear()
            self.assertEqual((relay.repo_of(bare), says(bare)), ("", ""))
            link = os.path.join(tmp, "link")
            try:
                if os.name == "nt":
                    import _winapi
                    _winapi.CreateJunction(repo, link)
                else:
                    os.symlink(repo, link)
            except (OSError, ImportError, AttributeError):
                link = ""
            if link:
                relay._ABOVE.clear()
                self.assertEqual(relay.repo_of(os.path.join(link, "pkg")), says(os.path.join(link, "pkg")))
                self.assertEqual(relay.repo_of(os.path.join(link, "pkg")), relay.norm(repo), "the resolved top")
            late = os.path.join(tmp, "late", "src")
            os.makedirs(late)
            relay._ABOVE.clear()
            self.assertEqual(relay.repo_of(late), "")
            subprocess.run(["git", "init", "-q", os.path.dirname(late)], check=True)
            self.assertEqual(relay.repo_of(late), "", "believed for ABOVE_S")
            relay._ABOVE_AT[0] -= relay.ABOVE_S + 1
            self.assertEqual(relay.repo_of(late), relay.norm(os.path.dirname(late)), "then looked for again")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sessions_are_read_again_only_when_they_change(self):
        tmp = tempfile.mkdtemp()
        try:
            home = os.path.join(tmp, "p4")
            path = os.path.join(home, "phi", "sessions", "a", "session.json")
            write(path, json.dumps({"sessionId": "a", "task": "one"}))
            first = relay._sessions(home)
            first["a"]["title"] = "a caller's own change"
            self.assertNotIn("title", relay._sessions(home)["a"], "each caller has its own copy")
            write(path, json.dumps({"sessionId": "a", "task": "one, changed on disk"}))
            self.assertEqual(relay._sessions(home)["a"]["task"], "one, changed on disk")
            shutil.rmtree(os.path.dirname(path))
            self.assertEqual(relay._sessions(home), {})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_path_on_a_missing_drive_has_no_repository(self):
        # dirname("s:/") is "s:/": the walk up stops at a root, so a path on a missing drive has no repository
        for p in ("s:/replaces", "q:/no/such/dir/file.txt", "/no/such/place"):
            self.assertEqual(relay.repo_of(p), "", p)


class _ThreeSessionsBase(unittest.TestCase):
    """The fixture of three sessions in one repository, and the helpers its tests share; it holds no test."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        t = self.t
        t.record(TOP, title="top")
        t.record(A, TOP, title="the layout work")
        t.record(B, TOP, title="the recall work")
        self.work = os.path.join(t.proj, "work")
        write(os.path.join(self.work, "lib", "x.py"), "x = 1\n")
        write(os.path.join(self.work, "lib", "y.py"), "y = 1\n")
        write(os.path.join(self.work, "docs", "d.md"), "d\n")
        for args in (("init", "-q"), ("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")):
            subprocess.run(["git", "-C", self.work, *args], check=True, capture_output=True)
        for host, prompt in ((TOP, "Build the two plugins"), (A, "Move the layout"), (B, "Fold recall in")):
            self.assertEqual(t.say(host, prompt).returncode, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def x(self, *rel):
        return os.path.join(self.work, *rel).replace("\\", "/")

    def edit_uncommitted(self, host, rel, uuid):
        """`host` edits a file in a turn and leaves it uncommitted."""
        path = self.x(*rel)
        with open(path, "a", encoding="utf-8") as f:
            f.write("more = 2\n")
        self.assertEqual(self.t.stop(host, "edit it", [("Edit", {"file_path": path}, "ok")], uuid=uuid).returncode, 0)
        return path

    OLD_RUN = ("Run the full suite once, on the commit being pushed, in this session, as one background command, "
               "and keep its verdict under that commit's hash with `phi.py note \"suite green at <hash>\" --source "
               "\"<the command>\"`, so no session runs it again for that hash. Once it passes, push that "
               "repository's main, without asking ezexe, "
               "and say in one line what was pushed. A force-push, a history rewrite or a deletion still waits on "
               "ezexe's go, asked as a `mcp__ccd_turn__wrap_up` question whose first button is that go.")

    def workflow(self, name, text):
        write(os.path.join(self.work, ".github", "workflows", name), text)

    def _tracked_store(self, uuid):
        t = self.t
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        self.assertEqual(t.stop(TOP, "plan it", report="Planned.", uuid=uuid).returncode, 0)
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        gd = subprocess.run(["git", "-C", t.p4, "rev-parse", "--absolute-git-dir"], capture_output=True,
                            text=True).stdout.strip()
        return gd

    def _subjects(self):
        return subprocess.run(["git", "-C", self.t.p4, "log", "--format=%s"], capture_output=True,
                              text=True).stdout.splitlines()

    def worktree_worker(self, name="the-flush"):
        """GRAND as a worker the app started in a git worktree of its own, and that worktree's folder."""
        own = os.path.join(self.work, ".claude", "worktrees", name).replace("\\", "/")
        subprocess.run(["git", "-C", self.work, "worktree", "add", "-q", "-b", "claude/" + name, own],
                       check=True, capture_output=True)
        self.t.record(GRAND, TOP, title="the flush worker", cwd=own)
        self.assertEqual(self.t.say(GRAND, "Task:\nPort the flush in lib.").returncode, 0)
        return own

    def holders(self, host, text):
        """Whom the address book gives a message of `host`'s to, as ids."""
        import book
        import phi
        from unittest import mock
        with mock.patch.dict(os.environ, self.t.env(host)), mock.patch.dict(phi.RECORDS, clear=True):
            return [e["id"] for e, _ in book.holders(self.t.p4, self.t.session(host), text)]

    def plan(self, host, inp):
        """An update_plan call of `host`'s, through the plan hook."""
        r = self.t.hook("plan", host, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                       "tool_input": inp, "tool_response": "Plan updated."})
        self.assertEqual(r.returncode, 0, r.stderr)

    def finish_under_a_step(self, uuid="a1"):
        """A, the child for the parent's step on the layout, finished: its work shown done and committed."""
        t = self.t
        self.plan(TOP, {"items": [{"content": "Move the layout of the store into recall", "status": "in_progress"},
                                  {"content": "Fold recall into the plugin", "status": "pending"}]})
        self.plan(A, {"items": [{"content": "Rename the folders", "status": "completed"},
                                {"content": "Commit the move", "status": "completed"}]})
        self.assertEqual(relay._session(t.p4, A).get("rootStep"), "1", "its parent step, by its brief's words")
        self.assertEqual(t.cli(A, "done", "test_layout.py: 3 tests OK").returncode, 0)
        self.assertEqual(t.stop(A, "move the layout", report="Moved the layout into lib.", uuid=uuid).returncode, 0)


class ThreeSessions(_ThreeSessionsBase):
    def test_a_child_with_no_issue_record_gets_no_push_line_for_its_closing_commit(self):
        """ezexe/p4#232: a worker with no issue record that commits `Closes #5` has run no regression test p4-phi
        saw, so its orchestrator gets no push line for it: the worker reports the commit and its orchestrator
        decides."""
        t = self.t
        self.edit_uncommitted(A, ("lib", "x.py"), "c1")
        g = ["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(g + ["commit", "-qam", "lib: fix x\n\nCloses #5"], check=True, capture_output=True)
        self.edit_uncommitted(A, ("lib", "y.py"), "c2")
        subprocess.run(g + ["commit", "-qam", "lib: tidy y\n\nThis does not close #6, and a prefix #7 is no keyword."],
                       check=True, capture_output=True)
        self.edit_uncommitted(A, ("lib", "x.py"), "c2b")             # a turn whose head is past both commits
        self.assertEqual([c[3] for c in relay.closing_commits(t.p4, A, relay._session(t.p4, A))], [["#5"]],
                         "the closing commit is there to be named, and a negated or prefixed keyword closes nothing")
        self.assertEqual(t.cli(A, "done", "test_x.py: 3 tests OK").returncode, 0)
        self.assertEqual(t.stop(A, "finish", report="Fixed x; suites green.", uuid="c3").returncode, 0)
        self.assertNotIn("close issues", context(t.say(TOP, "what next?")))

    def test_the_push_line_runs_the_suite_once_on_the_pushed_commit_and_keeps_its_verdict(self):
        """ezexe/p4#234: the push line has the full suite run once, on the commit being pushed, by the orchestrator, as
        one background command, and has its verdict kept with `phi.py note` under that commit's hash."""
        line = relay.push_text("the child", A, [(self.work, "abc1234def0", "lib: fix x", ["#5"])])
        self.assertIn("abc1234def0", line, "the closing commit, by its hash")
        self.assertIn("Run the full suite once, on the commit being pushed, in this session, as one background "
                      "command", line)
        self.assertIn("`phi.py note \"suite green at <hash>\" --source \"<the command>\"`", line)
        self.assertIn("so no session runs it again for that hash", line)
        self.assertIn("Once it passes, push that repository's main", line)
        self.assertNotIn("its suites pass", line, "no count, no commit and no record left to each reader")

    def test_a_repository_whose_workflow_runs_on_push_gets_the_workflow_line_and_no_full_local_run(self):
        """Where a workflow of the repository runs its tests on every push to the default branch, the push line has
        the named checks and the touched paths' test files run, then the push, then that workflow's run on the pushed
        commit read with `gh run watch`, and it names no full local run. The note says the workflow was green."""
        self.workflow("tests.yml", "name: tests\n\n# every push\non:\n  pull_request:\n  push:\n    branches: [main]\n"
                                   "  workflow_call:\n\njobs:\n  pytest:\n    runs-on: ubuntu-latest\n")
        self.workflow("pages.yml", "name: pages\non:\n  push:\n    branches: [main]\n    paths:\n      - \"docs/**\"\n")
        self.workflow("release.yml", "name: release\non:\n  push:\n    branches: [main]\n")
        flows = relay.push_workflows([self.work])
        self.assertEqual(flows, [("tests", "tests.yml")], "the tests workflow alone: no pages, no release")
        commits = [(self.work, "abc1234def0", "lib: fix x", ["#5"])]
        line = relay.push_text("the child", A, commits, workflows=flows)
        self.assertIn("That repository's own workflow `tests` runs every test on a push to the default branch, so "
                      "before the push run only the checks the task named and the test files of the paths the commits "
                      "touch, in this session. Once they pass, push that repository's main", line)
        self.assertIn("After the push, read the run of `tests` on the pushed commit: find it with `gh run list "
                      "--workflow tests.yml --commit <the pushed commit's full hash>`, watch it with `gh run watch "
                      "<run id> --exit-status` as one background command", line)
        self.assertIn("`phi.py note \"workflow tests green at <hash>\" --source \"gh run watch <run id> "
                      "--exit-status\"`", line)
        self.assertNotIn("full suite", line, "no full local run")
        self.assertNotIn("suite green at", line)
        self.assertIn("A force-push, a history rewrite or a deletion still waits on ezexe's go", line)
        green = relay.push_text("the child", A, commits, green=[("abc1234def0", "workflow tests green at abc1234")],
                                workflows=flows)
        self.assertIn("A note holds abc1234def0 green", green)
        self.assertNotIn("before the push run only", green)

    def test_a_repository_with_no_workflow_gets_the_old_line_unchanged(self):
        """Where no workflow of the repository runs its tests on a push to the default branch, a local run is the
        only run, and the push line is word for word what it was."""
        commits = [(self.work, "abc1234def0", "lib: fix x", ["#5"])]
        self.assertEqual(relay.push_workflows([self.work]), [], "no .github/workflows folder")
        head = ("phi (p4-phi): \"the child\" `" + A + "` finished with commits that close issues: abc1234def0 "
                "\"lib: fix x\" closes #5 in " + self.work + ". Green work that closes an issue is landed at once. ")
        self.assertEqual(relay.push_text("the child", A, commits, workflows=relay.push_workflows([self.work])),
                         head + self.OLD_RUN)
        self.workflow("pages.yml", "name: pages\non:\n  push:\n    branches: [main]\n    paths:\n      - \"docs/**\"\n")
        self.workflow("ci.yml", "name: ci\non:\n  pull_request:\n  workflow_dispatch:\n")
        self.workflow("tests.yml", "name: tests\non:\n  push:\n    branches:\n      - release/**\n")
        self.workflow("checks.yml", "name: checks\non:\n  push:\n    tags: ['v*']\n")
        self.assertEqual(relay.push_workflows([self.work]), [],
                         "a paths filter, no push event, another branch and tags only: none runs on each push")
        self.assertEqual(relay.push_text("the child", A, commits, workflows=relay.push_workflows([self.work])),
                         head + self.OLD_RUN)

    def test_on_push_reads_the_forms_an_on_key_takes(self):
        for text, want in (("on: push\n", True), ("on: [push, pull_request]\n", True), ("on: pull_request\n", False),
                           ("on:\n  - push\n  - pull_request\n", True), ("'on':\n  push:\n", True),
                           ("on:\n  push:\n    branches-ignore: [main]\n", False),
                           ("on:\n  push:\n    branches-ignore:\n      - 'dev/**'\n", True),
                           ("on:\n  push:\n    branches: ['*']  # all\n", True), ("jobs: {}\n", False)):
            self.assertIs(relay._on_push(text, "main"), want, text)

    def test_a_push_line_for_a_hash_noted_green_says_not_to_run_again(self):
        """ezexe/p4#234: once a note of the tree names the closing commit's hash as green, the push line names the note
        and has the suite not run again for that hash. A note names one hash and holds no other green."""
        t = self.t
        commits = [(self.work, "abc1234def0", "lib: fix x", ["#5"])]
        self.assertEqual(relay.green_notes(t.p4, [A, TOP], commits), [], "no note yet")
        self.assertEqual(t.cli(TOP, "note", "suite green at abc1234: 1006 passed and 1 skipped", "--source",
                               "python -m pytest").returncode, 0)
        green = relay.green_notes(t.p4, [A, TOP], commits)
        self.assertEqual([sha for sha, _ in green], ["abc1234def0"])
        line = relay.push_text("the child", A, commits, green=green)
        self.assertIn("A note holds abc1234def0 green, \"suite green at abc1234: 1006 passed and 1 skipped\"", line)
        self.assertIn("do not run the suite again for that hash. Push that repository's main", line)
        self.assertNotIn("Run the full suite once", line)
        self.assertEqual(relay.green_notes(t.p4, [A, TOP], [(self.work, "fff0000aaa1", "lib: other", ["#6"])]), [])
        self.assertEqual(t.cli(TOP, "note", "the run at fff0000 stopped at two failures", "--source",
                               "python -m pytest").returncode, 0)
        self.assertEqual(relay.green_notes(t.p4, [A, TOP], [(self.work, "fff0000aaa1", "lib: other", ["#6"])]), [],
                         "a note that names the hash without a green verdict holds nothing green")

    def test_a_machine_branch_of_the_store_behind_main_is_owed(self):
        """The other machine's pull is owed when its branch of the store is behind main."""
        store = os.path.join(self.t.tmp, "solo", ".claude", "p4")
        bare = os.path.join(self.t.tmp, "store.git")
        os.makedirs(store)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True, capture_output=True)
        g = ["git", "-C", store, "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", "-b", "main", store], check=True, capture_output=True)
        subprocess.run(g + ["remote", "add", "origin", bare], check=True, capture_output=True)
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "one"], check=True, capture_output=True)
        subprocess.run(g + ["push", "-q", "origin", "main", "main:mac"], check=True, capture_output=True)
        self.assertEqual(relay.owed([os.path.dirname(os.path.dirname(store))]), [], "every branch is at main")
        subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "two"], check=True, capture_output=True)
        subprocess.run(g + ["push", "-q", "origin", "main"], check=True, capture_output=True)
        got = relay.owed([os.path.dirname(os.path.dirname(store))])
        self.assertEqual(len(got), 1)
        self.assertIn("the machine branch `mac` of the store ", got[0])
        self.assertIn("is 1 commit behind main", got[0])

    def test_a_deprecation_is_handed_to_a_sibling_whole_and_stops_none_of_its_uncommitted_work(self):
        """Every session works in the one checkout, on the paths of its own `Files:` line, so a sibling's note and
        this session's files are held apart by those paths, not by a stop: the stop that held a session's uncommitted file against a note's path is gone, here
        with both sessions in one folder, where the two paths did meet. The note is still handed on in full, once,
        and the anchor holds the note's paths and no heads or files of the sibling's."""
        t = self.t
        self.edit_uncommitted(B, ("lib", "x.py"), "b1")
        self.assertEqual(t.cli(A, "note", f"deprecates: `{self.x('lib', 'x.py')}`; the layout lives in p4conf now",
                               "--source", "commit abc123").returncode, 0)
        self.assertEqual(t.stop(A, "deprecate x", [("Edit", {"file_path": self.x("docs", "d.md")}, "ok")],
                                uuid="a1").returncode, 0)
        anchor = json.load(open(relay.anchor_path(t.p4, TOP), encoding="utf-8"))
        self.assertGreaterEqual(anchor["version"], 1)
        self.assertEqual(anchor["nodes"][A]["marks"][0]["paths"], [relay.norm(self.x("lib", "x.py"))])
        for node in anchor["nodes"].values():
            self.assertEqual(set(node), {"title", "time", "marks", "shard", "plan", "root"}, "no heads and no files")
        last = [r for r in relay._rows(os.path.join(relay._dir(t.p4, A), "turns.jsonl")) if r.get("delta")][-1]
        self.assertTrue(any(h.startswith(relay.norm(self.work) + "@") for h in last["delta"]["heads"]),
                        "the turn's own row keeps its heads, which its outcome and the push line read")
        self.assertEqual(last["delta"]["files"], [relay.norm(self.x("docs", "d.md"))])
        ctx = context(t.say(B, "<side-sessions-event>a session finished a turn</side-sessions-event>"))
        self.assertNotIn("stop before any tool runs", ctx, "no path of B's is held against A's note")
        self.assertNotIn("this session has", ctx)
        self.assertIn("deprecates: `", ctx)
        self.assertIn("; source: commit abc123", ctx, "a deprecation is given in full, with its source")
        self.assertNotIn("what else changed beside this session", ctx, "no heads or files of a sibling's")
        self.assertNotIn("files changed", ctx)
        self.assertEqual(t.session(B)["anchorSeen"], anchor["version"])
        self.assertNotIn("othersGiven", t.session(B))
        again = context(t.say(B, "carry on"))
        self.assertNotIn("deprecated or replaced", again, "nothing changed since: quiet")

    def test_a_deprecation_of_nothing_this_session_holds_is_handed_on_without_a_warning(self):
        t = self.t
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit def456")
        t.stop(A, "replace docs", uuid="a1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("stop before any tool runs", ctx)
        self.assertIn("replaces: `", ctx)

    def test_a_note_naming_the_store_or_a_repository_top_warns_nobody(self):
        """A note naming the whole store or a repository's top folder warns nobody, and is still handed on in full."""
        t = self.t
        self.edit_uncommitted(B, ("lib", "x.py"), "b1")
        t.cli(A, "note", f"deprecates: any reading of `{t.p4}` as flat, and of `{self.work}` as one plugin",
              "--source", "commit ccc333")
        t.stop(A, "broad note", uuid="a1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("stop before any tool runs", ctx)
        self.assertIn("; source: commit ccc333", ctx, "the note is still handed on, in full")

    def test_thirty_sibling_notes_stay_in_the_relays_room_and_come_once(self):
        """A session with 30 sibling notes pending gets them within the room phi.py gives the relay's text, the
        remainder named by count and page, and none of the same notes on the prompt after."""
        import phi
        t = self.t
        filler = "The exporter's ports table moved to the store and the old flush path is gone. " * 12
        for k in range(27):
            self.assertEqual(t.cli(A, "note", f"replaces: narwhal exporter build {k:02d}. {filler}",
                                   "--source", f"commit far{k:02d}").returncode, 0)
        for k in range(3):
            self.assertEqual(t.cli(A, "note", f"replaces: the recall fold plan {k}: fold recall into phi as hook {k}",
                                   "--source", f"commit near{k}").returncode, 0)
        t.stop(A, "thirty notes", uuid="a30")
        ctx = context(t.say(B, "next"))
        notes = [p for p in ctx.split("\n\n") if "deprecated or replaced since" in p or "notes not shown" in p]
        self.assertEqual(len(notes), 2, ctx)
        self.assertLessEqual(sum(len(p) + 2 for p in notes), phi.RELAY_CHARS, "within the relay's room")
        self.assertLessEqual(len(ctx), phi.APP_CAP, "and the whole text under the app's cap")
        for k in range(3):
            self.assertIn(f"; source: commit near{k}", ctx, "what touches its task is given in full")
        self.assertNotIn("commit far", ctx, "what does not is not shown")
        self.assertIn("deprecation or replacement notes not shown: 27", ctx, "the remainder by count")
        relay.forget(t.p4)
        page = os.path.join(relay._dir(t.p4, A), "session.md").replace("\\", "/")
        self.assertIn(f"27 on {page}", ctx, "and by the page that holds it")
        self.assertIn("narwhal exporter build 26", open(page, encoding="utf-8").read(), "the page holds them whole")
        again = context(t.say(B, "and after"))
        self.assertNotIn("deprecat", again, "none of the same notes on the prompt after")
        self.assertNotIn("commit near", again)
        t.stop(A, "one more turn", [("Edit", {"file_path": self.x("docs", "d.md")}, "ok")], uuid="a31")
        self.assertNotIn("replaces:", context(t.say(B, "third")), "nor when the sibling changes again")

    def test_thirty_warnings_are_given_whole_once_and_none_is_held(self):
        """An orchestrator too: every warning is given whole and leads the text, none is kept on a page of p4-phi's
        own, since a text past the app's cap goes to the app's own file, and none comes again."""
        import phi
        t = self.t
        for k in range(30):
            relay.warn(t.p4, TOP, f"note:{k}", f"warning {k:02d} of thirty: " + "a sibling changed the layout. " * 10)
        ctx = context(t.say(TOP, "what now?"))
        line = [p for p in ctx.split("\n\n") if p.startswith(relay.STOP_HEAD)]
        self.assertEqual(len(line), 1, ctx[:400])
        for k in range(30):
            self.assertIn(f"({k + 1}) warning {k:02d} of thirty: " + "a sibling changed the layout. " * 9, line[0])
        self.assertLess(ctx.index(relay.STOP_HEAD), 400, "the warnings lead")
        self.assertNotIn("did not fit", ctx)
        self.assertNotIn("of thirty", context(t.say(TOP, "and now?")), "none of them again")

    def test_a_mark_is_handed_on_once(self):
        """A session that changes again does not send its older marks again."""
        t = self.t
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit ddd444")
        t.stop(A, "one", uuid="a1")
        self.assertIn("ddd444", context(t.say(B, "first")))
        t.cli(A, "note", f"replaces: `{self.x('docs', 'e.md')}` with the wiki", "--source", "commit eee555")
        t.stop(A, "two", uuid="a2")
        ctx = context(t.say(B, "second"))
        self.assertIn("eee555", ctx)
        self.assertNotIn("ddd444", ctx)

    def test_a_hook_leaves_the_first_commit_to_a_process_of_its_own(self):
        """Inside a hook the tree's first commit is not waited on: the hook starts it in a process of its own and
        returns, and that process makes it, with the .gitignore the hook changed, and marks the tree tracked."""
        gd = self._tracked_store("hk1")
        self.assertFalse(relay.track(self.t.p4, first_only=True), "the hook does not wait for the commit")
        mark = os.path.join(gd, relay.TRACKED_MARK)
        end = time.time() + 120
        while not os.path.exists(mark) and time.time() < end:
            time.sleep(0.2)
        self.assertTrue(os.path.exists(mark), "the process of its own made the commit")
        # The mark is not that process's end: after it, track_first still stages what a hook owed meanwhile, removes
        # its state file and gives up its lock, which is the last thing it does in the store. The test's folder is
        # removed when the test ends, so the test waits for that lock to go, where a wait for the mark alone left
        # the process writing under the store's git directory while the folder was being removed.
        lock = os.path.join(gd, relay.TRACK_LOCK)
        while os.path.exists(lock) and time.time() < end:
            time.sleep(0.05)
        self.assertFalse(os.path.exists(lock), "the process of its own has done with the store")
        self.assertEqual(self._subjects().count(relay.TRACK_SUBJECT), 1)
        shown = subprocess.run(["git", "-C", self.t.p4, "show", "--name-only", "--format=", "HEAD"],
                               capture_output=True, text=True).stdout.split()
        self.assertIn(".gitignore", shown)

    def test_a_failed_first_commit_backs_off_says_so_once_and_commits_what_it_owes_on_the_retry(self):
        t = self.t
        gd = self._tracked_store("fc1")
        held = os.path.join(gd, "index.lock")                  # a stale lock of git's own: every commit fails
        write(held, "")
        self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        self.assertFalse(os.path.exists(os.path.join(gd, relay.TRACKED_MARK)), "no mark without the commit")
        st = relay._read_json(os.path.join(gd, relay.TRACK_STATE))
        self.assertEqual(st["fails"], 1)
        self.assertGreater(st["next"], time.time(), "tried again only after a wait")
        self.assertIn(".gitignore", st["owed"])
        self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        self.assertEqual(relay._read_json(os.path.join(gd, relay.TRACK_STATE))["fails"], 1, "not tried in the wait")
        self.assertIn("index.lock", relay.track_notice(t.p4))
        self.assertEqual(relay.track_notice(t.p4), "", "said once")
        os.remove(held)
        st = relay._read_json(os.path.join(gd, relay.TRACK_STATE))
        relay._write_json(os.path.join(gd, relay.TRACK_STATE), dict(st, next=0))
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        shown = subprocess.run(["git", "-C", t.p4, "show", "--name-only", "--format=", "HEAD"], capture_output=True,
                               text=True).stdout.split()
        self.assertIn(".gitignore", shown, "the retry commits what the first try owed")

    def test_a_hook_spends_no_more_than_its_budget_on_git(self):
        """Every git call relay.track makes in a hook, the path filter's included, ends within TRACK_HOOK_S, however
        slow git is."""
        t = self.t
        self._tracked_store("bg1")
        real, old = relay._git, (relay.TRACK_HOOK_S, relay._start_track_first)

        def slow(cwd, *args, timeout=None):
            time.sleep(min(1.0, timeout or relay.GIT_S))
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git, relay.TRACK_HOOK_S, relay._start_track_first = slow, 2.0, lambda home: None
            began = time.time()
            relay.track(t.p4, first_only=True)
            took = time.time() - began
        finally:
            relay._git = real
            relay.TRACK_HOOK_S, relay._start_track_first = old
        self.assertLess(took, 2.0 + 1.5, "the path filter's git calls are inside the budget too")

    def test_a_running_first_commit_keeps_its_lock_fresh(self):
        """The track-first lock is touched before each git call, so a run longer than the stale limit is never taken
        for a dead one."""
        t = self.t
        gd = self._tracked_store("lk1")
        lock = os.path.join(gd, relay.TRACK_LOCK)
        real, seen = relay._git, []

        def aging(cwd, *args, timeout=None):
            if os.path.exists(lock):
                seen.append(time.time() - os.path.getmtime(lock))
                old = time.time() - relay.TRACK_STALE * relay.TRACK_S - 10
                r = real(cwd, *args, timeout=timeout)
                os.utime(lock, (old, old))            # as if this call took longer than the stale limit
                return r
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git = aging
            self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._git = real
        self.assertGreater(len(seen), 2)
        self.assertLess(max(seen), 60, "touched before every call")

    def test_what_a_hook_owes_while_the_first_commit_runs_is_staged(self):
        t = self.t
        gd = self._tracked_store("ow1")
        real = relay._git

        def owing(cwd, *args, timeout=None):
            r = real(cwd, *args, timeout=timeout)
            if "commit" in args:                     # a hook records an owed file while the commit runs
                write(os.path.join(t.p4, "owed.txt"), "x\n")
                relay._owe(gd, ["owed.txt"])
            return r
        try:
            relay._git = owing
            self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._git = real
        staged = subprocess.run(["git", "-C", t.p4, "diff", "--cached", "--name-only"], capture_output=True,
                                text=True).stdout.split()
        self.assertIn("owed.txt", staged)

    def test_a_staging_add_is_not_started_with_too_little_of_the_budget_left(self):
        t = self.t
        gd = self._tracked_store("ad1")
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        write(os.path.join(t.p4, "phi", "new.json"), "{}\n")
        real, old, calls = relay._git, relay.TRACK_HOOK_S, []

        def seen(cwd, *args, timeout=None):
            calls.append(args[0])
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git, relay.TRACK_HOOK_S = seen, relay.TRACK_ADD_LEFT_S - 0.5
            relay.track(t.p4)
        finally:
            relay._git, relay.TRACK_HOOK_S = real, old
        self.assertNotIn("add", calls)
        self.assertTrue(os.path.exists(os.path.join(gd, relay.TRACKED_MARK)))

    def test_the_first_commit_sets_the_path_filter_and_fails_closed_without_it(self):
        """A hook whose budget ran out before the path filter was set leaves it to track_first, which sets it before
        its add, and makes no commit when it cannot be set, since git takes an undefined filter as none."""
        t = self.t
        gd = self._tracked_store("pf1")
        real = relay._path_filter
        try:
            relay._path_filter = lambda home, g=None: False          # never set, as a hook out of budget
            self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._path_filter = real
        self.assertFalse(os.path.exists(os.path.join(gd, relay.TRACKED_MARK)))
        self.assertNotIn(relay.TRACK_SUBJECT, self._subjects(), "no commit without the filter")
        st = relay._read_json(os.path.join(gd, relay.TRACK_STATE))
        self.assertEqual(st["reason"], "the path filter is not set")
        subprocess.run(["git", "-C", t.p4, "config", "--local", "--unset", "filter.p4path.clean"], capture_output=True)
        relay._write_json(os.path.join(gd, relay.TRACK_STATE), dict(st, next=0))
        self.assertTrue(relay.track_first(t.p4), "track_first sets the filter itself")
        committed = subprocess.run(["git", "-C", t.p4, "show", f"HEAD:phi/sessions/{TOP}/session.json"],
                                   capture_output=True, text=True).stdout
        self.assertIn("{project}", committed)

    def test_a_failed_first_commit_keeps_what_hooks_owed_meanwhile(self):
        t = self.t
        gd = self._tracked_store("om1")
        write(os.path.join(gd, "index.lock"), "")                   # the add fails
        real = relay._git

        def owing(cwd, *args, timeout=None):
            if args[:1] == ("add",):
                relay._owe(gd, ["late.txt"])                       # a hook records an owed file meanwhile
            return real(cwd, *args, timeout=timeout)
        try:
            relay._git = owing
            self.assertFalse(relay.track(t.p4, first_only=True, wait=True))
        finally:
            relay._git = real
        self.assertIn("late.txt", relay._read_json(os.path.join(gd, relay.TRACK_STATE))["owed"])

    def test_a_commit_made_before_its_mark_is_not_made_again(self):
        t = self.t
        gd = self._tracked_store("lm1")
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        os.remove(os.path.join(gd, relay.TRACKED_MARK))       # a run that ended after its commit, before its mark
        write(os.path.join(t.p4, "phi", "later.json"), "{}\n")
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        self.assertEqual(self._subjects().count(relay.TRACK_SUBJECT), 1)

    def test_the_phi_folder_is_committed_once_without_logs_and_staged_after(self):
        t = self.t
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        self.assertFalse(relay.track(t.p4, first_only=True), "off until p4.json sets phi.track")
        status = subprocess.run(["git", "-C", t.p4, "status", "--porcelain", "-uall"], capture_output=True,
                                text=True).stdout                  # with tracking off, no tree file shows
        self.assertEqual(t.stop(TOP, "plan it", report="Planned.", uuid="tr1").returncode, 0)
        self.assertEqual(t.stop(A, "move it", report="Moved.", uuid="tr2").returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(t.p4, "phi", "reports.jsonl")))
        relay.forget(t.p4)

        def rel(sid, name):                        # a session's file as git names it: a started one's in its node
            return os.path.relpath(os.path.join(relay._dir(t.p4, sid), name), t.p4).replace("\\", "/")
        self.assertTrue(rel(A, "session.json").startswith("phi/tree/"), "a started session is in the tree")
        write(os.path.join(relay._dir(t.p4, A), "usage.json"), json.dumps({"context": 40}))
        self.assertFalse([x for x in status.splitlines() if "phi/sessions/" in x or x.endswith(
            ("phi/anchor.json", "phi/reports.jsonl", "phi/start-requests.jsonl"))], status)
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        self.assertTrue(relay.track(t.p4, first_only=True, wait=True))
        shown = subprocess.run(["git", "-C", t.p4, "show", "--name-only", "--format=%s", "HEAD"],
                               capture_output=True, text=True).stdout.split()
        self.assertEqual(shown[:4], ["phi:", "the", "session", "tree,"])
        files = [x for x in shown if x.startswith("phi/")]
        self.assertTrue(any(x.endswith("/session.json") for x in files))
        self.assertFalse(any(x.endswith(("log.jsonl", "session.md", "usage.json")) for x in files),
                         "per machine or made again, in a node's folder as in the root")
        self.assertIn(rel(A, "session.json"), files, "a nested session's session.json is committed")
        self.assertIn(rel(TOP, "session.json"), files, "and a flat one's")
        self.assertNotEqual(subprocess.run(["git", "-C", t.p4, "check-ignore", "-q",
                                            rel(A, "session.json")]).returncode, 0, "and not ignored")
        self.assertNotIn(relay.UNTRACKED_MARK, open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read(),
                         "tracking on takes the untracked tree's block out")
        self.assertFalse(relay.track(t.p4, first_only=True), "committed once")
        t.cli(B, "note", "the session tree is tracked in the store now", "--source", "test")
        relay.track(t.p4)
        staged = subprocess.run(["git", "-C", t.p4, "diff", "--cached", "--name-only"], capture_output=True,
                                text=True).stdout
        self.assertIn(rel(B, "notes.jsonl"), staged, "after the first time, staged for the next commit")
        root = pathfilter.project_of(t.p4)
        committed = subprocess.run(["git", "-C", t.p4, "show", f"HEAD:{rel(A, 'session.json')}"],
                                   capture_output=True, text=True).stdout
        on_disk = open(os.path.join(relay._dir(t.p4, A), "session.json"), encoding="utf-8").read()
        self.assertIn(root, on_disk.replace("\\\\", "/"), "the file on disk names this machine's root")
        self.assertIn("{project}", committed, "git holds the root as {project}, a nested file through the filter too")
        self.assertNotIn(root.lower(), committed.lower().replace("\\\\", "/"))

    def test_the_watchers_state_files_are_ignored_with_tracking_off_and_on(self):
        """A store is settled when only hook-committed paths show, so the watcher's three state files at the root of
        phi/ never show as untracked, whether phi.track is off or on."""
        t = self.t
        state = ("phi/.issue-states.json", "phi/.routes-checked", "phi/meta-ledger.md")
        for line in state:
            self.assertIn(line, relay.IGNORED)
        subprocess.run(["git", "-C", t.p4, "init", "-q"], check=True, capture_output=True)
        for line in state:
            write(os.path.join(t.p4, *line.split("/")), "{}\n")

        def shown():
            out = subprocess.run(["git", "-C", t.p4, "status", "--porcelain", "-uall"], capture_output=True,
                                 text=True).stdout
            return [x for x in out.splitlines() if x.endswith(state)]

        self.assertEqual(len(shown()), 3, "untracked before the lines are there")
        self.assertFalse(relay.track(t.p4), "tracking is off")
        self.assertEqual(shown(), [], "off: ignored all the same")
        text = open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read()
        relay.track(t.p4)
        self.assertEqual(open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read(), text, "written once")
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        relay.track(t.p4, wait=True)            # no first commit left running past the test's folder
        self.assertEqual(shown(), [], "on: still ignored")
        lines = open(os.path.join(t.p4, ".gitignore"), encoding="utf-8").read().splitlines()
        for line in state:
            self.assertEqual(lines.count(line), 1, line)

    def test_an_archived_tmp_and_lock_file_reach_another_machine_whole(self):
        """An older store's archive/ holds files named *.tmp and *.lock and one that names the project's root. The
        p4-temportal's `store make` moves it to phi/archive/ at a session start, the store is committed and pushed, and a second clone
        of it holds every archived file as it was."""
        t = self.t
        g = ["-c", "user.name=t", "-c", "user.email=t@t"]
        bare = os.path.join(t.tmp, "store.git").replace("\\", "/")
        root = pathfilter.project_of(t.p4)
        kept = {"x.tmp": "a temp file the old tree kept\n", "y.lock": "a lock file the old tree kept\n",
                "z.json": json.dumps({"cwd": root}) + "\n"}
        write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"track": True}}))
        subprocess.run(["git", "-C", t.p4, "init", "-q", "-b", "main"], check=True, capture_output=True)
        self.assertTrue(relay.track(t.p4, wait=True), "a store p4-phi tracks, with its ignore lines and its path filter")
        for name, text in kept.items():
            write(os.path.join(t.p4, "archive", name), text)
        for args in (("add", "-A", "--", "archive", "p4.json"), (*g, "commit", "-qm", "the old archive")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True, capture_output=True)
        temportal = os.path.join(SRC, "..", "..", "p4-temportal")
        self.assertIsNotNone(shutil.which("sh"), "sh is not found: a command hook starts it")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "P4_"))}
        env.update({"CLAUDE_PROJECT_DIR": t.proj, "CLAUDE_PLUGIN_ROOT": os.path.normpath(temportal)})
        made = subprocess.run(["sh", os.path.join(os.path.normpath(temportal), "hooks", "run-hook.sh"), "store", "make"],
                              input=json.dumps({"hook_event_name": "SessionStart", "source": "startup", "cwd": t.proj}),
                              capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(made.returncode, 0, made.stderr)
        self.assertEqual(t.hook(START, TOP, {"hook_event_name": "SessionStart", "source": "startup"}).returncode, 0)
        for name in kept:
            self.assertTrue(os.path.isfile(os.path.join(t.p4, "phi", "archive", name)), "moved under phi/")
        for args in (("add", "-A"), (*g, "commit", "-q", "--allow-empty", "-m", "the rest"), ("push", "-q", bare, "main")):
            subprocess.run(["git", "-C", t.p4, *args], check=True, capture_output=True)
        other = os.path.join(t.tmp, "other-machine").replace("\\", "/")
        subprocess.run(["git", "clone", "-q", bare, other], check=True, capture_output=True)
        for name, text in kept.items():
            path = os.path.join(other, "phi", "archive", name)
            self.assertTrue(os.path.isfile(path), f"phi/archive/{name} reaches the other machine")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), text, f"phi/archive/{name} as it was, no path rewritten")

    def test_the_path_filter_round_trips_every_spelling(self):
        root = "E:/projects/x"
        text = ('{"cwd": "E:\\\\projects\\\\x", "a": "e:/projects/x/lib/a.py", "b": "/e/projects/x/b", '
                '"c": "/mnt/e/projects/x", "d": "E:/projects/xy/no", "e": "C:/Users/me/tmp/f"}')
        out = pathfilter.clean(text, root)
        self.assertEqual(out.count("{project}"), 4)
        self.assertIn("E:/projects/xy/no", out, "a longer name is not the root")
        self.assertIn("C:/Users/me/tmp/f", out, "a path outside the project stays")
        self.assertIn('"a": "E:/projects/x/lib/a.py"', pathfilter.smudge(out, root))
        there = root if os.name == "nt" else "/projects/x"          # a folder this machine takes as absolute
        self.assertEqual(pathfilter.project_of(there + "/.claude/p4"), there)

    def test_owned_paths_are_kept_for_the_address_book_and_a_path_a_running_sibling_holds_is_refused(self):
        """`phi.py shard` keeps a session's owned paths, which the address book lists and routes by, and refuses a
        path a running sibling holds, with the return value 2; no sibling is told of an overlap."""
        t = self.t
        r = t.cli(A, "shard", self.x("lib"))
        self.assertIn("kept as this session's owned paths", r.stdout)
        r = t.cli(B, "shard", self.x("lib", "x.py"), self.x("docs"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("is held by", r.stderr)
        r = t.cli(B, "shard", self.x("docs"))
        self.assertIn("kept as this session's owned paths", r.stdout)
        self.assertNotIn("overlap", r.stdout)
        self.assertNotIn("overlap", context(t.say(A, "next")), "the sibling is told nothing")
        self.assertEqual(relay.shard_of(t.session(B)), [relay.norm(self.x("docs"))])
        anchor = json.load(open(relay.anchor_path(t.p4, TOP), encoding="utf-8"))
        self.assertEqual(anchor["nodes"][A]["shard"], [relay.norm(self.x("lib"))], "the anchor still holds them")
        self.assertIsNone(relay.set_shard(t.p4, A, [self.x("lib")], t.proj))

    def test_uncommitted_edits_in_another_sessions_owned_paths_are_stopped_by_nothing(self):
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.edit_uncommitted(B, ("lib", "y.py"), "b1")
        ctx = context(t.say(B, "next"))
        self.assertNotIn("inside the owned paths of", ctx)
        self.assertNotIn("stop before any tool runs", ctx)

    def test_a_message_about_another_sessions_owned_paths_is_routed_there_by_the_address_book(self):
        """relay.owners held the paths a message names against the other sessions' owned paths as absolute paths,
        which never meet once an owner works in a git worktree of its own, which a started session does not by
        default. So that compare is gone, and the route line reads the address book, which reads each path from its
        own repository's root: a message naming a file of the main checkout is sent to the worker that owns it."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        ctx = context(t.say(B, f"please fix {self.x('lib', 'y.py')} too"))
        self.assertIn(f"among the owned paths of \"the layout work\" `{A}`. Send it there with SendMessage to {A}", ctx)
        self.assertNotIn("Send it there", context(t.say(B, f"please fix {self.x('docs', 'd.md')}")),
                         "a path no session owns stays here")
        self.assertNotIn("Send it there", context(t.say(TOP, f"look at {self.x('lib', 'y.py')}")),
                         "a parent's owned paths cover its children's: the parent is not routed down")
        own = self.worktree_worker()
        self.assertEqual(t.cli(GRAND, "shard", own + "/docs").returncode, 0)
        named = f"please fix {self.x('docs', 'd.md')} too"
        self.assertFalse(relay.overlap(relay.norm(self.x("docs", "d.md")), relay.norm(own + "/docs")),
                         "the main checkout's path and the worktree's never meet as paths")
        self.assertEqual(self.holders(B, named), [GRAND], "the address book finds the worker in its worktree")
        ctx = context(t.say(B, named))
        self.assertIn(f"this message names docs, among the owned paths of \"the flush worker\" `{GRAND}`. Send it "
                      f"there with SendMessage to {GRAND}", ctx)
        import book
        import phi
        from unittest import mock
        with mock.patch.dict(os.environ, t.env(B)), mock.patch.dict(phi.RECORDS, clear=True):
            s = t.session(B)
            self.assertEqual(book.holders(t.p4, s, "Port the flush in lib/x.py", owned=True), [],
                             "the files a brief covers route no message beside a prompt")

    def test_an_archived_session_owns_no_paths_and_is_not_listed(self):
        """An archived session owns no paths a message is routed by."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        self.assertEqual(self.holders(B, f"please fix {self.x('lib', 'y.py')}"), [A])
        rec = os.path.join(t.app, A + ".json")
        d = json.loads(open(rec, encoding="utf-8").read())
        d["isArchived"] = True
        write(rec, json.dumps(d))
        self.assertEqual(self.holders(B, f"please fix {self.x('lib', 'y.py')}"), [])
        self.assertNotIn("Send it there", context(t.say(B, f"please fix {self.x('lib', 'y.py')} too")))

    def test_the_project_root_the_store_and_a_drive_name_no_owned_paths(self):
        """The project's root, the store, the folder above the project and a drive's root name no session's owned
        paths, and a brief that names only the root is advised fresh."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        for whole in (t.proj, t.p4, os.path.dirname(t.proj), os.path.splitdrive(t.proj)[0] + "/"):
            self.assertEqual(self.holders(B, f"work in `{whole}` on the docs"), [], whole)
        self.assertEqual(self.holders(B, f"work in `{t.proj}` on `{self.x('lib', 'y.py')}`"), [A],
                         "a real path beside the root is still routed")
        t.cli(TOP, "shard", self.x("docs"))
        advised, why = relay.advise_start(t.p4, TOP, {"prompt": f"Check one thing in `{t.proj}`, read-only"},
                                          10 * 1024)
        self.assertEqual(advised, "fresh", why)
        self.assertIn("names no path", why)
        self.assertTrue(relay.names_nothing(relay.norm(t.proj), t.p4, t.proj))
        self.assertFalse(relay.names_nothing(self.x("lib"), t.p4, t.proj))

    def test_a_sessions_scope_is_its_own_files_and_none_of_its_childrens(self):
        """relay.scope_of gave a start's advice and a puppeteer's routing the files of a session's children from its
        anchor. A child's files lie in its own worktree, where no path a brief or a message names from the parent's
        folder leads, so the scope is the session's owned paths, else the files of its own latest delta."""
        t = self.t
        t.stop(TOP, "its own edit", [("Edit", {"file_path": self.x("docs", "d.md")}, "ok")], uuid="t1")
        t.stop(A, "a child's edit", [("Edit", {"file_path": self.x("lib", "x.py")}, "ok")], uuid="a1")
        self.assertEqual(relay.scope_of(t.p4, TOP), [relay.norm(self.x("docs", "d.md"))])
        t.cli(TOP, "shard", self.x("lib"))
        self.assertEqual(relay.scope_of(t.p4, TOP), [relay.norm(self.x("lib"))])

    def test_nothing_new_is_quiet(self):
        t = self.t
        t.stop(A, "plain turn", uuid="a1")
        t.say(B, "first look")
        ctx = context(t.say(B, "second look"))
        self.assertNotIn("phi (p4-phi): what", ctx)
        self.assertNotIn("stop before", ctx)

    def test_a_child_a_sibling_supersedes_is_listed_as_ready_to_archive(self):
        """A finished child whose work a sibling's newer note supersedes, by its words on the child's parent step, is
        counted as archived and listed on ready-to-archive.md."""
        t = self.t
        self.finish_under_a_step()
        t.cli(B, "note", "replaces: the move of the store layout into recall with the move into phi",
              "--source", "abc123")
        self.assertEqual(t.stop(B, "replace it", uuid="b1").returncode, 0)
        self.assertEqual(t.session(A)["stale"]["by"], B, "superseded by the sibling's newer note")
        self.assertIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "listed on ready-to-archive.md")

    def test_a_note_that_names_a_finished_childs_file_or_owned_path_supersedes_nothing(self):
        """relay.superseded held the paths a newer note names against a finished child's changed files and owned
        paths, as absolute paths. Every session works in the one checkout, on its own paths, and the child's work
        stands in its commits until the tree's orchestrator pushes it. That arm is
        gone, here with both sessions in one folder, where the paths did meet: a note that names the child's very
        file and owned path, and says nothing of its parent step, marks it stale no longer."""
        t = self.t
        t.cli(A, "shard", self.x("lib"))
        path = self.x("lib", "x.py")
        with open(path, "a", encoding="utf-8") as f:
            f.write("more = 2\n")
        subprocess.run(["git", "-C", self.work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "x"],
                       check=True, capture_output=True)
        self.assertEqual(t.cli(A, "done", "test_layout.py: 3 tests OK").returncode, 0)
        self.assertEqual(t.stop(A, "edit x", [("Edit", {"file_path": path}, "ok")], report="Edited x.",
                                uuid="a1").returncode, 0)
        self.assertTrue(relay.finished(t.p4, A))
        self.assertEqual(relay.edited_files(t.p4, A), [relay.norm(path)])
        t.cli(B, "note", f"replaces: `{path}` with p4conf's table", "--source", "commit abc123")
        self.assertEqual(t.stop(B, "replace x", uuid="b1").returncode, 0)
        self.assertNotIn("stale", t.session(A))
        anchor = json.load(open(relay.anchor_path(t.p4, TOP), encoding="utf-8"))
        self.assertIn(A, anchor["nodes"], "still in the anchor")
        self.assertEqual(anchor["nodes"][B]["marks"][0]["paths"], [relay.norm(path)], "the note keeps its path")
        mark = (B, "the recall work", anchor["nodes"][B]["marks"][0])
        self.assertIsNone(relay.superseded(t.p4, A, t.session(A), [mark]), "no parent step: no note supersedes it")

    def test_a_superseded_child_messaged_again_leaves_the_page(self):
        """A superseded session that is messaged again is live: it leaves ready-to-archive.md at that message, and
        the Stop that clears its mark leaves a page without it."""
        t = self.t
        self.finish_under_a_step(uuid="s1")
        t.cli(B, "note", "replaces: the move of the store layout into recall with the move into phi",
              "--source", "abc123")
        self.assertEqual(t.stop(B, "replace it", uuid="s2").returncode, 0)
        self.assertIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "superseded: listed")
        t.say(A, "go on with the layout")
        self.assertNotIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "messaged again: off the page")
        self.assertEqual(t.stop(A, "go on with the layout", report="Went on.", uuid="s3").returncode, 0)
        self.assertNotIn(A, open(relay.ready_path(t.p4), encoding="utf-8").read(), "the Stop leaves it off")

    def test_ezexes_message_is_routed_to_the_worker_that_owns_its_path_in_a_worktree(self):
        """puppeteer.prompty picked a message's code owner by holding the paths it names against each other
        session's owned paths as absolute paths, which never meet once the owner works in a git worktree of its
        own. The pick now reads the address book, which reads each path from its own repository's root. Whether a
        message is within the session's own topic still reads relay.scope_of, the session's own paths alone."""
        import phi
        import puppeteer
        from unittest import mock
        t = self.t
        own = self.worktree_worker()
        self.assertEqual(t.cli(GRAND, "shard", own + "/docs").returncode, 0)
        named = self.x("docs", "d.md")
        self.assertFalse(relay.covers(relay.norm(own + "/docs"), relay.norm(named)),
                         "the worker's owned path and the main checkout's file never meet as paths")
        message = f"Fix the off-by-one in `{named}` that drops the last row of the ports table"
        with mock.patch.dict(os.environ, t.env(TOP)), mock.patch.dict(phi.RECORDS, clear=True):
            read = puppeteer.prompty(t.p4, t.session(TOP), message, t.proj)
            self.assertTrue(read["work"])
            self.assertEqual((read["owner"] or {}).get("sessionId"), GRAND, read["owner"])
            self.assertEqual(read["owner"]["why"], "its owned paths hold docs")
            other = puppeteer.prompty(t.p4, t.session(TOP), message.replace("docs/d.md", "lib/y.py"), t.proj)
            self.assertNotEqual((other["owner"] or {}).get("sessionId"), GRAND, "a path it does not own")
            t.cli(TOP, "shard", self.x("lib"))
            above = puppeteer.prompty(t.p4, t.session(GRAND), f"Fix the layout in `{self.x('lib', 'x.py')}` of the "
                                      f"ports table rows", own)
            self.assertNotEqual((above["owner"] or {}).get("sessionId"), TOP, "the session above it is never its owner")
            t.stop(TOP, "its own edit", [("Edit", {"file_path": self.x("lib", "y.py")}, "ok")], uuid="t1")
            self.assertEqual(relay.scope_of(t.p4, TOP), [relay.norm(self.x("lib"))])
            mine = puppeteer.prompty(t.p4, t.session(TOP), f"Rewrite `{self.x('lib', 'y.py')}` for the zebra "
                                     f"importer's nightly quota", t.proj)
            self.assertTrue(mine["within"], "a path in its own scope is within its topic")


class ForkOrFresh(_ThreeSessionsBase):
    """The advice on start_session, a fork's pinned agenda, and a fresh child's slice of the parent's anchor."""

    def advise(self, host, context_, prompt, size, **more):
        path = os.path.join(self._tmp.name, host + "-transcript.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * size)
        r = self.t.hook("start-advice", host, {"hook_event_name": "PreToolUse",
                                               "tool_name": "mcp__ccd_session__start_session",
                                               "tool_input": {"initiation": "user_asked", "context": context_,
                                                              "title": "a child", "prompt": prompt + "\nFiles: none",
                                                              **more},
                                               "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_a_fork_of_a_long_parent_is_advised_fresh(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fork", f"Fix `{self.x('lib', 'x.py')}`", 3 * 1024 * 1024)
        self.assertEqual(out["permissionDecision"], "ask", "asked, never blocked")
        self.assertIn('advises context "fresh"', out["permissionDecisionReason"])
        self.assertIn("3.0 MB", out["permissionDecisionReason"])

    def test_a_fork_whose_owned_paths_are_the_parents_is_allowed(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        self.assertIsNone(self.advise(TOP, "fork", f"Rework `{self.x('lib')}`", 200 * 1024))

    def test_a_fork_of_a_short_parent_for_other_paths_is_advised_fresh(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fork", f"Write `{self.x('docs', 'new.md')}`", 10 * 1024)
        self.assertIn('advises context "fresh"', out["permissionDecisionReason"])
        self.assertIn("cover 0%", out["permissionDecisionReason"])

    def test_a_fresh_start_where_a_fork_fits_is_asked_too(self):
        self.t.cli(TOP, "shard", self.x("lib"))
        out = self.advise(TOP, "fresh", f"Rework `{self.x('lib')}`", 10 * 1024)
        self.assertIn('advises context "fork"', out["permissionDecisionReason"])

    def writer(self, host, context_, size=10 * 1024, cwd=None, **more):
        """The start-advice hook for a call whose brief writes `lib/x.py`, from `host` working in `cwd`."""
        path = os.path.join(self._tmp.name, host + "-writer.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x" * size)
        r = self.t.hook("start-advice", host, {
            "hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
            **({"cwd": cwd} if cwd else {}),
            "tool_input": {"initiation": "user_asked", "context": context_, "title": "the lib rework",
                           "prompt": f"Rework `{self.x('lib')}` and commit it.\nFiles: {self.x('lib', 'x.py')}",
                           **more}})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_a_writers_fork_is_advised_by_size_and_paths_like_any_and_asked_about_only_for_a_worktree(self):
        """advise_start returns two values, the advice and its why, and no longer advises a worktree: a writer's
        start is advised "fork" or "fresh" by the parent's size and the paths its brief covers, as a reader's is, and
        only a call that passes `use_worktree: true` is asked about, since every session p4-phi starts works in its
        starter's checkout. A fork from a plain checkout is no longer held against a writer, and phi.fork_apart is
        gone."""
        import phi
        import starts
        t = self.t
        t.cli(TOP, "shard", self.x("lib"))
        brief = f"Rework `{self.x('lib')}` and commit it.\nFiles: {self.x('lib', 'x.py')}"
        self.assertTrue(starts.writes(brief, t.proj))
        self.assertFalse(hasattr(phi, "fork_apart"), "no fork is judged by the folder it starts from")
        got = relay.advise_start(t.p4, TOP, {"prompt": brief}, 10 * 1024)
        self.assertEqual(len(got), 2, "the advice and why, nothing about a worktree")
        self.assertEqual(got[0], "fork", "a short parent whose scope the brief covers: a writer forks as a reader does")
        self.assertEqual(relay.advise_start(t.p4, TOP, {"prompt": brief}, 3 * 1024 * 1024)[0], "fresh")
        self.assertIsNone(self.writer(TOP, "fork", cwd=self.work), "a fork that fits is not asked about")
        self.assertIsNone(self.writer(TOP, "fork", cwd=self.work, use_worktree=False))
        out = self.writer(TOP, "fresh", cwd=self.work)
        self.assertEqual(out["permissionDecision"], "ask", "asked, never blocked")
        self.assertIn('advises context "fork" here, not "fresh"', out["permissionDecisionReason"])
        self.assertNotIn("use_worktree", out["permissionDecisionReason"])
        big = self.writer(TOP, "fork", size=3 * 1024 * 1024, cwd=self.work)
        self.assertIn("3.0 MB", big["permissionDecisionReason"], "a long parent's fork is advised fresh by its size")
        self.assertIsNone(self.advise(TOP, "fork", f"Rework `{self.x('lib')}`", 200 * 1024),
                          "a brief that only reads forks as before")
        import puppeteer
        import inspect
        self.assertIn('context = "fresh"', inspect.getsource(puppeteer.prompter), "every drafted start is fresh")

    def test_a_start_of_a_writer_that_names_no_worktree_is_not_asked_about_one(self):
        """A writer's start that leaves `use_worktree` out, or passes `false`, is asked nothing about a worktree
        from a plain folder or with a start of another place; relay.advise_start names none. One that passes `true`
        is asked about, with the reason that every session p4-phi starts works in its starter's checkout."""
        import phi
        t = self.t
        t.cli(TOP, "shard", self.x("lib"))
        brief = f"Rework `{self.x('lib')}` and commit it.\nFiles: {self.x('lib', 'x.py')}"
        self.assertEqual(len(relay.advise_start(t.p4, TOP, {"prompt": brief}, 10 * 1024)), 2)
        for extra in ({}, {"use_worktree": False}, {"cwd": "D:/another/project"}, {"target": "cloud"},
                      {"preset": "the api repo"}, {"host": "devbox"}):
            path = os.path.join(self._tmp.name, "short.jsonl")
            write(path, "x")
            r = t.hook("start-advice", TOP, {
                "hook_event_name": "PreToolUse", "tool_name": "mcp__ccd_session__start_session", "cwd": self.work,
                "transcript_path": path, "tool_input": {"initiation": "user_asked", "context": "fork",
                                                        "title": "the lib rework", "prompt": brief, **extra}})
            self.assertEqual((r.returncode, r.stdout.strip()), (0, ""), f"not asked: {extra}")
        out = self.writer(TOP, "fork", cwd=self.work, use_worktree=True)
        self.assertEqual(out["permissionDecision"], "ask", "asked, never blocked")
        why = out["permissionDecisionReason"]
        self.assertTrue(why.startswith("phi (p4-phi) advises `use_worktree: false` here: "), why)
        self.assertIn("every session p4-phi starts works in its starter's checkout", why)
        self.assertEqual(self.writer(TOP, "fork", cwd=self.work, use_worktree=True,
                                     initiation="own_initiative")["permissionDecision"],
                         "ask", "a suggested task card starts the same call")
        for reads in ("Check the layout of `lib` and report.\nFiles: none",
                      "Build the importer's nightly run and commit it. " + starts.ORCHESTRATOR_BRIEF):
            self.assertEqual(relay.advise_start(t.p4, TOP, {"prompt": reads}, 3 * 1024 * 1024)[0], "fresh", reads[:40])
        self.assertIsNone(self.advise(TOP, "fresh", "Write the docs", 3 * 1024 * 1024),
                          "a brief that names no worktree and no scope is asked nothing")

    def test_a_start_that_passes_use_worktree_true_is_asked_about_and_one_that_passes_false_is_not(self):
        """Every session p4-phi starts works in its starter's checkout, on the paths of its `Files:` line, so a start
        that passes `use_worktree: true`, with or without a branch name or a source branch, is asked about, and its
        own word for a new worker's call is `use_worktree: false`. A fresh start that passes false where a fork
        fits is advised the fork, as any is."""
        self.t.cli(TOP, "shard", self.x("lib"))
        path = os.path.join(self._tmp.name, "short.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        for extra in ({"use_worktree": True}, {"use_worktree": True, "branch_name": "my-branch"},
                      {"use_worktree": True, "source_branch": "main"}):
            r = self.t.hook("start-advice", TOP, {"tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
                                                  "tool_input": {"context": "fresh", "prompt": "write docs\nFiles: none", **extra}})
            out = json.loads(r.stdout)["hookSpecificOutput"]
            self.assertEqual(out["permissionDecision"], "ask", f"asked: {extra}")
            self.assertIn("advises `use_worktree: false`", out["permissionDecisionReason"], extra)
        r = self.t.hook("start-advice", TOP, {"tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
                                              "tool_input": {"context": "fresh", "prompt": "write docs\nFiles: none",
                                                             "use_worktree": False}})
        self.assertEqual(r.stdout.strip(), "", "not asked: use_worktree false")
        self.assertIn("advises `use_worktree: false`", self.advise(
            TOP, "fresh", f"Rework `{self.x('lib')}`", 10 * 1024, use_worktree=True)["permissionDecisionReason"])
        self.assertIn('advises context "fork"', self.advise(TOP, "fresh", f"Rework `{self.x('lib')}`", 10 * 1024,
                                                            use_worktree=False)["permissionDecisionReason"])

    def test_a_session_in_its_own_worktree_is_asked_about_no_branch_and_one_that_shares_a_checkout_before_it_moves_it(self):
        """The stop on a child's own worktree is gone: a session started in a git worktree of its own makes a branch,
        moves to one and enters a worktree unasked, since worktrees.md gives each such session "a separate copy of
        the files to edit". What still guards something stays: a child that shares its starter's checkout is asked
        before it moves that checkout to another branch, and every child before it lands work."""
        def guard(host, cmd, tool="Bash", cwd=None):
            r = self.t.hook("branch-guard", host, {"tool_name": tool, "tool_input": {"command": cmd},
                                                   **({"cwd": cwd} if cwd else {})})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        self.assertEqual(guard(B, "git switch -c mine")["permissionDecision"], "ask", "it moves the shared checkout")
        self.assertEqual(guard(B, "git checkout -b mine")["permissionDecision"], "ask")
        import hook
        self.assertNotIn("EnterWorktree", hook.PHI_CHECK,
                         "entering a worktree is Claude Code's own way apart: no check is routed for the tool")
        self.assertEqual({t for t, names in hook.PHI_CHECK.items() if "branch-guard" in names},
                         {"Bash", "PowerShell"}, "the guard reads shell calls alone")
        self.assertIsNone(guard(B, "git worktree add ../wt -b mine"), "a worktree made moves no checkout")
        self.assertIsNone(guard(B, "git branch mine"), "a branch made without a move")
        self.assertIsNone(guard(B, "git status"), "a status reads")
        out = guard(B, "git status && git commit -qm x")
        self.assertEqual(out["permissionDecision"], "deny", "a commit in a shared checkout takes the others' changes")
        self.assertIn('phi.py" commit -m "<message>" -- <path> ...', out["permissionDecisionReason"])
        self.assertIsNone(guard(B, "grep -n 'git checkout -b' docs.md"), "quoted text is not a command")
        self.assertIsNone(guard(B, "git checkout -- lib/x.py"), "restoring a file is not a branch change")
        self.assertEqual(guard(B, "git switch main")["permissionDecision"], "ask", "a branch change in a child")
        self.assertIn("moves the parent's too", guard(B, "git checkout feature/x")["permissionDecisionReason"])
        self.assertIsNone(guard(TOP, "git switch -c mine"), "an orchestrator decides its own branches")
        # a worker the app started in a worktree of its own: the hook's `cwd` is the worktree
        own = os.path.join(self.work, ".claude", "worktrees", "the-flush")
        subprocess.run(["git", "-C", self.work, "worktree", "add", "-q", "-b", "claude/the-flush", own],
                       check=True, capture_output=True)
        reader = "local_reader01"
        CLI.setdefault(reader, "eeee5555-0000-4000-8000-000000000000")
        self.t.record(GRAND, TOP, title="the flush worker", cwd=own)
        self.t.record(reader, GRAND, title="a check of the flush", cwd=own)
        for host in (GRAND, reader):
            self.assertEqual(self.t.say(host, "Task:\nLook at the flush.").returncode, 0)
        for cmd in ("git switch -c mine", "git checkout -b mine", "git switch main", "git checkout feature/x",
                    "git worktree add ../wt -b mine", "git branch mine"):
            self.assertIsNone(guard(GRAND, cmd, cwd=own), f"its own worktree: {cmd}")
        self.assertIn("merges and pushes", guard(GRAND, "git push origin HEAD", cwd=own)["permissionDecisionReason"],
                      "landing stays the orchestrator's")
        self.assertEqual(guard(reader, "git switch main", cwd=own)["permissionDecision"], "ask",
                         "a reader started with use_worktree false shares its starter's worktree")

    def test_a_hand_pull_or_push_in_a_store_is_asked_and_names_p4_sync(self):
        """A hand pull or push in a store is asked first."""
        p4 = self.t.p4
        subprocess.run(["git", "init", "-q", p4], check=True, capture_output=True)
        clone = os.path.join(p4, "temportal", "tmp", "s1", "p4")
        os.makedirs(clone)
        subprocess.run(["git", "init", "-q", clone], check=True, capture_output=True)

        def guard(host, cmd, cwd=None):
            r = self.t.hook("store-guard", host, {"tool_name": "Bash", "tool_input": {"command": cmd},
                                                  "cwd": cwd or self.t.proj})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        for host in (TOP, B):
            out = guard(host, f"cd {p4} && git pull origin main")
            self.assertEqual(out["permissionDecision"], "ask")
            self.assertIn("Two machines write the same", out["permissionDecisionReason"])
        self.assertIn("force-push", guard(TOP, f'git -C "{p4}" push --force origin win')["permissionDecisionReason"])
        self.assertIsNotNone(guard(TOP, "git push", cwd=p4), "the call's own folder")
        self.assertIsNone(guard(TOP, f"git -C {self.work} push"), "a project checkout is not a store")
        self.assertIsNone(guard(TOP, f"cd {clone} && git push origin main"), "a clone kept in a scratchpad directory")
        self.assertIsNone(guard(TOP, f"git -C {p4} status"), "reading a store is never asked")

    def test_a_started_sessions_hand_pull_in_a_store_through_lookup_check_names_p4_sync(self):
        """ezexe/p4#240: through `recall-hook.sh lookup-check`, which runs what the hooks module runs for a checked call, a
        started session's hand pull or push inside a store is asked by the store guard, which runs ahead of the
        branch guard: its reason names the store guard's ask and the tree's orchestrator as the session
        that runs it. The same session's pull in the project's own checkout keeps the branch guard's ask."""
        p4 = self.t.p4.replace("\\", "/")
        subprocess.run(["git", "init", "-q", p4], check=True, capture_output=True)
        gate = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")

        def check(host, tool, cmd, k):
            body = {"session_id": CLI[host], "cwd": self.t.proj, "hook_event_name": "PreToolUse", "tool_name": tool,
                    "tool_input": {"command": cmd}, "tool_use_id": f"toolu_store00{k}"}
            r = inproc.run(["sh", gate, "lookup-check"], input=json.dumps(body), capture_output=True, text=True,
                           timeout=60, env=self.t.env(host))
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
        for k, (tool, cmd) in enumerate((("Bash", f"cd {p4} && git pull origin main"),
                                         ("Bash", f"git -C {p4} push origin main"),
                                         ("PowerShell", f"cd {p4}; git pull origin main"),
                                         ("PowerShell", f"git -C {p4} push origin main"))):
            out = check(B, tool, cmd, k)
            self.assertEqual(out.get("permissionDecision"), "ask", f"{tool}: {cmd}")
            reason = out.get("permissionDecisionReason", "")
            self.assertIn("Two machines write the same", reason, f"{tool}: {cmd}")
            self.assertIn(relay.norm(p4), relay.norm(reason), "the store by its path")
            self.assertIn(f"a move of the store is its tree's orchestrator's to make, \"top\" `{TOP}`", reason, "and the session that runs it")
            self.assertNotIn("Ask its parent session", reason, "not the branch guard's reason")
        own = check(B, "Bash", "git pull", 7)
        self.assertEqual(own.get("permissionDecision"), "ask")
        self.assertIn("merges and pushes", own.get("permissionDecisionReason", ""), "outside a store: the branch guard")
        self.assertNotIn("Two machines write the same", own.get("permissionDecisionReason", ""))
        top = check(TOP, "Bash", f"cd {p4} && git pull origin main", 8)
        self.assertIn("Two machines write the same", top.get("permissionDecisionReason", ""))
        self.assertNotIn("orchestrator's to make", top.get("permissionDecisionReason", ""),
                         "the orchestrator moves the store itself")
        import hook
        for tool in ("Bash", "PowerShell"):
            names = hook.PHI_CHECK[tool]
            self.assertLess(names.index("store-guard"), names.index("branch-guard"), tool)

    def test_a_child_landing_work_is_always_asked(self):
        """ezexe/p4#232: only the tree's orchestrator merges and pushes. Neither a brief that says "Closes #7" and
        "push it yourself", a brief that names issues, an issue on the child's record, nor its parent's message lets
        a child land its own work."""
        def guard(host, cmd):
            r = self.t.hook("branch-guard", host, {"tool_name": "Bash", "tool_input": {"command": cmd}})
            return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None
        for cmd in ("git push origin main", "cd /x && git merge feature", "git -C p4 rebase main", "git pull",
                    "git -C /x/work push", "git push origin HEAD:main", "x & git push", "(git push)",
                    '& "C:/Program Files/Git/cmd/git.exe" push origin main', "/usr/bin/git push", "FOO=1 git push",
                    'bash -c "git push origin main"', 'pwsh -Command "git push"', "env GIT_TRACE=1 git push",
                    "git --git-dir=/x/.git push", "git -c core.x=y push", "echo $(git push)",
                    "gh pr merge 12 --squash", "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
                    "gh api repos/o/r/merges -f base=main -f head=fix", "gh api -X PUT repos/o/r/pulls/3/merge",
                    'bash -lc "git push"', 'iex "git push"', "{ git push; }", "if x; then git push; fi",
                    "sudo -u x git push", "gh api -XDELETE repos/o/r/git/refs/heads/x",
                    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"P\"}) { a } }'",
                    "gh api graphql -f query='\nmutation {\n  mergePullRequest(input: {pullRequestId: \"P\"}) {\n"
                    "    clientMutationId\n  }\n}'",
                    'git -C "C:/Users/a b/repo" push', 'git -c "user.name=a b" push', "cmd /c git push",
                    'Invoke-Expression "git push"'):
            out = guard(B, cmd)
            self.assertIsNotNone(out, cmd)
            self.assertEqual(out["permissionDecision"], "ask", cmd)
            self.assertIn("merges and pushes", out["permissionDecisionReason"])
        r = self.t.hook("branch-guard", B, {"tool_name": "PowerShell", "tool_input": {
            "command": "Set-Location C:/x; & git.exe push origin main"}})
        self.assertEqual(json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], "ask", "a PowerShell push")
        out = guard(B, 'git commit -qm "x" && git push')
        self.assertEqual(out["permissionDecision"], "deny", "the commit is refused before the push is asked about")
        self.assertIn('phi.py" commit -m "<message>" -- <path> ...', out["permissionDecisionReason"])
        gate = os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")
        for k, cmd in enumerate(("gh pr merge 12", "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=abc",
                                 "/usr/bin/git push", "/usr/bin/git pull", "/usr/bin/git rebase main",
                                 "C:\\Git\\bin\\git rebase main", '"/usr/bin/git" pull',
                                 '"/usr/bin/git" rebase main')):
            body = {"session_id": CLI[B], "cwd": self.t.proj, "hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": cmd}, "tool_use_id": f"toolu_gate000{k}"}
            r = subprocess.run(["sh", gate, "lookup-check"], input=json.dumps(body), capture_output=True,
                               text=True, encoding="utf-8", timeout=60, env=self.t.env(B))   # the script itself
            out = json.loads(r.stdout).get("hookSpecificOutput", {}) if r.stdout.strip() else {}
            self.assertEqual(out.get("permissionDecision"), "ask", f"through the runner: {cmd}")
        self.assertIsNone(guard(B, "git merge-base --is-ancestor a b"), "merge-base lands nothing")
        self.assertIsNone(guard(B, "git log --grep 'push'"), "quoted words are not a command")
        self.assertIsNone(guard(B, "git log --grep push"), "a log reads")
        self.assertIsNone(guard(B, "git status"), "a status reads")
        self.assertIsNone(guard(B, "echo push"), "an echo lands nothing")
        for cmd, what in (('git commit -qm "say git push to land it"', "a message naming a push"),
                          ('git commit -q --message="then git push"', "a --message= value is data")):
            out = guard(B, cmd)     # denied as a commit, never asked as a push: its message is data
            self.assertEqual(out["permissionDecision"], "deny", what)
            self.assertIn('phi.py" commit -m "<message>" -- <path> ...', out["permissionDecisionReason"], what)
            self.assertNotIn("merges and pushes", out["permissionDecisionReason"], what)
        self.assertIsNone(guard(B, 'grep -rn "git push" docs/'), "a quoted pattern is data")
        self.assertIsNone(guard(B, 'echo "then git pull"'), "a quoted echo is data")
        self.assertIsNone(guard(B, 'rg "gh pr merge"'), "a quoted search is data")
        self.assertIsNone(guard(B, "cat > n.md <<'EOF'\nrun git push, then gh pr merge 3\nEOF"), "a heredoc is data")
        self.assertIsNone(guard(B, "gh api graphql -f query='query { repository(name: \"x\") { id } }'"), "a query")
        self.assertIsNone(guard(B, "gh pr view 12"), "a view lands nothing")
        self.assertIsNone(guard(B, "gh api repos/o/r/git/refs/heads/main"), "reading a ref lands nothing")
        self.assertIsNone(guard(TOP, "git push origin main"), "the orchestrator lands the work")
        s = relay._session(self.t.p4, B)
        for task in ("Fix x. Closes #7 on ezexe/demo; run the suites, then push it yourself.",
                     "Build the queue: issues #19 to #24 on ezexe/p4, the fix for each in its body."):
            s["task"] = task
            relay._write_json(os.path.join(relay._dir(self.t.p4, B), "session.json"), s)
            self.assertEqual(guard(B, "git push origin main")["permissionDecision"], "ask", task)
        s["issue"] = {"repo": "ezexe/demo", "number": 7, "url": "https://github.com/ezexe/demo/issues/7"}
        relay._write_json(os.path.join(relay._dir(self.t.p4, B), "session.json"), s)
        self.assertEqual(guard(B, "git push origin main")["permissionDecision"], "ask", "an issue on its record")
        self.t.say(B, f'<cross-session-message from="{TOP}" from-name="top">Push each green commit as it closes '
                      f'its issue.</cross-session-message>')
        self.assertEqual(guard(B, "git push origin main")["permissionDecision"], "ask", "its parent's message")

    def test_a_fresh_child_starts_with_only_the_slice_for_its_paths(self):
        t = self.t
        t.cli(A, "note", f"deprecates: `{self.x('lib', 'x.py')}`; use p4conf", "--source", "commit aaa111")
        t.cli(A, "note", f"replaces: `{self.x('docs', 'd.md')}` with the README", "--source", "commit bbb222")
        t.stop(A, "two decisions", [("Edit", {"file_path": self.x("lib", "x.py")}, "ok")], uuid="a1")
        t.record(GRAND, TOP, title="the lib child")
        ctx = context(t.say(GRAND, f"Make `{self.x('lib')}` read its paths from p4conf"))
        self.assertIn("what the parent, \"top\", has for this session's paths", ctx)
        self.assertIn("deprecates: `", ctx)
        self.assertIn("; source: commit aaa111", ctx)
        self.assertNotIn("bbb222", ctx, "what does not touch the child's paths is left out")
        for gone in ("Heads to build on:", "Changed there:"):
            self.assertNotIn(gone, ctx, "a sibling's files and heads lie in its own worktree: nothing to build on")

    def test_a_fresh_childs_start_waits_for_its_brief_and_replaces_the_parents_background(self):
        """No slice before the brief, and the slice holds the parent's notes on the child's paths and no sibling's last
        turn."""
        t = self.t
        t.cli(TOP, "note", f"the docs keep their old layout in `{self.x('docs', 'd.md')}`", "--source", "fff666")
        t.cli(TOP, "note", f"the lib reads `{self.x('lib', 'x.py')}` first", "--source", "ggg777")
        t.stop(A, "a sibling's turn", uuid="a1")
        t.record(GRAND, TOP, title="the lib child")
        start = context(t.hook("session-start", GRAND, {"hook_event_name": "SessionStart", "source": "startup"}))
        self.assertNotIn("has for this session's paths", start, "no slice before the brief")
        ctx = context(t.say(GRAND, f"Make `{self.x('lib')}` read its paths from p4conf"))
        self.assertIn("has for this session's paths", ctx)
        self.assertIn("ggg777", ctx, "the parent's note on the child's paths")
        self.assertNotIn("fff666", ctx, "the parent's note on other paths is left out")
        self.assertNotIn("The last turn of", ctx, "the siblings' last turns are left out")

    def test_a_fresh_child_the_parent_has_nothing_for_is_told_in_one_line(self):
        t = self.t
        t.record(GRAND, TOP, title="the docs child")
        ctx = context(t.say(GRAND, f"Write `{self.x('docs', 'new.md')}`"))
        self.assertIn("It has nothing for them yet.", ctx)

    def test_a_forked_child_keeps_its_own_task_above_the_inherited_conversation(self):
        t = self.t
        t.record(GRAND, TOP, title="the forked child")
        brief = f"Fix `{self.x('lib', 'y.py')}` and nothing else"
        first = context(t.say(GRAND, "Task (from the session that started this one):\n" + brief))
        self.assertIn("this session is a fork", first)
        self.assertTrue(t.session(GRAND)["forked"])
        t.cli(GRAND, "shard", self.x("lib", "y.py"))
        later = context(t.say(GRAND, "carry on"))
        self.assertIn(f"Its own task: \"{brief}\"", later)
        self.assertIn("its owned paths: " + relay.norm(self.x("lib", "y.py")), later)
        self.assertNotIn("what the parent", later, "a fork is not given the fresh child's slice")



class MergedWorktrees(unittest.TestCase):
    """The app removes a session's worktree itself and `clean_up_worktrees` removes inactive ones, desktop.md, "Keep
    uncommitted changes when a session is archived", so an orchestrator is never told to remove one."""

    def test_a_merged_clean_worktree_is_not_named_at_a_step_boundary(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            g = lambda cwd, *a: subprocess.run(["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                               check=True, capture_output=True, text=True)
            write(os.path.join(repo, "a.txt"), "a\n")
            subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True, capture_output=True)
            g(repo, "add", "-A")
            g(repo, "commit", "-qm", "one")
            g(repo, "worktree", "add", "-q", "-b", "done", os.path.join(tmp, ".claude", "worktrees", "done"))
            t = Tree(os.path.join(tmp, "t"))
            t.record(TOP, title="top", cwd=repo)
            r = t.hook("plan", TOP, {"hook_event_name": "PostToolUse", "tool_name": "mcp__ccd_turn__update_plan",
                                     "tool_input": {"advance": True}, "tool_response": "Plan updated."})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("git worktree remove", r.stdout)


class GhWrapper(unittest.TestCase):
    """relay.gh runs the gh it found, so a gh installed as a .cmd wrapper answers as gh.exe would."""

    @unittest.skipUnless(os.name == "nt", "a .cmd wrapper is a Windows install")
    def test_a_gh_cmd_wrapper_is_run(self):
        tmp = tempfile.mkdtemp(prefix="p4-phi-gh-")
        old = {k: os.environ.get(k) for k in ("PATH", "P4_PHI_GH")}
        try:
            os.environ.pop("P4_PHI_GH", None)               # an environment that names a gh cannot change the result
            os.environ["PATH"] = tmp + os.pathsep + os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
            for listed, want in (("1", True), ("0", False)):
                with open(os.path.join(tmp, "gh.cmd"), "w") as f:
                    f.write(f"@echo {listed}\n")
                r = relay.gh(["pr", "list", "--head", "topic"], cwd=tmp)
                self.assertEqual(r.stdout.strip() == "1", want, listed)
            # cmd.exe reads a .cmd wrapper's arguments again: a branch named x&... must run no second command
            mark = os.path.join(tmp, "ran.txt")
            for name in ("x&echo.>ran.txt", "x|echo.>ran.txt"):     # no space, so no quotes guard it
                r = relay.gh(["pr", "list", "--head", name], cwd=tmp)
                self.assertFalse(os.path.exists(mark), name)
                self.assertEqual(r.returncode, 1)
                self.assertIn("'&'" if "&" in name else "'|'", r.stderr, "the refusal names what cmd.exe would act on")
            # a comment's body, with lines and parentheses, reaches the wrapper whole as a --body-file
            with open(os.path.join(tmp, "gh.cmd"), "w") as f:
                f.write('@copy /y %7 "%~dp0got.md" >nul\n@echo ok\n')
            body = "p4-phi re-ran it: **passed** (exit code 0).\n\n```\nRan 3 tests\nOK & done | (all)\n```"
            r = relay.gh(["issue", "comment", "7", "-R", "o/r", "--body", body], cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(tmp, "got.md"), encoding="utf-8") as f:
                self.assertEqual(f.read(), body)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)


class GhSetting(unittest.TestCase):
    """P4_PHI_GH names the gh every p4-phi call runs."""

    def test_gh_runs_the_gh_p4_phi_gh_names(self):
        tmp = tempfile.mkdtemp(prefix="p4-phi-ghset-")
        stand_in = os.path.join(tmp, "gh_stand_in.py")
        with open(stand_in, "w", encoding="utf-8") as f:
            f.write("print(1)" + chr(10))
        old = {k: os.environ.get(k) for k in ("PATH", "P4_PHI_GH")}
        try:
            os.environ["PATH"] = tmp                         # no gh on PATH
            os.environ["P4_PHI_GH"] = stand_in
            self.assertEqual(relay.gh(["pr", "list", "--head", "topic"], cwd=tmp).stdout.strip(), "1")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)


class SharedHome(unittest.TestCase):
    """Two projects naming one store as `phi.home`: a session in one hears a session in the other."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self.home = Tree(os.path.join(base, "home"))
        self.a = Tree(os.path.join(base, "a"))
        self.b = Tree(os.path.join(base, "b"))
        for t in (self.home, self.a, self.b):
            subprocess.run(["git", "-C", t.p4, "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.home.p4, "remote", "add", "origin", "https://example.com/team/home.git"],
                       check=True, capture_output=True)
        self.stores = os.path.join(base, "p4-stores.json")
        for t in (self.home, self.a, self.b):
            t.stores = self.stores
        write(os.path.join(self.home.p4, "p4.json"), json.dumps({"phi": {"home": "https://example.com/team/home.git"}}))
        self.home.record(TOP, title="the home")
        self.assertEqual(self.home.hook("session-start", TOP, {"source": "startup"},
                                        P4_PHI_STORES=self.stores).returncode, 0)
        self.assertEqual(json.load(open(self.stores, encoding="utf-8")),
                         {"example.com/team/home": self.home.p4}, "the start keeps this machine's folder for the remote")
        for t in (self.a, self.b):
            write(os.path.join(t.p4, "p4.json"), json.dumps({"phi": {"home": "git@example.com:team/home.git"}}))
        self.a.record(A, title="the tree in repo a")
        self.b.record(B, title="the tree in repo b")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_deprecation_in_one_repo_reaches_a_session_in_the_other(self):
        a, b = self.a, self.b
        a.say(A, "Rework the exporter", P4_PHI_STORES=self.stores)
        b.say(B, "Port the exporter docs", P4_PHI_STORES=self.stores)
        self.assertTrue(os.path.isdir(os.path.join(self.home.p4, "phi", "sessions", A)), "a's tree is in the home")
        self.assertFalse(os.path.isdir(os.path.join(a.p4, "phi", "sessions", A)))
        r = inproc.run([sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "note",
                        "deprecates: the exporter's v1 table, for both repositories", "--source", "commit iii999"],
                       capture_output=True, text=True, env={**a.env(A), "P4_PHI_STORES": self.stores}, cwd=a.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        a.stop(A, "deprecate v1", uuid="a1", P4_PHI_STORES=self.stores)
        ctx = context(b.say(B, "next", P4_PHI_STORES=self.stores))
        self.assertIn("deprecates: the exporter's v1 table", ctx)
        self.assertIn("; source: commit iii999", ctx)

    def test_no_map_is_written_by_a_store_that_names_no_home(self):
        other = Tree(os.path.join(self._tmp.name, "plain"))
        subprocess.run(["git", "-C", other.p4, "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", other.p4, "remote", "add", "origin", "https://example.com/team/plain.git"],
                       check=True, capture_output=True)
        other.record(TOP, title="plain")
        other.hook("session-start", TOP, {"source": "startup"}, P4_PHI_STORES=self.stores)
        self.assertNotIn("example.com/team/plain", json.load(open(self.stores, encoding="utf-8")))

    def test_a_home_this_machine_has_not_seen_is_said_once_and_the_tree_stays_home(self):
        a = self.a
        write(os.path.join(a.p4, "p4.json"), json.dumps({"phi": {"home": "git@example.com:team/elsewhere.git"}}))
        ctx = context(a.hook("session-start", A, {"source": "startup"}, P4_PHI_STORES=self.stores))
        self.assertIn("names the shared store git@example.com:team/elsewhere.git for the session tree, and this "
                      "machine has not seen it", ctx)
        a.say(A, "Rework the exporter", P4_PHI_STORES=self.stores)
        self.assertTrue(os.path.isdir(os.path.join(a.p4, "phi", "sessions", A)), "the tree stays in its own store")


class WarnTogether(unittest.TestCase):
    def test_concurrent_warnings_keep_every_one(self):
        import threading
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            gate = threading.Barrier(12)

            def one(k):
                gate.wait()
                relay.warn(home, top, f"key{k}", f"warning number {k}")
            runs = [threading.Thread(target=one, args=(k,)) for k in range(12)]
            for r in runs:
                r.start()
            for r in runs:
                r.join()
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(len(pend), 12, "no warning is lost to another's write")
            self.assertFalse(os.path.exists(path + ".lock"))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_record_that_reads_empty_keeps_the_warning_for_later(self):
        """A warning that meets a record reading empty, as while another writer's os.replace is under way on Windows,
        is kept on a file of its own and taken in at the next locked write."""
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        read = relay._read_json
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            relay._read_json = lambda p: {} if p == path else read(p)
            self.assertTrue(relay.warn(home, top, "key1", "met an empty read"), "kept, not dropped")
            relay._read_json = read
            self.assertEqual(len(glob.glob(os.path.join(relay._dir(home, top), "warn-pending-*.json"))), 1)
            relay.warn(home, top, "key2", "written under the lock")
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(sorted(w["text"] for w in pend), ["met an empty read", "written under the lock"])
        finally:
            relay._read_json = read
            shutil.rmtree(home, ignore_errors=True)

    def test_another_write_of_the_record_never_drops_a_waiting_warning(self):
        """No other write of the record drops a waiting warning, however old the copy it writes, from phi.save_session
        or a plain write alike."""
        import threading
        import phi
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            stale = relay._read_json(path)                 # a copy a hook read before the warning came
            relay.warn(home, top, "key0", "came while a hook held an older copy")
            relay._write_json(path, {**stale, "stepRelayed": "1 x"})
            self.assertEqual(len(relay._read_json(path)["relayPending"]), 1, "a plain write keeps it")
            gate = threading.Barrier(16)

            def warns(k):
                gate.wait()
                relay.warn(home, top, f"key{k}", f"warning number {k}")

            def saves(k):
                gate.wait()
                phi.save_session(home, {**stale, "nudged": [str(k)]})
                relay._write_json(path, {**stale, "keptGoing": {"turn": str(k), "n": 1}})
            runs = [threading.Thread(target=warns if k % 2 else saves, args=(k,)) for k in range(1, 17)]
            for r in runs:
                r.start()
            for r in runs:
                r.join()
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(len(pend), 9, "the eight warnings and the first, through eight saves and eight writes")
            self.assertFalse(os.path.exists(path + ".lock"))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_lock_given_up_on_after_permission_errors_is_remembered(self):
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        real, wait = os.open, relay.LOCK_WAIT_S
        try:
            path = os.path.join(home, "session.json")

            def never(p, *a, **k):
                if str(p).endswith(".lock"):
                    raise PermissionError(13, "Permission denied", p)
                return real(p, *a, **k)
            os.open, relay.LOCK_WAIT_S = never, 0.05
            with relay.locked(path) as lk:
                self.assertFalse(lk.held)
            self.assertIn(path + ".lock", relay._GAVE_UP)
        finally:
            os.open, relay.LOCK_WAIT_S = real, wait
            relay._GAVE_UP.pop(os.path.join(home, "session.json") + ".lock", None)
            shutil.rmtree(home, ignore_errors=True)

    def test_a_permission_error_on_the_lock_is_waited_out(self):
        """Windows raises PermissionError creating a lock file another thread is removing: the lock is tried again
        within LOCK_WAIT_S, and the warning lands on the record under the lock."""
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        real = os.open
        hits = []
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})

            def once(p, *a, **k):
                if str(p).endswith("session.json.lock") and not hits:
                    hits.append(p)
                    raise PermissionError(13, "Permission denied", p)
                return real(p, *a, **k)
            os.open = once
            relay.warn(home, top, "key1", "after one PermissionError")
            os.open = real
            self.assertTrue(hits, "the lock met a PermissionError")
            on = [w["text"] for w in relay._read_json(path).get("relayPending") or []]
            self.assertEqual(on, ["after one PermissionError"])
            self.assertEqual(glob.glob(os.path.join(relay._dir(home, top), "warn-pending-*.json")), [])
        finally:
            os.open = real
            shutil.rmtree(home, ignore_errors=True)

    def test_a_child_counted_as_archived_meets_an_empty_read_and_is_kept(self):
        """A parent's record that reads empty under its lock, as while another writer's os.replace runs on Windows,
        drops no child counted as archived: the child is kept on a file of its own."""
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        read = relay._read_json
        try:
            path = os.path.join(relay._dir(home, "top"), "session.json")
            relay._write_json(path, {"sessionId": "top"})
            relay._read_json = lambda p: {} if p == path else read(p)
            relay._pend_archive(home, "top", "kid1", {"title": "kid one"}, "done")
            relay._read_json = read
            self.assertEqual([x["id"] for x in relay.drain_archive(home, "top")], ["kid1"])
        finally:
            relay._read_json = read
            shutil.rmtree(home, ignore_errors=True)

    def test_a_warning_that_cannot_get_the_lock_is_kept_and_drained(self):
        home = tempfile.mkdtemp(prefix="p4-phi-warn-")
        wait = relay.LOCK_WAIT_S
        try:
            top = "local_topwarn"
            path = os.path.join(relay._dir(home, top), "session.json")
            relay._write_json(path, {"sessionId": top})
            relay.LOCK_WAIT_S = 0.05
            with relay.locked(path):
                self.assertTrue(relay.warn(home, top, "key1", "held back"))
                self.assertFalse(relay._read_json(path).get("relayPending"), "never written unlocked")
            relay.warn(home, top, "key2", "written under the lock")
            pend = relay._read_json(path).get("relayPending")
            self.assertEqual(sorted(w["text"] for w in pend), ["held back", "written under the lock"])
            self.assertEqual(glob.glob(os.path.join(relay._dir(home, top), "warn-pending-*.json")), [])
        finally:
            relay.LOCK_WAIT_S = wait
            shutil.rmtree(home, ignore_errors=True)


class Nodes(unittest.TestCase):
    """A node's folder in phi/tree: tree_of, nodes, claim, unclaim, migrate_nested, and _dir and _sessions through
    them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "proj", ".claude", "p4")
        os.makedirs(os.path.join(self.home, "phi"))

    def same(self, a, b):
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

    def tree(self, *parts):
        return os.path.join(self.home, "phi", relay.TREE, *parts)

    def test_a_session_and_two_workers_under_it_are_folders_nested_by_parent_with_places_1_1_2(self):
        s = relay.claim(self.home, "sid", "session", "top")
        w1 = relay.claim(self.home, "w1", "worker", "sid", ["1"])
        w2 = relay.claim(self.home, "w2", "worker", "sid", ["2"])
        self.assertEqual((s, w1, w2), (self.tree("sid"), self.tree("sid", "w1"), self.tree("sid", "w2")))
        self.assertEqual(relay.nodes(self.home), {"sid": s, "w1": w1, "w2": w2})
        self.assertEqual([relay.node_record(self.home, k)["place"] for k in ("sid", "w1", "w2")], [1, 1, 2])
        for folder in (s, w1, w2):
            self.assertTrue(os.path.isfile(os.path.join(folder, relay.NODE)))
        self.assertEqual(os.listdir(w1), [relay.NODE], "a node's folder holds its files and nothing else")
        self.assertEqual(relay.claim(self.home, "w1", "worker", "sid"), w1, "one folder for an id asked twice")
        n = relay.node_record(self.home, "w1")
        self.assertEqual((n["id"], n["kind"], n["parent"], n["sections"]), ("w1", "worker", "sid", ["1"]))

    def test_a_node_whose_parent_is_no_node_sits_at_the_top_and_the_chain_holds_each_ancestor_that_is_one(self):
        a = relay.claim(self.home, "a", "worker", "outside")
        self.assertEqual(a, self.tree("a"))
        b = relay.claim(self.home, "b", "session", "a")
        c = relay.claim(self.home, "c", "worker", "b")
        self.assertEqual((b, c), (self.tree("a", "b"), self.tree("a", "b", "c")))
        self.assertEqual(relay.tree_of(self.home, "d", "c"), self.tree("a", "b", "c", "d"))
        self.assertEqual(relay.tree_of(self.home, "d", "nobody"), self.tree("d"))

    def test_a_folder_that_holds_only_folders_is_a_container_and_no_node(self):
        os.makedirs(self.tree("box", "inner"))
        write(os.path.join(self.tree("box", "inner"), relay.NODE), json.dumps({"id": "kid"}))
        os.makedirs(self.tree("work", "x.tmp-1-abcdef12"))
        write(os.path.join(self.tree("work", "x.tmp-1-abcdef12"), relay.NODE), json.dumps({"id": "half"}))
        relay.forget(self.home)
        self.assertEqual(relay.nodes(self.home), {"kid": self.tree("box", "inner")},
                         "a container is no node, and a folder a claim is still making is passed over")

    def test_a_claim_whose_write_fails_leaves_no_folder_and_the_next_claim_gets_place_1(self):
        with mock.patch.object(relay, "_write_raw", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                relay.claim(self.home, "kid", "session", "top")
        self.assertFalse(os.path.isdir(self.tree("kid")) or glob.glob(self.tree("*")), "no folder and no temporary one")
        self.assertEqual(relay.nodes(self.home), {})
        self.assertEqual(relay.claim(self.home, "kid", "session", "top"), self.tree("kid"))
        self.assertEqual(relay.node_record(self.home, "kid")["place"], 1)

    def test_a_claim_another_process_makes_right_after_a_walk_is_seen(self):
        self.assertEqual(relay.nodes(self.home), {})
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import relay; "
                "print(relay.claim(sys.argv[2], sys.argv[3], 'session', sys.argv[4]))")
        made = subprocess.run([sys.executable, "-I", "-c", code, SRC, self.home, "kid", "top"], capture_output=True,
                              text=True, timeout=60).stdout.strip()
        self.assertEqual(relay.nodes(self.home), {"kid": made}, "no forget() needed")
        grand = subprocess.run([sys.executable, "-I", "-c", code, SRC, self.home, "g", "kid"], capture_output=True,
                               text=True, timeout=60).stdout.strip()
        self.assertEqual(relay.nodes(self.home).get("g"), grand, "a claim under a node's folder too")
        self.assertEqual(grand, self.tree("kid", "g"))

    def test_track_stages_the_tree_and_no_other_file_under_claude(self):
        for args in (("init", "-q"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                                       "-m", "store")):
            subprocess.run(["git", "-C", self.home, *args], check=True, capture_output=True)
        write(os.path.join(self.home, "p4.json"), json.dumps({"phi": {"track": True}}))
        write(os.path.join(self.home, "phi", "sessions", "top", "session.json"), json.dumps({"sessionId": "top"}))
        folder = relay.claim(self.home, "kid", "session", "top")
        write(os.path.join(folder, "session.json"), json.dumps({"sessionId": "kid"}))
        write(os.path.join(folder, "log.jsonl"), "{}\n")
        write(os.path.join(self.home, ".claude", "settings.local.json"), "{}")
        self.assertTrue(relay.track(self.home, first_only=True, wait=True))
        shown = subprocess.run(["git", "-C", self.home, "show", "--name-only", "--format=", "HEAD"],
                               capture_output=True, text=True).stdout.split()
        self.assertIn("phi/tree/kid/session.json", shown)
        self.assertIn("phi/tree/kid/node.json", shown)
        self.assertFalse([x for x in shown if x.endswith(("settings.local.json", "log.jsonl"))], shown)

    def test_dir_is_the_nodes_folder_for_a_claimed_id_and_the_flat_one_for_any_other(self):
        folder = relay.claim(self.home, "kid", "session", "top")
        self.assertTrue(self.same(relay._dir(self.home, "kid"), folder))
        self.assertTrue(self.same(relay._dir(self.home, "top"), os.path.join(self.home, "phi", "sessions", "top")))
        self.assertTrue(self.same(relay._dir(self.home, "top"), relay.flat(self.home, "top")))

    def test_sessions_and_session_dirs_hold_a_flat_session_and_each_session_node_and_no_worker(self):
        write(os.path.join(self.home, "phi", "sessions", "top", "session.json"), json.dumps({"sessionId": "top"}))
        folder = relay.claim(self.home, "kid", "session", "top")
        write(os.path.join(folder, "session.json"),
              json.dumps({"sessionId": "kid", "spawnedFrom": {"sessionId": "top"}}))
        w = relay.claim(self.home, "w1", "worker", "kid", ["1"])
        self.assertEqual(sorted(relay._sessions(self.home)), ["kid", "top"])
        self.assertEqual(relay.session_dirs(self.home), [relay.flat(self.home, "top"), folder])
        self.assertNotIn(w, relay.session_dirs(self.home))

    def test_the_cache_sees_a_folder_added_under_the_tree_by_another_process(self):
        folder = relay.claim(self.home, "kid", "session", "top")
        self.assertEqual(sorted(relay.nodes(self.home)), ["kid"])
        os.makedirs(os.path.join(folder, "w9"))
        write(os.path.join(folder, "w9", relay.NODE), json.dumps({"id": "w9", "parent": "kid"}))
        self.assertEqual(sorted(relay.nodes(self.home)), ["kid", "w9"], "no forget() needed")

    def test_two_processes_that_claim_at_once_get_two_folders_for_two_ids_and_one_for_one(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import relay; "
                "print(relay.claim(sys.argv[2], sys.argv[3], 'session', 'top'))")

        def at_once(*ids):
            procs = [subprocess.Popen([sys.executable, "-I", "-c", code, SRC, self.home, i], stdout=subprocess.PIPE,
                                      text=True) for i in ids]
            return [p.communicate(timeout=60)[0].strip() for p in procs]
        two = at_once("a", "b")
        self.assertEqual(set(two), {self.tree("a"), self.tree("b")})
        one = at_once("c", "c")
        self.assertEqual(one[0], one[1])
        relay.forget(self.home)
        self.assertEqual(sorted(relay.nodes(self.home)), ["a", "b", "c"])
        self.assertEqual(sorted(relay.node_record(self.home, k)["place"] for k in "abc"), [1, 2, 3])

    def test_two_claims_for_one_id_with_the_lock_given_up_both_return_the_first_folder(self):
        first = relay.claim(self.home, "kid", "session", "top")
        real = relay.nodes
        asked = []

        def blind(home):                       # the second caller looked before the first wrote its node.json
            asked.append(home)
            return {} if len(asked) == 1 else real(home)
        with mock.patch.object(relay, "nodes", blind):
            second = relay.claim(self.home, "kid", "session", "top")
        self.assertEqual(second, first)
        self.assertEqual(os.listdir(first), [relay.NODE])

    def test_claim_makes_nothing_where_the_folders_path_would_pass_180_characters(self):
        above, made = "top", []
        for k in range(12):
            ident = f"n{k}" + "x" * 30
            got = relay.claim(self.home, ident, "session", above)
            if not got:
                break
            made.append(ident)
            above = ident
            self.assertLessEqual(len(os.path.abspath(got)), relay.NODE_PATH_MAX)
        self.assertLess(len(made), 12, "a chain deep enough is refused")
        self.assertEqual(relay.claim(self.home, "z" * 80, "session", above), "")
        self.assertEqual(sorted(relay.nodes(self.home)), sorted(made), "nothing is made")

    def test_unclaim_removes_a_fresh_folder_and_each_container_it_leaves_empty_and_no_other(self):
        os.makedirs(self.tree("box", "inner"))
        write(os.path.join(self.tree("box", "inner"), relay.NODE), json.dumps({"id": "fresh", "parent": ""}))
        relay.forget(self.home)
        self.assertTrue(relay.unclaim(self.home, "fresh"))
        self.assertFalse(os.path.exists(self.tree("box")), "the container it left empty goes with it")
        self.assertTrue(os.path.isdir(self.tree()) or not os.path.exists(self.tree()))
        s = relay.claim(self.home, "sid", "session", "top")
        w = relay.claim(self.home, "w", "worker", "sid")
        write(os.path.join(w, "brief-w.md"), "x")
        self.assertFalse(relay.unclaim(self.home, "w"), "a folder that holds a file is kept")
        os.remove(os.path.join(w, "brief-w.md"))
        self.assertTrue(relay.unclaim(self.home, "w"))
        self.assertTrue(os.path.isdir(s), "the parent's folder is a node, not a container")
        self.assertFalse(relay.unclaim(self.home, "nobody"))

    def test_each_ignore_line_of_a_session_folder_has_a_twin_for_the_tree_and_no_line_opens_a_nested_claude(self):
        for lines in (relay.IGNORED, relay.UNTRACKED):
            for k, x in enumerate(lines):
                if x.startswith("phi/sessions/*/"):
                    self.assertEqual(lines[k + 1], "phi/tree/**/" + x[len("phi/sessions/*/"):])
                elif x == "phi/sessions/":
                    self.assertEqual(lines[k + 1], "phi/tree/")
        self.assertIn("phi/tree/**/log.jsonl", relay.IGNORED)
        self.assertIn("phi/tree/", relay.UNTRACKED)
        self.assertFalse([x for x in relay.IGNORED + relay.UNTRACKED + relay.ATTRS if ".claude" in x])
        self.assertEqual(relay.ATTRS, ("phi/** filter=p4path", "phi/archive/** -filter"))
        self.assertEqual(relay._tracked(self.home), ["phi"])


class Migration(unittest.TestCase):
    """relay.migrate_nested: the old nested stores, of both layouts, moved into phi/tree once."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "proj", ".claude", "p4")
        os.makedirs(os.path.join(self.home, "phi"))
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("P4_PHI_MIGRATE", None)

    def old(self, store, ident, kind, parent, time="2026-11-24 10:00"):
        write(os.path.join(store, "phi", relay.NODE),
              json.dumps({"id": ident, "kind": kind, "parent": parent, "sections": [], "time": time}))

    def made(self):
        """A session node `sid` under a top session, in the first-place store of the new layout, with two workers
        in its own, one of each layout."""
        one = os.path.join(self.home, ".claude", "p4")
        self.old(one, "sid", "session", "top")
        write(os.path.join(one, "phi", "sessions", "sid", "session.json"), json.dumps({"sessionId": "sid"}))
        write(os.path.join(one, "phi", "sessions", "sid", "turns.jsonl"), "{}\n")
        w1 = os.path.join(one, ".claude", "p4")                                 # the first child: `.claude/p4`
        w2 = os.path.join(one, ".claude", "2", ".claude", "p4")                 # the second: `.claude/2/.claude/p4`
        for store, name, time in ((w1, "w1", "2026-11-24 10:01"), (w2, "w2", "2026-11-24 10:02")):
            self.old(store, name, "worker", "sid", time)
            for f in (f"brief-{name}.md", f"log-{name}.jsonl", f"report-{name}.md"):
                write(os.path.join(store, "phi", f), f)

    def test_the_old_stores_move_into_the_tree_at_the_first_read_with_every_file_and_the_walk_is_gone(self):
        self.made()
        self.assertEqual(relay.nodes(self.home), {"sid": os.path.join(self.home, "phi", "tree", "sid"),
                                                  "w1": os.path.join(self.home, "phi", "tree", "sid", "w1"),
                                                  "w2": os.path.join(self.home, "phi", "tree", "sid", "w2")})
        tree = os.path.join(self.home, "phi", "tree", "sid")
        self.assertEqual(sorted(os.listdir(tree)), ["node.json", "session.json", "turns.jsonl", "w1", "w2"])
        for name in ("w1", "w2"):
            self.assertEqual(sorted(os.listdir(os.path.join(tree, name))),
                             sorted([relay.NODE, f"brief-{name}.md", f"log-{name}.jsonl", f"report-{name}.md"]))
        with open(os.path.join(tree, "w2", "report-w2.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "report-w2.md")
        self.assertEqual([relay.node_record(self.home, k)["place"] for k in ("sid", "w1", "w2")], [1, 1, 2])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")), "the old walk is removed")
        import node
        # child("101", 1) is "10101" and child("101", 2) "101001", by node.py's rule that no address holds "11"
        self.assertEqual([node.address_of(self.home, k) for k in ("sid", "w1", "w2")], ["101", "10101", "101001"])

    def test_the_old_one_i_claude_layout_is_moved_too_and_a_second_read_changes_nothing(self):
        a = os.path.join(self.home, ".claude", "p4")
        b = os.path.join(self.home, ".claude", ".claude", "p4")
        self.old(a, "a", "session", "top", "2026-11-24 09:00")
        self.old(b, "b", "session", "top", "2026-11-24 09:30")
        self.assertEqual(sorted(relay.nodes(self.home)), ["a", "b"])
        self.assertEqual([relay.node_record(self.home, k)["place"] for k in "ab"], [1, 2], "by their time")
        before = sorted(os.path.join(at, n) for at, ds, fs in os.walk(self.home) for n in ds + fs)
        self.assertFalse(relay.migrate_nested(self.home), "a second run finds nothing")
        relay.forget(self.home)
        self.assertEqual(sorted(relay.nodes(self.home)), ["a", "b"])
        self.assertEqual(before, sorted(os.path.join(at, n) for at, ds, fs in os.walk(self.home) for n in ds + fs))

    def test_a_file_the_tree_folder_holds_is_kept_and_the_old_one_dropped_and_a_late_file_comes_in_later(self):
        store = os.path.join(self.home, ".claude", "p4")
        self.old(store, "w", "worker", "top")
        write(os.path.join(store, "phi", "report-w.md"), "old")
        write(os.path.join(self.home, "phi", "tree", "w", "report-w.md"), "new")
        self.assertEqual(sorted(relay.nodes(self.home)), ["w"])
        with open(os.path.join(self.home, "phi", "tree", "w", "report-w.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")
        late = os.path.join(self.home, ".claude", "p4", "phi")      # a worker mid-run wrote on at its old path
        write(os.path.join(late, "log-w.jsonl"), "late")
        self.old(os.path.join(self.home, ".claude", "p4"), "w", "worker", "top")
        self.assertTrue(relay.migrate_nested(self.home))
        self.assertTrue(os.path.isfile(os.path.join(self.home, "phi", "tree", "w", "log-w.jsonl")))

    def test_nothing_is_moved_where_the_environment_holds_p4_phi_migrate_0(self):
        self.made()
        os.environ["P4_PHI_MIGRATE"] = "0"
        self.assertFalse(relay.migrate_nested(self.home))
        relay.forget(self.home)
        self.assertEqual(relay.nodes(self.home), {}, "the old stores are not read, and not moved")
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".claude", "p4", "phi", relay.NODE)))
        self.assertEqual(relay.claim(self.home, "new", "session", "top"), os.path.join(self.home, "phi", "tree", "new"))
        self.assertTrue(os.path.isdir(os.path.join(self.home, ".claude")))
        del os.environ["P4_PHI_MIGRATE"]
        relay.forget(self.home)
        self.assertEqual(sorted(relay.nodes(self.home)), ["new", "sid", "w1", "w2"], "moved at the next read")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))


class Partition(unittest.TestCase):
    """A session's paths and who holds a path: paths_of, above, holders, running_children, set_shard and mark_paths,
    on session records written into a store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.join(self._tmp.name, "proj")
        self.home = os.path.join(self.base, ".claude", "p4")
        os.makedirs(os.path.join(self.home, "phi", "sessions"))

    def put(self, sid, above="", **more):
        s = {"sessionId": sid, "title": "title of " + sid, "cwd": self.base,
             **({"spawnedFrom": {"sessionId": above}} if above else {}), **more}
        write(os.path.join(self.home, "phi", "sessions", sid, "session.json"), json.dumps(s))
        relay.forget(self.home)
        return s

    def x(self, *parts):
        return relay.norm(os.path.join(self.base, *parts))

    def test_paths_of_gives_shard_else_fileset_else_nothing(self):
        self.assertEqual(relay.paths_of({"shard": ["a/"], "fileSet": ["b/"]}), ["a/"])
        self.assertEqual(relay.paths_of({"fileSet": ["b/", 3, ""]}), ["b/"])
        self.assertEqual(relay.paths_of({"shard": [], "fileSet": ["b/"]}), ["b/"])
        self.assertEqual(relay.paths_of({}), [])
        self.assertEqual(relay.paths_of(None), [])

    def test_above_gives_the_chain_nearest_first_and_ends_on_a_loop_or_a_parent_with_no_record(self):
        self.put("top")
        self.put("mid", "top")
        self.put("leaf", "mid")
        self.assertEqual(relay.above(self.home, "leaf"), ["mid", "top"])
        self.assertEqual(relay.above(self.home, "top"), [])
        self.put("orphan", "missing")
        self.assertEqual(relay.above(self.home, "orphan"), ["missing"])
        self.put("p", "q")
        self.put("q", "p")
        self.assertEqual(relay.above(self.home, "p"), ["q"], "a loop is cut where an id comes twice")

    def test_holders_names_a_running_sibling_whose_glob_overlaps_and_no_other_session(self):
        self.put("top")
        self.put("me", "top", fileSet=[self.x("lib", "x.py")])
        self.put("sib", "top", fileSet=[self.x("lib", "**")])
        self.put("far", "other", fileSet=[self.x("lib")])
        self.put("quiet", "top")
        self.put("elsewhere", "top", fileSet=[self.x("docs")])
        self.put("done", "top", fileSet=[self.x("lib")], archived=True)
        self.put("othertop", "", fileSet=[self.x("lib")])
        self.put("below", "me", fileSet=[self.x("lib", "x.py")])
        self.put("top2", fileSet=[self.x("lib")])
        got = {h[0] for h in relay.holders(self.home, "me", [self.x("lib", "x.py")], self.base)}
        self.assertEqual(got, {"sib", "far", "othertop", "top2"}, "none above, below, gone or with no paths")
        self.assertEqual({h[0] for h in relay.holders(self.home, "", [self.x("docs")], self.base)}, {"elsewhere"},
                         "with no id, a session about to be started")

    def test_running_children_are_the_live_children_that_hold_paths(self):
        self.put("top")
        self.put("a", "top", fileSet=["a/"])
        self.put("b", "top")
        self.put("c", "top", fileSet=["c/"], archived=True)
        self.put("d", "a", fileSet=["d/"])
        self.assertEqual([k for k, _ in relay.running_children(self.home, "top")], ["a"])

    def test_set_shard_refuses_a_path_a_running_sibling_holds_and_one_outside_its_parents_and_takes_one_inside(self):
        self.put("top", shard=[self.x("lib"), self.x("docs")])
        self.put("sib", "top", shard=[self.x("lib", "a.py")])
        self.put("me", "top")
        with self.assertRaises(ValueError) as held:
            relay.set_shard(self.home, "me", [self.x("lib", "a.py")], self.base)
        self.assertIn("held", str(held.exception))
        self.assertIn("sib", str(held.exception))
        with self.assertRaises(ValueError) as outside:
            relay.set_shard(self.home, "me", [self.x("src")], self.base)
        self.assertIn("outside", str(outside.exception))
        relay.set_shard(self.home, "me", [self.x("docs", "a.md")], self.base)
        relay.forget(self.home)
        self.assertEqual(relay.shard_of(relay._session(self.home, "me")), [self.x("docs", "a.md")])

    def test_mark_paths_makes_the_marker_while_a_live_session_holds_paths_and_removes_it_once_none_does(self):
        marker = os.path.join(self.home, *relay.PATHS_ON.split("/"))
        self.put("top")
        relay.mark_paths(self.home, self.home)
        self.assertFalse(os.path.exists(marker))
        self.put("kid", "top", fileSet=["a/"])
        relay.mark_paths(self.home, self.home)
        self.assertTrue(os.path.exists(marker))
        self.put("kid", "top", fileSet=["a/"], archived=True)
        relay.mark_paths(self.home, self.home)
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main(verbosity=1)
