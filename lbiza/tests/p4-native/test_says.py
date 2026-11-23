"""Deciding tests for the lines for sessions of p4-native's record: that each row of a kind a module cannot list
carries one, that a row of the kind `doc` stands for a page of the docs index, that a command's and a tool's line is
read from the session and kept nowhere, and that lbiza/scripts/native_says.py reads each source as it is written."""
import importlib.util
import json
import re
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
# the folder of the code these tests read
PLUGIN = LBIZA / "plugins" / "p4-native"
ROWS = json.loads((PLUGIN / "hooks" / "weighed.json").read_text(encoding="utf-8"))["rows"]
MANIFEST = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
MODULE = (PLUGIN / "hooks" / "register.ts").read_text(encoding="utf-8")
INVENTORY = (PLUGIN / "hooks" / "inventory.ts").read_text(encoding="utf-8")
README = (PLUGIN / "README.md").read_text(encoding="utf-8")
SECTION = README.split("## What a row says, and what is new in a build\n", 1)[1].split("\n## ", 1)[0]

_spec = importlib.util.spec_from_file_location("native_says", LBIZA / "scripts" / "native_says.py")
SAYS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SAYS)

TYPES = """\
      session: {
          /**
           * Returns the session's root folder, absolute.
           * A second sentence that is left out.
           *
           * @example
           * await $.session.root()
           */
          root: () => Promise<string>;
          /**
           * The machine the session runs on: its name and its system.
           */
          machine: EventCalls['session']['machine'];
          /**
           * A property and no call.
           */
          label: string;
      };
  /**
   * The input of `session.attach`: a surface joined the session's roster
   * of attached clients. Every field is the engine's.
   */
  export type SessionAttachInput = {
  /**
   * The input of `vcs.diff`; every key is pinned, so no hook passes another down.
   */
  export type VcsDiffInput = {
""".split("\n")
HOOKS = """\
## Hook lifecycle

| Event | When it fires |
| :- | :- |
| `SessionStart` | When a session begins or resumes |
| `PreToolUse` | Before a tool call executes. Can [block](https://code.claude.com/docs/en/hooks.md#x) it |

More of the page.
"""
INDEX = """\
# Claude Code Docs

- [Hooks reference](https://code.claude.com/docs/en/hooks.md): Reference for hook events.
- [Use the mods API](https://code.claude.com/docs/en/plugins/mods/api.md): Call the mods API.
- [French (205 pages)](https://code.claude.com/docs/_llms/fr.txt): Premiers pas.
"""


