#!/usr/bin/env python3
"""test_sub_agentic.py: p4-phi's skill sub-agentic, its ten rules and its table of roles, and each hand-out of p4-phi
that gives an agent or a session its model and effort.

The head of each rule is the source skill's word for word, with ezexe where the source says the owner. Each role of
the table is an agent the plugin ships, whose file carries the role's model and effort, so the right model runs with
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

# The head of each of the source skill's ten rules, word for word.
HEADS = ["**Do it here unless delegation buys something.**", "**Scale the count to the task.**",
         "**Say the shape first**", "**Bound every loop.**",
         "**Set model and effort on every agent by its role; nothing inherits by default.**",
         "**The brief is the agent's only context.**", "**Large outputs go to files.**", "**Report the spend.**",
         "**Ultracode changes the opt-in, not the duty.**", "**Writers never share files.**"]

# Each role of the table, the agent the plugin ships for it, its model alias and effort, and the kinds of step whose
# start carries that role.
ROLES = {"writer": ("writer", "opus", "medium", ("build", "design")),
         "integrator, fixer": ("integrator", "sonnet", "medium", ("static",)),
         "cross-check, judge, grader, truth check": ("check", "sonnet", "medium", ("review",)),
         "evidence finder": ("finder", "haiku", "low", ())}
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

    def test_the_ten_rules_keep_the_source_heads_in_order(self):
        body = text()
        at = [body.find(f"{n}. {h}") for n, h in enumerate(HEADS, 1)]
        self.assertNotIn(-1, at, [h for h, i in zip(HEADS, at) if i < 0])
        self.assertEqual(at, sorted(at))

    def test_ezexe_is_named_and_never_the_owner_or_the_user(self):
        body = text().lower()
        for word in (r"\bthe owner\b", r"\bthe user\b", r"\bboss\b"):
            self.assertNotRegex(body, word)
        self.assertIn("only when ezexe asked for that scale", text())
        self.assertIn("only when ezexe names it", text())

    def test_each_role_is_an_agent_the_plugin_ships_with_its_model_and_effort_in_its_file(self):
        rows = table()
        for role, (name, model, effort, _kinds) in ROLES.items():
            self.assertIn(f"`p4-phi:{name}` / {model} / {effort}", rows[role][0], role)
            f = front(AGENTS / f"{name}.md")
            self.assertEqual((f.get("name"), f.get("model"), f.get("effort")), (name, model, effort), name)

    def test_readers_hold_only_read_tools(self):
        for name in ("check", "finder"):
            self.assertEqual(front(AGENTS / f"{name}.md").get("tools"), "Read, Grep, Glob", name)

    def test_the_orchestrator_and_a_fork_run_on_the_session_model(self):
        rows = table()
        self.assertEqual(rows["orchestrator, fork"][:2], ["the session model", "no `model`, no `effort`"])
        self.assertEqual(rows["fable"][0], "only when ezexe names it")

    def test_rule_6_says_what_a_started_session_is_given_at_its_start(self):
        body = text()
        self.assertNotIn("p4-phi gives it CLAUDE.md", body)
        for word in ("Claude Code loads its CLAUDE.md and the first lines of its memory index `MEMORY.md` at its start",
                     "p4-phi puts its built-in rules in its system prompt",
                     "hands it each feedback or user memory that changes while it works"):
            self.assertIn(word, body, word)

    def test_rule_5_names_each_call_form(self):
        body = text()
        for word in ("`agent(prompt, {model, effort})`", "A session start takes `model` as a model id",
                     "A fork runs on the session model"):
            self.assertIn(word, body, word)

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
        brief = "This session is a new top session, orchestrating its own topic.\nFiles: none"
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

    def test_a_fork_takes_neither(self):
        call = {"context": "fork", "prompt": "Fix relay.py"}
        self.assertEqual(plans.with_level(call), call)

    def test_a_search_goes_to_the_finder_whose_file_names_its_model(self):
        self.assertEqual(plans.LEVEL_WHERE["read"], plans.EXPLORE)
        self.assertIn("`p4-phi:finder`", plans.EXPLORE)
        self.assertIn("goes to " + plans.EXPLORE, phi.LEVELS)

    def test_the_levels_rule_names_the_skill_and_each_agent_before_a_launch(self):
        for word in ("Before an Agent call, a fork, a Workflow call or a session start, the skill "
                     "`p4-phi:sub-agentic` decides", "the reply's first line says that shape ahead of the call",
                     "`p4-phi:check`, on `sonnet` at `medium`", "`p4-phi:writer`, on `opus` at `medium`",
                     "`p4-phi:integrator`, on `sonnet` at `medium`", "`agent(prompt, {model, effort})`",
                     "After a run, the report says the agents launched and finished and what they spent"):
            self.assertIn(word, phi.LEVELS, word)

    def test_the_start_advice_names_the_skill_and_the_shape_line(self):
        for word in ("skill `p4-phi:sub-agentic`", "a writer's, on Opus at medium effort",
                     "say the shape in the reply's first line ahead of the calls"):
            self.assertIn(word, plans.LEVEL_HOW, word)
        self.assertNotIn("high effort", plans.LEVEL_HOW)


if __name__ == "__main__":
    unittest.main()
