#!/usr/bin/env python3
"""sections.py: an approved plan's sections as the starts of the workers that land them.

    python -m pytest tests/p4-phi/test_sections.py

agent-teams.md, "Avoid file conflicts": "Break the work so each teammate owns a different set of files." Sections
that share a file or depend on one another are one run, every other section is a run of its own, and a run is one
start call with an integrator's model and effort, since its fences are written.
"""

import os
import sys
import tempfile
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import plans  # noqa: E402
import sections  # noqa: E402

PLAN = """# The exporter's move

## Context

No worker lands this.

## 1. The writer

- **Files:** `src/export/writer.py`, `tests/test_writer.py`
- **Depends on:** none
- **Checks:** `python -m pytest tests/test_writer.py`

```markdown
## A heading inside a fence

- **Files:** `src/never.py`
```

## 2. The flush

- **Files:** `src/export/flush.py`
- **Depends on:** 1
- **Checks:** `python -m pytest tests/test_flush.py`

## 3. The page

- **Files:** `docs/export.md`
- **Depends on:** none

## 4. The writer's page

- **Files:** `src/export/writer.py`
- **Depends on:** none

## Distribution

- **Files:** none
"""


class Sections(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self.path = os.path.join(self.base, "plan.md")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(PLAN)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_section_is_a_heading_outside_a_fence_that_names_files(self):
        title, found = sections.parse(PLAN, self.base)
        self.assertEqual(title, "The exporter's move")
        self.assertEqual([s["n"] for s in found], ["1", "2", "3", "4"])
        self.assertEqual(found[1]["after"], ["1"])
        self.assertEqual(found[0]["checks"], "`python -m pytest tests/test_writer.py`")
        self.assertFalse(any("never.py" in f for s in found for f in s["files"]))

    def test_sections_that_share_a_file_or_depend_on_one_another_are_one_run(self):
        _, found = sections.parse(PLAN, self.base)
        self.assertEqual([[s["n"] for s in run] for run in sections.runs(found)], [["1", "2", "4"], ["3"]])

    def test_each_run_is_one_start_call_of_an_integrator_in_a_worktree(self):
        first, second = sections.calls(self.path, self.base)
        self.assertEqual(first["title"], "The exporter's move: sections 1, 2, 4")
        self.assertEqual((first["initiation"], first["context"], first["use_worktree"]), ("user_asked", "fresh", True))
        self.assertEqual(first["model"], plans.CHILD_LEVELS["static"]["model"])
        self.assertGreaterEqual(len(first["background"]), 80, "the app refuses a fresh start with a shorter one")
        for word in (f"of the plan `{self.path}`, in that order",
                     "Files: `src/export/writer.py`, `tests/test_writer.py`, `src/export/flush.py`",
                     "write no approach of this session's own", "never edits the plan file",
                     "python -m pytest tests/test_flush.py", "Done looks like: every fence of sections 1, 2, 4 landed",
                     "Model and effort: "):
            self.assertIn(word, first["prompt"], word)
        self.assertNotIn("export.md", first["prompt"])
        self.assertIn("Done looks like: every fence of section 3 landed, committed and reported.", second["prompt"])

    def test_a_heading_with_no_number_takes_a_free_one_and_a_files_line_ends_where_its_list_ends(self):
        text = ("# A plan\n\n## Setup\n\n- **Files:** `a.py`\n\n## 1. The writer\n\n"
                "- **Files:** `b.py`. The second is new, and so is its test.\n")
        title, found = sections.parse(text, self.base)
        self.assertEqual([s["n"] for s in found], ["2", "1"])
        self.assertEqual([[s["n"] for s in run] for run in sections.runs(found)], [["2"], ["1"]])
        self.assertIn("\nFiles: `b.py`\n", sections.brief(self.path, title, [found[1]]))

    def test_a_plan_with_no_files_line_has_no_run(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# A plan\n\n## Context\n\nNothing to land.\n")
        self.assertEqual(sections.calls(self.path, self.base), [])

    def test_a_section_counts_its_fences_and_the_lines_under_its_assumed(self):
        ticks = chr(96) * 3
        text = ("# A plan\n\n## 1. The writer\n\n**Files:** `a.py`\n\n**Observed:**\n\n"
                "- the writer flushes: `a.py:3`\n\n**Assumed:**\n\n"
                "- the reader waits\n- the queue is short\n\nIt lands as below.\n\n"
                f"{ticks}python\nx = 1\n{ticks}\n\n{ticks}python\n- **Assumed:** a line in a fence\n{ticks}\n\n"
                "## 2. The page\n\n**Files:** `b.md`\n**Checks:** none\n\n**Assumed:** none\n\n"
                "## 3. The flush\n\n**Files:** `c.py`\n\n**Assumed:**\n\n- None of the readers waits.\n")
        _, found = sections.parse(text, self.base)
        self.assertEqual([(s["n"], s["fences"], s["assumed"]) for s in found], [("1", 2, 2), ("2", 0, 0), ("3", 0, 1)])
        self.assertEqual(found[1]["checks"], "", "a Checks line that says none names no check")
        self.assertFalse(sections.team([found[1]]))
        self.assertIn("That section holds 2 lines under `Assumed:`", sections.brief(self.path, "A plan", [found[0]]))
        self.assertNotIn("Assumed", sections.brief(self.path, "A plan", [found[1]]))

    def section(self, n, fences, checks=""):
        return {"n": str(n), "files": [f"src/file{n}.py"], "after": [], "fences": fences, "checks": checks}

    def test_runs_are_joined_into_groups_of_five_fences_with_no_bound_on_their_count(self):
        def nums(found):
            return [[s["n"] for s in group] for group in sections.groups(found)]
        self.assertEqual(nums([self.section(1, 6), self.section(2, 2), self.section(3, 1), self.section(4, 7)]),
                         [["1"], ["2", "3", "4"]])
        self.assertEqual(nums([self.section(1, 6), self.section(2, 2)]), [["1", "2"]], "a last small group joins")
        self.assertEqual(nums([self.section(1, 13), self.section(2, 12), self.section(3, 6), self.section(4, 13)]),
                         [["1"], ["2"], ["3"], ["4"]], "the plan this rule was first read by")
        self.assertEqual(nums([self.section(1, 1)]), [["1"]])
        six = [self.section(k, fences) for k, fences in enumerate((9, 5, 5, 9, 6, 5), 1)]
        self.assertEqual(nums(six), [["1"], ["2"], ["3"], ["4"], ["5"], ["6"]], "six groups stay six")
        self.assertEqual(nums([]), [])

    def test_a_group_earns_a_team_by_five_fences_or_a_check(self):
        self.assertFalse(sections.team([self.section(1, 2)]))
        self.assertTrue(sections.team([self.section(1, 2, "`python -m pytest tests/test_a.py`")]))
        self.assertTrue(sections.team([self.section(1, 3), self.section(2, 2)]))

    def test_a_runs_brief_names_the_environment_its_worktree_shares(self):
        import json
        import p4conf
        main = os.path.realpath(tempfile.mkdtemp())
        os.makedirs(os.path.join(main, ".git"))
        os.makedirs(os.path.join(main, ".claude", "p4"))
        os.makedirs(os.path.join(main, ".venv"))
        open(os.path.join(main, ".venv", "python.exe"), "w").close()
        with open(p4conf.path(os.path.join(main, ".claude", "p4")), "w", encoding="utf-8") as f:
            json.dump({"phi": {"worktree_python": ".venv/python.exe"}}, f)
        first = sections.calls(self.path, main)[0]
        self.assertIn("build no environment here", first["prompt"])
        self.assertIn(main.replace("\\", "/") + "/.venv/python.exe", first["prompt"])
        self.assertNotIn("build no environment here", sections.calls(self.path, self.base)[0]["prompt"])
