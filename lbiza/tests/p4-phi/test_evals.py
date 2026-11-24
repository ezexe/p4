#!/usr/bin/env python3
"""evals/: the cases `claude plugin eval` runs against p4-phi, read as its docs page lays a suite out.

    python -m pytest tests/p4-phi/test_evals.py

Checked: the suite holds five to ten cases; every case has a prompt with a body, front matter of the keys the page
lists and at least one grader; every grader is of a type the page gives, with the options that type takes and a
pattern that compiles; a case no judge grades is tagged `smoke`; no case asks for a tool outside the read-only set,
so none needs the shell, a write, a fetch or a desktop app tool; a case.yaml names its own folder and a scaffold
script and project folder that exist; a grader that says a tool is never called is scored in both arms; the cases
rest on words the plugin still says, the two built-in rules, the skill's description and the check agent's name;
and git ignores what a run writes.

The page is https://code.claude.com/docs/en/plugin-evals.md, "Eval suite reference". A pattern is a JavaScript
regex there and is compiled by Python's `re` here, so the cases keep to what both read alike. The front matter and
case.yaml are read by the few lines below and not by a YAML library, which the suite does not have: a line they
cannot read fails the test, which keeps the files to plain `key: value` lines. No test here calls a model.
"""

import json
import os
import re
import sys
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
PLUGIN = os.path.dirname(SRC)
REPO = os.path.dirname(os.path.dirname(os.path.dirname(PLUGIN)))
EVALS = os.path.join(PLUGIN, "evals")
sys.path.insert(0, SRC)
import phi  # noqa: E402

# plugin-evals.md, "prompt.md frontmatter": "An unknown key is an error".
PROMPT_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
               "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}
# The same page, "Grader frontmatter" and "Grader types": the keys every grader takes, then each type's options.
GRADER_KEYS = {"type", "weight", "arm"}
GRADER_TYPES = {"regex": {"pattern", "flags", "match", "target"},
                "tool_used": {"tool", "input_match", "min", "max"},
                "tool_order": {"before", "after"},
                "file_exists": {"path", "exists"},
                "llm": {"criteria", "focus"},
                "baseline": {"baseline_file", "criteria"}}
JUDGED = {"llm", "baseline"}                      # "`llm` and `baseline` call a judge model and add to the run's cost"
# The same page, "Grant tools": the read-only tools a case may list. Anything else needs a grant on the command line,
# and a shell grant has no sandbox on native Windows.
READ_ONLY = {"Read", "Glob", "Grep", "NotebookRead", "Skill", "AskUserQuestion", "Agent", "TodoWrite", "TaskCreate",
             "TaskGet", "TaskList", "TaskUpdate", "TaskStop"}
CONTEXT_KEYS = {"scaffold_script", "history_file", "add_dirs"}
FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def value(text):
    """One front matter value: a list in brackets, a quoted string with YAML's doubled quote, a whole number or
    bare words."""
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        return [value(x) for x in text[1:-1].split(",") if x.strip()]
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return json.loads(text)
    return int(text) if re.fullmatch(r"-?\d+", text) else text


def mapping(text, where):
    """The `key: value` lines of a front matter block or a case.yaml, with one level of indented keys under a key
    that has no value. Any other line raises, naming the file."""
    out, under = {}, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"( *)([A-Za-z_]+):(.*)", line)
        if not m or len(m.group(1)) not in (0, 2):
            raise ValueError(f"{where}: this line is no `key: value`: {line!r}")
        indent, key, rest = len(m.group(1)), m.group(2), m.group(3)
        if indent:
            if under is None:
                raise ValueError(f"{where}: an indented key under no key: {line!r}")
            out[under][key] = value(rest)
        elif rest.strip():
            out[key], under = value(rest), None
        else:
            out[key], under = {}, key
    return out


def front(path):
    """A Markdown file's front matter as a mapping, and its body."""
    m = FRONT.match(read(path))
    if not m:
        raise ValueError(f"{path}: no front matter between --- lines")
    return mapping(m.group(1), path), m.group(2).strip()


def cases():
    """Each case of the suite: its name, folder, prompt front matter and body, case.yaml and graders by name. A
    case is a folder holding a prompt.md or a case.yaml, as the page says, and `results` is what a run writes."""
    out = []
    for name in sorted(os.listdir(EVALS)):
        folder = os.path.join(EVALS, name)
        if name in ("results", "mocks") or not os.path.isdir(folder):
            continue
        prompt, yaml = os.path.join(folder, "prompt.md"), os.path.join(folder, "case.yaml")
        if not os.path.isfile(prompt) and not os.path.isfile(yaml):
            continue
        meta, body = front(prompt) if os.path.isfile(prompt) else ({}, "")
        graders = {}
        gdir = os.path.join(folder, "graders")
        for g in sorted(os.listdir(gdir)) if os.path.isdir(gdir) else []:
            if g.endswith(".md"):
                graders[g[:-3]] = front(os.path.join(gdir, g))[0]
        out.append({"name": name, "folder": folder, "meta": meta, "body": body, "graders": graders,
                    "yaml": mapping(read(yaml), yaml) if os.path.isfile(yaml) else None})
    return out


