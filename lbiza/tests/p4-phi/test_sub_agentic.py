#!/usr/bin/env python3
"""test_sub_agentic.py: p4-phi's skill sub-agentic, its table of roles, and each hand-out of p4-phi that gives an
agent or a session its model and effort.

Each role of the table is an agent the plugin ships, whose file carries the role's model and effort, so the right model runs with
nothing a call or a project names. Each kind of step p4-phi's start advice names is a role of that table, and its
start carries the role's model id and effort, or neither for an orchestrator.

    python -m pytest tests/p4-phi/test_sub_agentic.py
"""

import pathlib
import re
import sys
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / "plugins" / "p4-phi"
SKILL = PLUGIN / "skills" / "sub-agentic" / "SKILL.md"
README = PLUGIN / "README.md"
AGENTS = PLUGIN / "agents"
sys.path.insert(0, str(PLUGIN / "scripts"))
import phi  # noqa: E402
import plans  # noqa: E402
import starts  # noqa: E402

# Each role of the table, the agent the plugin ships for it, its model alias and effort, and the kinds of step whose
# start carries that role.
ROLES = {"writer": ("writer", "opus", "medium", ("build", "design")),
         "integrator, fixer": ("integrator", "sonnet", "high", ("static",)),
         "cross-check, judge, grader, truth check": ("check", "sonnet", "high", ("review",)),
         "evidence finder": ("finder", "haiku", "medium", ())}
FAMILY = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


def text(path=SKILL):
    return path.read_text(encoding="utf-8")


def front(path):
    head = re.match(r"---\n(.*?)\n---\n", text(path), re.S)
    return dict(re.findall(r"^(\w+): (.+)$", head.group(1), re.M)) if head else {}


def table():
    rows = {}
    for line in text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) == 4 and not set(cells[0]) <= set("-"):
            rows[cells[0]] = cells[1:]
    return rows


class SkillText(unittest.TestCase):
    def test_the_skill_is_the_plugins_own_and_named_sub_agentic(self):
        f = front(SKILL)
        self.assertEqual(f.get("name"), "sub-agentic")

    def test_each_role_is_an_agent_the_plugin_ships_with_its_model_and_effort_in_its_file(self):
        rows = table()
        for role, (name, model, effort, _kinds) in ROLES.items():
            self.assertIn(f"`p4-phi:{name}` / {model} / {effort}", rows[role][0], role)
            f = front(AGENTS / f"{name}.md")
            self.assertEqual((f.get("name"), f.get("model"), f.get("effort")), (name, model, effort), name)

    def test_lib_first_is_a_skill_of_the_plugin_that_each_code_writing_agent_preloads(self):
        self.assertEqual(front(PLUGIN / "skills" / "lib-first" / "SKILL.md").get("name"), "lib-first")
        for name in ("writer", "integrator"):
            head = re.match(r"---\n(.*?)\n---\n", text(AGENTS / f"{name}.md"), re.S).group(1)
            self.assertRegex(head, r"(?m)^skills:\n  - p4-phi:lib-first$", name)

    def test_readers_hold_only_read_tools(self):
        for name in ("check", "finder"):
            self.assertEqual(front(AGENTS / f"{name}.md").get("tools"), "Read, Grep, Glob", name)

    def test_the_prose_writes_no_parenthetical_and_each_list_item_is_one_line(self):
        prose = text().split("---\n", 2)[2]
        prose = re.sub(r"`[^`]*`", "", prose)
        prose = re.sub(r"https?://\S+", "", prose)
        self.assertNotRegex(prose, r"\([^)]*\)")
        lines = text().split("\n")
        for i, line in enumerate(lines[:-1]):
            if re.match(r"\s*(- |\d+\. )", line):
                self.assertTrue(lines[i + 1] == "" or re.match(r"\s*(- |\d+\. |#|\|)", lines[i + 1]), line)


class HandOuts(unittest.TestCase):
    """Each place p4-phi gives a model or an effort, held to the table."""

    def test_each_kind_of_step_starts_with_its_roles_model_id_and_effort(self):
        rows = table()
        for role, (_name, model, effort, kinds) in ROLES.items():
            for kind in kinds:
                self.assertEqual(plans.CHILD_LEVELS_DEFAULT[kind], {"model": FAMILY[model], "effort": effort}, kind)
                self.assertIn(f"`{FAMILY[model]}` at `{effort}`", rows[role][1], role)
                self.assertIn(plans.ROLES[kind], role)
        self.assertEqual(plans.CHILD_LEVELS_DEFAULT["top"], {"model": "inherit", "effort": "inherit"})

    def test_a_step_is_given_its_role_by_its_words(self):
        for step, kind in (("Write the docs page for the settings", "static"),
                           ("Fix the review findings in relay.py", "build"),
                           ("Design the store's layout", "design"),
                           ("Review the landed commits of relay.py", "review"),
                           ("Check the settings page against p4conf.py", "review")):
            self.assertEqual(plans.child_level(step)["kind"], kind, step)

    def test_a_new_top_sessions_start_carries_no_model_and_no_effort(self):
        brief = starts.ORCHESTRATOR_BRIEF + "\nFiles: none"
        call = plans.with_level({"initiation": "user_asked", "context": "fresh", "title": "Fix the store",
                                 "prompt": brief})
        self.assertNotIn("model", call)
        self.assertNotIn("effort", call)
        self.assertIn("Model and effort: the parent session's own model at its own effort", call["prompt"])

    def test_a_writers_start_names_opus_at_medium_and_the_skill(self):
        call = plans.with_level({"initiation": "user_asked", "context": "fresh", "title": "Fix relay.py",
                                 "prompt": "Fix the ten findings in relay.py.\nFiles: scripts/relay.py"})
        self.assertEqual((call["model"], call["effort"]), ("claude-opus-5-5", "medium"))
        self.assertIn("a writer's, as the skill sub-agentic gives it", call["prompt"])

    def test_a_planner_starts_on_mythos_at_its_starters_own_effort(self):
        self.assertIn("terminal worker in plan mode", table()["planner"][1])
        self.assertEqual(plans.CHILD_LEVELS_DEFAULT["plan"], {"model": "claude-mythos-5-2", "effort": "inherit"})
        self.assertEqual(plans.ROLES["plan"], "planner")
        brief = "It starts in plan mode, and writes the plan of the exporter's move.\nFiles: none"
        for text in ("Plan the exporter's move", "Write the plan for the exporter", "the exporter: planner\n" + brief):
            self.assertEqual(plans.child_kind(text), "plan", text)
        for text, kind in (("Write the plan parser in src/plan.py", "build"), ("Review the plan", "review"),
                           ("Design the store's layout", "design"),
                           ("Fix the case where a session starts in plan mode twice in phi.py", "build")):
            self.assertEqual(plans.child_kind(text), kind, text)
        call = plans.with_level({"initiation": "user_asked", "context": "fresh", "title": "the exporter: planner",
                                 "prompt": brief})
        self.assertEqual(call.get("model"), "claude-mythos-5-2")
        self.assertNotIn("effort", call, "the starter's own")
        self.assertIn("Model and effort: claude-mythos-5-2 at its own effort", call["prompt"])

    def test_a_fork_takes_neither(self):
        call = {"context": "fork", "prompt": "Fix relay.py"}
        self.assertEqual(plans.with_level(call), call)

if __name__ == "__main__":
    unittest.main()
