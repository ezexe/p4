#!/usr/bin/env python3
"""dox/plugin-development.html: the page on developing p4-phi while it is installed.

    python3 -I lbiza/plugins/p4-phi/scripts/test_devpage.py

Checked: the page is linked from the index and the README, says the commands and settings of Claude Code's own
that a development session uses, shows the development project's local settings, cites its sources and keeps a
section of what they do not confirm, and describes nothing p4-phi builds in their place.
"""

import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
PAGE = os.path.join(REPO, "dox", "plugin-development.html")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Page(unittest.TestCase):
    def test_the_page_is_linked_from_the_index_and_the_readme(self):
        self.assertIn('href="plugin-development.html"', read(os.path.join(REPO, "dox", "index.html")))
        self.assertIn("dox/plugin-development.html", read(os.path.join(os.path.dirname(HERE), "README.md")))

    def test_the_page_says_the_native_commands_and_settings_and_their_sources(self):
        page = read(PAGE)
        for said in ("claude --plugin-dir &lt;clone&gt;/lbiza/plugins/p4-phi --debug", "/reload-plugins",
                     "claude -p --plugin-dir &lt;clone&gt;/lbiza/plugins/p4-phi --debug",
                     "claude plugin update p4-phi@p4-marketplace", "claude plugin update p4-temportal@p4-marketplace",
                     "settings.local.json", '"p4-phi@p4-marketplace": false', '"autoMemoryEnabled": false',
                     '"disableSkillShellExecution": false', "CLAUDE_PLUGIN_DATA", "P4_*",
                     "names the clone path and the commit", "plugins/loading.md", "plugins/create.md",
                     "plugins/components.md", "plugins/cli-reference.md", "anthropics/claude-code/issues/110694",
                     'id="not-confirmed"'):
            self.assertIn(said, page, said)

    def test_the_page_describes_nothing_p4_phi_builds_in_place_of_a_native_feature(self):
        page = read(PAGE)
        for gone in ("livecopy", "writtenBy", "stamp", "start line"):
            self.assertNotIn(gone, page, gone)


if __name__ == "__main__":
    unittest.main()
