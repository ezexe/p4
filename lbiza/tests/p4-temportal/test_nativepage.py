#!/usr/bin/env python3
"""docs/temportal-native.html: the one table of what a project keeps over time, with what was set out for p4-temportal,
what Claude Code does and the docs page that says so, what the plugin does today, what it only configures, what the
native feature lacks, and the part of the work each row belongs to.

    python -m pytest tests/p4-temportal/test_nativepage.py

Checked: the page is linked from the index, holds one table with a row for each thing kept and the seven columns,
names each docs page it quotes in its footer, gives every row a part the order section holds or says none is built,
keeps a section of what the docs do not confirm, writes no parenthetical, and every link of it leads somewhere.
"""

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
DOX = REPO / "docs"
PAGE = DOX / "temportal-native.html"

ROWS = ("compaction", "memory", "consolidation", "rules", "checkpoints", "transcripts", "scratchpad", "worktrees",
        "plans", "notebook", "lifetimes", "commands", "tools")
COLUMNS = ("What is kept", "Set out for the plugin", "What Claude Code does, and the page", "p4-temportal today",
           "What it only configures", "What the native feature lacks, which the plugin adds", "Part")
NO_PART = ("none", "built", "left")
LANDED = ("1", "2", "3", "4", "5")                         # the parts of the order that are on main


def page():
    return PAGE.read_text(encoding="utf-8")


def rows(text):
    """{row id: the row's html} of the page's one table."""
    body = text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return {m.group(1): m.group(2) for m in re.finditer(r'<tr id="row-([a-z]+)">(.*?)</tr>', body, re.S)}


