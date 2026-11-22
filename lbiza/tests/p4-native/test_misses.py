"""Deciding tests for p4-native's lines at a miss: that each row has a miss seen live or a by-hand way behind it and
is listed in the README, that every row of the record a plugin uses is watched by a row or says why none watches
it, and that the module refuses no call, swallows no other hook's answer, starts no process and can be turned off."""
import json
import re
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
# the folder of the code these tests read
PLUGIN = LBIZA / "plugins" / "p4-native"
MISSES = (PLUGIN / "hooks" / "misses.ts").read_text(encoding="utf-8")
MODULE = (PLUGIN / "hooks" / "register.ts").read_text(encoding="utf-8")
README = (PLUGIN / "README.md").read_text(encoding="utf-8")
SECTION = README.split("## One line at a miss\n", 1)[1].split("\n## ", 1)[0]

LIST = MISSES.split("export const MISSES: readonly Miss[] = [", 1)[1].split("\n]\n", 1)[0]
# each row as (id, `seen` or `hand`, that field's sentence, the keys of the record it stands for, where it is checked)
ROWS = [(m.group(1), m.group(2), m.group(3), re.findall(r"'([^']+)'", m.group(4)), m.group(5)) for m in
        re.finditer(r"(?s)id: '([a-z-]+)',\n    (seen|hand): (.+?),\n    native: \[(.*?)\],\n    names: .+?\n    at: '(call|end)',",
                    LIST)]
RECORD = json.loads((PLUGIN / "hooks" / "weighed.json").read_text(encoding="utf-8"))["rows"]


class TableTest(unittest.TestCase):
    def test_each_row_has_a_miss_seen_live_or_a_by_hand_way_behind_it_and_is_in_the_readme(self):
        """Six rows went in with a miss seen live, and each says when. The others are written from the record,
        each with the by-hand way it is read off, which the README gives beside the rows it stands for."""
        self.assertEqual(len(ROWS), LIST.count("    id: '"))
        self.assertEqual(len(ROWS), 43)
        self.assertEqual(len({name for name, *_ in ROWS}), 43, "an id is one row's")
        self.assertEqual(sum(1 for _, field, *_ in ROWS if field == "seen"), 6)
        for name, field, sentence, native, at in ROWS:
            where = "after a call" if at == "call" else "at a turn's end"
            self.assertIn(f"- `{name}`, {where}: ", SECTION, name)
            if field == "seen":
                self.assertIn("seen on 2026-11-19", sentence, name)
                continue
            self.assertTrue(native, f"{name} is written from the record and stands for no row of it")
            line = next(line for line in SECTION.splitlines() if line.startswith(f"- `{name}`, "))
            said = sentence.strip()[1:-1].replace("\\'", "'")
            self.assertIn(said[1:], line, name)
            for key in native:
                self.assertIn(f"`{key}`", line.split(" It stands for ", 1)[1], name)

    def test_every_row_of_the_record_a_plugin_uses_is_watched_or_says_why_not(self):
        """A used row names under `miss` the rows of the table that watch it, or says under `nowatch` in one line
        why no by-hand call exists to watch, and never both. A row of the table stands for rows of the record,
        and each of those names it back, so neither file can move without the other."""
        ids = {name: native for name, _, _, native, _ in ROWS}
        used = {key: row for key, row in RECORD.items() if row.get("used")}
        self.assertGreater(len(used), 120)
        for key, row in used.items():
            self.assertTrue(bool(row.get("miss")) != bool(row.get("nowatch")), f"{key} is watched or says why not, and not both")
        for key, row in RECORD.items():
            for name in row.get("miss") or []:
                self.assertIn(name, ids, f"{key} names a row the table lacks")
                self.assertIn(key, ids[name], f"{name} does not stand for {key}")
            if "nowatch" in row:
                self.assertIn(key, used, f"{key} says why no row watches it and no plugin uses it")
                self.assertRegex(row["nowatch"], r"^[A-Z][^\n]{40,}\.$", key)
        for name, native in ids.items():
            for key in native:
                self.assertIn(name, RECORD[key].get("miss") or [], f"{key} does not name {name}")
        # only a hooks module hooks an event or calls a method, so none of those rows has a by-hand call
        for key, row in used.items():
            if row["kind"] in ("hook", "event", "method"):
                self.assertIn("a session has no call that does this by hand", row["nowatch"], key)
        by_miss = sum(1 for row in used.values() if row.get("miss"))
        self.assertIn(f"Of the {len(used)} used rows, {by_miss} are watched by a row of the table and {len(used) - by_miss} say why "
                      "none watches them", SECTION)
        inventory = README.split("## The inventory\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"- `used`: {len(used)} rows, {by_miss} watched by a row of misses.ts, {len(used) - by_miss} with no by-hand "
                      "call to watch, 0 with neither\n", inventory)

    def test_a_row_is_a_pattern_and_no_model_judges_it(self):
        for word in ("$.model", "$.process", "$.http", "$.agent", "import type { EngineInterface"):
            self.assertNotIn(word, MISSES)