class RecordTest(unittest.TestCase):
    def test_each_row_of_a_kind_a_module_cannot_list_says_what_it_does(self):
        """A hook event, a module event and a module method carry their line in the record, one line that ends as
        a sentence does."""
        for key, row in ROWS.items():
            if row["kind"] in ("hook", "event", "method"):
                self.assertRegex(row.get("says", ""), r"^[^\n]{12,300}[.!?)`]$", key)

    def test_a_commands_and_a_tools_line_is_read_from_the_session_and_kept_nowhere(self):
        """`$.command.list` and `$.tool.list` give each its own description, so the record holds no copy that a
        new build could leave stale."""
        for key, row in ROWS.items():
            if row["kind"] in ("command", "tool"):
                self.assertNotIn("says", row, key)
        looked = MODULE.split("async function lookedUp(", 1)[1].split("\n}\n", 1)[0]
        for part in ("await $.command.list()", "$.tool.list()", "brief(live?.description)", "isHere: live !== undefined"):
            self.assertIn(part, looked)
        lines = INVENTORY.split("export function rowLines(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("const says = (live.description ?? '') !== '' ? live.description : row.says", lines)

    def test_a_doc_row_stands_for_a_page_of_the_docs_index(self):
        docs = {key: row for key, row in ROWS.items() if row["kind"] == "doc"}
        self.assertGreater(len(docs), 150)
        for key, row in docs.items():
            self.assertEqual(sorted(row), ["kind", "page", "says"], key)
            self.assertEqual(row["page"], f"https://code.claude.com/docs/en/{key.removeprefix('docs:')}.md", key)
            self.assertRegex(row["says"], r"^[^\n]{8,300}$", key)
        for key in ("docs:hooks", "docs:settings", "docs:env-vars", "docs:cli-reference", "docs:plugins/mods/api"):
            self.assertIn(key, docs)
        self.assertIn(f"{len(docs)} rows", SECTION)


class ModuleTest(unittest.TestCase):
    def test_the_docs_index_is_fetched_through_the_host_from_a_host_the_manifest_declares(self):
        """https://code.claude.com/docs/en/plugins/manifest-reference.md: `network.hosts` lists the hosts a plugin
        reaches. The module makes one kind of request, of the docs index, and a refusal costs the probes nothing."""
        self.assertEqual(MANIFEST["network"], {"hosts": ["code.claude.com"]})
        self.assertIn("const INDEX = 'https://code.claude.com/docs/llms.txt'", MODULE)
        self.assertEqual(MODULE.count("$.http.fetch("), 1)
        fetched = MODULE.split("function fetched(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("$.http.fetch(INDEX)", fetched)
        self.assertIn("$.clock.after(CALL_MS, () => resolve(undefined))", fetched)
        self.assertEqual(ROWS["$.http.fetch"]["used"], ["p4-native"])
        self.assertNotIn("p4-native", ROWS["$.http.fetch"]["declined"])

    def test_what_is_new_in_a_build_is_kept_at_the_change_and_handed_at_each_start_behind_hints(self):
        check = MODULE.split("async function check(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("const line = !wants.hints || isDue || fresh?.claude !== kept.claude ? undefined : freshLine(kindOf(kept), fresh)",
                      check)
        self.assertIn("if (line !== undefined) waiting.push(line)", check)
        settle = MODULE.split("async function settle(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if (before !== undefined && ran.claude !== '' && ran.claude !== host.claude) {", settle)
        self.assertLess(settle.index("ran.names = [...more.names]"), settle.index("ran.claude = host.claude"))

    def test_a_word_that_is_no_command_is_looked_up(self):
        answer = MODULE.split("async function answer(", 1)[1].split("\n}\n", 1)[0]
        for part in ("if (name === 'docs') return documented($)", "if (name === 'new') return newHere($)",
                     "if (name !== 'map') return lookedUp($, name)"):
            self.assertIn(part, answer)
        self.assertNotIn("enum:", MODULE.split("const TOOL = {", 1)[1].split("} as const", 1)[0])


class ScriptTest(unittest.TestCase):
    def test_a_methods_line_is_the_first_sentence_of_its_comment_and_a_property_is_no_call(self):
        said, calls = SAYS.methods_of(TYPES)
        self.assertEqual(said["$.session.root"], "Returns the session's root folder, absolute.")
        self.assertEqual(said["$.session.machine"], "The machine the session runs on: its name and its system.")
        self.assertEqual(calls, {"$.session.root", "$.session.machine"})

    def test_an_events_line_is_what_its_inputs_comment_says(self):
        said, named = SAYS.events_of(TYPES)
        self.assertEqual(said, {"session.attach": "A surface joined the session's roster of attached clients."})
        # a comment that goes on after a semicolon gives no line, and its event is known to exist all the same,
        # which is how `vcs.diff` once had no row and was not printed as missing
        self.assertEqual(named, {"session.attach", "vcs.diff"})

    def test_a_hook_events_line_is_its_cell_of_the_lifecycle_table_with_no_link(self):
        self.assertEqual(SAYS.hooks_of(HOOKS), {"SessionStart": "When a session begins or resumes.",
                                                "PreToolUse": "Before a tool call executes. Can block it."})

    def test_a_page_of_the_index_is_keyed_by_its_path_and_a_translation_is_no_page(self):
        self.assertEqual(SAYS.pages_of(INDEX), [
            ("docs:hooks", "https://code.claude.com/docs/en/hooks.md", "Hooks reference: Reference for hook events."),
            ("docs:plugins/mods/api", "https://code.claude.com/docs/en/plugins/mods/api.md", "Use the mods API: Call the mods API."),
        ])
        pages = INVENTORY.split("export function pagesOf(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(r"/^- \[[^\]]+\]\(https:\/\/code\.claude\.com\/docs\/en\/([^)]+)\)/gm", pages, "the module reads the index the same way")

    def test_the_readme_gives_the_count_of_module_events_with_a_line_of_their_own(self):
        own = sum(1 for row in ROWS.values() if row["kind"] == "event" and not row["says"].startswith("An event of the hooks module"))
        self.assertIn(f"{own} of 60 module events", SECTION)


if __name__ == "__main__":
    unittest.main()
