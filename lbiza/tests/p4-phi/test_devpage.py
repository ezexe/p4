#!/usr/bin/env python3
"""dox/plugin-development.html: the page on developing p4-phi while it is installed.

    python -m pytest tests/p4-phi/test_devpage.py

Checked: the page is linked from the index and the README, says the commands and settings of Claude Code's own
that a development session uses, shows the development project's local settings, cites its sources and keeps a
section of what they do not confirm, and describes nothing p4-phi builds in their place; the evals suite's command
and a row for each of its cases in place of a prompt piped by hand, both installed plugins off, the marketplace as it
is registered and the installed copy as a copy in Claude Code's cache that auto-update moves, what seven live probes
showed of Claude Code's goal and plan and which of p4-phi's pieces a goal covers, what the live checks of the hooks
module showed in the desktop app with what they showed wrong, and every link of the page leading somewhere.
"""

import os
import re
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SRC))))
PAGE = os.path.join(REPO, "dox", "plugin-development.html")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def phi_settings():
    """The keys phi.py reads from a store's phi/phi.json, read from its SETTINGS table as written."""
    table = read(os.path.join(SRC, "phi.py")).split("\nSETTINGS = {", 1)[1].split("}", 1)[0]
    return re.findall(r'"([a-z_]+)":', table)


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

    def test_the_page_holds_both_arms_scores_of_the_two_cases_on_the_rule_as_rewritten(self):
        """plugin-evals.md, "The no-plugin baseline": "If a case scores 1.0 both with and without the plugin, the
        plugin isn't what made it pass." The two cases on the act-don't-wait rule scored so at the first run, so
        the page sets out each variant tried, the scores of both arms of the kept ones, how the two run alone, and
        what the rule does not add on the pinned model."""
        page = read(PAGE)
        self.assertIn('<h3 id="the-two-cases-on-the-rule">The two cases on the rule, rewritten</h3>', page)
        rewritten = page.split('id="the-two-cases-on-the-rule"', 1)[1].split("<h3>What a run's trace showed</h3>")[0]
        for said in ("<tr><td><code>decides-from-the-files</code></td><td>0.67</td><td>0.67</td><td>0.00</td></tr>",
                     "<tr><td><code>asks-before-an-irreversible-step</code></td><td>0.33</td><td>0.00</td>"
                     "<td>+0.33</td></tr>",
                     "<code>--max-cost-usd 1.5</code>", "<code>--tag rule</code>", "<code>claude-sonnet-5-5</code>",
                     "What the rule does not add"):
            self.assertIn(said, rewritten, said)
        for case in ("decides-from-the-files", "asks-before-an-irreversible-step"):
            self.assertEqual(rewritten.count(f"<tr><td><code>{case}</code></td><td>"), 4, "three variants, and kept")
        self.assertIn("<code>--tag rule</code> at its end", page.split('id="the-two-cases-on-the-rule"', 1)[0])

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

    def test_the_auto_update_pass_is_set_out_as_seen_and_no_longer_as_not_confirmed(self):
        """The pass moved both installed copies after the landing of 92c34f7, with no update command, while only
        desktop app sessions ran. So rule 2 holds what `installed_plugins.json`, the cache and the app's records
        showed, and "Not confirmed" lists neither that no pass was seen nor whether an app session runs one."""
        page = read(PAGE)
        rule = page.split("<h3>2. A landing's version bump reaches the installed copy by auto-update</h3>", 1)[1]
        rule = rule.split("<h3>", 1)[0]
        for said in ("bumped p4-phi to 0.11.48 and p4-temportal to 0.3.23",
                     "the <code>gitCommitSha</code> 92c34f7 and a <code>lastUpdated</code> of 08:04:54 UTC",
                     "with <code>installedAt</code> still at 07:37 UTC",
                     "<code>0.11.48</code> and <code>0.3.23</code> beside <code>0.11.46</code> and <code>0.3.22</code>",
                     "A session of the desktop app runs the pass.",
                     "created at 07:55:38 UTC and at 08:04:44 UTC",
                     "no session ran an update command"):
            self.assertIn(said, rule, said)
        open_still = page.split('id="not-confirmed"', 1)[1]
        for gone in ("has not been seen on ezexe's machine yet", "no pass has had a newer one to take",
                     "Whether a session of the desktop app runs the auto-update pass"):
            self.assertNotIn(gone, page, gone)
        self.assertNotIn("auto-update pass", open_still)

    def test_goal_and_plan_holds_what_each_probe_showed_and_what_a_goal_covers(self):
        """The section sets what the docs say of Claude Code's goal and plan beside what seven live probes showed,
        each with the Claude Code version it ran on, and names which of p4-phi's pieces a goal covers. The answer the
        build rests on is there in words: a hooks module's `$.command.run` set a goal in a started session with no
        dialog, and `SetGoal` is no tool of such a session."""
        page = read(PAGE)
        self.assertIn('href="#goal-and-plan"', page.split("</nav>", 1)[0])
        section = page.split('<section id="goal-and-plan"', 1)[1].split("</section>", 1)[0]
        for said in ("Claude Code 2.1.328", "Claude Code 2.1.326", "2026-11-19", "<code>p4-goal-probe</code>",
                     "<code>goal.md</code>", "<code>hooks-guide.md</code>", "<code>plugins/mods/api.md</code>",
                     "<code>permission-modes.md</code>", "<code>settings-reference.md</code>",
                     "<code>desktop.md</code>", "<code>plugins/loading.md</code>",
                     "<code>mcp__ccd_turn__update_plan</code>"):
            self.assertIn(said, section, said)
        rows = section.split("<tbody>", 1)[1].split("</tbody>", 1)[0].split("</tr>")[:-1]
        self.assertEqual(len(rows), 7, "one row for each probe the report lists")
        for row, said in zip(rows, (
                ("Plan pane", "From plan mode's plan file", "<code>step one of the probe plan</code>",
                 "<code>Probe step one</code>", "neither step of the list",
                 "<code>Showing the plan pane.</code>", "<code>Plan shown (2 steps).</code>"),
                ("<code>$.command.run</code>", "Yes, with no dialog", "<code>Goal set: &lt;condition&gt;</code>",
                 "idle and never typed into", "<code>turn.complete</code>", "it was rejected"),
                ("<code>SetGoal</code>", "No.", '<code>no tool named "SetGoal" in this session</code>'),
                ("first prompt begins with <code>/goal</code>", "No.", "<code>Task:</code>", "A fork was not tried",
                 "<code>peer</code>"),
                ("achieved entry", "<code>goal_status</code>", '<code>"met":true</code>',
                 '<code>"met":false,"failed":true</code>', '<code>"met":true,"sentinel":true</code>',
                 "after the Stop hooks of its Stop have answered", "<code>stopReason</code>"),
                ("worker's message", "Yes.", "<code>A hook blocked the turn from ending 9 consecutive times</code>",
                 "eight more continuations"),
                ("one count of eight", "Yes.", "the goal's two blocks and the module's six"))):
            for part in said:
                self.assertIn(part, row, part)
        covers = section.split("What a goal covers of p4-phi, and what it does not</h3>", 1)[1]
        for said in ("The Stop send-back is the piece a goal covers", "<code>plans.keep_going</code>",
                     "The done mark is covered in part", "The wake after a wait is covered in part",
                     "stays a Stop hook", "Nothing else of p4-phi is covered", "The plan copies nothing p4-phi builds"):
            self.assertIn(said, covers, said)
        built = section.split('<h3 id="the-goal-behind-its-setting">The goal behind its setting</h3>', 1)[1]
        for said in ("<code>goal</code> in the store's <code>phi/phi.json</code>, false unless set true",
                     "<code>P4_PHI_GOAL</code>", "<code>phi.py goal on</code>", "<code>phi.py goal off</code>",
                     "<code>Done looks like:</code>",
                     "<code>$.command.run({ command: 'goal', args })</code>", "<code>phi.py goal set</code>",
                     "<code>plans.keep_going</code> sends no turn back", "stay the Stop hook they are",
                     "<code>goal_status</code>", "<code>goal met:</code>", "With <code>goal</code> unset",
                     "is not yet seen"):
            self.assertIn(said, built, said)
        self.assertIn("goal", phi_settings(), "the key the page names is one phi.json's settings hold")
        self.assertIn("which the Plan pane does not show", covers)
        open_still = page.split('id="not-confirmed"', 1)[1]
        self.assertNotIn("What the desktop app's Plan pane holds.", open_still, "a look at the pane settled it")
        self.assertIn("Whether a forked session's first prompt runs as a command", open_still)

    def test_live_checks_holds_what_each_check_of_the_hooks_module_showed(self):
        """The parts of the hooks module that were built with no desktop session have a row each for what a live
        check showed, with the Claude Code version, and the page says what the checks showed wrong, what changed for
        each and why every read of the app's record files stays. What a check saw is no longer listed as not
        confirmed, and what the page says of the code holds in the code."""
        page = read(PAGE)
        self.assertIn('<a href="#live-checks">Live checks</a>', page)
        live = page.split('<section id="live-checks"', 1)[1].split("</section>", 1)[0]
        for said in ("Claude Code 2.1.326", "on 2.1.328", "<code>a-live-probe</code>", "<code>z-live-probe</code>",
                     "<code>~/.claude/dev-mods/</code>",
                     "it can only start sessions where this one runs, in this project.",
                     "Start sessions only on the user's own words to you here",
                     "<h3>What each check showed</h3>",
                     "<code>mcp__ccd_session_mgmt__get_session</code> took <code>session_id</code> <code>\"self\"</code>",
                     "<code>no tool named \"mcp__ccd_session_mgmt__get_session\" in this session</code>",
                     "<code>result</code> is a list of one text block",
                     "Whether such a call leaves a row in the transcript, spends tokens or disturbs a turn in flight",
                     "None of the three.",
                     "Another plugin's hooks saw all three and the calling plugin's own hooks saw none.",
                     "<code>toolu_plugin_</code> and 32 hex digits",
                     "wrote <code>app.json</code> with <code>at</code>, <code>self</code> and <code>sessions</code>",
                     "<code>mcp__ccd_session_mgmt__search_session_transcripts</code>", "called it five times",
                     "<h3>What the checks showed wrong, and what changed</h3>",
                     "A plugin's own call was recorded as the session's.",
                     "A session whose project has no store read itself from the record files.",
                     "<code>phi.py app_tools on</code> and <code>phi.py app_tools off</code>",
                     "<h3>Which reads of the app's record files stay</h3>", "Every one stays, and none was deleted."):
            self.assertIn(said, live, said)
        self.assertEqual(live.count("<tr><td>"), live.count("</td></tr>"))
        self.assertGreaterEqual(live.count("<tr><td>"), 6, "a row a check")
        open_still = page.split('id="not-confirmed"', 1)[1]
        self.assertNotIn("No desktop session has made the call yet", open_still, "a desktop session has made it")
        # what the section says of the code, held against the code
        hook = read(os.path.join(SRC, "hook.py"))
        self.assertIn('PLUGIN_CALL = "toolu_plugin_"', hook)
        self.assertEqual(hook.count("if plugins_own(payload):"), 3, "the three record handlers")
        self.assertIn("toolu_plugin_", read(os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh")))
        phi = read(os.path.join(SRC, "phi.py"))
        self.assertIn("def app_tools_switch(home, on=None):", phi)
        self.assertIn("app_tools", phi_settings())
        for name in ("cliSessionId", "lastAssistantCliSessionId", "startChain", "forkedFromSessionId",
                     "lastTurnStopped"):                # each key the page says the record alone holds is still read
            self.assertIn(f"<code>{name}</code>", live, name)
            self.assertTrue(any(name in read(os.path.join(SRC, f)) for f in ("phi.py", "starts.py", "node.py")), name)
        for reader in ("puppeteer.app_index", "node.record_tree", "controls.started_by", "controls.sections"):
            module, _, function = reader.partition(".")
            self.assertIn(f"<code>{reader}</code>", live, reader)
            self.assertIn(f"def {function}(", read(os.path.join(SRC, module + ".py")), reader)

    def test_live_checks_holds_the_pane_the_goal_the_terminal_worker_and_the_plan_folder(self):
        """The checks that needed a session on screen, a worker of the app and an orchestrator with a finished
        session under it: a row each, the four things they showed wrong with what changed, the route by which a
        desktop session got the copy, and what no session a session starts could reach, said as not confirmed."""
        page = read(PAGE)
        live = page.split('<section id="live-checks"', 1)[1].split("</section>", 1)[0]
        for said in ("with the origin <code>composer</code>", "<code>p4-phi's pane is open.</code> 56 milliseconds later",
                     "<code>placement</code> <code>dock</code>, 26 body columns",
                     "no-surface: no surface is attached",
                     "the pane drew the new text at 14:45:04.5",
                     "<code>This session keeps no board and no ledger: it is no puppeteer and no orchestrator, or no "
                     "look has run yet.</code>",
                     "<code>\"met\":false,\"sentinel\":true</code>", "<code>durationMs</code> 12829",
                     "kept <code>over</code> <code>met</code> with the evaluator's reason",
                     "start a worker in the Terminal panel for it, named <code>upkeep-08dc6384</code>",
                     "<code>worker-settings.json</code>, <code>brief-upkeep-08dc6384.md</code> and "
                     "<code>start-upkeep-08dc6384.ps1</code>", "<code>{\"tab_id\":\"c1\"}</code>",
                     "<code>claude session upkeep-08dc6384 (pid 10844)</code>",
                     "<code>is_running_command</code> false",
                     "<code>Deleted branch worktree-upkeep-08dc6384 (was eabd9b9)</code>",
                     "Three were seen and three were not.", "<code>\"wake_when_done\": true</code>",
                     "<code>plansDirectory</code> to <code>.claude/p4/temportal/plans</code>",
                     "twenty-five linked sessions",
                     "is already taken by an installed plugin (p4-phi@p4-marketplace), which takes precedence.",
                     "Can't create a worktree in this repository yet",
                     "hears its own plugin's drawings alone",
                     "A brief no prompt hook saw gave no goal.",
                     "A report that repeated the one before it started a turn for nothing.",
                     "it repeated your previous message",
                     "A due step went back to the session it had waited on.",
                     "The lines that start a terminal worker were handed a second time."):
            self.assertIn(said, live, said)
        self.assertNotIn("seven linked sessions", live)
        self.assertEqual(live.count("<tr><td>"), 14)
        session = page.split('<section id="a-development-session"', 1)[1].split("</section>", 1)[0]
        self.assertIn("the copy under <code>.claude/skills/</code> did not load", session)
        self.assertIn("a desktop session gets the copy through its mods folder", session)
        open_still = page.split('id="not-confirmed"', 1)[1]
        self.assertIn("Three lines p4-phi hands were not seen in the app.", open_still)
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
                self.assertTrue(os.path.isfile(os.path.join(REPO, "dox", target)), href)
            if frag:
                self.assertIn(frag, ids if not target else set(re.findall(
                    r'\bid="([^"]+)"', read(os.path.join(REPO, "dox", target)))), href)


if __name__ == "__main__":
    unittest.main()
