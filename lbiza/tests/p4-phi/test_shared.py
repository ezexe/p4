"""shared.py: what a worktree's session takes from its main checkout, and the links a worktree holds."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import p4conf  # noqa: E402
import shared  # noqa: E402
import phi  # noqa: E402


def link(at, target):
    """A junction on Windows, which needs no privilege, and a symbolic link elsewhere."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", at, target], check=True, capture_output=True)
    else:
        os.symlink(target, at, target_is_directory=True)


class Shared(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.main = os.path.join(os.path.realpath(tmp.name), "main")
        self.tree = os.path.join(os.path.realpath(tmp.name), "tree")
        gitdir = os.path.join(self.main, ".git", "worktrees", "tree")
        os.makedirs(gitdir)
        os.makedirs(os.path.join(self.tree, "src"))
        with open(os.path.join(gitdir, "commondir"), "w", encoding="utf-8") as f:
            f.write("../..\n")
        with open(os.path.join(self.tree, ".git"), "w", encoding="utf-8") as f:
            f.write("gitdir: " + gitdir + "\n")
        self.p4 = os.path.join(self.main, ".claude", "p4")
        os.makedirs(self.p4)
        self.py = os.path.join(self.main, ".venv", "python.exe")
        os.makedirs(os.path.dirname(self.py))
        open(self.py, "w").close()

    def conf(self, **phi):
        with open(p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"phi": phi}, f)

    def test_a_project_with_neither_key_has_no_line(self):
        self.assertEqual(shared.lines(self.tree), [])
        self.assertEqual(shared.start_text(self.tree), "")

    def test_a_worktree_is_handed_the_main_checkouts_interpreter_by_its_full_path(self):
        self.conf(worktree_python=".venv/python.exe", worktree_lines=["Fill `node_modules` from {main}/cache."])
        got = shared.lines(os.path.join(self.tree, "src"))
        self.assertEqual(len(got), 2)
        self.assertIn("`" + self.py.replace("\\", "/") + "`", got[0])
        self.assertIn("build no environment here", got[0])
        self.assertEqual(got[1], "Fill `node_modules` from " + self.main.replace("\\", "/") + "/cache.")
        self.assertEqual(shared.start_text(self.tree), "\n".join(got))
        self.assertEqual(shared.start_text(self.main), "", "a main checkout's session is told nothing")
        self.assertEqual(shared.lines(self.main), got, "a brief drafted in the main checkout carries them")

    def test_an_interpreter_that_is_not_on_disk_is_never_named(self):
        self.conf(worktree_python=".venv/absent.exe", worktree_lines="not a list")
        self.assertEqual(shared.lines(self.tree), [])

    def test_a_link_is_found_and_taken_away_and_its_target_is_left(self):
        target = os.path.join(self.main, "node_modules")
        os.makedirs(target)
        kept = os.path.join(target, "keep.txt")
        open(kept, "w").close()
        at = os.path.join(self.tree, "node_modules")
        link(at, target)
        os.makedirs(os.path.join(self.tree, "build"))
        status = "!! node_modules/\n!! build/\n M src/a.py\n"
        self.assertEqual(shared.links(self.tree, status), [at.replace("\\", "/")])
        self.assertFalse(shared.is_link(target))
        self.assertFalse(shared.unlink(os.path.join(self.tree, "build")), "a real folder is never taken")
        self.assertTrue(shared.unlink(at))
        self.assertFalse(os.path.lexists(at))
        self.assertTrue(os.path.isfile(kept), "what the link pointed at is whole")

    def test_a_session_that_starts_in_a_worktree_is_told_and_one_in_the_main_checkout_is_not(self):
        self.conf(worktree_python=".venv/python.exe")
        got = phi.share_notice({"cwd": os.path.join(self.tree, "src")})
        self.assertTrue(got.startswith("phi (p4-phi): this session's folder is a git worktree. "), got)
        self.assertIn("build no environment here", got)
        self.assertEqual(phi.share_notice({"cwd": self.main}), "")
        self.assertEqual(phi.share_notice({}), "")


class Commands(unittest.TestCase):
    """`phi.py shared` and `phi.py unlink`, on a real repository and a real worktree of it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = os.path.realpath(tmp.name)
        self.main, self.tree, self.target = (os.path.join(root, n) for n in ("main", "tree", "target"))
        os.makedirs(self.target)
        self.kept = os.path.join(self.target, "keep.txt")
        open(self.kept, "w").close()
        for args in (["init", "-q", self.main],
                     ["-C", self.main, "-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c",
                      "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "first"],
                     ["-C", self.main, "worktree", "add", "-q", self.tree, "-b", "work"]):
            subprocess.run(["git", *args], check=True, capture_output=True)
        with open(os.path.join(self.main, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("node_modules\n")
        self.at = os.path.join(self.tree, "node_modules")
        link(self.at, self.target)

    def run_phi(self, *argv):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = phi.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_shared_needs_no_store_and_says_so_where_nothing_is_named(self):
        code, out, _ = self.run_phi("shared", self.tree)
        self.assertEqual((code, out.strip()), (0, shared.NONE))

    def test_unlink_refuses_a_main_checkout_and_a_subfolder(self):
        os.makedirs(os.path.join(self.tree, "src"))
        for folder in (self.main, os.path.join(self.tree, "src")):
            code, _, err = self.run_phi("unlink", folder)
            self.assertEqual(code, 2, folder)
            self.assertIn("not the top folder of a linked worktree", err)
        self.assertTrue(os.path.lexists(self.at))

    def test_unlink_takes_the_link_away_leaves_its_target_and_prints_the_removal(self):
        code, out, _ = self.run_phi("unlink", self.tree)
        self.assertEqual(code, 0)
        self.assertIn("unlinked ", out)
        self.assertIn("worktree remove", out)
        self.assertNotIn("--force", out)
        self.assertFalse(os.path.lexists(self.at))
        self.assertTrue(os.path.isfile(self.kept), "what the link pointed at is whole")


if __name__ == "__main__":
    unittest.main()
