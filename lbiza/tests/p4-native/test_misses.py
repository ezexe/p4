"""Deciding tests for p4-native's lines at a miss: that each row has a miss seen live behind it and is listed in the
README, and that the module refuses no call, swallows no other hook's answer, starts no process and can be turned
off."""
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
ROWS = [(m.group(1), m.group(2), m.group(3)) for m in
        re.finditer(r"(?s)id: '([a-z-]+)',\n    seen: (.+?),\n    names: .+?\n    at: '(call|end)',", LIST)]


class TableTest(unittest.TestCase):
    def test_each_row_has_a_miss_seen_live_behind_it_and_is_in_the_readme(self):
        """A row goes in only with a miss seen live, so each says when it was seen, and none comes from a guess."""
        self.assertEqual(len(ROWS), LIST.count("    id: '"))
        self.assertEqual(len(ROWS), 6)
        for name, seen, at in ROWS:
            self.assertIn("seen on 2026-11-19", seen, name)
            where = "after a call" if at == "call" else "at a turn's end"
            self.assertIn(f"- `{name}`, {where}: ", SECTION, name)

    def test_a_row_is_a_pattern_and_no_model_judges_it(self):
        for word in ("$.model", "$.process", "$.http", "$.agent", "import type { EngineInterface"):
            self.assertNotIn(word, MISSES)


class HookTest(unittest.TestCase):
    HOOK = MODULE.split("on('classic.PostToolUse'", 1)[1].split("\n\n  on(", 1)[0]

    def test_the_hook_passes_on_what_the_hooks_beneath_answered_and_only_adds_context(self):
        """A function at `classic.PostToolUse` that answers without `next` skips every other plugin's hooks. This
        one calls `next` first, hands its answer back whole, and puts its line after the context already there."""
        self.assertIn("const out = await next(e)", self.HOOK)
        self.assertLess(self.HOOK.index("const out = await next(e)"), self.HOOK.index("await called("))
        self.assertIn("return lines.length === 0 ? out : { ...out, additionalContext: [...(out.additionalContext ?? []), ...lines] }",
                      self.HOOK)
        self.assertIn(".catch(($, e, next) => next(e))", self.HOOK)

    def test_it_refuses_no_call_and_starts_no_process(self):
        for word in ("deny", "block", "preventContinuation"):
            self.assertNotIn(word, self.HOOK)
        self.assertNotIn("$.process.", MODULE)
        self.assertEqual(MODULE.count("on('classic."), 1)
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