class RefusalTest(unittest.TestCase):
    MANIFEST = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["userConfig"]
    REFUSES = README.split("## A row's option refuses the by-hand call\n", 1)[1].split("\n## ", 1)[0]

    def test_each_row_checked_at_a_call_has_an_option_that_is_off_by_default(self):
        """https://code.claude.com/docs/en/plugins/manifest-reference.md, "User configuration": a key takes letters,
        digits and underscores, `options` "applies to a `string` field that isn't `multiple`", and a `multiple` list
        is no row of `/config`, so each row has one boolean of its own. A row checked at a turn's end has none,
        since an answer already written is no call to refuse."""
        at_a_call = ["refuse_" + name.replace("-", "_") for name, _, _, _, at in ROWS if at == "call"]
        self.assertEqual(len(at_a_call), 35)
        self.assertEqual(sorted(name for name in self.MANIFEST if name.startswith("refuse_")), sorted(at_a_call))
        for name in at_a_call:
            option = self.MANIFEST[name]
            self.assertRegex(name, r"^[a-z][a-z0-9_]*$")
            self.assertEqual(option["type"], "boolean", name)
            self.assertIs(option["default"], False, name)
            self.assertTrue(option["title"].startswith("Refuse: "), name)
            self.assertIn("With this on, the call is refused before it runs and the refusal names ", option["description"], name)
            self.assertNotIn("required", option, name)
        self.assertIn("return `refuse_${id.replaceAll('-', '_')}`", MISSES)
        self.assertIn(f"{len(at_a_call)} in all", self.REFUSES)
        self.assertIn("The eight rows checked at a turn's end have no option", self.REFUSES)
        self.assertEqual(sum(1 for *_, at in ROWS if at == "end"), 8)

    def test_the_module_refuses_before_the_call_runs_and_only_where_an_option_is_on(self):
        """With no such option on the module hooks no call of another tool. With one on, the call is refused at
        `tool.call`, which comes before the permission check and the run, and every other call goes on."""
        self.assertIn("refused = new Set(MISSES.filter(miss => miss.at === 'call' && options[optionOf(miss.id)] === true)"
                      ".map(miss => miss.id))", MODULE)
        gate = MODULE.split("  if (refused.size > 0) {\n", 1)[1].split("\n  }\n", 1)[0]
        self.assertIn("on('tool.call', async ($, e, next) => {", gate)
        self.assertIn("return line === undefined ? next(e) : { deny: line }", gate)
        self.assertIn(".catch(($, e, next) => next(e))", gate)
        self.assertEqual(MODULE.count("on('tool.call', async ($, e, next) => {"), 1, "the one hook with no tool named")
        refusal = MODULE.split("async function refusal(", 1)[1].split("\n}\n", 1)[0]
        for part in ("!READ_OFF.has(tool)", "startsWith('toolu_plugin_')", "if (miss === undefined || !refused.has(id)) continue",
                     "if (miss.names.length > 0 && here.length === 0) continue", "optionOf(id)"):
            self.assertIn(part, refusal)
        self.assertNotIn("hints", refusal, "a refusal is no line, so the switch for the lines does not turn it off")

    def test_a_tool_a_refusal_can_stop_is_one_the_table_reads(self):
        read_off = set(re.findall(r"'(\w+)'", MISSES.split("export const READ_OFF = new Set([", 1)[1].split("])", 1)[0]))
        watched = set(re.findall(r"'(\w+)'", MISSES.split("export const WATCHED = new Set([", 1)[1].split("])", 1)[0]))
        self.assertTrue(read_off <= watched, read_off - watched)
        self.assertEqual(len(read_off), 11)


