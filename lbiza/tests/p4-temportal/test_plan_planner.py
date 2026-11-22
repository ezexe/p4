#!/usr/bin/env python3
"""test_plan_planner.py: p4-temportal's skill plan-planner, its rules for a plan's sections and its three places.

The rules of a section are the source skill's word for word, but that ezexe is named where the source says the boss.
A plan is worked in the store's temportal/plans, finished in temportal/plans/complete and parked in
temportal/plans/todo, and the retention sweep, the copy out of Claude Code's own plans folder and the carry out of a
worktree each keep to those places.

    python -m pytest tests/p4-temportal/test_plan_planner.py
"""

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
TEMPORTAL = PLUGIN / "skills" / "temportal" / "SKILL.md"
PAGE = pathlib.Path(__file__).resolve().parents[3] / "docs" / "temportal-native.html"
sys.path.insert(0, str(PLUGIN / "hooks"))
import lifetime  # noqa: E402

DAY = 86400

# The source skill's section rules, word for word, with ezexe where it says the boss.
SECTION = """## What every section of a plan holds

- **Intents:** the section opens by listing what it means to change, one line each.
- **Fences:** every edit is a fenced code block, and above it, its intent:
  - **Documented:** the source in detail: the upstream page or file and line, read live or in the checkout, quoted where a quote fits.
  - **Derivation:** in prose, how the approach follows from that source, and why this approach rather than another.
- **No choices for ezexe:** a section avoids, with all the effort it takes, putting a choice to ezexe. Wherever the plan's writer wants to present one, that is the sign the section's planning failed to find the documented approach: the writer goes back to the upstream sources, finds how upstream does it, and writes that approach with its Documented and Derivation, the alternatives named only in the Derivation's "rather than another". A choice reaches ezexe only when no upstream source settles it after that search; it then names the sources searched and what each said.
- **Evidence:** once a section is implemented, its evidence is added to that same section: links to the implemented lines (`[path:N-M](../../../../path:N-M)`) with what ran and its output. Only then does the next section start.
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
        for word in ("temportal/plans", "complete/", "todo/", "Invoke BEFORE writing, landing, closing, parking, "
                     "reviving or reading a plan or design doc", "Never the repo root, the scratchpad or an ad-hoc "
                     "directory"):
            self.assertIn(word, description, word)

    def test_every_section_holds_the_source_skills_rules_word_for_word(self):
        self.assertTrue(text().endswith(SECTION), "the section rules are the source's, with ezexe for the boss")

    def test_ezexe_is_named_and_never_the_boss_or_the_owner(self):
        body = text()
        self.assertNotRegex(body.lower(), r"\bboss\b")
        self.assertNotRegex(body.lower(), r"\bthe owner\b")
        self.assertIn("No choices for ezexe", body)
        self.assertIn("Park** on ezexe's word only", body)
        self.assertIn("Revive** on ezexe's word only", body)

    def test_the_three_places_are_folders_of_the_store_and_no_orphan_branch(self):
        body = text()
        for place in ("`.claude/p4/temportal/plans/<plan>.md`", "`.claude/p4/temportal/plans/complete/<plan>.md`",
                      "`.claude/p4/temportal/plans/todo/<plan>.md`"):
            self.assertIn(place, body, place)
        self.assertIn("closed plans add nothing to the code branches' history", body)
        self.assertIn("`plansDirectory`", body)
        self.assertIn("git -C .claude/p4 mv temportal/plans/<plan>.md", body)
        self.assertNotIn("orphan", body)
        self.assertNotIn("git worktree add", body)
        self.assertNotIn("origin plans", body)

    def test_the_skill_says_what_keeps_a_finished_or_parked_plan(self):
        body = text()
        self.assertIn("`cleanupPeriodDays`", body)
        self.assertIn("Nothing in `complete/` or `todo/` is cleared by age", body)

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

    def test_the_temportal_skill_points_to_it(self):
        body = TEMPORTAL.read_text(encoding="utf-8")
        self.assertIn("is the skill `plan-planner` of this plugin", body)
        self.assertIn("`plans/complete/` or `plans/todo/` stays until ezexe's word moves it", body)

    def test_the_page_has_its_passage(self):
        page = PAGE.read_text(encoding="utf-8")
        row = re.search(r'<tr id="row-plans">.*?</tr>', page, re.S).group(0)
        for word in ("<code>plan-planner</code>", "temportal/plans/complete", "temportal/plans/todo",
                     "orphan branch", "Plan files written during plan mode", "No live session has closed a plan"):
            self.assertIn(word, row, word)


class Places(unittest.TestCase):
    """The places on a store on disk."""

    def setUp(self):
        from unittest import mock
        self.base = tempfile.mkdtemp(prefix="p4-temportal-planner-")
        self.addCleanup(wipe, self.base)
        self.root = os.path.join(self.base, "proj")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        self.plans = os.path.join(self.p4, "temportal", "plans")
        os.makedirs(self.plans)
        self.config = os.path.join(self.base, "config")
        self.own = os.path.join(self.config, "plans")
        env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)

    def test_the_age_clears_a_worked_plan_and_keeps_every_finished_and_parked_one(self):
        worked = put(os.path.join(self.plans, "old-worked.md"), age_days=40)
        done = put(os.path.join(self.plans, "complete", "old-done.md"), age_days=400)
        parked = put(os.path.join(self.plans, "todo", "old-parked.md"), age_days=400)
        said = lifetime.sweep(self.p4, days=30.0)
        self.assertEqual(said, "p4-temportal: cleared plans older than the 30 days of cleanupPeriodDays: 1, in plans/.")
        self.assertEqual([os.path.exists(p) for p in (worked, done, parked)], [False, True, True])
        self.assertEqual(lifetime.sweep(self.p4, days=1.0), "")

    def test_neither_place_takes_a_cookie_whole_and_a_plan_in_one_takes_its_own(self):
        done = put(os.path.join(self.plans, "complete", "a.md"))
        put(os.path.join(self.plans, "todo", "b.md"))
        for folder in ("plans/complete", "plans/todo"):
            with self.assertRaises(ValueError, msg=folder):
                lifetime.set_cookie(self.p4, folder, "7d")
        self.assertEqual(lifetime.set_cookie(self.p4, done, "7d")[0], "plans/complete/a.md")

    def test_a_closed_or_parked_plan_is_not_copied_back_out_of_claude_codes_own_folder(self):
        with open(os.path.join(self.root, ".claude", "settings.local.json"), "w", encoding="utf-8") as f:
            f.write('{"plansDirectory": ".claude/p4/temportal/plans"}')
        put(os.path.join(self.plans, "complete", "closed.md"), "STATUS: COMPLETED\n", age_days=1)
        put(os.path.join(self.plans, "todo", "parked.md"), "STATUS: TODO\n", age_days=1)
        made = [put(os.path.join(self.own, name), "# again\n") for name in ("closed.md", "parked.md", "new.md")]
        said = lifetime.keep_plans(self.root, made, made)
        self.assertEqual(sorted(os.listdir(self.plans)), ["complete", "new.md", "todo"])
        self.assertIn("new.md", said[0])
        self.assertNotIn("closed.md", said[0])
        self.assertEqual(read(os.path.join(self.plans, "complete", "closed.md")), "STATUS: COMPLETED\n")


class CarriedPlaces(unittest.TestCase):
    """A plan a worktree closed, parked or revived leaves its old place in the main checkout's store, and an older
    copy a worktree still holds brings no plan back that the main checkout closed."""

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
        self.here = os.path.join(self.tree, ".claude", "p4", "temportal", "plans")
        self.there = os.path.join(self.main, ".claude", "p4", "temportal", "plans")

    def test_a_plan_closed_in_a_worktree_leaves_the_worked_place_of_the_main_checkout(self):
        put(os.path.join(self.there, "p.md"), "# worked\n", age_days=1)
        put(os.path.join(self.here, "complete", "p.md"), "STATUS: COMPLETED\n")
        said = lifetime.carry_over(self.tree)
        self.assertFalse(os.path.exists(os.path.join(self.there, "p.md")))
        self.assertEqual(read(os.path.join(self.there, "complete", "p.md")), "STATUS: COMPLETED\n")
        self.assertIn("moved 1 plan of the main checkout's store", said[-1])
        self.assertIn("plans/p.md", said[-1])

    def test_a_plan_revived_in_a_worktree_leaves_the_parked_place(self):
        put(os.path.join(self.there, "todo", "p.md"), "STATUS: TODO\n", age_days=1)
        put(os.path.join(self.here, "p.md"), "# worked again\n")
        lifetime.carry_over(self.tree)
        self.assertFalse(os.path.exists(os.path.join(self.there, "todo", "p.md")))
        self.assertEqual(read(os.path.join(self.there, "p.md")), "# worked again\n")

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
        put(os.path.join(self.here, "todo", "p.md"), "STATUS: TODO\n")
        lifetime.carry_over(self.tree)
        staged = git(store, "diff", "--cached", "--name-status").stdout.decode()
        self.assertIn("D\ttemportal/plans/p.md", staged)


if __name__ == "__main__":
    unittest.main()
