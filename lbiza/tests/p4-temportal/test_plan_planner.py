#!/usr/bin/env python3
"""test_plan_planner.py: p4-temportal's skill plan-planner, its rules for a plan's sections and its places.

The rules of a section are the source skill's word for word, but that ezexe is named where the source says the boss.
A plan is the one plan mode writes into the plugin's plans folder, and it is sorted into complete/, todo/ or
unplanned/ under it, which no session reads unless ezexe names the file. The retention sweep, the copy out of Claude
Code's own plans folder and the carry out of a worktree each keep to those places.

    python -m pytest tests/p4-temportal/test_plan_planner.py
"""

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

PLUGIN = pathlib.Path(__file__).resolve().parents[2] / "plugins" / "p4-temportal"
SKILL = PLUGIN / "skills" / "plan-planner" / "SKILL.md"
sys.path.insert(0, str(PLUGIN / "hooks"))
import lifetime  # noqa: E402

DAY = 86400

# The source skill's section rules, word for word, with ezexe where it says the boss, with the evidence rule's
# last sentence holding back only a section that depends on the one implemented, since runs land side by side, and
# with the Research rule, which is this skill's own.
SECTION = """## What every section of a plan holds

- **Intents:** the section opens by listing what it means to change, one line each.
- **Research:** after the intents and before any fence, the references the round's research found for each intent and what each recommends, one line each: the upstream page read live on the web with its link, then the file and line in the checkout, and the recommendation learned from them.
- **Fences:** every edit is a fenced code block, and above it, its intent:
  - **Documented:** the source in detail: the upstream page or file and line, read live or in the checkout, quoted where a quote fits.
  - **Derivation:** in prose, how the approach follows from that source, and why this approach rather than another.
- **No choices for ezexe:** a section avoids, with all the effort it takes, putting a choice to ezexe. Wherever the plan's writer wants to present one, that is the sign the section's planning failed to find the documented approach: the writer goes back to the upstream sources, finds how upstream does it, and writes that approach with its Documented and Derivation, the alternatives named only in the Derivation's "rather than another". A choice reaches ezexe only when no upstream source settles it after that search; it then names the sources searched and what each said.
- **Evidence:** once a section is implemented, its evidence is added to that same section: links to the implemented lines (`[path:N-M](../../../../path:N-M)`) with what ran and its output. Only then does a section that depends on it start.
"""


def text():
    return SKILL.read_text(encoding="utf-8")


