#!/usr/bin/env python3
"""node.py: the content words two texts share, which order the notes and the siblings' tasks of a session's start.

    python -m pytest tests/p4-phi/test_node.py
"""

import sys
import unittest
from pathlib import Path

# the folder of the code these tests run
SRC = Path(__file__).resolve().parents[2] / "plugins" / "p4-phi" / "scripts"
sys.path.insert(0, str(SRC))
import node  # noqa: E402


class Overlap(unittest.TestCase):
    def test_items_nearest_the_task_come_first_and_ties_keep_their_order(self):
        items = ["the build cache lives in out/", "golden images of the plotter", "plotter presets per machine"]
        self.assertEqual(node.by_overlap(items, "fix the plotter presets"),
                         ["plotter presets per machine", "golden images of the plotter", "the build cache lives in out/"])
        self.assertEqual(node.by_overlap(items, ""), items, "no task: the order is kept")

    def test_a_key_reads_the_text_of_an_item_and_the_words_leave_the_common_ones_out(self):
        items = [{"t": "golden images"}, {"t": "the plotter presets"}]
        self.assertEqual(node.by_overlap(items, "plotter presets", key=lambda x: x["t"]), [items[1], items[0]])
        self.assertEqual(node.words("The plotter and the presets"), {"plotter", "presets"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
