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

    def test_each_run_has_a_brief_that_names_its_plan_files_checks_and_what_done_looks_like(self):
        title, found = sections.parse(PLAN, self.base)
        first, second = [sections.brief(self.path, title, run, self.base) for run in sections.runs(found)]
        self.assertTrue(first.startswith("# The exporter's move: sections 1, 2, 4"))
        for word in (f"of the plan `{self.path}`, in that order",
                     "Files: `src/export/writer.py`, `tests/test_writer.py`, `src/export/flush.py`",
                     "write no approach of this session's own", "never edits the plan file",
                     "python -m pytest tests/test_flush.py", "Done looks like: every fence of sections 1, 2, 4 landed"):
            self.assertIn(word, first, word)
        self.assertNotIn("export.md", first)
        self.assertIn("Done looks like: every fence of section 3 landed, committed and reported.", second)

    def test_a_heading_with_no_number_takes_a_free_one_and_a_files_line_ends_where_its_list_ends(self):
        text = ("# A plan\n\n## Setup\n\n- **Files:** `a.py`\n\n## 1. The writer\n\n"
                "- **Files:** `b.py`. The second is new, and so is its test.\n")
        title, found = sections.parse(text, self.base)
        self.assertEqual([s["n"] for s in found], ["2", "1"])
        self.assertEqual([[s["n"] for s in run] for run in sections.runs(found)], [["2"], ["1"]])
        self.assertIn("\nFiles: `b.py`\n", sections.brief(self.path, title, [found[1]]))

    def test_a_section_with_evidence_is_landed_and_joins_no_run(self):
        text = PLAN.replace("## 1. The writer\n", "## 1. The writer\n\n**Evidence:** landed as abc1234\n", 1)
        _, found = sections.parse(text, self.base)
        self.assertEqual([s["landed"] for s in found], [True, False, False, False])
        runs = [[s["n"] for s in run] for run in sections.runs(found)]
        self.assertEqual(runs, [["2"], ["3"], ["4"]], "section 2 depends on 1, which is met, and joins nothing")
        self.assertEqual([[s["n"] for s in g] for g in sections.groups(found)], [["2", "3", "4"]])

    def test_a_brief_with_no_where_names_the_checkout_and_one_with_where_holds_those_lines_and_none_of_it(self):
        title, found = sections.parse(PLAN, self.base)
        plain = sections.brief(self.path, title, found[:1], self.base)
        self.assertEqual(plain, sections.brief(self.path, title, found[:1], self.base, where=None))
        cmd = sections.puppeteer._phi().commands()
        lines = [line.replace("{cmd}", cmd) for line in sections.puppeteer.CHECKOUT_LINES]
        self.assertEqual(len(lines), 3, "the three lines of CHECKOUT_LINES")
        for line in lines:
            self.assertIn(line, plain)
        self.assertNotIn("worktree of its own", plain)
        there = sections.brief(self.path, title, found[:1], self.base, where=["Work in E:/repo, no worktree.", ""])
        self.assertIn("\nWork in E:/repo, no worktree.\n", there)
        for line in lines:
            self.assertNotIn(line, there)

    def test_a_plan_with_no_files_line_has_no_run(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("# A plan\n\n## Context\n\nNothing to land.\n")
        self.assertEqual(sections.runs(sections.parse(open(self.path, encoding="utf-8").read(), self.base)[1]), [])

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



PIECES = """# Pieces

## 1. The reader

- **Files:** `src/a.py`, `tests/test_a.py`
- **Depends on:** none
- **Checks:** `python -m pytest tests/test_a.py`
- **Runner:** print api

## 2. The writer

- **Files:** `src/b.py`
- **Depends on:** none
- **Checks:** `python -m pytest tests/test_b.py`
- **Runner:** print max
- Model: claude-opus-5-5
- Effort: high

## 3. The joiner

- **Files:** `src/c.py`
- **Depends on:** 1, 2
- **Checks:** `python -m pytest tests/test_c.py`
- **Runner:** team

## 4. The second writer

- **Files:** `src/b.py`, `src/d.py`
- **Depends on:** 2
- **Checks:** `python -m pytest tests/test_d.py`

## 5. The docs

- **Files:** `README.md`
- **Depends on:** 3, 4
"""


class Waves(unittest.TestCase):
    """A plan written as pieces: runs joined by shared files only, `Depends on:` as waves, and the three readers'
    checks."""

    def found(self, text=PIECES):
        return sections.parse(text)[1]

    def test_a_depends_on_orders_runs_into_waves_and_only_a_shared_file_joins_two_sections(self):
        found = self.found()
        runs = [[s["n"] for s in r] for r in sections.file_runs(found)]
        self.assertEqual(runs, [["1"], ["2", "4"], ["3"], ["5"]], "2 and 4 share src/b.py; 1 and 3 share nothing")
        waves = [[[s["n"] for s in r] for r in w] for w in sections.waves(found)]
        self.assertEqual(waves, [[["1"], ["2", "4"]], [["3"]], [["5"]]])
        self.assertEqual([[s["n"] for s in r] for r in sections.ready(found)], [["1"], ["2", "4"]])
        self.assertEqual([[s["n"] for s in r] for r in sections.ready(found, met={"1", "2", "4"})],
                         [["1"], ["2", "4"], ["3"]], "ready reads needs only; the caller drops what started")

    def test_a_landed_section_is_met_and_a_need_the_plan_lacks_holds_nothing(self):
        text = PIECES.replace("## 1. The reader\n", "## 1. The reader\n\n**Evidence:** abc1234\n")
        text = text.replace("- **Depends on:** 1, 2", "- **Depends on:** 1, 2, 9")
        found = self.found(text)
        self.assertEqual(sections.needs([s for s in found if s["n"] == "3"]), ["1", "2", "9"])
        self.assertNotIn(["3"], [[s["n"] for s in r] for r in sections.ready(found)], "2 is not met")
        self.assertIn(["3"], [[s["n"] for s in r] for r in sections.ready(found, met={"2", "4"})])

    def test_a_runner_line_names_mode_pool_team_and_the_sections_own_level(self):
        by = {s["n"]: s["runner"] for s in self.found()}
        self.assertEqual((by["1"]["mode"], by["1"]["pool"], by["1"]["team"]), ("print", "api", False))
        self.assertEqual((by["2"]["mode"], by["2"]["pool"]), ("print", "max"))
        self.assertEqual(by["2"]["level"], {"model": "claude-opus-5-5", "effort": "high"})
        self.assertEqual((by["3"]["mode"], by["3"]["team"]), ("interactive", True))
        self.assertEqual(by["4"], {})
        self.assertEqual(sections.runner_of("- **Runner:** `print max`, Opus at high\n")["pool"], "max")

    def test_lint_flags_a_shared_file_with_no_order_a_missing_dependency_and_a_section_with_no_check(self):
        self.assertEqual([lens for lens, _ in sections.lint(PIECES)], ["checks"], "only section 5 has no check")
        clash = PIECES.replace("- **Depends on:** 2\n", "- **Depends on:** none\n")
        lines = sections.lint(clash)
        self.assertIn("fences", [lens for lens, _ in lines])
        self.assertTrue(any("sections 2 and 4 both write src/b.py" in line for _, line in lines), lines)
        reads = PIECES.replace("## 3. The joiner\n", "## 3. The joiner\n\nIt reads `src/d.py` for its names.\n")
        self.assertTrue(any(lens == "sources" and "names src/d.py, which section 4 writes" in line
                            for lens, line in sections.lint(reads)), sections.lint(reads))
        ghost = PIECES.replace("- **Depends on:** 3, 4", "- **Depends on:** 3, 4, 8")
        self.assertTrue(any("depends on section 8, which the plan does not hold" in line
                            for _, line in sections.lint(ghost)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