def wipe(path):
    def again(fn, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            fn(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=again)


def put(path, body="x", age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    if age_days:
        t = time.time() - age_days * DAY
        os.utime(path, (t, t))
    return path


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def git(root, *args):
    who = ["-c", "user.name=p4", "-c", "user.email=p4@example.invalid", "-c", "commit.gpgsign=false"]
    return subprocess.run(["git", "-C", root, *who, *args], check=True, capture_output=True)


class SkillText(unittest.TestCase):
    def test_the_skill_is_the_plugins_own_and_named_plan_planner(self):
        head = re.match(r"---\n(.*?)\n---\n", text(), re.S)
        self.assertIsNotNone(head)
        self.assertIn("name: plan-planner\n", head.group(1) + "\n")
        description = re.search(r"^description: (.+)$", head.group(1), re.M).group(1)
        for word in ("temportal/plan-planner", "plansDirectory", "complete/, todo/ or unplanned/",
                     "which no session reads unless ezexe names the file", "Invoke BEFORE writing",
                     "Never the repo root, the scratchpad or an ad-hoc directory"):
            self.assertIn(word, description, word)

    def test_every_section_holds_the_source_skills_rules_word_for_word(self):
        self.assertTrue(text().endswith(SECTION), "the section rules are the source's, with ezexe for the boss")

    def test_ezexe_is_named_and_never_the_boss_or_the_owner(self):
        body = text()
        self.assertNotRegex(body.lower(), r"\bboss\b")
        self.assertNotRegex(body.lower(), r"\bthe owner\b")
        for word in ("No choices for ezexe", "Park** on ezexe's word only", "Drop** on ezexe's word only",
                     "Revive** on ezexe's word only"):
            self.assertIn(word, body, word)

    def test_the_plan_is_the_one_plan_mode_writes_into_the_plugins_folder(self):
        body = text()
        places = ["`.claude/p4/temportal/plan-planner/<plan>.md`"]
        places += [f"`.claude/p4/temportal/plan-planner/{shelf}/<plan>.md`" for shelf in lifetime.SHELVES]
        for place in places:
            self.assertIn(place, body, place)
        for word in ("## Plan mode writes the plan", "A plan is written in plan mode", "`plansDirectory`",
                     "`Ctrl+G`", "reads the plan in again from disk"):
            self.assertIn(word, body, word)

    def test_a_taken_name_is_numbered_and_a_started_planner_and_a_prep_have_their_rules(self):
        body = text()
        for word in ("Plan mode gives every plan of one session that same name", "`<stem>.<n>.md`",
                     "the smallest number from 2 that no place of a plan holds with that stem",
                     "## A planner another session starts", "by the start tool's `permission_mode`",
                     "under a name of the session's own making", "edits only its plan file",
                     "`PREP COMPLETE <subject>` on line 1", "reads the prep as findings to check"):
            self.assertIn(word, body, word)
        self.assertLess(body.index("## Plan mode writes the plan"), body.index("## A planner another session starts"))
        self.assertLess(body.index("## A planner another session starts"), body.index("## What a session reads"))

    def test_a_sorted_plan_takes_its_titles_name_and_a_worked_one_keeps_plan_modes(self):
        body = text()
        for word in ("While a plan is worked, the file keeps the name plan mode gave it",
                     "fixes one plan file name per session", "treats any other file in this folder as a protected path",
                     "under the name its title makes", "The title is the plan file's first heading line, `# ...`.",
                     "cut at the last hyphen that keeps it within 60 characters",
                     "A plan with no heading, or whose slug is empty, keeps the name plan mode gave it.",
                     "A prep is sorted the same way, by its own first heading",
                     "where a place of a plan already holds that name, the plan moves as `<stem>.<n>.md`",
                     "A revive moves the plan back into `plan-planner/` under its sorted name as it stands",
                     "copies the plan's content into its own plan file", "into `complete/` under its title's name",
                     "into `todo/` under its title's name", "into `unplanned/` under its title's name"):
            self.assertIn(word, body, word)

    def test_the_loops_reader_traces_live_paths_and_a_check_runs_as_written(self):
        body = text()
        loop = body.split("## The plan loop")[1].split("## Handing a plan's sections to workers")[0]
        for word in ("the feature not work in a real session", "traces the live path of each new hook",
                     "names the interpreter by its full path", "says at its head how its loop ended"):
            self.assertIn(word, loop, word)
        hand = body.split("## Handing a plan's sections to workers")[1].split("## What every section")[0]
        self.assertIn("the plugin's whole test folder is run once there before a push", hand)

    def test_a_move_makes_no_commit_and_no_orphan_branch(self):
        body = text()
        self.assertIn("A move is a plain move of the file into its subfolder", body)
        move = body.split("## Moving a plan")[1].split("## The plan loop")[0]
        for word in ("orphan", "git worktree add", "origin plans", "git -C", "commit -m"):
            self.assertNotIn(word, move, word)
        for word in ("orphan", "origin plans", "commit -m"):
            self.assertNotIn(word, body, word)

    def test_the_prose_writes_no_parenthetical_and_each_list_item_is_one_line(self):
        # the section rules are the source's word for word, its parenthesis round the evidence link with them
        own = text().split("---\n", 2)[2].split("## What every section of a plan holds")[0]
        prose = re.sub(r"```.*?```", "", own, flags=re.S)
        prose = re.sub(r"`[^`]*`", "", prose)
        prose = re.sub(r"\[[^\]]*\]\([^)]*\)", "", prose)
        self.assertNotRegex(prose, r"\([^)]*\)")
        lines = text().split("\n")
        for i, line in enumerate(lines[:-1]):
            if re.match(r"\s*- ", line):
                self.assertTrue(lines[i + 1] == "" or re.match(r"\s*(- |#)", lines[i + 1]), line)

    def test_a_plan_is_looped_until_dry_and_its_sections_are_handed_to_workers_by_run(self):
        """workflows.md, "Find issues until the list stops growing": "stop once two rounds in a row find nothing
        new". building-effective-agents, "Agents": "stopping conditions (such as a maximum number of iterations)".
        agent-teams.md, "Avoid file conflicts": "each teammate owns a different set of files"."""
        body = text()
        loop = body.split("## The plan loop")[1].split("## Handing a plan's sections to workers")[0]
        for word in ("researches the section first", "in both places every time",
                     "sends a research agent to the upstream pages", "the upstream page wins",
                     "restates nothing an upstream page says", "`See more: <url>`", "one writer of the plan file",
                     "a reader that has not seen the writing", "two dry rounds in a row, or after five rounds",
                     "under a last heading `## Loop log`", "`- Round <n> of 5: <what the round changed>`",
                     "`- Round <n> of 5: dry`",
                     "no session that writes is started and no file but the plan is edited"):
            self.assertIn(word, loop, word)
        hand = body.split("## Handing a plan's sections to workers")[1].split("## What every section")[0]
        for word in ("`**Files:**`", "`**Depends on:**`", "`**Checks:**`", "share a file or depend on one another",
                     "section `Distribution`", "landed by an integrator", "`phi.py sections <plan file>`",
                     "A worker never edits the plan file", "subagents and never sessions",
                     "worktree add -b <run> <main checkout>/.claude/worktrees/<run> origin/main",
                     "naming each branch, its commits and its check results"):
            self.assertIn(word, hand, word)
        self.assertLess(body.index("## The plan loop"), body.index("## What every section of a plan holds"))


class Places(unittest.TestCase):
    """The places on a store on disk, under the plans folder as the code names it."""

    def setUp(self):
        from unittest import mock
        self.base = tempfile.mkdtemp(prefix="p4-temportal-planner-")
        self.addCleanup(wipe, self.base)
        self.root = os.path.join(self.base, "proj")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        self.plans = os.path.join(self.p4, "temportal", lifetime.PLANS)
        os.makedirs(self.plans)
        self.config = os.path.join(self.base, "config")
        self.own = os.path.join(self.config, "plans")
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)

    def test_the_age_clears_a_worked_plan_and_keeps_every_sorted_one(self):
        worked = put(os.path.join(self.plans, "old-worked.md"), age_days=40)
        sorted_ = [put(os.path.join(self.plans, shelf, f"old-{shelf}.md"), age_days=400)
                   for shelf in lifetime.SHELVES]
        said = lifetime.sweep(self.p4, days=30.0)
        self.assertEqual(said, "p4-temportal: cleared plans older than the 30 days of cleanupPeriodDays: 1, "
                               f"in {lifetime.PLANS}/.")
        self.assertFalse(os.path.exists(worked))
        self.assertEqual([os.path.exists(p) for p in sorted_], [True, True, True])
        self.assertEqual(lifetime.sweep(self.p4, days=1.0), "")

    def test_no_category_takes_a_cookie_whole_and_a_plan_in_one_takes_its_own(self):
        done = put(os.path.join(self.plans, "complete", "a.md"))
        for shelf in lifetime.SHELVES:
            put(os.path.join(self.plans, shelf, "b.md"))
            with self.assertRaises(ValueError, msg=shelf):
                lifetime.set_cookie(self.p4, f"{lifetime.PLANS}/{shelf}", "7d")
        self.assertEqual(lifetime.set_cookie(self.p4, done, "7d")[0], f"{lifetime.PLANS}/complete/a.md")

    def test_a_sorted_plan_is_not_copied_back_out_of_claude_codes_own_folder(self):
        with open(os.path.join(self.root, ".claude", "settings.local.json"), "w", encoding="utf-8") as f:
            json.dump({"plansDirectory": ".claude/p4/" + lifetime.p4conf.PLANS}, f)
        for shelf in lifetime.SHELVES:
            put(os.path.join(self.plans, shelf, f"{shelf}.md"), f"STATUS: {shelf}\n", age_days=1)
        names = [f"{shelf}.md" for shelf in lifetime.SHELVES] + ["new.md"]
        made = [put(os.path.join(self.own, name), "# again\n") for name in names]
        said = lifetime.keep_plans(self.root, made, made)
        self.assertEqual(sorted(os.listdir(self.plans)), sorted([*lifetime.SHELVES, "new.md"]))
        self.assertIn("new.md", said[0])
        for shelf in lifetime.SHELVES:
            self.assertNotIn(f"{shelf}.md", said[0])
            self.assertEqual(read(os.path.join(self.plans, shelf, f"{shelf}.md")), f"STATUS: {shelf}\n")

    def test_a_plan_sorted_under_its_title_name_is_not_copied_back_either(self):
        with open(os.path.join(self.root, ".claude", "settings.local.json"), "w", encoding="utf-8") as f:
            json.dump({"plansDirectory": ".claude/p4/" + lifetime.p4conf.PLANS}, f)
        put(os.path.join(self.plans, "complete", "closed-plan.md"), "STATUS: COMPLETED\n# Closed plan\n", age_days=1)
        put(os.path.join(self.plans, "todo", "parked-plan.2.md"), "STATUS: TODO\n# Parked plan\n", age_days=1)
        made = [put(os.path.join(self.own, "brave-otter.md"), "# Closed plan\n"),
                put(os.path.join(self.own, "quiet-fox.md"), "# Parked plan\n"),
                put(os.path.join(self.own, "new-heron.md"), "# Another plan\n")]
        said = lifetime.keep_plans(self.root, made, made)
        self.assertEqual(sorted(os.listdir(self.plans)), ["complete", "new-heron.md", "todo"])
        self.assertIn("new-heron.md", said[0])


class TitleName(unittest.TestCase):
    """A sorted plan is named by its title, its first heading line, and keeps plan mode's name where it has none."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="p4-temportal-planner-title-")
        self.addCleanup(wipe, self.base)

    def name(self, body):
        return lifetime.sorted_name(put(os.path.join(self.base, "brave-otter.md"), body))

    def test_a_plain_title_is_its_slug(self):
        self.assertEqual(self.name("# Plan files take their title's name\n\n## Context\n"),
                         "plan-files-take-their-title-s-name.md")
        self.assertEqual(self.name("STATUS: TODO 2026-11-23: none\n# p4-temportal 0.3.71: names  --  sorted\n"),
                         "p4-temportal-0-3-71-names-sorted.md")

    def test_a_title_of_punctuation_only_and_no_heading_keep_plan_modes_name(self):
        self.assertIsNone(self.name("# ?!. -- ...\n"))
        self.assertIsNone(self.name("# \n"))
        self.assertIsNone(self.name("plain prose\n## a second level heading\n#nospace\n"))
        self.assertIsNone(self.name(""))
        self.assertIsNone(lifetime.sorted_name(os.path.join(self.base, "none-here.md")))

    def test_a_prep_takes_the_heading_after_its_marker_or_none(self):
        self.assertIsNone(self.name("PREP COMPLETE plan names\nfindings\n"))
        self.assertEqual(self.name("PREP COMPLETE plan names\n# Prep: plan names\n"), "prep-plan-names.md")

    def test_a_long_title_is_cut_at_a_hyphen_within_sixty_characters(self):
        title = "A sorted plan takes a file name made from its own title in place of plan mode's"
        got = self.name(f"# {title}\n")
        self.assertEqual(got, "a-sorted-plan-takes-a-file-name-made-from-its-own-title-in.md")
        self.assertLessEqual(len(got) - len(".md"), 60)
        self.assertEqual(self.name("# " + "x" * 70 + "\n"), "x" * 60 + ".md")
        self.assertEqual(self.name("# " + "y" * 60 + " z\n"), "y" * 60 + ".md")

    def test_only_the_files_first_bytes_are_read(self):
        self.assertIsNone(self.name("x" * lifetime.TITLE_BYTES + "\n# Too far down\n"))
        self.assertIsNone(self.name("x" * (lifetime.TITLE_BYTES - 6) + "\n# Cut\n"))
        self.assertEqual(self.name("﻿# Héllo wörld\r\n"), "h-llo-w-rld.md")


class CarriedPlaces(unittest.TestCase):
    """A plan a worktree moved leaves its old place in the main checkout's store, and an older copy a worktree still
    holds brings no plan back that the main checkout sorted."""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="p4-temportal-planner-carry-")
        self.addCleanup(wipe, self.base)
        self.main = os.path.join(self.base, "proj")
        os.makedirs(os.path.join(self.main, ".claude", "p4", "temportal"))
        put(os.path.join(self.main, ".gitignore"), ".claude/\n")
        git(self.main, "init", "-q")
        git(self.main, "add", ".gitignore")
        git(self.main, "commit", "-q", "-m", "start")
        self.tree = os.path.join(self.base, "tree")
        git(self.main, "worktree", "add", "-q", self.tree, "-b", "work")
        self.here = os.path.join(self.tree, ".claude", "p4", "temportal", lifetime.PLANS)
        self.there = os.path.join(self.main, ".claude", "p4", "temportal", lifetime.PLANS)

    def test_a_plan_sorted_in_a_worktree_leaves_the_worked_place_of_the_main_checkout(self):
        for shelf in lifetime.SHELVES:
            put(os.path.join(self.there, f"{shelf}.md"), "# worked\n", age_days=1)
            put(os.path.join(self.here, shelf, f"{shelf}.md"), f"STATUS: {shelf}\n")
        said = lifetime.carry_over(self.tree)
        for shelf in lifetime.SHELVES:
            self.assertFalse(os.path.exists(os.path.join(self.there, f"{shelf}.md")), shelf)
            self.assertEqual(read(os.path.join(self.there, shelf, f"{shelf}.md")), f"STATUS: {shelf}\n")
        self.assertIn("moved 3 plans of the main checkout's store", said[-1])
        self.assertIn(f"{lifetime.PLANS}/complete.md", said[-1])

    def test_a_plan_worked_under_a_sorted_name_is_carried_and_the_sorted_copy_goes_once_it_is_sorted_again(self):
        """Plan mode gives every plan of one session the same name, so a worked plan newer than a sorted one of its
        name takes no sorted plan away. A revived plan's sorted copy goes once the plan is sorted again."""
        parked = put(os.path.join(self.there, "todo", "p.md"), "STATUS: TODO\n", age_days=2)
        put(os.path.join(self.here, "p.md"), "# worked again\n", age_days=1)
        lifetime.carry_over(self.tree)
        self.assertEqual(read(parked), "STATUS: TODO\n")
        self.assertEqual(read(os.path.join(self.there, "p.md")), "# worked again\n")
        os.remove(os.path.join(self.here, "p.md"))
        put(os.path.join(self.here, "complete", "p.md"), "STATUS: COMPLETED\n")
        lifetime.carry_over(self.tree)
        self.assertFalse(os.path.exists(parked))
        self.assertFalse(os.path.exists(os.path.join(self.there, "p.md")))
        self.assertEqual(read(os.path.join(self.there, "complete", "p.md")), "STATUS: COMPLETED\n")

    def test_a_sessions_next_plan_in_a_worktree_takes_away_no_plan_the_main_checkout_holds_closed(self):
        first = put(os.path.join(self.there, "complete", "s.md"), "STATUS: COMPLETED\n", age_days=1)
        put(os.path.join(self.here, "complete", "s.md"), "STATUS: COMPLETED\n", age_days=2)
        put(os.path.join(self.here, "s.md"), "# the next plan\n")
        lifetime.carry_over(self.tree)
        self.assertEqual(read(first), "STATUS: COMPLETED\n")
        self.assertEqual(read(os.path.join(self.there, "s.md")), "# the next plan\n")

    def test_a_numbered_close_in_a_worktree_leaves_the_worked_place_and_an_older_copy_brings_it_back_nowhere(self):
        one = put(os.path.join(self.there, "complete", "s.md"), "STATUS: COMPLETED one\n", age_days=3)
        put(os.path.join(self.there, "s.md"), "# the second\n", age_days=2)
        put(os.path.join(self.here, "complete", "s.2.md"), "STATUS: COMPLETED two\n", age_days=1)
        said = lifetime.carry_over(self.tree)
        self.assertFalse(os.path.exists(os.path.join(self.there, "s.md")))
        self.assertEqual(read(os.path.join(self.there, "complete", "s.2.md")), "STATUS: COMPLETED two\n")
        self.assertEqual(read(one), "STATUS: COMPLETED one\n")
        self.assertIn("moved 1 plan of the main checkout's store", said[-1])
        put(os.path.join(self.here, "s.md"), "# the second\n", age_days=2)
        self.assertEqual(lifetime.carry_over(self.tree), [])
        self.assertFalse(os.path.exists(os.path.join(self.there, "s.md")))
        self.assertIsNotNone(lifetime.NUMBERED.fullmatch("s.2.md"))
        self.assertIsNone(lifetime.NUMBERED.fullmatch("quick-plan-brave-otter.md"))

    def test_a_numbered_close_leaves_the_plan_the_worktree_still_works_under_the_stem(self):
        put(os.path.join(self.here, "s.md"), "# the third\n", age_days=2)
        lifetime.carry_over(self.tree)
        put(os.path.join(self.here, "complete", "s.2.md"), "STATUS: COMPLETED two\n", age_days=1)
        lifetime.carry_over(self.tree)
        self.assertEqual(read(os.path.join(self.there, "s.md")), "# the third\n")
        self.assertEqual(read(os.path.join(self.there, "complete", "s.2.md")), "STATUS: COMPLETED two\n")

    def test_an_older_worked_copy_in_a_worktree_brings_back_no_plan_the_main_checkout_closed(self):
        put(os.path.join(self.here, "p.md"), "# worked\n", age_days=1)
        put(os.path.join(self.there, "complete", "p.md"), "STATUS: COMPLETED\n")
        self.assertEqual(lifetime.carry_over(self.tree), [])
        self.assertFalse(os.path.exists(os.path.join(self.there, "p.md")))
        self.assertEqual(read(os.path.join(self.there, "complete", "p.md")), "STATUS: COMPLETED\n")

    def test_the_move_is_staged_where_the_main_checkouts_store_is_its_own_repository(self):
        store = os.path.join(self.main, ".claude", "p4")
        put(os.path.join(self.there, "p.md"), "# worked\n", age_days=1)
        git(store, "init", "-q")
        git(store, "add", "-A")
        git(store, "commit", "-q", "-m", "the plan")
        put(os.path.join(self.here, "unplanned", "p.md"), "STATUS: UNPLANNED\n")
        lifetime.carry_over(self.tree)
        staged = git(store, "diff", "--cached", "--name-status").stdout.decode()
        self.assertIn(f"D\ttemportal/{lifetime.PLANS}/p.md", staged)

    def test_a_plan_sorted_in_a_worktree_under_its_title_leaves_the_worked_place_of_the_main_checkout(self):
        put(os.path.join(self.there, "brave-otter.md"), "# Plan names\n", age_days=2)
        put(os.path.join(self.there, "quiet-fox.md"), "# Taken title\n", age_days=2)
        put(os.path.join(self.there, "other-heron.md"), "# Another plan\n", age_days=2)
        put(os.path.join(self.here, "complete", "plan-names.md"), "STATUS: COMPLETED\n# Plan names\n", age_days=1)
        put(os.path.join(self.here, "todo", "taken-title.2.md"), "STATUS: TODO\n# Taken title\n", age_days=1)
        said = lifetime.carry_over(self.tree)
        self.assertFalse(os.path.exists(os.path.join(self.there, "brave-otter.md")))
        self.assertFalse(os.path.exists(os.path.join(self.there, "quiet-fox.md")))
        self.assertEqual(read(os.path.join(self.there, "other-heron.md")), "# Another plan\n")
        self.assertEqual(read(os.path.join(self.there, "complete", "plan-names.md")),
                         "STATUS: COMPLETED\n# Plan names\n")
        self.assertIn("moved 2 plans of the main checkout's store", said[-1])

    def test_a_worked_plan_the_worktree_still_holds_is_left_by_a_title_named_close(self):
        put(os.path.join(self.here, "brave-otter.md"), "# Plan names\n", age_days=2)
        lifetime.carry_over(self.tree)
        put(os.path.join(self.here, "complete", "plan-names.md"), "STATUS: COMPLETED\n# Plan names\n", age_days=1)
        lifetime.carry_over(self.tree)
        self.assertEqual(read(os.path.join(self.there, "brave-otter.md")), "# Plan names\n")

    def test_an_older_worked_copy_brings_back_no_plan_the_main_checkout_closed_under_its_title(self):
        put(os.path.join(self.here, "brave-otter.md"), "# Plan names\n", age_days=2)
        put(os.path.join(self.here, "quiet-fox.md"), "# Taken title\n", age_days=2)
        put(os.path.join(self.there, "complete", "plan-names.md"), "STATUS: COMPLETED\n# Plan names\n", age_days=1)
        put(os.path.join(self.there, "todo", "taken-title.3.md"), "STATUS: TODO\n# Taken title\n", age_days=1)
        self.assertEqual(lifetime.carry_over(self.tree), [])
        self.assertFalse(os.path.exists(os.path.join(self.there, "brave-otter.md")))
        self.assertFalse(os.path.exists(os.path.join(self.there, "quiet-fox.md")))

    def test_a_sessions_next_plan_takes_away_no_plan_the_main_checkout_holds_under_its_title(self):
        first = put(os.path.join(self.there, "complete", "plan-names.md"), "STATUS: COMPLETED\n", age_days=2)
        put(os.path.join(self.here, "brave-otter.md"), "# Plan names\n# the next plan\n")
        lifetime.carry_over(self.tree)
        self.assertEqual(read(first), "STATUS: COMPLETED\n")
        self.assertEqual(read(os.path.join(self.there, "brave-otter.md")), "# Plan names\n# the next plan\n")

    def test_a_plan_sorted_under_plan_modes_name_still_matches_by_name_in_both_directions(self):
        """Plans sorted before p4-temportal 0.3.71 hold plan mode's name, and a title that makes another name leaves
        that match as it was."""
        put(os.path.join(self.there, "brave-otter.md"), "# Plan names\n", age_days=2)
        put(os.path.join(self.here, "complete", "brave-otter.md"), "STATUS: COMPLETED\n# Plan names\n", age_days=1)
        put(os.path.join(self.here, "quiet-fox.md"), "# Another plan\n", age_days=2)
        put(os.path.join(self.there, "todo", "quiet-fox.2.md"), "STATUS: TODO\n# Another plan\n", age_days=1)
        lifetime.carry_over(self.tree)
        self.assertFalse(os.path.exists(os.path.join(self.there, "brave-otter.md")))
        self.assertEqual(read(os.path.join(self.there, "complete", "brave-otter.md")),
                         "STATUS: COMPLETED\n# Plan names\n")
        self.assertFalse(os.path.exists(os.path.join(self.there, "quiet-fox.md")))


class FolderMove(unittest.TestCase):
    """The plans folder was temportal/plans until p4-temportal 0.3.55 and is temportal/plan-planner since. The layout
    move takes the old folder into the new one once, with its complete/ and todo/, its cookies and its cache rules,
    and a plan a session still writes into the old folder is taken in again, so none is lost."""

    def setUp(self):
        self.p4 = tempfile.mkdtemp(prefix="p4-temportal-planner-move-")
        self.addCleanup(wipe, self.p4)
        self.old = os.path.join(self.p4, "temportal", "plans")
        self.new = os.path.join(self.p4, *lifetime.p4conf.PLANS.split("/"))

    def test_the_folder_is_the_plugins_plan_planner_and_the_old_one_its_earlier_place(self):
        self.assertEqual(lifetime.p4conf.PLANS, "temportal/plan-planner")
        self.assertEqual(lifetime.PLANS, "plan-planner")
        self.assertEqual(lifetime.p4conf.OLDER["plans"], ["temportal/plans"])

    def test_the_old_folder_moves_with_its_categories_cookies_and_cache_rules(self):
        put(os.path.join(self.old, "worked.md"), "# worked\n")
        put(os.path.join(self.old, "complete", "done.md"), "STATUS: COMPLETED\n")
        put(os.path.join(self.old, "todo", "parked.md"), "STATUS: TODO\n")
        with open(os.path.join(self.p4, "temportal", "expires.json"), "w", encoding="utf-8") as f:
            json.dump({"plans/worked.md": {"expires": 1e12}}, f)
        with open(lifetime.p4conf.path(self.p4), "w", encoding="utf-8") as f:
            json.dump({"temportal": {"cache": {"plans": {"max_age_days": 90}}}}, f)
        lines = lifetime.p4conf.migrate_layout(self.p4)
        self.assertTrue(any("moved temportal/plans/ to temportal/plan-planner/" in line for line in lines), lines)
        self.assertFalse(os.path.exists(self.old))
        self.assertEqual(read(os.path.join(self.new, "worked.md")), "# worked\n")
        self.assertEqual(read(os.path.join(self.new, "complete", "done.md")), "STATUS: COMPLETED\n")
        self.assertEqual(read(os.path.join(self.new, "todo", "parked.md")), "STATUS: TODO\n")
        self.assertEqual(list(lifetime.read_expires(self.p4)), ["plan-planner/worked.md"])
        conf = json.loads(read(lifetime.p4conf.path(self.p4)))
        self.assertEqual(list(conf["temportal"]["cache"]), ["plan-planner"])
        self.assertEqual(lifetime.p4conf.migrate_layout(self.p4), [], "the move is made once")

    def test_a_plan_a_session_still_writes_into_the_old_folder_is_taken_in_again(self):
        """A session whose Claude Code read the old plansDirectory at its start writes its plan there until it ends.
        Each sweep starts with the layout move, which keeps the newer of two differing copies in the new folder and
        sets the older aside."""
        put(os.path.join(self.old, "running.md"), "# first\n", age_days=1)
        lifetime.p4conf.migrate_layout(self.p4)
        put(os.path.join(self.old, "running.md"), "# first\n# and more\n")
        lifetime.start_sweep(self.p4)
        self.assertFalse(os.path.exists(self.old))
        self.assertEqual(read(os.path.join(self.new, "running.md")), "# first\n# and more\n")
        aside = os.path.join(self.p4, "temportal", lifetime.p4conf.LAYOUT_CONFLICTS, "plans", "running.md")
        self.assertEqual(read(aside), "# first\n")


if __name__ == "__main__":
    unittest.main()
