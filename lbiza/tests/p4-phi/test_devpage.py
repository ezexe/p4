#!/usr/bin/env python3
"""docs/plugin-development.html: the page on developing p4-phi while it is installed.

    python -m pytest tests/p4-phi/test_devpage.py

Checked: the page is linked from the index and the README, each case of the evals suite has its row on the page,
the catalog is at the repository's root, the keys the page names are the ones the code holds, what the live-checks
section says of the code holds in the code, and every link of the page leads somewhere.
"""

import os
import re
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SRC))))
PAGE = os.path.join(REPO, "docs", "plugin-development.html")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def phi_settings():
    """The keys phi.py reads from a store's phi/phi.json, read from its SETTINGS table as written."""
    table = read(os.path.join(SRC, "phi.py")).split("\nSETTINGS = {", 1)[1].split("}", 1)[0]
    return re.findall(r'"([a-z_]+)":', table)


class Page(unittest.TestCase):
    def test_the_page_is_linked_from_the_index_and_the_readme(self):
        self.assertIn('href="plugin-development.html"', read(os.path.join(REPO, "docs", "index.html")))
        self.assertIn("docs/plugin-development.html", read(os.path.join(os.path.dirname(SRC), "README.md")))

    def test_what_the_plugin_makes_a_model_do_is_checked_by_the_evals_suite_and_by_no_piped_prompt(self):
        page = read(PAGE)
        evals = os.path.join(os.path.dirname(SRC), "evals")
        named = [d for d in sorted(os.listdir(evals)) if os.path.isfile(os.path.join(evals, d, "prompt.md"))]
        self.assertTrue(named)
        for case in named:                             # every case of the suite has its row on the page
            self.assertIn(f"<td><code>{case}</code></td>", page, case)

    def test_the_catalog_is_at_the_repositorys_root_and_lbiza_holds_none(self):
        """The marketplace's one catalog is at the repository's root, and lbiza/ holds none."""
        catalog = os.path.join(REPO, ".claude-plugin", "marketplace.json")
        self.assertTrue(os.path.isfile(catalog), "the catalog at the root")
        self.assertFalse(os.path.exists(os.path.join(REPO, "lbiza", ".claude-plugin", "marketplace.json")),
                         "lbiza/ holds none")

    def test_the_goal_key_is_a_setting_and_the_draft_hands_no_permission_mode(self):
        """The goal section of the page names the key `goal`, which phi.json's settings hold, and says the start
        draft is built with no permission mode."""
        self.assertIn("goal", phi_settings(), "the key the page names is one phi.json's settings hold")
        self.assertNotIn('"permission_mode"', read(os.path.join(SRC, "puppeteer.py")),
                         "the draft's call is built with no permission mode, as the page says")

    def test_live_checks_holds_what_each_check_of_the_hooks_module_showed(self):
        """What the live-checks section says of the code holds in the code: the marker of a plugin's own call, the
        three record handlers, the switch, each key of the app's record files that is still read, and each reader the
        section names."""
        page = read(PAGE)
        live = page.split('<section id="live-checks"', 1)[1].split("</section>", 1)[0]
        hook = read(os.path.join(SRC, "hook.py"))
        self.assertIn('PLUGIN_CALL = "toolu_plugin_"', hook)
        self.assertEqual(hook.count("if plugins_own("), 3, "the three record handlers")
        self.assertIn("toolu_plugin_", read(os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")))
        phi = read(os.path.join(SRC, "phi.py"))
        self.assertIn("def app_tools_switch(home, on=None):", phi)
        self.assertIn("app_tools", phi_settings())
        for name in ("cliSessionId", "lastAssistantCliSessionId", "startChain", "forkedFromSessionId",
                     "lastTurnStopped"):                # each key the page says the record alone holds is still read
            self.assertIn(f"<code>{name}</code>", live, name)
            self.assertTrue(any(name in read(os.path.join(SRC, f)) for f in ("phi.py", "starts.py", "node.py")), name)
        for reader in ("puppeteer.app_index", "controls.started_by", "controls.sections"):
            module, _, function = reader.partition(".")
            self.assertIn(f"<code>{reader}</code>", live, reader)
            self.assertIn(f"def {function}(", read(os.path.join(SRC, module + ".py")), reader)

    def test_live_checks_holds_the_pane_the_goal_the_terminal_worker_and_the_plan_folder(self):
        """What the live-checks section says changed holds in the code: each tool the page's open section names is
        still a word of the code's own, and the lines the section says were fixed are in the code."""
        page = read(PAGE)
        open_still = page.split('id="not-confirmed"', 1)[1]
        for tool in ("mcp__ccd_session__list_start_targets", "mcp__ccd_host__get_storage_usage",
                     "mcp__ccd_host__discard_kept_worktree"):       # each is still a word of the code's own
            self.assertIn(f"<code>{tool}</code>", open_still, tool)
            self.assertTrue(any(tool in read(os.path.join(SRC, f)) for f in ("controls.py", "upkeep.py")), tool)
        # what the section says changed, held against the code
        self.assertIn("if (text === reported) return", read(os.path.join(os.path.dirname(SRC), "hooks", "register.ts")))
        upkeep = read(os.path.join(SRC, "upkeep.py"))
        self.assertIn("route(home, s, text, by, store, k, d, hand)", upkeep)
        self.assertIn('os.path.isdir(f"{worker[1]}/.claude/worktrees/{worker[0]}")', upkeep)
        self.assertIn('s["doneLine"] = plans.done_line(turn.get("prompt"))', read(os.path.join(SRC, "phi.py")))

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
                self.assertTrue(os.path.isfile(os.path.join(REPO, "docs", target)), href)
            if frag:
                self.assertIn(frag, ids if not target else set(re.findall(
                    r'\bid="([^"]+)"', read(os.path.join(REPO, "docs", target)))), href)


if __name__ == "__main__":
    unittest.main()
