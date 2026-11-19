"""Deciding tests for p4-native's record of what was weighed, hooks/weighed.json: that it holds what each of the
three plugins uses as their own files have it, that each row comes to a verdict, and that the module names a
command or a tool of the build only when it has no row."""
import json
import re
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
PLUGINS = LBIZA / "plugins"
# the folder of the code these tests read
PLUGIN = PLUGINS / "p4-native"
RECORD = json.loads((PLUGIN / "hooks" / "weighed.json").read_text(encoding="utf-8"))
ROWS = RECORD["rows"]
MODULE = (PLUGIN / "hooks" / "register.ts").read_text(encoding="utf-8")
README = (PLUGIN / "README.md").read_text(encoding="utf-8")
KINDS = ("command", "tool", "hook", "event", "method")
# the kinds walked row by row, so none of their rows says weighed by nobody
WALKED = ("command",)


def verdict(row):
    """What a row comes to in one word, as `verdictOf` of inventory.ts has it."""
    if row.get("used"):
        return "used"
    if row.get("open"):
        return "open"
    return "declined" if row.get("declined") else "nobody"


def uses():
    """What each plugin's own files use, as (kind, key, plugin): the events its module hooks, the methods it calls,
    the hook events it runs or hooks, and the desktop app's tools it names."""
    out = []
    for folder in sorted(p for p in PLUGINS.iterdir() if (p / ".claude-plugin" / "plugin.json").is_file()):
        hooks = folder / "hooks"
        for file in sorted(hooks.glob("*.ts")):
            if file.name.endswith(".test.ts"):
                continue
            text = file.read_text(encoding="utf-8")
            for name in re.findall(r"\bon\('([a-z]+\.[A-Za-z.]+)'", text):
                kind = "hook" if name.startswith("classic.") else "event"
                out.append((kind, name.removeprefix("classic."), folder.name))
            for name in re.findall(r"\$\.([a-z]+\.[A-Za-z]+)\(", text):
                out.append(("method", "$." + name, folder.name))
            for name in re.findall(r"'(mcp__ccd_\w+__\w+|PushNotification)'", text):
                out.append(("tool", name, folder.name))
        config = hooks / "hooks.json"
        if config.is_file():
            for name in json.loads(config.read_text(encoding="utf-8")).get("hooks", {}):
                out.append(("hook", name, folder.name))
    return sorted(set(out))


class RecordTest(unittest.TestCase):
    def test_every_row_has_a_kind_and_comes_to_a_verdict(self):
        self.assertRegex(RECORD["claude"], r"^\d+\.\d+\.\d+$")
        self.assertGreater(len(ROWS), 300)
        for key, row in ROWS.items():
            self.assertIn(row["kind"], KINDS, key)
            self.assertTrue(row.get("used") or row.get("open") or row.get("declined") or row.get("nobody") is True, key)
            for plugin, why in (row.get("declined") or {}).items():
                self.assertTrue(plugin and why, key)
            self.assertFalse(row.get("nobody") and row.get("used"), key)

    def test_a_key_is_spelled_as_its_kind_is(self):
        for key, row in ROWS.items():
            if row["kind"] == "command":
                self.assertRegex(key, r"^/[a-z_][a-z_-]*\*?$", key)
            elif row["kind"] == "method":
                self.assertRegex(key, r"^\$\.[a-z]+\.[A-Za-z]+$", key)
            elif row["kind"] == "event":
                self.assertRegex(key, r"^[a-z]+\.[A-Za-z.]+$", key)
            else:
                self.assertRegex(key, r"^[A-Za-z][A-Za-z_]*$", key)

    def test_the_record_holds_what_each_plugins_own_files_use(self):
        """A plugin that begins to hook an event, call a method or name a tool of the desktop app gains its row
        here in the same commit, so the record never says nobody weighed what a plugin runs on."""
        found = uses()
        self.assertGreater(len(found), 60)
        for kind, key, plugin in found:
            row = ROWS.get(key) or next((r for k, r in ROWS.items() if k.endswith("__") and key.startswith(k)), None)
            self.assertIsNotNone(row, f"{key}, used by {plugin}, has no row")
            self.assertEqual(row["kind"], kind, key)
            self.assertIn(plugin, row.get("used") or [], f"{key} is used by {plugin}")

    def test_the_names_no_audit_weighed_are_marked_so(self):
        for key in ("SetGoal", "GetGoal", "PauseGoal", "TaskCreate", "TodoWrite", "MultiEdit", "KillShell",
                    "$.mcp.call"):
            self.assertIs(ROWS[key].get("nobody"), True, key)
        self.assertEqual(ROWS["$.settings.read"].get("open"), ["p4-phi", "p4-temportal"])

    def test_no_row_of_a_walked_kind_says_weighed_by_nobody(self):
        """The slash commands of the desktop build were walked one by one, the seven the inventory found with no
        row among them, so each comes to used, open or declined."""
        for key, row in ROWS.items():
            if row["kind"] in WALKED:
                self.assertNotEqual(verdict(row), "nobody", key)
                self.assertIsNone(row.get("nobody"), key)
        for key in ("/motion", "/artifact-design", "/whiteboard", "/keybindings-help", "/__remote-workflow",
                    "/workflow-launch-exec", "/extra-usage", "/send-to-project"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)


