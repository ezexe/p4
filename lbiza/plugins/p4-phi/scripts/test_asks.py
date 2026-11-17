#!/usr/bin/env python3
"""asks.py and the routing of a puppeteer's messages, run through p4-phi's own hooks.

The routing reads only a message's own words for work: a path it names is taken out first, so a folder named `land`
or `build` drafts no start.
"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import issues  # noqa: E402
from test_phi import KID, TOP, Tree, context  # noqa: E402

TASK = "Make the narwhal exporter write its ports table to the store"
DRAFT = "its start draft is"


class Routing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(self._tmp.name)
        t.record(TOP, title="the exporter top")
        t.record(KID, TOP, title="the flush port")

    def test_a_folder_named_land_or_build_in_a_path_drafts_no_start(self):                       # ezexe/p4#209
        """A brief whose one work word is a folder named `land` or `build` in a path it names, run through the prompt
        hook, gets no start draft; the same brief with a work word of its own does."""
        t = self.t
        t.say(TOP, TASK)
        for folder in ("land", "build"):
            ctx = context(t.say(TOP, f"Read `src/{folder}/flush.py` under the exporter and say what the table "
                                     f"rows hold there"))
            self.assertNotIn(DRAFT, ctx, folder)
            ctx = context(t.say(TOP, f"Read lib\\{folder}\\rows.py under the exporter and say what the table "
                                     f"rows hold there"))
            self.assertNotIn(DRAFT, ctx, folder + " in a backslash path")
        ctx = context(t.say(TOP, "Rename the retry helper in `src/export/flush.py` for the ports table and update "
                                 "its callers"))
        self.assertIn(DRAFT, ctx, "a work word of the message's own is still read")

    def test_writing_reads_the_words_and_not_the_paths(self):
        self.assertFalse(issues.writing("Read phi.py under E:/work/land/ and say what it holds."))
        self.assertFalse(issues.writing("Say what https://example.com/build/fix holds."))
        self.assertTrue(issues.writing("Fix the flush in `E:/work/copy/phi.py`."))
        self.assertTrue(issues.writing("Add/remove the retry flag on the exporter's flush."),
                        "a slash-joined pair of words is no path")
        self.assertTrue(issues.writing("Port/rename the retry helper of the exporter."))


if __name__ == "__main__":
    unittest.main()