def never_called(grader):
    return grader.get("type") == "tool_used" and grader.get("min") == 0 and grader.get("max") == 0


def graders_of(tool):
    """Every `tool_used` grader of the suite on `tool`, as (case name, grader)."""
    return [(c["name"], g) for c in cases() for g in c["graders"].values()
            if g.get("type") == "tool_used" and g.get("tool") == tool]


class Suite(unittest.TestCase):
    def test_the_suite_holds_five_to_ten_cases(self):
        self.assertTrue(5 <= len(cases()) <= 10, [c["name"] for c in cases()])

    def test_every_case_has_a_prompt_and_names_a_grader(self):
        for c in cases():
            self.assertTrue(c["body"], c["name"])
            self.assertEqual(set(c["meta"]) - PROMPT_KEYS, set(), c["name"])
            self.assertTrue(c["meta"].get("description"), c["name"])
            self.assertTrue(c["graders"], c["name"])     # "a case without one fails to load"

    def test_every_grader_is_of_a_type_the_page_gives_with_that_types_options(self):
        for c in cases():
            for name, g in c["graders"].items():
                where = f"{c['name']}/{name}"
                self.assertIn(g.get("type"), GRADER_TYPES, where)
                self.assertEqual(set(g) - GRADER_KEYS - GRADER_TYPES[g["type"]], set(), where)
                self.assertIn(g.get("arm", "both"), ("both", "with-only"), where)
                if g["type"] == "tool_used":
                    self.assertTrue(g.get("tool"), where)
                if g["type"] == "regex":
                    self.assertTrue(g.get("pattern"), where)
                    self.assertIn(g.get("target", "last_message"), ("last_message", "trace", "files"), where)
                    self.assertTrue(re.fullmatch(r"contains|not_contains|count:\d+", g.get("match", "contains")), where)
                for key in ("pattern", "input_match"):
                    if key in g:
                        re.compile(g[key])                # raises on a pattern that does not compile

    def test_a_case_no_judge_grades_is_tagged_smoke(self):
        for c in cases():
            judged = any(g.get("type") in JUDGED for g in c["graders"].values())
            self.assertEqual("smoke" in (c["meta"].get("tags") or []), not judged, c["name"])

    def test_no_case_asks_for_a_tool_outside_the_read_only_set(self):
        for c in cases():
            asked = c["meta"].get("allowed_tools") or []
            self.assertTrue(asked, c["name"])
            self.assertEqual(set(asked) - READ_ONLY, set(), c["name"])
            for g in c["graders"].values():
                if g.get("type") == "tool_used":
                    self.assertIn(g["tool"], READ_ONLY, c["name"])

    def test_a_case_yaml_names_its_folder_and_files_that_exist(self):
        seeded = 0
        for c in cases():
            if c["yaml"] is None:
                continue
            self.assertEqual(c["yaml"].get("schema_version"), "1.1", c["name"])
            self.assertEqual(c["yaml"].get("name"), c["name"])
            context = c["yaml"].get("context") or {}
            self.assertEqual(set(context) - CONTEXT_KEYS, set(), c["name"])
            script = context.get("scaffold_script")
            if script:
                seeded += 1
                self.assertTrue(os.path.isfile(os.path.join(c["folder"], script)), c["name"])
                self.assertIn("/project/.", read(os.path.join(c["folder"], script)), c["name"])
                self.assertTrue(os.listdir(os.path.join(c["folder"], "project")), c["name"])
        self.assertTrue(seeded)

    def test_a_grader_that_says_a_tool_is_never_called_is_scored_in_both_arms(self):
        seen = 0
        for c in cases():
            for name, g in c["graders"].items():
                if never_called(g):
                    seen += 1
                    self.assertEqual(g.get("arm"), "both", f"{c['name']}/{name}")
        self.assertTrue(seen)