class ModuleTest(unittest.TestCase):
    def test_the_inventory_runs_with_the_probes_and_on_request_and_never_at_a_start(self):
        self.assertIn("const RECORD = 'hooks/weighed.json'", MODULE)
        self.assertEqual(MODULE.count("await weigh($, host)"), 2, "in `run` and in `inventory`")
        start = MODULE.split("on('session.start'", 1)[1].split("\n  })", 1)[0]
        self.assertNotIn("weigh(", start)
        run = MODULE.split("async function run(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("settle($, host, answers, true, weighed?.missing)", run)

    def test_only_the_hosts_own_commands_and_tools_are_held_against_the_record(self):
        """A plugin's command and another server's tool are no part of the host: the slash commands Claude Code
        ships, its own tools and the desktop app's are."""
        weigh = MODULE.split("async function weigh(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(".filter(command => command.source === 'builtin')", weigh)
        self.assertIn("unweighed(record.rows, [...commands, ...host.tools.native, ...host.tools.app])", weigh)

    def test_a_name_with_no_row_is_told_once_for_a_kind_of_host(self):
        self.assertIn("const fresh = missing.filter(name => !told.has(name))", MODULE)
        self.assertIn("ran.unweighed = [...missing]", MODULE)
        self.assertIn("that no p4 plugin ` +\n          `has weighed: ${fresh.join(', ')}.", MODULE)


class ReadmeTest(unittest.TestCase):
    def test_the_readme_says_what_the_record_holds_and_what_a_module_cannot_list(self):
        section = README.split("## The inventory\n", 1)[1].split("\n## ", 1)[0]
        for words in ("`hooks/weighed.json`", "weighed by nobody", "`/native weighed`", "cannot list",
                      "`/motion`", "`/whiteboard`"):
            self.assertIn(words, section)
        self.assertIn(f"{len(ROWS)} rows", section)

    def test_the_readme_says_how_many_rows_of_each_kind_are_used_open_and_declined(self):
        """The five lines are the ones `counted` of inventory.ts prints for `/native weighed`."""
        section = README.split("## The inventory\n", 1)[1].split("\n## ", 1)[0]
        for kind in KINDS:
            of = [verdict(row) for row in ROWS.values() if row["kind"] == kind]
            count = of.count
            self.assertIn(f"- `{kind}`: {len(of)} rows, {count('used')} used, {count('open')} open, "
                          f"{count('declined')} declined, {count('nobody')} weighed by nobody\n", section, kind)
        for kind in ("hook", "event", "method"):
            if kind not in WALKED:
                nobody = sum(1 for r in ROWS.values() if r["kind"] == kind and r.get("nobody"))
                total = sum(1 for r in ROWS.values() if r["kind"] == kind)
                self.assertIn(f"{nobody} of the {total}", section, kind)


if __name__ == "__main__":
    unittest.main()
