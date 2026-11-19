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
                    "/send-to-project", "$.mcp.call"):
            self.assertIs(ROWS[key].get("nobody"), True, key)
        self.assertEqual(ROWS["$.settings.read"].get("open"), ["p4-phi", "p4-temportal"])


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
        counts = {kind: sum(1 for r in ROWS.values() if r["kind"] == kind) for kind in KINDS}
        self.assertIn(f"{len(ROWS)} rows", section)
        for kind in ("hook", "event", "method"):
            nobody = sum(1 for r in ROWS.values() if r["kind"] == kind and r.get("nobody"))
            self.assertIn(f"{nobody} of the {counts[kind]}", section, kind)


if __name__ == "__main__":
    unittest.main()
