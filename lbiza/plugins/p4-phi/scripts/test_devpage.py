#!/usr/bin/env python3
"""dox/plugin-development.html: the page on developing p4-phi while it is installed.

    python3 -I lbiza/plugins/p4-phi/scripts/test_devpage.py

Checked: the page is linked from the index and the README, says the commands and settings of Claude Code's own
that a development session uses, shows the development project's local settings, cites its sources and keeps a
section of what they do not confirm, and describes nothing p4-phi builds in their place; a live check's prompt on
stdin, the override line, both installed plugins off, and every link of the page leading somewhere.
"""

import os
import re
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


    def test_a_live_check_takes_its_prompt_on_stdin_and_names_the_override_line(self):
        page = read(PAGE)
        self.assertIn('echo "&lt;prompt&gt;" | claude -p --plugin-dir &lt;clone&gt;/lbiza/plugins/p4-phi --debug', page)
        self.assertIn('Plugin "p4-phi" from --plugin-dir overrides installed version', page)
        self.assertIn("~/.claude/debug/latest", page)

    def test_both_installed_plugins_are_off_in_the_development_project(self):
        page = read(PAGE)
        for plugin in ("p4-phi", "p4-temportal"):
            self.assertIn(f'"{plugin}@p4-marketplace": false', page, plugin)

    def test_every_link_of_the_page_leads_somewhere(self):
        page = read(PAGE)
        ids = set(re.findall(r'\bid="([^"]+)"', page))
        links = re.findall(r'href="([^"]+)"', page)
        self.assertTrue(links)
        for href in links:
            if href.startswith(("https://", "data:")):
                continue
            target, _, frag = href.partition("#")
            if target:
                self.assertTrue(os.path.isfile(os.path.join(REPO, "dox", target)), href)
            if frag:
                self.assertIn(frag, ids if not target else set(re.findall(
                    r'\bid="([^"]+)"', read(os.path.join(REPO, "dox", target)))), href)


if __name__ == "__main__":
    unittest.main()