class Page(unittest.TestCase):
    def test_the_page_is_linked_from_the_index(self):
        self.assertIn('href="temportal-native.html"', (DOX / "index.html").read_text(encoding="utf-8"))

    def test_the_page_is_one_table_with_a_row_for_each_thing_kept(self):
        text = page()
        self.assertEqual(text.count("<table>"), 1)
        head = text.split("<thead>", 1)[1].split("</thead>", 1)[0]
        self.assertEqual(tuple(re.findall(r"<th[^>]*>([^<]+)</th>", head)), COLUMNS)
        found = rows(text)
        self.assertEqual(tuple(found), ROWS)
        for name, row in found.items():                # a row head and one cell under each other column
            self.assertEqual(len(re.findall(r'<th scope="row">', row)), 1, name)
            self.assertEqual(len(re.findall(r"<td[ >]", row)), len(COLUMNS) - 1, name)

    def test_each_docs_page_the_page_quotes_is_named_in_its_footer(self):
        text = page()
        body, footer = text.split("<footer>", 1)
        quoted = set(re.findall(r"<code>([a-z/-]+\.md)</code>", body))
        listed = set(re.findall(r"<code>([a-z/-]+\.md)</code>", footer))
        self.assertTrue(quoted)
        self.assertEqual(quoted - listed, set())
        self.assertEqual(listed - quoted, set())
        self.assertIn("https://code.claude.com/docs/llms.txt", footer)
        self.assertIn("<code>https://code.claude.com/docs/en/</code>", body)

    def test_every_row_names_a_part_of_the_order_or_says_none_is_built(self):
        text = page()
        parts = set(re.findall(r'<li id="part-(\d+)">', text))
        self.assertTrue(parts)
        named = set()
        for name, row in rows(text).items():
            part = re.search(r'<td class="n">([^<]+)</td>', row).group(1)
            self.assertTrue(part in parts or part in NO_PART, f"{name}: {part}")
            named.add(part)
        self.assertEqual(parts - named, set(), "a part of the order no row belongs to")
        self.assertEqual(rows(text)["compaction"].count('<td class="n">1</td>'), 1, "compaction is the first part")

    def test_each_part_that_landed_says_the_version_it_landed_in(self):
        text = page()
        said = {part: re.search(r"It landed in p4-temportal \d+[.]\d+[.]\d+[.]</li>", item) is not None
                for part, item in re.findall(r'<li id="part-(\d+)">(.*?</li>)', text)}
        self.assertEqual({part for part, landed in said.items() if landed}, set(LANDED))
        today = rows(text)["compaction"]
        for word in ("session.compact", "temportal.compact_at", "$.command.run", "2.1.326"):
            self.assertIn(word, today, word)
        for word in ("mcp__p4-temportal__lifetime", "tool.run", "2.1.328"):
            self.assertIn(word, rows(text)["lifetimes"], word)
        self.assertIn("consolidate-memory", rows(text)["consolidation"])
        for name in ("memory", "scratchpad", "lifetimes"):
            self.assertIn("deleted", rows(text)[name], name)
            self.assertNotIn("still answers", rows(text)[name], name)

    def test_plan_files_are_kept_in_the_store_by_plansDirectory(self):
        """The settings keeper writes plansDirectory, and the page of the settings p4 keeps says so in the row that
        said no plugin moves a plan. The row of this page says what is written, when it is not, what lifetimes add
        and what the live check saw, and the order holds the part as landed."""
        text = page()
        row = rows(text)["plans"]
        self.assertIn('<td class="n">5</td>', row)
        for said in ('href="claude-settings.html"', "<code>.claude/p4/temportal/plans</code>", "2.1.328",
                     "neither asked about nor refused", "a cache rule on <code>plans</code>", "sets it false"):
            self.assertIn(said, row, said)
        self.assertEqual(set(re.findall(r'<li id="part-(\d+)">', text)), set(LANDED))
        self.assertNotIn('id="left"', text)
        settings = (DOX / "claude-settings.html").read_text(encoding="utf-8")
        self.assertNotIn("no plugin moves a plan", settings)
        self.assertEqual(settings.count("<tr><td><code>plansDirectory</code></td>"), 2)

    def test_the_settings_come_from_the_hooks_module_where_it_loads(self):
        """The memory row says where the plugin's python gets Claude Code's settings: from the hooks module, by
        `$.settings.read` at classic.SessionStart, with the file reads kept where no module loads, and what the live
        check saw. What the hand-over rests on, and no page states, is among what the docs do not confirm."""
        text = page()
        row = rows(text)["memory"]
        for said in ("<code>$.settings.read</code>", "<code>classic.SessionStart</code>", "<code>p4_settings</code>",
                     "every managed tier merged", "loads no module", "2.1.328", "<code>flag</code>"):
            self.assertIn(said, row, said)
        open_still = text.split('id="not-confirmed"', 1)[1].split("</section>", 1)[0]
        self.assertIn("a field a module adds to the input", open_still)
        self.assertIn("<code>$.settings.read</code>", open_still)

    def test_the_host_is_read_from_p4_natives_map_first(self):
        """The lifetimes row says which reading of the host goes to p4-native's capability map first, what it falls
        back to, and which readings were left with the reason for each."""
        row = rows(page())["lifetimes"]
        for said in ("p4-native", "<code>.claude/p4/native/host.json</code>", "search for a python",
                     "no entry for the session", "ask their own interpreter", "written after the start hooks ran"):
            self.assertIn(said, row, said)

    def test_each_thing_once_not_seen_live_is_seen_or_says_why_it_is_not(self):
        """Eight things p4-temportal built had been seen in no real session. The page names each one where it keeps
        such results: as seen, with what was seen, or as still not seen, with what stands in the way. Three of them
        were seen later in the desktop app: the message behind a summary, the cleanup and a project's plans folder,
        and where a plan-mode session's plan lands."""
        text = page()
        found = rows(text)
        open_still = text.split('id="not-confirmed"', 1)[1].split("</section>", 1)[0]
        seen = {
            "the plugin's own compaction at a quiet moment": (found["compaction"], (
                "<code>temportal.compact_at</code> to 1", "a minute after a turn ended", "<code>manual</code>",
                "50,068 tokens to 9,549", "each with the plugin as its origin", "No second compaction followed")),
            "a compaction Claude Code starts by itself": (found["compaction"], (
                "a compaction Claude Code starts by itself", "<code>CLAUDE_CODE_AUTO_COMPACT_WINDOW</code>",
                "each read <code>auto</code>", "carried from list to list")),
            "the compaction of a subagent's transcript": (found["compaction"], (
                "the compaction of a subagent's transcript", "with the subagent's id",
                "The main conversation was not compacted")),
            "the ask before a call of the lifetime tool": (found["lifetimes"], (
                "put to the host as an ask before anything ran", "with no command of <code>lifetime.py</code> run",
                "an allowed one ran <code>list</code>")),
            "plansDirectory from the keeper to a plan": (found["plans"], (
                "as one chain", "the first session's start wrote the key", "neither asked about nor refused",
                "the session after the one whose start wrote it")),
            "an older build": (open_still, (
                "Seen on Claude Code 2.1.322 and 2.1.311", "<code>tool.run</code> is no event on either",
                "<code>hooks module p4-temportal@inline loaded</code>", "names the glob <code>tool.*</code>",
                "registers no tool there", "was seen on those builds")),
            "how the app draws the message": (open_still, (
                "Seen in the desktop app on Claude Code 2.1.326, in a session in plan mode whose worktree's own",
                "91,362 tokens to 18,383",
                "with the plugin as its origin", "the session's last prompt", "The plugin's list was not drawn in view", "was not the first one due", "was not seen itself",
                "keeps the end of the last turn in the session's state", "no live session has shown it")),
            "whether the cleanup reaches a plansDirectory": (open_still, (
                "Seen in the desktop app on Claude Code 2.1.326, one sweep did not", "at most once per session",
                "ten minutes and six or seven seconds", "in the session's own plans folder stayed",
                "read from that timing alone", "it may have been skipped",
                "Not seen: the sweep of a terminal session")),
            "the plan chain in the desktop app": (found["plans"], (
                "Seen in the desktop app on Claude Code 2.1.326, in two sessions in plan mode",
                "under its own worktree", "copied when the worktree is made", "was not told apart",
                "a <code>.claude/p4</code> of its own",
                "copies its plans, its notebook and its saved code into the main checkout's store",
                "the path resolves outside the project root", "still there after the worktree was removed",
                "Not seen in the desktop app")),
        }
        for what, (where, words) in seen.items():
            for said in words:
                self.assertIn(said, where, f"{what}: {said}")
        unseen = {
            "a first session of the desktop app and a worktree off Windows": (found["plans"], (
                "Still not seen: a first session of the desktop app", "anywhere but on Windows",
                "a machine that is not this one")),
        }
        for what, (where, words) in unseen.items():
            for said in words:
                self.assertIn(said, where, f"{what}: {said}")
        self.assertNotIn("Not seen live: a compaction Claude Code starts by itself", text)
        # what one run did not show: its project began with both keys in its settings file
        self.assertNotIn("the settings keeper wrote both keys", text)

    def test_old_plans_in_the_stores_folder_are_cleared_at_claude_codes_own_age(self):
        """The plans row says that the sweep clears a plan at the age of cleanupPeriodDays, where that age comes
        from, when no plan is cleared by age, what stands in its place, and that only tests have shown it."""
        text = page()
        row = rows(text)["plans"]
        for said in ("does not reach a folder a project names", "since p4-temportal 0.3.45",
                     "at that same age", "<code>$.settings.read</code>", "takes 30 days where no file sets the key",
                     "no plan is cleared by age", "pauses its own sweep", "an empty one keeps every plan",
                     "with its removal staged", "<code>/lifetime list</code> shows the age in force",
                     "no live session was kept until a plan came of age"):
            self.assertIn(said, row, said)
        self.assertNotIn("a plan with neither stays", text)
        open_still = text.split('id="not-confirmed"', 1)[1].split("</section>", 1)[0]
        self.assertIn("with no rule written", open_still)

    def test_the_plugins_compaction_puts_no_typed_looking_list_into_the_transcript(self):
        """The compaction row says how the list reaches the model since 0.3.46, by which call the module compacts
        and where it falls back, and what a scripted session showed. What the desktop app still draws like a typed
        message, what was tried against it and what was not seen is among what the docs do not confirm."""
        text = page()
        row = rows(text)["compaction"]
        for said in ("Since p4-temportal 0.3.46", "additional context of the SessionStart",
                     "no row of the transcript reads as a message ezexe typed", "recorded as the session's last prompt",
                     "It asks by <code>$.session.compact</code>", "with no words after it",
                     "not available in a headless (-p / SDK) session yet", "35,449 tokens to 8,704",
                     "nothing after the command's name", "no row of the user's that holds the list",
                     "stayed the prompt a person had sent", "the first carried from the list before",
                     "adds their output to the compacted context", "with no new version",
                     "<code>session-compact-from-a-module</code>"):
            self.assertIn(said, row, said)
        open_still = text.split('id="not-confirmed"', 1)[1].split("</section>", 1)[0]
        for said in ('id="drawn"', "The list is no message any more", "<code>list_events</code>",
                     "each a turn of the user's", "did not draw", "What is left is the command's own row",
                     "It cannot be taken out by a plugin", "<code>$.prompt.submit</code>",
                     "<code>session.append</code>", "Not seen on screen with 0.3.46"):
            self.assertIn(said, open_still, said)

    def test_the_first_sessions_plan_is_copied_into_the_store(self):
        """The plans row says how the plan of the session whose start wrote the key reaches the store, that the
        original stays, and what the live checks showed of a move and of the copy."""
        row = rows(page())["plans"]
        for said in ("The plan of that first session reaches the store all the same", "copies the ones in",
                     "The original stays", "the same bytes as the original",
                     "A move was tried first and taken back", "made it anew",
                     "the store's copy held the edit"):
            self.assertIn(said, row, said)

    def test_the_page_says_what_was_set_out_and_what_the_docs_do_not_confirm(self):
        text = page()
        set_out = text.split('id="set-out"', 1)[1].split("</section>", 1)[0]
        for said in ("f2323b2", "b01f260", "58bdde0", "Native first", "compaction first"):
            self.assertIn(said, set_out, said)
        open_still = text.split('id="not-confirmed"', 1)[1].split("</section>", 1)[0]
        for said in ("consolidate-memory", "session.compact", "plansDirectory", "watchPaths"):
            self.assertIn(said, open_still, said)

    def test_the_page_writes_no_parenthetical(self):
        """ezexe's rule for prose: a thought gets its own sentence or is dropped. Code is not prose."""
        text = page().split("</style>", 1)[1].split("<script>", 1)[0]
        prose = re.sub(r"<code>.*?</code>", "", text, flags=re.S)
        prose = re.sub(r"<[^>]+>", "", prose)
        self.assertNotIn("(", prose)
        self.assertNotIn(")", prose)

    def test_every_link_of_the_page_leads_somewhere(self):
        text = page()
        ids = set(re.findall(r'\bid="([^"]+)"', text))
        links = re.findall(r'href="([^"]+)"', text)
        self.assertTrue(links)
        for href in links:
            if href.startswith(("https://", "data:")):
                continue
            target, _, frag = href.partition("#")
            if target:
                self.assertTrue((DOX / target).is_file(), href)
            if frag:
                there = ids if not target else set(re.findall(r'\bid="([^"]+)"',
                                                              (DOX / target).read_text(encoding="utf-8")))
                self.assertIn(frag, there, href)


if __name__ == "__main__":
    unittest.main()
