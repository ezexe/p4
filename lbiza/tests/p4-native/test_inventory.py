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
# the events and methods the types file of Claude Code 2.1.330 holds and the record of 2.1.326 lacked
NEW_IN_2_1_330 = ("agent.report", "tool.offer", "ui.close", "vcs.detect", "vcs.diff", "vcs.isolate", "vcs.list", "vcs.release",
                  "vcs.status", "$.session.machine", "$.vcs.detect", "$.vcs.diff", "$.vcs.isolate", "$.vcs.list", "$.vcs.release",
                  "$.vcs.status")


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
            # a glob stands for the events its hook tests `next.event` against, which is how a module names an
            # event an older Claude Code lacks
            if re.search(r"\bon\('[a-z]+\.\*'", text):
                for name in re.findall(r"next\.event === '([a-z]+\.[A-Za-z.]+)'", text):
                    out.append(("event", name, folder.name))
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
            # a page of the docs index is no thing a plugin builds on, so its row carries no verdict
            if row["kind"] == "doc":
                self.assertFalse(set(row) & {"used", "open", "would", "declined", "nobody"}, key)
                continue
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
            elif row["kind"] == "doc":
                self.assertRegex(key, r"^docs:[a-z0-9][a-z0-9/_-]*$", key)
            else:
                # a tool's name, where an MCP server's own name may hold a hyphen, as `scheduled-tasks` does
                self.assertRegex(key, r"^[A-Za-z][A-Za-z_-]*$", key)

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
        `MultiEdit` and `KillShell` are declined by all three, and p4-phi names neither in its matchers, its
        hooks module or its scripts: one is a legacy name and the other a previous name of `TaskStop`."""
        self.assertEqual(ROWS["SetGoal"]["open"], ["p4-phi"])
        self.assertIn("`set-goal-tool`", ROWS["SetGoal"]["would"]["p4-phi"])
        # each of the three was tried through a module and looked for in a tool list on every kind of host
        hosts = "in the desktop app, in a terminal session at its prompt or in a scripted run"
        self.assertIn(hosts, ROWS["SetGoal"]["would"]["p4-phi"])
        for key in ("GetGoal", "PauseGoal"):
            self.assertIn(hosts, ROWS[key]["declined"]["p4-phi"], key)
            self.assertIn('rejected with "no tool named"', ROWS[key]["declined"]["p4-phi"], key)
        probes = (PLUGIN / "hooks" / "probes.ts").read_text(encoding="utf-8")
        fault = probes.split("id: 'set-goal-tool'", 1)[1].split("was:", 1)[0]
        for word in ("`SetGoal`", "`GetGoal`", "`PauseGoal`", "a terminal session at its prompt", "2.1.328"):
            self.assertIn(word, fault, word)
        for key in ("GetGoal", "PauseGoal", "TaskCreate", "TaskList", "TaskUpdate", "TodoWrite"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)
            self.assertEqual(sorted(ROWS[key]["declined"]), PLUGIN_NAMES, key)
        phi = PLUGINS / "p4-phi"
        named = [phi / "hooks" / "hooks.json", phi / "hooks" / "register.ts", phi / "hooks" / "recall-hook.sh",
                 *sorted((phi / "scripts").glob("*.py"))]
        for key in ("MultiEdit", "KillShell"):
            for file in named:
                self.assertNotIn(key, file.read_text(encoding="utf-8"), f"{key} in {file.name}")
            self.assertEqual(verdict(ROWS[key]), "declined", key)
            self.assertEqual(sorted(ROWS[key]["declined"]), PLUGIN_NAMES, key)
        self.assertIsNone(ROWS["$.settings.read"].get("open"))
        self.assertEqual(ROWS["$.settings.read"].get("used"), ["p4-phi", "p4-temportal"])
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
        self.assertEqual(ROWS["PostToolBatch"]["used"], ["p4-phi"])
        self.assertIsNone(ROWS["PostToolBatch"].get("open"))
        counts = {kind: sum(1 for row in ROWS.values() if row["kind"] == kind) for kind in KINDS}
        self.assertEqual((counts["event"], counts["method"]), (60, 100))
        for key in ("$.mcp.call", "$.store.get", "$.model.complete", "$.ui.ask", "tool.describe", "ui.press"):
            self.assertEqual(verdict(ROWS[key]), "declined", key)

    def test_the_rows_that_were_open_for_p4_native_and_p4_temportal_are_used(self):
        """Five rows stood open for the two plugins. Each module now hooks the event or calls the method, so the
        row names the plugin under `used` and says nothing more of what it would do. p4-phi's module took
        `$.process.hookEnv` up too, so that row is open for nobody."""
        found = uses()
        for kind, key in (("hook", "Notification"), ("event", "session.attach"), ("event", "session.detach"),
                          ("method", "$.ui.notify")):
            self.assertIn((kind, key, "p4-native"), found, key)
            self.assertEqual(ROWS[key]["used"], ["p4-native"], key)
            self.assertNotIn("open", ROWS[key], key)
            self.assertNotIn("would", ROWS[key], key)
        self.assertIn(("method", "$.process.hookEnv", "p4-temportal"), found)
        self.assertEqual(ROWS["$.process.hookEnv"]["used"], ["p4-phi", "p4-temportal"])
        self.assertNotIn("open", ROWS["$.process.hookEnv"])
        self.assertNotIn("would", ROWS["$.process.hookEnv"])
        temportal = (PLUGINS / "p4-temportal" / "hooks" / "register.ts").read_text(encoding="utf-8")
        self.assertIn("const env = { ...(await hookEnv($)), CLAUDE_PROJECT_DIR: await $.session.root() }", temportal)
        self.assertIn("const told = (await hookEnv($))?.CLAUDE_PLUGIN_DATA", temportal)

    def test_the_state_library_counts_as_the_methods_it_calls(self):
        """p4-phi's pane reads and writes `$.state` through `read` and `update` of `claude-code`, which no pattern
        of `$.state.get(` finds, so the record had both methods as weighed by nobody."""
        found = uses()
        self.assertIn(("method", "$.state.get", "p4-phi"), found)
        self.assertIn(("method", "$.state.set", "p4-phi"), found)
        self.assertEqual(ROWS["$.state.set"]["used"], ["p4-phi", "p4-temportal"])

    def test_a_glob_counts_as_the_events_its_hook_tests(self):
        """p4-temportal names `tool.*` and answers where `next.event` is `tool.run`, so it loads on a Claude Code
        with no such event. It still uses `tool.run`, and it reads the version to register no tool where the
        event is missing. It answers at `tool.call` too, where Claude Code 2.1.330 hands no `tool.run` to a glob."""
        found = uses()
        self.assertIn(("event", "tool.run", "p4-temportal"), found)
        self.assertIn(("event", "tool.call", "p4-temportal"), found)
        self.assertEqual(ROWS["tool.call"]["used"], ["p4-native", "p4-phi", "p4-temportal"])
        self.assertIn(("method", "$.session.version", "p4-temportal"), found)
        # p4-phi's module serves its four tools the same way, so it loads on those builds too: it answers at
        # `tool.run` where the glob is handed it and at `tool.call` where Claude Code 2.1.330 hands a glob none
        for use in (("event", "tool.run", "p4-phi"), ("event", "tool.call", "p4-phi"),
                    ("method", "$.session.version", "p4-phi")):
            self.assertIn(use, found)
        self.assertIn("p4-phi", ROWS["tool.call"]["used"])
        self.assertEqual(ROWS["tool.run"]["used"], ["p4-phi", "p4-temportal"])
        self.assertEqual(ROWS["$.session.version"]["used"], ["p4-native", "p4-phi", "p4-temportal"])

    def test_the_state_p4_temportal_keeps_for_a_reload_is_in_the_record(self):
        """p4-temportal's module keeps the end of the last turn in the session's state, so a module loaded anew
        inside the quiet minute still compacts, and it reads the time for it."""
        found = uses()
        for method in ("$.state.get", "$.state.set", "$.clock.now"):
            self.assertIn(("method", method, "p4-temportal"), found)
            self.assertIn("p4-temportal", ROWS[method]["used"], method)

    def test_an_open_row_names_a_plugin_and_what_it_would_replace_or_add_there(self):
        """`open` lists plugins of this repository, and `would` holds one sentence for each of them and for no
        other, which begins with what the plugin would do: replace a copy it builds by hand or add what it cannot
        do today."""
        opened = {key: row for key, row in ROWS.items() if row.get("open")}
        self.assertGreater(len(opened), 0, "the rows that wait on the host, each behind a probe")
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

    def test_the_record_holds_every_event_and_method_of_claude_code_2_1_330(self):
        """The types file of Claude Code 2.1.330 holds nine events and seven methods the record of 2.1.326 lacked.
        Each has a row that says what the thing does and carries the verdict of every p4 plugin: p4-temportal and
        p4-native declined all sixteen, and p4-phi declined it or holds it open."""
        self.assertEqual(RECORD["claude"], "2.1.330")
        self.assertEqual(len(NEW_IN_2_1_330), 16)
        for key in NEW_IN_2_1_330:
            row = ROWS[key]
            self.assertEqual(row["kind"], "method" if key.startswith("$.") else "event", key)
            self.assertLessEqual({"p4-native", "p4-temportal"}, set(row["declined"]), key)
            weighed = set(row["declined"]) | set(row.get("open") or []) | set(row.get("used") or [])
            self.assertEqual(sorted(weighed), PLUGIN_NAMES, key)
            self.assertTrue(row.get("says"), key)
        inventory = README.split("## The inventory\n", 1)[1].split("\n## ", 1)[0]
        for words in ("as Claude Code 2.1.330 has them", "`vcs.diff`", "`$.session.machine`"):
            self.assertIn(words, inventory)


class ModuleTest(unittest.TestCase):
    def test_the_inventory_runs_with_the_probes_and_on_request_and_never_at_a_start(self):
        self.assertIn("const RECORD = 'hooks/weighed.json'", MODULE)
        self.assertEqual(MODULE.count("await weigh($, host)"), 2, "in `run` and in `inventory`")
        start = MODULE.split("on('session.start'", 1)[1].split("\n  })", 1)[0]
        self.assertNotIn("weigh(", start)
        run = MODULE.split("async function run(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("settle($, host, answers, true, weighed?.missing, more)", run)

    def test_only_the_hosts_own_commands_and_tools_are_held_against_the_record(self):
        """A plugin's command and another server's tool are no part of the host: the slash commands Claude Code
        ships, its own tools and the desktop app's are."""
        weigh = MODULE.split("async function weigh(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn(".filter(command => command.source === 'builtin')", weigh)
        self.assertIn("const names = [...commands, ...host.tools.native, ...host.tools.app]", weigh)
        self.assertIn("return { record, missing: unweighed(record.rows, names), names }", weigh)

    def test_a_name_with_no_row_is_told_once_for_a_kind_of_host(self):
        self.assertIn("const fresh = missing.filter(name => !told.has(name))", MODULE)
        self.assertIn("ran.unweighed = [...missing]", MODULE)
        self.assertIn("that no p4 plugin ` +\n          `has weighed: ${fresh.join(', ')}.", MODULE)


class ReadmeTest(unittest.TestCase):
    def test_the_readme_says_what_the_record_holds_and_what_a_module_cannot_list(self):
        section = README.split("## The inventory\n", 1)[1].split("\n## ", 1)[0]
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
