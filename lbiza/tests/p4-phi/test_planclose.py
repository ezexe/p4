#!/usr/bin/env python3
"""planclose.py: a plan closes into `plan-planner/complete/` only past the gate of its Evidence and audit.

    python -m pytest tests/p4-phi/test_planclose.py

Each test of check() holds a plan that passes but for the one thing it takes away, read against a git repository
of three commits: `one` and `two` on the line HEAD stands on, and `aside` on a branch HEAD does not contain.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import planclose  # noqa: E402


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, name):
    with open(os.path.join(repo, name), "w", encoding="utf-8") as f:
        f.write(name)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


class Repo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = os.path.join(cls.tmp, "repo")
        os.makedirs(cls.repo)
        git(cls.repo, "init", "-q", "-b", "main")
        git(cls.repo, "config", "user.email", "t@example.com")
        git(cls.repo, "config", "user.name", "t")
        git(cls.repo, "config", "commit.gpgsign", "false")
        cls.base = commit(cls.repo, "base")
        cls.one = commit(cls.repo, "one")
        git(cls.repo, "checkout", "-q", "-b", "side")
        cls.aside = commit(cls.repo, "aside")
        git(cls.repo, "checkout", "-q", "main")
        cls.two = commit(cls.repo, "two")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def plan(self, evidence2=None, audited=None, findings=None, audit=True, title="# The exporter's move"):
        e2 = f"- **Evidence:** writer.py:1-40, by {self.two[:8]}; 12 passed" if evidence2 is None else evidence2
        au = (f"Audited: 2026-11-24: {self.base[:8]}..{self.two[:8]}, code-review and p4-phi:check"
              if audited is None else audited)
        fs = [f"- Finding: the flush drops a row: fixed, {self.two[:8]}",
              "- Finding: the name reads oddly: answered, it is the name the spec gives"] if findings is None \
            else findings
        lines = [title, "", "## Context", "", "No worker lands this.", "",
                 "## 1. The writer", "", "- **Files:** `src/writer.py`", "- **Checks:** `pytest`",
                 f"- **Evidence:** writer.py:1-20, by {self.one[:8]} (ezexe/p4#256, 0.11.175); 3 passed", "",
                 "## 2. The flush", "", "- **Files:** `src/flush.py`", "- **Depends on:** 1"]
        if evidence2 != "":
            lines.append(e2)
        if audit:
            lines += ["", "## Audit", ""] + ([au] if au else []) + fs
        return "\n".join(lines) + "\n"


class Check(Repo):
    def test_a_whole_plan_may_close(self):
        self.assertEqual(planclose.check(self.plan(), self.repo), [])

    def test_a_section_with_no_evidence(self):
        out = planclose.check(self.plan(evidence2=""), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("section 2", out[0])
        self.assertIn("Evidence", out[0])

    def test_no_audited_line(self):
        out = planclose.check(self.plan(audited=""), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("Audited:", out[0])

    def test_no_audit_record(self):
        out = planclose.check(self.plan(audit=False), self.repo)
        self.assertEqual(out, ["the plan holds no `## Audit` record"])

    def test_an_audited_line_with_no_range(self):
        out = planclose.check(self.plan(audited="Audited: 2026-11-24, code-review and p4-phi:check"), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("range", out[0])

    def test_head_missing_an_evidence_sha(self):
        audited = f"Audited: 2026-11-24: {self.base[:8]}..{self.one[:8]}, code-review and p4-phi:check"
        out = planclose.check(self.plan(audited=audited), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn(self.two[:8], out[0])
        self.assertIn("does not contain", out[0])

    def test_an_evidence_sha_that_is_no_commit(self):
        out = planclose.check(self.plan(evidence2="- **Evidence:** by 0badc0de1; 1 passed"), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("0badc0de1", out[0])

    def test_a_head_that_is_no_commit(self):
        audited = f"Audited: 2026-11-24: {self.base[:8]}..0badc0de1, code-review and p4-phi:check"
        out = planclose.check(self.plan(audited=audited), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("head", out[0])

    def test_an_open_finding(self):
        out = planclose.check(self.plan(findings=["- Finding: the flush drops a row: open"]), self.repo)
        self.assertEqual(out, ["the finding `the flush drops a row` is open"])

    def test_a_fixed_sha_not_in_head(self):
        out = planclose.check(self.plan(findings=[f"- Finding: the flush drops a row: fixed, {self.aside[:8]}"]),
                              self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("not in", out[0])
        self.assertIn("HEAD", out[0])

    def test_a_fixed_sha_that_is_no_commit(self):
        out = planclose.check(self.plan(findings=["- Finding: the flush drops a row: fixed, 0badc0de1"]), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("no commit", out[0])

    def test_a_finding_with_no_outcome(self):
        out = planclose.check(self.plan(findings=["- Finding: the flush drops a row"]), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("states no outcome", out[0])

    def test_an_answer_with_no_reason(self):
        out = planclose.check(self.plan(findings=["- Finding: the name: answered"]), self.repo)
        self.assertEqual(out, ["the finding `the name` is answered with no reason"])

    def test_no_finding_line_at_all(self):
        out = planclose.check(self.plan(findings=[]), self.repo)
        self.assertEqual(len(out), 1)
        self.assertIn("Finding: none", out[0])

    def test_finding_none_may_close(self):
        self.assertEqual(planclose.check(self.plan(findings=["- Finding: none"]), self.repo), [])

    def test_an_audit_inside_a_fence_is_no_audit(self):
        text = self.plan(audit=False) + "\n```markdown\n## Audit\n\n- Finding: none\n```\n"
        self.assertEqual(planclose.check(text, self.repo), ["the plan holds no `## Audit` record"])

    def test_every_refusal_is_listed(self):
        out = planclose.check(self.plan(evidence2="", findings=["- Finding: a: open", "- Finding: b: open"]),
                              self.repo)
        self.assertEqual(len(out), 3)


class Close(Repo):
    def setUp(self):
        self.home = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, text, name="plan-mode-name.md"):
        path = os.path.join(self.home, name)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return path

    def test_a_clean_close_writes_status_and_moves_the_file(self):
        path = self.write(self.plan())
        dest = planclose.close(path, self.repo, self.home, today="2026-11-24")
        self.assertEqual(dest, os.path.join(self.home, "complete", "the-exporter-s-move.md"))
        self.assertFalse(os.path.exists(path))
        with open(dest, encoding="utf-8") as f:
            lines = f.read().split("\n")
        self.assertEqual(lines[0], "# The exporter's move")
        self.assertEqual(lines[1], f"STATUS: COMPLETED 2026-11-24: 2 sections; audit {self.base[:8]}..{self.two[:8]}"
                                   f": 2 findings, 1 fixed, 1 answered")
        self.assertEqual(lines[2], "")
        self.assertEqual(lines[3], "## Context")

    def test_a_status_line_already_there_is_replaced(self):
        text = self.plan().replace("\n", "\nSTATUS: TODO 2026-11-20: parked\n", 1)
        dest = planclose.close(self.write(text), self.repo, self.home, today="2026-11-24")
        with open(dest, encoding="utf-8") as f:
            lines = f.read().split("\n")
        self.assertTrue(lines[1].startswith("STATUS: COMPLETED 2026-11-24: 2 sections;"))
        self.assertNotIn("STATUS: TODO", "\n".join(lines))

    def test_a_taken_name_is_numbered(self):
        os.makedirs(os.path.join(self.home, "complete"))
        os.makedirs(os.path.join(self.home, "todo"))
        open(os.path.join(self.home, "complete", "the-exporter-s-move.md"), "w").close()
        open(os.path.join(self.home, "todo", "the-exporter-s-move.2.md"), "w").close()
        dest = planclose.close(self.write(self.plan()), self.repo, self.home, today="2026-11-24")
        self.assertEqual(os.path.basename(dest), "the-exporter-s-move.3.md")

    def test_a_plan_under_its_title_name_moves_under_it(self):
        path = self.write(self.plan(), name="the-exporter-s-move.md")
        dest = planclose.close(path, self.repo, today="2026-11-24")
        self.assertEqual(dest, os.path.join(self.home, "complete", "the-exporter-s-move.md"))

    def test_a_plan_with_no_title_keeps_its_name(self):
        path = self.write(self.plan(title="No heading here"), name="plan-mode-name.md")
        dest = planclose.close(path, self.repo, self.home, today="2026-11-24")
        self.assertEqual(os.path.basename(dest), "plan-mode-name.md")

    def test_a_refused_close_raises_with_the_list_and_moves_nothing(self):
        path = self.write(self.plan(findings=["- Finding: the flush drops a row: open"]))
        with self.assertRaises(planclose.Refused) as got:
            planclose.close(path, self.repo, self.home)
        self.assertEqual(got.exception.reasons, ["the finding `the flush drops a row` is open"])
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(os.path.join(self.home, "complete")))

    def test_a_long_title_is_cut_at_a_hyphen(self):
        title = "# " + "word " * 20
        self.assertEqual(planclose.title_name(title), "-".join(["word"] * 12) + ".md")


class Guard(unittest.TestCase):
    PLANS = "E:/projects/p4-phi/.claude/p4/temportal/plan-planner"

    def test_a_write_under_complete(self):
        self.assertIn("refused", planclose.guard("Write", {"file_path": f"{self.PLANS}/complete/x.md"}))

    def test_an_edit_under_complete_with_backslashes(self):
        path = self.PLANS.replace("/", "\\") + "\\complete\\x.md"
        self.assertIn("refused", planclose.guard("Edit", {"file_path": path}))

    def test_a_notebook_edit_under_complete(self):
        self.assertIn("refused", planclose.guard("NotebookEdit", {"notebook_path": f"{self.PLANS}/complete/n.ipynb"}))

    def test_an_edit_of_a_plan_being_worked(self):
        self.assertIsNone(planclose.guard("Edit", {"file_path": f"{self.PLANS}/x.md"}))
        self.assertIsNone(planclose.guard("Write", {"file_path": f"{self.PLANS}/completed/x.md"}))
        self.assertIsNone(planclose.guard("Write", {}))

    def test_a_bash_move_into_complete(self):
        cmd = f"mv {self.PLANS}/x.md {self.PLANS}/complete/x.md"
        self.assertIn("refused", planclose.guard("Bash", {"command": cmd}))

    def test_a_powershell_move_with_backslashes(self):
        cmd = (r"Move-Item E:\p\.claude\p4\temportal\plan-planner\x.md "
               r"E:\p\.claude\p4\temportal\plan-planner\complete\x.md")
        self.assertIn("refused", planclose.guard("PowerShell", {"command": cmd}))

    def test_a_plan_close_line(self):
        cmd = (f"python -I -X utf8 E:/p/scripts/phi.py plan close \"{self.PLANS}/x.md\" --checkout E:/p "
               f"# into plan-planner/complete")
        self.assertIsNone(planclose.guard("Bash", {"command": cmd}))
        ps = f"& python E:\\p\\scripts\\phi.py plan close {self.PLANS}\\complete\\x.md --checkout E:\\p 2>&1"
        self.assertIsNone(planclose.guard("PowerShell", {"command": ps}))

    def test_a_plan_close_line_chained_with_a_move(self):
        cmd = f"python phi.py plan close a.md --checkout . && mv b.md {self.PLANS}/complete/b.md"
        self.assertIn("refused", planclose.guard("Bash", {"command": cmd}))
        cmd = f"python phi.py plan close a.md --checkout .; cp b.md plan-planner/complete/"
        self.assertIn("refused", planclose.guard("Bash", {"command": cmd}))

    def test_a_command_that_names_no_complete(self):
        self.assertIsNone(planclose.guard("Bash", {"command": f"mv {self.PLANS}/x.md {self.PLANS}/todo/x.md"}))
        self.assertIsNone(planclose.guard("Bash", {"command": "git status"}))
        self.assertIsNone(planclose.guard("Bash", {}))

    def test_another_tool(self):
        self.assertIsNone(planclose.guard("Read", {"file_path": f"{self.PLANS}/complete/x.md"}))
        self.assertIsNone(planclose.guard("Grep", {"path": f"{self.PLANS}/complete"}))
        self.assertIsNone(planclose.guard("Write", None))


if __name__ == "__main__":
    unittest.main()