class HookTest(unittest.TestCase):
    CAUGHT = ".catch(($, e, next) => next(e))"
    HOOK = MODULE.split("on('classic.PostToolUse'", 1)[1].split(CAUGHT, 1)[0] + CAUGHT

    def test_the_hook_passes_on_what_the_hooks_beneath_answered_and_only_adds_context(self):
        """A function at `classic.PostToolUse` that answers without `next` skips every other plugin's hooks. This
        one calls `next` first, hands its answer back whole, and puts its line after the context already there."""
        self.assertIn("const out = await next(e)", self.HOOK)
        self.assertLess(self.HOOK.index("const out = await next(e)"), self.HOOK.index("await called("))
        self.assertIn("return lines.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...lines] }",
                      self.HOOK)
        self.assertIn(".catch(($, e, next) => next(e))", self.HOOK)

    def test_a_line_refuses_no_call_and_the_module_starts_no_process(self):
        for word in ("deny", "block", "preventContinuation"):
            self.assertNotIn(word, self.HOOK)
        self.assertNotIn("$.process.", MODULE)
        self.assertEqual(MODULE.count("on('classic."), 2, "after a tool call, and at a notification of Claude Code's own")
        self.assertNotIn("on('classic.PreToolUse'", MODULE)

    def test_the_option_turns_it_off_and_a_modules_own_call_is_no_miss(self):
        self.assertIn("if (!wants.hints || isOwn || !WATCHED.has(e.tool_name)) return out", self.HOOK)
        self.assertIn("startsWith('toolu_plugin_')", self.HOOK)
        end = MODULE.split("on('turn.complete'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("if (e.agentId === undefined && wants.hints && !e.isAborted) {", end)


class LineTest(unittest.TestCase):
    HINTS = MODULE.split("function hints(", 1)[1].split("\n}\n", 1)[0]

    def test_a_situation_is_told_once_in_a_session(self):
        self.assertIn("if (miss === undefined || hinted.has(id)) continue", self.HINTS)
        self.assertIn("hinted.add(id)", self.HINTS)
        start = MODULE.split("on('session.start'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("hinted.clear()", start)

    def test_a_line_names_only_a_tool_the_map_says_answers_here(self):
        self.assertIn("const here = miss.names.filter(name => answersHere(host, name))", self.HINTS)
        self.assertIn("if (miss.names.length > 0 && here.length === 0) continue", self.HINTS)
        answers = MODULE.split("function answersHere(", 1)[1].split("\n}\n", 1)[0]
        for part in ("host.tools.native.includes(name)", "host.tools.app.includes(name)", "host.tools.servers[server]"):
            self.assertIn(part, answers)

    def test_a_turns_end_line_reaches_ezexe_at_once_and_the_model_with_the_next_prompt(self):
        end = MODULE.split("on('turn.complete'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("for (const line of lines) $.ui.log(line)", end)
        self.assertIn("waiting.push(...lines)", end)
        prompt = MODULE.split("on('prompt.submit'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("const lines = [...notices, ...waiting]", prompt)
        self.assertIn("waiting = []", prompt)


if __name__ == "__main__":
    unittest.main()
