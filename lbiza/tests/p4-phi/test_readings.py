#!/usr/bin/env python3
"""workflows/readings.js: the workflow p4-phi ships for the readings of an under-determined message.

    python -m pytest tests/p4-phi/test_readings.py

Checked, first against the rules workflows.md gives a saved script, "Edit a saved script" and "Behavior and limits":
`export const meta` is the first statement and a plain object literal with a `name` and a `description`; each title
`meta.phases` lists is one the body passes to `phase()`; the body loads no module and reads no clock and no random
number, which the runtime refuses; and the plugin's manifest leaves the `workflows` key out, so Claude Code scans the
default `workflows/` folder, which holds this one script.

Then the script's own logic, with its body run under node and `agent()` answered from a list, since the runtime is
Claude Code's and a test calls no model: one agent for each reading, each with the result schema; a reading that
changes no file, and none runs in a worktree; results that agree return
`collapsed` with the result; results that differ return `forked` with an option for each reading and a default; a
reading that cannot go on without ezexe returns its question as data and the run forks on it; a stopped or failed
agent is a lost reading; and fewer than two distinct readings is an error before any agent starts. The compare is the
one puppeteer.py made before the workflow took it over, so the table of pairs below is what that function answered,
and the two word lists the script carries are held to plans.COMMON and puppeteer.STOP.

The cases under node are skipped where no `node` is on the PATH. https://code.claude.com/docs/en/workflows.md
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
PLUGIN = os.path.dirname(SRC)
WORKFLOWS = os.path.join(PLUGIN, "workflows")
SCRIPT = os.path.join(WORKFLOWS, "readings.js")
sys.path.insert(0, SRC)
import plans  # noqa: E402
import puppeteer  # noqa: E402

NODE = shutil.which("node")

# The body of a workflow script run as the runtime runs it: an async function given `agent`, `parallel`, `phase`,
# `log` and `args`. `agent` answers from the scenario's replies in the order the script starts its agents.
HARNESS = r"""
const fs = require('fs')
const src = fs.readFileSync(process.argv[1], 'utf8').replace(/^export const meta/m, 'const meta')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', src)
const scenarios = JSON.parse(fs.readFileSync(0, 'utf8'))
;(async () => {
  const out = []
  for (const sc of scenarios) {
    const calls = [], logs = [], phases = []
    let i = 0
    const agent = async (prompt, opts) => {
      const reply = (sc.replies || [])[i++]
      calls.push({ prompt, opts })
      if (reply && reply.throws) throw new Error(reply.throws)
      return reply === undefined ? null : reply
    }
    const parallel = async thunks => Promise.all(thunks.map(t => t().catch(() => null)))
    const refused = async () => { throw new Error('not given to this script') }
    try {
      const returned = await run(agent, parallel, refused, t => phases.push(t), m => logs.push(m), sc.args,
                                 { total: null }, refused)
      out.push({ returned, calls, logs, phases })
    } catch (e) {
      out.push({ error: String(e.message || e), calls, logs, phases })
    }
  }
  process.stdout.write(JSON.stringify(out))
})()
"""

WORDS = "make the export either a CSV file or a JSON file"
CSV = {"result": "The export is written as a CSV file.", "question": ""}
JSON_ = {"result": "The export is written as a JSON file.", "question": ""}
ROWS = {"result": "The parser drops empty lines before counting rows.", "question": ""}

# What puppeteer.same_result answered for each pair before the workflow took the compare over.
PAIRS = [("The export is a CSV file.", "the  export is a csv file", True),
         ("The export is written as a CSV file.", "The export is written as a JSON file.", False),
         ("The parser drops empty lines before counting rows.",
          "Empty lines are dropped by the parser before rows are counted.", False),
         ("The parser drops empty lines before counting rows.",
          "The parser drops empty lines before counting the rows of a table.", True),
         ("Retry the upload three times with backoff.", "The upload is retried three times, with backoff.", True),
         ("The cache key includes the user id.",
          "The cache key includes the user id, the tenant id, the region and the locale.", False),
         ("greet returns the greeting in upper case", "greet ends the greeting with an exclamation mark", False),
         ("Yes.", "No.", False),
         ("The limit is 20 requests a minute.", "The limit is 20 requests a minute for each key.", True)]

SCENARIOS = {
    "fork": {"args": {"words": WORDS, "readings": ["a CSV file", {"text": "a JSON file", "writes": True}]},
             "replies": [CSV, JSON_]},
    "collapse": {"args": {"words": "w", "readings": ["a", "b"]},
                 "replies": [ROWS, {"result": "the parser drops empty lines before counting rows", "question": ""}]},
    "all lost": {"args": {"words": "w", "readings": ["a", "b"]}, "replies": [None, {"throws": "its agent failed"}]},
    "one lost": {"args": {"words": "w", "readings": ["a", "b"]}, "replies": [ROWS, None]},
    "question": {"args": {"words": "w", "readings": ["a", "b", "c"]},
                 "replies": [{"result": "It got as far as the upload.", "question": "Which bucket holds the exports?"},
                             ROWS, ROWS]},
    "all ask": {"args": {"words": "w", "readings": ["a", "b"]},
                "replies": [{"result": "", "question": "Which bucket?"}, {"result": "", "question": "Which region?"}]},
    "one reading": {"args": {"words": "w", "readings": ["only one", " Only  ONE "]}},
    "no args": {},
    "a list": {"args": ["x one", "y two"], "replies": [ROWS, ROWS]},
    "a string": {"args": json.dumps({"words": "w", "readings": ["x one", "y two"]}), "replies": [ROWS, ROWS]},
    "six": {"args": {"readings": ["1", "2", "3", "4", "5", "6"]}, "replies": [ROWS] * 4},
}
for k, (a, b, _) in enumerate(PAIRS):
    SCENARIOS[f"pair {k}"] = {"args": {"readings": ["a", "b"]},
                              "replies": [{"result": a, "question": ""}, {"result": b, "question": ""}]}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def meta_of(script):
    """The text of the `meta` object literal, from its opening brace to the brace that closes it."""
    start = script.index("{", script.index("export const meta"))
    depth = 0
    for k in range(start, len(script)):
        depth += {"{": 1, "}": -1}.get(script[k], 0)
        if not depth:
            return script[start:k + 1]
    raise AssertionError("the meta block is not closed")


class Script(unittest.TestCase):
    """What Claude Code asks of a saved script when it loads and runs it."""

    def setUp(self):
        self.script = read(SCRIPT)
        self.meta = meta_of(self.script)
        self.body = self.script[self.script.index(self.meta) + len(self.meta):]

    def test_meta_is_the_first_statement_and_a_plain_literal_with_a_name_and_a_description(self):
        self.assertTrue(self.script.startswith("export const meta = {"), "export const meta is the first statement")
        self.assertRegex(self.meta, r"\bname: 'readings'")
        self.assertRegex(self.meta, r"\bdescription: '[^']{20,}'")
        for mark, what in (("`", "a template"), ("${", "an interpolation"), ("...", "a spread"), ("(", "a call"),
                           (" + ", "a sum")):
            self.assertNotIn(mark, self.meta, f"meta holds {what}, and Claude Code then drops the command")

    def test_each_phase_meta_lists_is_one_the_body_starts(self):
        listed = re.findall(r"title: '([^']+)'", self.meta)
        started = re.findall(r"\bphase\('([^']+)'\)", self.body)
        self.assertEqual(listed, started)
        self.assertEqual(set(re.findall(r"\bphase: '([^']+)'", self.body)), set(listed), "each agent is in a listed phase")

    def test_the_body_loads_no_module_and_reads_no_clock_or_random_number(self):
        code = re.sub(r"(?m)^\s*//.*$", "", self.body)
        for refused in ("import(", "require(", "Date.now(", "Math.random(", "new Date()", "process.", "fs."):
            self.assertNotIn(refused, code, f"the runtime refuses or lacks {refused}")
        self.assertNotRegex(code, r"(?m)^\s*import\s", "a script loads no module")

    def test_the_plugin_ships_the_script_from_the_default_workflows_folder(self):
        manifest = json.loads(read(os.path.join(PLUGIN, ".claude-plugin", "plugin.json")))
        self.assertNotIn("workflows", manifest, "the key replaces the default scan of workflows/")
        self.assertEqual(sorted(os.listdir(WORKFLOWS)), ["readings.js"], "every .js file there is a workflow")

    def test_the_words_that_carry_no_content_are_those_routing_drops(self):
        lists = dict(re.findall(r"(?s)const (COMMON|STOP) = `([^`]*)`", self.script))
        self.assertEqual(set(lists["COMMON"].split()), set(plans.COMMON))
        self.assertEqual(set(lists["STOP"].split()), set(puppeteer.STOP))
        self.assertIn("[A-Za-z_][A-Za-z0-9_]{2,}", self.script, "a word is what plans.WORD matches")
        self.assertEqual(plans.WORD.pattern, "[A-Za-z_][A-Za-z0-9_]{2,}")

    def test_a_reading_takes_at_most_the_options_one_question_holds(self):
        """The AskUserQuestion tool takes two to four options, so one run works four readings at most."""
        self.assertRegex(self.body, r"(?m)^const MOST = 4\b")


@unittest.skipUnless(NODE, "no node on the PATH to run the script's body")
class Run(unittest.TestCase):
    """The script's body run under node, with every agent answered from a list."""

    @classmethod
    def setUpClass(cls):
        names = list(SCENARIOS)
        r = subprocess.run([NODE, "-e", HARNESS, SCRIPT], input=json.dumps([SCENARIOS[n] for n in names]),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if r.returncode:
            raise AssertionError(r.stderr[-2000:])
        cls.got = dict(zip(names, json.loads(r.stdout)))

    def ran(self, name):
        got = self.got[name]
        self.assertNotIn("error", got, got.get("error"))
        return got["returned"], got["calls"]

    def test_each_reading_gets_an_agent_with_the_result_schema(self):
        _, calls = self.ran("fork")
        self.assertEqual([c["opts"]["label"] for c in calls], ["reading 1", "reading 2"])
        for c in calls:
            schema = c["opts"]["schema"]
            self.assertEqual(schema["type"], "object")
            self.assertEqual(schema["required"], ["result", "question"])
            self.assertLessEqual({"result", "question"}, set(schema["properties"]))
            self.assertEqual(c["opts"]["phase"], "Readings")
            self.assertEqual((c["opts"]["model"], c["opts"]["effort"]), ("opus", "medium"), "the writer's level")
        self.assertEqual(self.got["fork"]["phases"], ["Readings"])
        self.assertIn(f"The message: {WORDS}", calls[0]["prompt"], "the message's words reach each reading")
        self.assertIn("Your reading of it: a CSV file", calls[0]["prompt"])
        self.assertIn("reading 2 of 2", calls[1]["prompt"])

    def test_no_reading_writes_or_runs_in_a_worktree_and_a_writes_key_is_ignored(self):
        _, calls = self.ran("fork")
        for c in calls:
            self.assertNotIn("isolation", c["opts"])
            self.assertIn("This reading changes no file", c["prompt"])
            self.assertNotIn("worktree", c["prompt"])
        got, _ = self.ran("fork")
        self.assertEqual(got["state"], "forked", "a `writes` key of a reading does not fail the run")
        for o in got["options"]:
            self.assertFalse({"branch", "worktree", "wrote"} & set(o))

    def test_no_reading_can_ask_ezexe_so_its_question_comes_back_as_data(self):
        _, calls = self.ran("fork")
        for c in calls:
            self.assertIn("put that one question in `question`", c["prompt"])
            self.assertIn("You cannot ask ezexe yourself", c["prompt"])
        got, _ = self.ran("question")
        self.assertEqual(got["state"], "forked", "a reading stopped on a question, so ezexe is asked once")
        self.assertEqual(got["options"][0]["question"], "Which bucket holds the exports?")
        self.assertEqual(got["default"], 2, "the default is the first reading that went through")
        got, _ = self.ran("all ask")
        self.assertEqual((got["state"], got["default"]), ("forked", 1))

    def test_results_that_agree_collapse_to_the_result(self):
        got, _ = self.ran("collapse")
        self.assertEqual(got["state"], "collapsed")
        self.assertEqual(got["result"], "The parser drops empty lines before counting rows.")
        self.assertEqual([r["k"] for r in got["readings"]], [1, 2])
        self.assertIn("put no question to ezexe", got["next"])
        self.assertNotIn("options", got)

    def test_results_that_differ_fork_with_an_option_for_each_reading_and_a_default(self):
        got, _ = self.ran("fork")
        self.assertEqual(got["state"], "forked")
        self.assertEqual(got["question"], f'Which reading of "{WORDS}" is meant?')
        self.assertEqual(got["default"], 1)
        self.assertEqual([(o["k"], o["text"], o["result"]) for o in got["options"]],
                         [(1, "a CSV file", CSV["result"]), (2, "a JSON file", JSON_["result"])])
        self.assertIn("`AskUserQuestion`", got["next"])
        self.assertIn("child session", got["next"])
        self.assertNotIn("result", {k for k in got if k != "options"})

    def test_a_stopped_or_failed_agent_is_a_lost_reading(self):
        got, _ = self.ran("all lost")
        self.assertEqual(got["state"], "lost")
        self.assertEqual([(x["k"], x["why"]) for x in got["lost"]],
                         [(1, "its agent was stopped or failed"), (2, "its agent failed")])
        got, _ = self.ran("one lost")
        self.assertEqual(got["state"], "collapsed", "it closes on what the other reading gave")
        self.assertEqual([x["k"] for x in got["lost"]], [2])
        self.assertIn("Reading 1 alone gave a result", got["next"])
        self.assertIn("Reading 2 gave no result.", got["next"])

    def test_fewer_than_two_distinct_readings_start_no_agent(self):
        for name in ("one reading", "no args"):
            got = self.got[name]
            self.assertIn("two or more distinct readings", got.get("error", ""), name)
            self.assertEqual(got["calls"], [], name)

    def test_the_args_may_be_a_bare_list_or_arrive_as_a_string(self):
        for name in ("a list", "a string"):
            got, calls = self.ran(name)
            self.assertEqual((got["state"], len(calls)), ("collapsed", 2), name)
            self.assertIn("Your reading of it: x one", calls[0]["prompt"])

    def test_readings_past_the_fourth_are_left_out_and_said(self):
        got, calls = self.ran("six")
        self.assertEqual(len(calls), 4)
        self.assertEqual(got["dropped"], ["5", "6"])
        self.assertIn("2 readings past the first 4 left out", self.got["six"]["logs"][0])

    def test_the_compare_answers_as_puppeteers_did(self):
        for k, (a, b, same) in enumerate(PAIRS):
            got, _ = self.ran(f"pair {k}")
            self.assertEqual(got["state"], "collapsed" if same else "forked", (a, b))


if __name__ == "__main__":
    unittest.main()