class Covers(unittest.TestCase):
    """The cases the suite is for."""

    def test_the_rules_two_halves_each_have_a_case(self):
        asks = graders_of("AskUserQuestion")
        self.assertTrue(any(never_called(g) for _, g in asks), asks)
        by_name = {c["name"]: c for c in cases()}
        held = by_name["asks-before-an-irreversible-step"]["graders"]
        self.assertTrue(any(g.get("match") == "not_contains" for g in held.values()), held)

    def test_the_case_on_ezexes_authority_grades_the_reply_the_rule_names(self):
        """A run's session is offered neither `mcp__ccd_turn__wrap_up` nor `AskUserQuestion`, so the rule sends its
        question to the reply, and the case on ezexe's authority looks for the question there."""
        held = {c["name"]: c for c in cases()}["asks-before-an-irreversible-step"]["graders"]
        asked = [g for g in held.values() if g.get("type") == "regex" and g.get("match", "contains") == "contains"
                 and g.get("target", "last_message") == "last_message"]
        self.assertTrue(asked, held)

    def test_the_two_cases_on_the_rule_run_alone_by_their_tag(self):
        """plugin-evals.md, "Choose what to evaluate": "Add `--case <glob>` to filter by case name and `--tag <tag>`
        to keep cases with any of the given tags." `--case` takes one glob and no list, so the two cases on the rule
        carry a tag of their own, and no other case does."""
        tagged = sorted(c["name"] for c in cases() if "rule" in (c["meta"].get("tags") or []))
        self.assertEqual(tagged, ["asks-before-an-irreversible-step", "decides-from-the-files"])

    def test_only_the_decisions_file_answers_and_the_answer_counts_beside_its_source(self):
        """plugin-evals.md, "The no-plugin baseline": "If a case scores 1.0 both with and without the plugin, the
        plugin isn't what made it pass." The case as first written had the code answer too. Now the code writes
        either format, the project's decisions file alone settles which, and the grader passes a reply that names
        the format beside that file or its entry, never one that lists both formats and cannot tell."""
        case = {c["name"]: c for c in cases()}["decides-from-the-files"]
        project = os.path.join(case["folder"], "project")
        settled = [os.path.relpath(os.path.join(d, f), project).replace("\\", "/")
                   for d, _, files in os.walk(project) for f in files
                   if "JSON Lines" in read(os.path.join(d, f))]
        self.assertEqual(settled, ["docs/decisions.md"])
        self.assertIn("D-17", read(os.path.join(project, "docs", "decisions.md")))
        self.assertNotRegex(read(os.path.join(project, "src", "export.py")), r"(?i)csv|json")
        g = case["graders"]["answer-from-the-file"]
        self.assertEqual((g["type"], g.get("flags"), g.get("match", "contains")), ("regex", "i", "contains"))
        for reply in ("It is JSON Lines, by D-17.", "The report is `.jsonl`.\nSource: docs/decisions.md"):
            self.assertTrue(re.search(g["pattern"], reply, re.I), reply)
        for reply in ("I can't tell: the code writes csv or jsonl by an environment variable.", "CSV, by D-17.",
                      "JSON Lines, I believe."):
            self.assertFalse(re.search(g["pattern"], reply, re.I), reply)
        never = [x for x in case["graders"].values() if never_called(x)]
        self.assertEqual([x.get("weight") for x in never], ["0.01"], "a grader that cannot fail weighs next to nothing")

    def test_the_go_counts_only_in_a_reply_that_publishes_nothing(self):
        """The first grader of the go passed "I can't confirm the bot's result" under a publish block, so a run
        that published scored half. The go now counts only in a reply with no publish block, and the request of
        the case names the release list and no publish, which the list alone leaves open."""
        case = {c["name"]: c for c in cases()}["asks-before-an-irreversible-step"]
        go, held = case["graders"]["puts-the-go-to-ezexe"], case["graders"]["publishes-nothing"]
        published = "Publishing now.\n```run\npublish 3.0.0\n```\nI can't confirm the bot's result. Tell me if it fails?"
        asked = "I haven't published: the registry keeps a version for good. Do you want me to publish 3.0.0?"
        self.assertTrue(re.search(go["pattern"], asked, re.I))
        self.assertFalse(re.search(go["pattern"], published, re.I))
        self.assertFalse(re.search(go["pattern"], "The one open item is the publish.", re.I))
        self.assertEqual(held.get("match"), "not_contains")
        self.assertTrue(re.search(held["pattern"], published))
        self.assertFalse(re.search(held["pattern"], asked))
        self.assertNotRegex(case["body"], r"(?i)publish")
        self.assertIn("- [ ] published", read(os.path.join(case["folder"], "project", "RELEASING.md")))

    def test_the_skill_is_called_by_its_own_name_and_one_case_must_not_call_it(self):
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "skills", "phi", "SKILL.md")))
        skill = graders_of("Skill")
        for _, g in skill:
            self.assertTrue(re.search(g["input_match"], '"skill":"phi"'), g)
            self.assertTrue(re.search(g["input_match"], '"skill": "p4-phi:phi"'), g)
            self.assertFalse(re.search(g["input_match"], '"skill":"code-review"'), g)
        self.assertTrue([n for n, g in skill if not never_called(g)], skill)
        self.assertTrue([n for n, g in skill if never_called(g)], skill)

    def test_the_check_agent_is_called_by_its_namespaced_type(self):
        name = json.loads(read(os.path.join(PLUGIN, ".claude-plugin", "plugin.json")))["name"]
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "agents", "check.md")))
        agent = graders_of("Agent")
        self.assertTrue(agent)
        self.assertTrue(any(re.search(g["input_match"], f'"subagent_type":"{name}:check"') for _, g in agent), agent)


class Kept(unittest.TestCase):
    def test_git_ignores_what_a_run_writes(self):
        self.assertIn("lbiza/plugins/*/evals/results/", read(os.path.join(REPO, ".gitignore")).splitlines())


if __name__ == "__main__":
    unittest.main()
