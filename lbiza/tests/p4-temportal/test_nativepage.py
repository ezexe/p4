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
        quoted = set(re.findall(r"<code>([a-z/-]+\.md)</code>", body)) - {"CONTRIBUTING.md"}
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
