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
WALKED = ("command", "tool", "hook", "event", "method")
# the functions of the state library a module imports from `claude-code`, each with the methods of `$` it calls
STATE_HELPERS = {"read": ("$.state.get",), "update": ("$.state.get", "$.state.set")}
PLUGIN_NAMES = sorted(p.name for p in PLUGINS.iterdir() if (p / ".claude-plugin" / "plugin.json").is_file())


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
            # the state library of `claude-code`: `read` is a `$.state.get`, and `update` reads and then writes
            helpers = re.search(r"import \{([^}]*)\} from 'claude-code'", text)
            for helper in re.findall(r"\w+", helpers.group(1)) if helpers else []:
                if helper in STATE_HELPERS and re.search(rf"\b{helper}\(\$,", text):
                    out.extend(("method", method, folder.name) for method in STATE_HELPERS[helper])
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

    def test_the_nine_tools_no_audit_weighed_have_a_verdict(self):
        """The goal tools are in the build's types and in no session's tool list, so `SetGoal` is open for p4-phi
        behind p4-native's probe and the other two are declined. The Task tools and `TodoWrite` are declined, and
        `MultiEdit` and `KillShell`, which p4-phi's matchers name, are used by it."""
        self.assertEqual(ROWS["SetGoal"]["open"], ["p4-phi"])
        self.assertIn("`set-goal-tool`", ROWS["SetGoal"]["would"]["p4-phi"])
        for key in ("GetGoal", "PauseGoal", "TaskCreate", "TaskList", "TaskUpdate", "TodoWrite"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)
            self.assertEqual(sorted(ROWS[key]["declined"]), PLUGIN_NAMES, key)
        matcher = (PLUGINS / "p4-phi" / "hooks" / "hooks.json").read_text(encoding="utf-8")
        for key in ("MultiEdit", "KillShell"):
            self.assertIn(f"|{key}|", matcher, key)
            self.assertEqual(ROWS[key]["used"], ["p4-phi"], key)
        self.assertEqual(ROWS["$.settings.read"].get("open"), ["p4-phi"])
        self.assertEqual(ROWS["$.settings.read"].get("used"), ["p4-temportal"])
        self.assertFalse([key for key, row in ROWS.items() if row.get("nobody")])

    def test_no_row_of_a_walked_kind_says_weighed_by_nobody(self):
        """The slash commands of the desktop build were walked one by one, the seven the inventory found with no
        row among them, and so were the hook events of hooks.md and the events and methods of the hooks module as
        the types file of Claude Code 2.1.326 lists them, so each comes to used, open or declined."""
        for key, row in ROWS.items():
            if row["kind"] in WALKED:
                self.assertNotEqual(verdict(row), "nobody", key)
                self.assertIsNone(row.get("nobody"), key)
        for key in ("/motion", "/artifact-design", "/whiteboard", "/keybindings-help", "/__remote-workflow",
                    "/workflow-launch-exec", "/extra-usage", "/send-to-project"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)
        self.assertEqual(sum(1 for row in ROWS.values() if row["kind"] == "hook"), 33)
        for key in ("Setup", "WorktreeCreate", "PermissionRequest", "PostCompact", "TeammateIdle"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)
        self.assertEqual(ROWS["Notification"]["open"], ["p4-native"])
        self.assertEqual(ROWS["PostToolBatch"]["open"], ["p4-phi"])
        counts = {kind: sum(1 for row in ROWS.values() if row["kind"] == kind) for kind in KINDS}
        self.assertEqual((counts["event"], counts["method"]), (51, 93))
        for key in ("$.mcp.call", "$.store.get", "$.model.complete", "$.ui.ask", "tool.describe", "ui.press"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)
        self.assertEqual(ROWS["$.process.hookEnv"]["open"], ["p4-phi", "p4-temportal"])
        self.assertEqual(ROWS["$.ui.notify"]["open"], ["p4-native"])
        self.assertEqual(ROWS["session.attach"]["open"], ["p4-native"])
        self.assertEqual(ROWS["session.detach"]["open"], ["p4-native"])

    def test_the_state_library_counts_as_the_methods_it_calls(self):
        """p4-phi's pane reads and writes `$.state` through `read` and `update` of `claude-code`, which no pattern
        of `$.state.get(` finds, so the record had both methods as weighed by nobody."""
        found = uses()
        self.assertIn(("method", "$.state.get", "p4-phi"), found)
        self.assertIn(("method", "$.state.set", "p4-phi"), found)
        self.assertEqual(ROWS["$.state.set"]["used"], ["p4-phi"])

    def test_an_open_row_names_a_plugin_and_what_it_would_replace_or_add_there(self):
        """`open` lists plugins of this repository, and `would` holds one sentence for each of them and for no
        other, which begins with what the plugin would do: replace a copy it builds by hand or add what it cannot
        do today."""
        opened = {key: row for key, row in ROWS.items() if row.get("open")}
        self.assertGreater(len(opened), 2)
        for key, row in opened.items():
            self.assertEqual(row["open"], sorted(row["open"]), key)
            for plugin in row["open"]:
                self.assertIn(plugin, PLUGIN_NAMES, key)
                self.assertNotIn(plugin, row.get("declined") or {}, key)
            would = row.get("would") or {}
            self.assertEqual(sorted(would), row["open"], key)
            for plugin, sentence in would.items():
                self.assertRegex(sentence, r"^(replace|add|read) .{40,}\.$", f"{key}, {plugin}")
        for key, row in ROWS.items():
            self.assertFalse(row.get("would") and not row.get("open"), key)

    def test_a_declined_row_gives_each_of_the_three_plugins_a_reason_once_walked(self):
        for key, row in ROWS.items():
            if row["kind"] in ("hook", "event", "method") and verdict(row) == "declined":
                self.assertEqual(sorted(row["declined"]), PLUGIN_NAMES, key)


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
