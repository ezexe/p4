#!/usr/bin/env python3
"""dox/plugin-development.html: the page on developing p4-phi while it is installed.

    python -m pytest tests/p4-phi/test_devpage.py

Checked: the page is linked from the index and the README, says the commands and settings of Claude Code's own
that a development session uses, shows the development project's local settings, cites its sources and keeps a
section of what they do not confirm, and describes nothing p4-phi builds in their place; the evals suite's command
and a row for each of its cases in place of a prompt piped by hand, both installed plugins off, the marketplace as it
is registered and the installed copy as a copy in Claude Code's cache that auto-update moves, and every link of the
page leading somewhere.
"""

import os
import re
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "lbiza", "plugins", "p4-phi", "scripts"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SRC))))
PAGE = os.path.join(REPO, "dox", "plugin-development.html")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Page(unittest.TestCase):
    def test_the_page_is_linked_from_the_index_and_the_readme(self):
        self.assertIn('href="plugin-development.html"', read(os.path.join(REPO, "dox", "index.html")))
        self.assertIn("dox/plugin-development.html", read(os.path.join(os.path.dirname(SRC), "README.md")))

    def test_the_page_says_the_native_commands_and_settings_and_their_sources(self):
        page = read(PAGE)
        for said in ("claude --plugin-dir &lt;clone&gt;/lbiza/plugins/p4-phi --debug", "/reload-plugins",
                     "claude plugin eval .", "plugin-evals.md",
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


    def test_what_the_plugin_makes_a_model_do_is_checked_by_the_evals_suite_and_by_no_piped_prompt(self):
        page = read(PAGE)
        self.assertIn('id="the-evals-suite"', page)
        self.assertIn("<code>claude plugin eval . --scaffold --trust-plugin --model claude-sonnet-5-5 "
                      "--judge-model claude-haiku-5-5 --no-publish --max-cost-usd 5</code>", page)
        self.assertIn("It gates no landing.", page)
        self.assertIn("<code>hook_response</code>", page)
        self.assertIn("counts for <code>tool_used</code>", page)
        evals = os.path.join(os.path.dirname(SRC), "evals")
        named = [d for d in sorted(os.listdir(evals)) if os.path.isfile(os.path.join(evals, d, "prompt.md"))]
        self.assertTrue(named)
        for case in named:                             # every case of the suite has its row on the page
            self.assertIn(f"<td><code>{case}</code></td>", page, case)
        for gone in ("| claude -p", "~/.claude/debug/latest"):   # the by-hand check the cases took the place of
            self.assertNotIn(gone, page, gone)

    def test_a_plugin_dir_session_runs_only_from_a_scratch_project(self):
        page = read(PAGE)
        self.assertIn("A development copy is any session that loads a clone of p4, by the <code>--plugin-dir</code> flag or "
                      "by the <code>CLAUDE_CODE_PLUGIN_DIRS</code> variable", page)
        self.assertIn("It runs only from a scratch project: never in the development project, and never in a project "
                      "where p4 is used.", page)
        self.assertNotIn("development runs on a clone with the installed copies off", page)
        self.assertIn("Sessions in the development project start without the flag, so no p4 hook runs there.", page)
        self.assertIn("ConfigChange", page)

    def test_both_installed_plugins_are_off_in_the_development_project(self):
        page = read(PAGE)
        for plugin in ("p4-phi", "p4-temportal"):
            self.assertIn(f'"{plugin}@p4-marketplace": false', page, plugin)

    def test_the_marketplace_is_registered_from_github_and_the_installed_copy_is_a_copy_in_the_cache(self):
        """The marketplace is added by the repository's name, its one catalog is at the repository's root, and an
        installed copy is a folder of Claude Code's plugin cache with the version in its path: no checkout is one."""
        page = read(PAGE)
        self.assertIn('id="the-marketplace"', page)
        self.assertIn('href="#the-marketplace"', page)
        for said in ("<code>claude plugin marketplace add ezexe/p4</code>",
                     "<code>claude plugin install p4-phi@p4-marketplace</code>",
                     "<code>claude plugin install p4-temportal@p4-marketplace</code>",
                     "<code>.claude-plugin/marketplace.json</code> at the repository's root",
                     "<code>~/.claude/plugins/cache/p4-marketplace/p4-phi/&lt;version&gt;/</code>",
                     "So no checkout of ezexe/p4 on the machine is the installed copy.",
                     "<code>extraKnownMarketplaces</code>", '"autoUpdate": true', '"repo": "ezexe/p4"',
                     "<code>Source path does not exist</code>", "Claude Code 2.1.328",
                     "uninstalls every plugin you installed from it",
                     "plugins/marketplace-reference.md", "plugins/install.md", "plugins/create-marketplace.md"):
            self.assertIn(said, page, said)
        catalog = os.path.join(REPO, ".claude-plugin", "marketplace.json")
        self.assertTrue(os.path.isfile(catalog), "the catalog the page names")
        self.assertFalse(os.path.exists(os.path.join(REPO, "lbiza", ".claude-plugin", "marketplace.json")),
                         "the page says lbiza/ holds none")

    def test_a_landings_version_bump_reaches_the_installed_copy_by_auto_update(self):
        """Rule 2 of the setup in force: auto-update is on for the marketplace, the version lives in plugin.json
        alone, and `claude plugin update` is the move by hand. The page no longer holds the installed copy back until
        a release is cut, and no longer lists in place or from the cache as not confirmed."""
        page = read(PAGE)
        for said in ("<h3>2. A landing's version bump reaches the installed copy by auto-update</h3>",
                     "bumps the version in that plugin's <code>.claude-plugin/plugin.json</code>, and no entry of the "
                     "catalog carries one",
                     "The <code>version</code> field in the plugin's manifest comes first",
                     "It then refreshes every marketplace with auto-update on and updates the plugins installed from "
                     "them on disk.",
                     "The running session keeps the versions it loaded",
                     "The move by hand is one update for each plugin:",
                     "A marketplace added from a folder runs its plugins in place."):
            self.assertIn(said, page, said)
        for gone in ("No plugin update after each landing", "only when a release is cut",
                     "Whether an installed copy from a marketplace added from a folder runs in place or from the "
                     "cache", "which <a href=\"#not-confirmed\">Not confirmed</a> takes up"):
            self.assertNotIn(gone, page, gone)
        self.assertNotIn("only when a release is cut", read(os.path.join(REPO, "dox", "index.html")))
        self.assertNotIn("only when a release is cut", read(os.path.join(os.path.dirname(SRC), "README.md")))

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
