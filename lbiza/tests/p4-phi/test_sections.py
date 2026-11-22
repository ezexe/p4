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
