#!/usr/bin/env python3
"""coworker.py: a plan's groups of sections as the coworkers that read and land them.

    python -m pytest tests/p4-phi/test_coworker.py

agent-teams.md: "In non-interactive mode with the `-p` flag, including Agent SDK sessions, Claude doesn't spawn
teammates". A coworker's start file is an interactive `claude` run with the team variable set in its shell, in the
checkout, with a session id p4-phi gives it and a settings file that turns p4's plugins off. A coworker and a
terminal worker are each a node, a store nested in their starter's, where their files are.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import phi  # noqa: E402,F401  phi.py hands its own module to upkeep.py, which coworker.py reads
import coworker  # noqa: E402
import p4conf  # noqa: E402
import plans  # noqa: E402
import relay  # noqa: E402

TICKS = chr(96) * 3
FIVE = "".join(f"{TICKS}python\nx = {k}\n{TICKS}\n\n" for k in range(5))    # a group's fill, sections.FULL
PLAN = ("# The exporter's move\n\n## Context\n\nNo worker lands this.\n\n"
        "## 1. The writer\n\n- **Files:** `src/export/writer.py`\n- **Depends on:** none\n"
        "- **Checks:** `python -m pytest tests/test_writer.py`\n\n" + FIVE +
        "## 2. The page\n\n- **Files:** `docs/export.md`\n- **Depends on:** none\n\n" + FIVE)
SMALL = "# A note\n\n## 1. The page\n\n- **Files:** `docs/export.md`\n\n" + f"{TICKS}markdown\nA line.\n{TICKS}\n"
WHO = "Plan: the exporter's \"move\" $HOME"
TODAY = '{"enabledPlugins": {"p4-phi@p4-marketplace": false, "p4-temportal@p4-marketplace": false}}'
PLANNER = "local_plan0001"


class Coworker(unittest.TestCase):
    def setUp(self):
        base = tempfile.TemporaryDirectory(prefix="p4-phi-coworker-")
        self.addCleanup(base.cleanup)
        self.base = os.path.realpath(base.name)    # the long path, since a short one holds a `~` a task line drops
        self.path = os.path.join(self.base, "plan.md")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(PLAN)
        self.home = os.path.join(self.base, "proj", ".claude", "p4")
        os.makedirs(self.home)

    def node(self, i=1):
        """The folder `phi` of the planner's i-th child store."""
        return relay.store_of(self.home, i).replace("\\", "/") + "/phi"

    def drafts(self, path=None, checkout="E:/repo"):
        return coworker.drafts(path or self.path, checkout)

    def land(self, path=None, mode="auto", claim=True):
        return coworker.land(path or self.path, "E:/repo", WHO, mode, self.home, PLANNER, self.home, claim=claim,
                             windows=True)

    def test_drafts_print_each_group_with_its_sections_fences_and_whether_it_earns_a_team_and_make_nothing(self):
        first, second = self.drafts()
        self.assertEqual((first["sections"], first["fences"], first["team"]), (["1"], 5, True))
        self.assertEqual((second["sections"], second["fences"], second["team"]), (["2"], 5, True))
        self.assertEqual([sorted(one) for one in (first, second)], [["fences", "sections", "team"]] * 2)
        self.assertEqual([sorted(one) for one in self.land(claim=False)], [["name", "sections"]] * 2)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")), "nothing is made")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SMALL)
        self.assertEqual(self.drafts(), [{"sections": ["1"], "fences": 1, "team": False}])
        self.assertEqual(len(self.land()), 1, "a terminal worker lands a group that earns no team")

    def test_a_planners_task_names_its_title_asks_for_three_readers_and_holds_no_character_a_shell_reads(self):
        said = coworker.planner_task("Plan: the exporter's \"move\" $HOME")
        self.assertNotRegex(said, r"['\"`$;|&<>\\]")
        self.assertIn("plan-planner", said)
        self.assertIn("fences, sources and checks", said)
        self.assertIn("ExitPlanMode", said)
        self.assertIn("the exporter s  move   HOME", said)

    def test_a_planner_is_a_worker_in_plan_mode_with_the_team_variable_a_prompt_and_p4_temportal_on(self):
        found = coworker.worker("tw-plan-0001", "Plan the move.", "The plan is put", "/repo", self.home, PLANNER,
                                self.home, windows=False, team=True, mode="plan",
                                prompt=coworker.planner_task("the move"))
        self.assertEqual(found["file"], "start-tw-plan-0001.sh")
        self.assertEqual(found["lines"][1:3], ["export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1", "cd '/repo'"])
        run = found["lines"][3]
        self.assertIn("--permission-mode plan ", run)
        self.assertNotIn("/goal", run, "a planner's turn ends on ExitPlanMode, not on a goal")
        self.assertIn("Write the plan for the move in plan mode", run)
        self.assertIn(found["brief_file"], run, "its prompt names its brief")
        self.assertEqual(found["typed"], f"sh '{self.node()}/start-tw-plan-0001.sh'")
        self.assertTrue(found["temportal"])
        coworker.write([found], "/repo")
        with open(os.path.join(found["folder"], "coworker-settings.json"), encoding="utf-8") as f:
            on = json.load(f)["enabledPlugins"]
        self.assertEqual(on, {"p4-phi@p4-marketplace": False, "p4-temportal@p4-marketplace": True})
        plain = coworker.worker("tw-plain-0002", "Do it.", "It is done", "/repo", self.home, PLANNER, self.home,
                                windows=False)
        self.assertFalse(plain["temportal"])
        self.assertNotIn(coworker.TEAMS, "\n".join(plain["lines"]))
        self.assertIn("--permission-mode bypassPermissions ", plain["lines"][-1])

    def test_the_files_are_written_into_the_node_with_p4s_two_plugins_off_and_no_other_setting(self):
        found = self.land()
        wrote = coworker.write(found, self.base)
        self.assertEqual(sorted(os.listdir(found[0]["folder"])),
                         sorted(["coworker-settings.json", found[0]["file"], os.path.basename(found[0]["brief_file"]),
                                 relay.NODE]))
        self.assertEqual(len(wrote), 6)
        with open(os.path.join(found[0]["folder"], "coworker-settings.json"), encoding="utf-8") as f:
            settings = json.load(f)
        self.assertLessEqual(set(settings), {"enabledPlugins", "claudeMdExcludes"})
        self.assertIn("enabledPlugins", settings)
        self.assertEqual([x for x in settings.get("claudeMdExcludes", []) if x.startswith(self.base.replace("\\", "/"))],
                         [], "no exclude is of this test's own making; one above the temp folder is the machine's")
        self.assertEqual(sorted(settings["enabledPlugins"]),
                         ["p4-phi@p4-marketplace", "p4-temportal@p4-marketplace"])
        self.assertEqual(set(settings["enabledPlugins"].values()), {False})
        with open(os.path.join(found[0]["folder"], found[0]["file"]), encoding="utf-8") as f:
            self.assertEqual(f.read().rstrip("\n").split("\n"), found[0]["lines"])

    def test_settings_exclude_each_claude_local_md_above_the_checkout_that_imports_the_store(self):
        checkout = os.path.join(self.base, "a", "b", "repo")
        os.makedirs(checkout)
        above = [os.path.join(self.base, "CLAUDE.local.md"), os.path.join(self.base, "a", "b", "CLAUDE.local.md")]
        for path, text in ((above[0], f"# notes\n\n{p4conf.LINE}\n"), (above[1], f"  {p4conf.LINE}  \n"),
                           (os.path.join(self.base, "a", "CLAUDE.local.md"), "# no import here\n"),
                           (os.path.join(checkout, "CLAUDE.local.md"), p4conf.LINE + "\n")):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        got = json.loads(coworker.settings(checkout))
        mine = [x for x in got["claudeMdExcludes"] if x.startswith(self.base.replace("\\", "/"))]
        self.assertEqual(mine, [above[1].replace("\\", "/"), above[0].replace("\\", "/")],
                         "the nearest first; one without the line and the checkout's own are not listed")
        self.assertTrue(all("\\" not in x for x in got["claudeMdExcludes"]))
        self.assertEqual(sorted(got), ["claudeMdExcludes", "enabledPlugins"])

    def test_settings_are_todays_where_no_folder_above_holds_the_line(self):
        checkout = os.path.join(self.base, "repo")
        os.makedirs(checkout)
        with open(os.path.join(self.base, "CLAUDE.local.md"), "w", encoding="utf-8") as f:
            f.write("# notes, with no import\n")
        got = coworker.settings(checkout)
        if "claudeMdExcludes" in json.loads(got):         # a file above the temp folder of this machine
            self.skipTest("a CLAUDE.local.md above this machine's temp folder holds the line")
        self.assertEqual(got, TODAY)

    def test_a_terminal_worker_starts_in_its_node_with_no_worktree_and_no_add_dir_and_a_goal_as_its_prompt(self):
        one, second = self.land()
        name = one["name"]
        self.assertRegex(name, r"^tw-the-exporter-s-m-1-[0-9a-f]{4}$")
        self.assertEqual(name, coworker.worker_name(self.path, ["1"]))
        self.assertEqual(second["name"], name.replace("-m-1-", "-m-2-"))
        self.assertEqual(one["file"], f"start-{name}.ps1")
        self.assertEqual(len(one["lines"]), 3, "no team variable")
        self.assertNotIn(coworker.TEAMS, "\n".join(one["lines"]))
        run = one["lines"][-1]
        for word in ("--worktree", "--add-dir", "--session-id"):
            self.assertNotIn(word, run, word)
        self.assertIn("--permission-mode bypassPermissions ", run, "whatever mode its starter is in")
        self.assertTrue(run.startswith(f"claude --name {name} --model "), run)
        at = one["folder"].replace("/", "\\")
        self.assertIn(f"--settings '{at}\\coworker-settings.json' '/goal ", run)
        prompt = run.rsplit(" '", 1)[1]
        self.assertTrue(run.endswith("'") and prompt.startswith("/goal "), "the goal is the last argument")
        self.assertEqual(prompt[:-1], one["goal"])
        for word in (f"section 1 of the plan {self.path.replace(chr(92), '/')}", f"the brief {one['brief_file']} says",
                     f"the report {one['report']} is written", "Stop after 60 turns"):
            self.assertIn(word, one["goal"], word)
        self.assertEqual(one["brief_file"], f"{self.node()}/brief-{name}.md")
        self.assertEqual(one["report"], f"{self.node()}/report-{name}.md")
        self.assertEqual(one["typed"], f"& '{at}\\start-{name}.ps1'")
        self.assertEqual(relay.node_record(self.home, name)["kind"], "worker")

    def test_a_worker_for_any_brief_is_a_node_with_its_brief_report_and_a_goal_that_waits_on_its_done(self):
        found = coworker.worker("tw-a-check-0001", "Check the flush.\nFiles: none", "The check is done and passes",
                                "E:/repo", self.home, PLANNER, self.home, windows=True)
        self.assertEqual(found["name"], "tw-a-check-0001")
        self.assertEqual(relay.node_record(self.home, "tw-a-check-0001")["kind"], "worker")
        self.assertEqual(found["report"], f"{found['folder']}/report-tw-a-check-0001.md")
        self.assertTrue(found["brief"].endswith("Check the flush.\nFiles: none"))
        self.assertIn("Publish no issue", found["brief"])
        self.assertTrue(found["goal"].startswith("/goal The check is done and passes, as the brief "))
        self.assertIn(found["goal"], found["lines"][-1], "its goal is its prompt")
        self.assertNotIn(coworker.TEAMS, "\n".join(found["lines"]))
        for word in ("--worktree", "--add-dir"):
            self.assertNotIn(word, found["lines"][-1])
        again = coworker.worker("tw-a-check-0001", "x", "y", "E:/repo", self.home, PLANNER, self.home, windows=True)
        self.assertEqual(list(again), ["name", "started"], "a name that has a node is not started twice")
        with self.assertRaises(ValueError):
            coworker.worker("tw-b-0002", "x", "y", "E:/re'po", self.home, PLANNER, self.home)
        self.assertIsNone(relay.nodes(self.home).get("tw-b-0002"))

    def test_a_drafted_workers_name_is_tw_the_slug_of_its_title_and_the_last_four_of_its_draft_id(self):
        self.assertEqual(coworker.draft_name("Fix the Flush: rows & more!", "drf-0123456789"), "tw-fix-the-flush-rows-more-6789")
        self.assertEqual(coworker.draft_name("", "drf-ab12cd34ef"), "tw-work-34ef")
        self.assertLessEqual(len(coworker.draft_name("x" * 80, "drf-0000000000")), len("tw-") + 24 + 5)

    def test_the_start_file_names_the_profile_where_its_credentials_are_and_no_key_anywhere(self):
        win = coworker.script("tw-a", "E:/repo", "", "the prompt", "E:/n/phi", windows=True, team=False,
                              profile="p4-workers")[1]
        self.assertEqual(len(win), 4, "the clearing line, the profile line, the folder, the run")
        self.assertIn("'CLAUDE_CODE_HOST_SESSION_ID'", win[0])
        self.assertIn("Test-Path (Join-Path $d 'credentials\\p4-workers.json')", win[1])
        self.assertIn("$env:ANTHROPIC_PROFILE = 'p4-workers'", win[1])
        self.assertIn("$env:ANTHROPIC_CONFIG_DIR", win[1])
        sh = coworker.script("tw-a", "/repo", "", "the prompt", "/n/phi", windows=False, team=True,
                             profile="p4-workers")[1]
        self.assertEqual(sh[1], 'd="${ANTHROPIC_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/anthropic}"; '
                                '[ -f "$d/credentials/p4-workers.json" ] && export ANTHROPIC_PROFILE=p4-workers')
        self.assertEqual(sh[2], "export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1", "ahead of the team variable")
        for lines in (win, sh):
            self.assertFalse([x for x in lines if "API_KEY" in x], "no key is named")
        for windows in (True, False):
            plain = coworker.script("tw-a", "/repo", "", "the prompt", "/n/phi", windows=windows, team=False,
                                    profile="")[1]
            self.assertFalse([x for x in plain if "ANTHROPIC_PROFILE" in x], "an empty profile is off")
            for bad in ("p4 workers", "p4;workers", "p4/workers", "a'b"):
                with self.assertRaises(ValueError):
                    coworker.script("tw-a", "/repo", "", "the prompt", "/n/phi", windows=windows, profile=bad)

    def test_a_worker_and_a_landing_pass_the_profile_to_their_start_file(self):
        one = coworker.worker("tw-p-0001", "Do it.", "It is done", "E:/repo", self.home, PLANNER, self.home,
                              windows=True, profile="p4-workers")
        self.assertTrue(any("ANTHROPIC_PROFILE" in x for x in one["lines"]))
        found = coworker.land(self.path, "E:/repo", WHO, "auto", self.home, PLANNER, self.home, claim=True,
                              windows=True, profile="p4-workers")
        self.assertTrue(all(any("ANTHROPIC_PROFILE" in x for x in f["lines"]) for f in found))

    def test_the_brief_names_the_checkout_the_whole_commit_command_and_the_report_file(self):
        one = self.land()[0]
        brief = one["brief"]
        phi = os.path.join(SRC, "phi.py").replace("\\", "/")
        for word in ("Work in E:/repo, on the branch that is checked out, and make no worktree and no branch.",
                     f'python -I -X utf8 {phi} commit --checkout E:/repo -m "<message>" -- <path> ...',
                     "Never `git add -A`, `git commit -a` or a plain `git commit`. Push nothing and merge nothing.",
                     f"write your report to {one['report']} and end.", f"land section 1 of the plan `"):
            self.assertIn(word, brief, word)
        self.assertNotIn("worktree of its own", brief)

    def test_a_landed_section_is_in_no_brief_and_a_landed_plan_has_no_worker(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(PLAN.replace("## 1. The writer\n", "## 1. The writer\n\n**Evidence:** landed as abc1234\n"))
        (one,) = self.land()
        self.assertEqual(one["sections"], ["2"])
        self.assertNotIn("writer.py", one["brief"])
        self.assertIn("export.md", one["brief"])
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(PLAN.replace("## 1. The writer\n", "## 1. The writer\n\n**Evidence:** x\n")
                    .replace("## 2. The page\n", "## 2. The page\n\n**Evidence:** y\n"))
        self.assertEqual(self.land(), [])

    def test_land_refuses_a_quote_in_the_plans_path_and_write_adds_a_brief_for_each(self):
        quoted = os.path.join(self.base, "it's")
        os.makedirs(quoted)
        other = os.path.join(quoted, "plan.md")
        with open(other, "w", encoding="utf-8") as f:
            f.write(PLAN)
        with self.assertRaises(ValueError):
            self.land(other)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")), "nothing claimed for a refused plan")
        found = self.land()
        wrote = coworker.write(found, self.base)
        for one in found:
            self.assertEqual(sorted(os.listdir(one["folder"])),
                             sorted(["coworker-settings.json", one["file"], os.path.basename(one["brief_file"]),
                                     relay.NODE]))
        self.assertEqual(len(wrote), 6)
        with open(found[0]["brief_file"], encoding="utf-8") as f:
            self.assertEqual(f.read().rstrip("\n"), found[0]["brief"])

    def test_a_second_start_of_one_name_writes_nothing_and_names_the_node(self):
        first = self.land()
        coworker.write(first, self.base)
        again = self.land()
        self.assertEqual([one["started"] for one in again], [one["folder"] for one in first])
        self.assertFalse([one for one in again if one.get("file")])
        self.assertEqual(coworker.write(again, self.base), [])
        self.assertEqual(len(relay.stores(self.home)), 3, "no further store")

    def send(self, to, message, at="2026-11-23T10:00:00Z", name="SendMessage"):
        return {"type": "assistant", "timestamp": at,
                "message": {"content": [{"type": "text", "text": "ok"},
                                        {"type": "tool_use", "name": name, "input": {"to": to, "message": message}}]}}

    def team(self, name="cw-a", session="0c0ffee0-0000-4000-8000-000000000001"):
        """A reading team's node with its session id, and the path Claude Code keeps its lead's transcript at in
        the folder of `projects` it names after the checkout E:/repo."""
        relay.claim(self.home, self.home, name, "reader", PLANNER, ["1"], session=session)
        config = os.path.join(self.base, "config")
        return config, os.path.join(config, "projects", "E--repo", session + ".jsonl")

    def lead(self, *rows):
        from unittest import mock
        config, lead = self.team()
        os.makedirs(os.path.dirname(lead), exist_ok=True)
        with open(lead, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        return mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config})

    def test_kept_finds_the_sessions_transcript_in_the_checkouts_folder_of_projects(self):
        from unittest import mock
        config, lead = self.team()
        session = os.path.splitext(os.path.basename(lead))[0]
        mate = os.path.join(os.path.dirname(lead), session, "subagents", "agent-afences-1.jsonl")
        elsewhere = os.path.join(config, "projects", "E--other", session + ".jsonl")
        for path in (lead, mate, elsewhere, os.path.join(os.path.dirname(lead), "another.jsonl")):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
            self.assertEqual(coworker.kept("cw-a", self.home, "E:/repo"), [lead])
            self.assertEqual(coworker.kept("cw-a", self.home, "E:/repo", deep=True), sorted([lead, mate]))
            self.assertEqual(coworker.kept("cw-a", self.home, ""), sorted([lead, elsewhere]), "any folder")
            self.assertEqual(coworker.kept("cw-none", self.home, "E:/repo"), [], "a name with no node")

    def test_last_list_gives_the_last_message_to_the_holders_title(self):
        title = "Plan: the move"
        with self.lead(self.send(title, "round 1", "2026-11-23T10:00:00Z"),
                       self.send(title, "round 2\nline two", "2026-11-23T11:00:00Z"),
                       self.send("fences", "to a teammate", "2026-11-23T12:00:00Z"),
                       self.send("main", "after", "2026-11-23T13:00:00Z")):
            self.assertEqual(coworker.last_list("cw-a", title, self.home, "E:/repo"),
                             "2026-11-23T11:00:00Z to Plan: the move\nround 2\nline two")

    def test_where_none_names_the_holder_the_last_one_sent_outside_the_team_is_given(self):
        with self.lead(self.send("main", "the list", "2026-11-23T10:00:00Z"),
                       self.send("sources", "to a teammate", "2026-11-23T11:00:00Z"),
                       self.send("checks", "again", "2026-11-23T11:30:00Z"),
                       self.send("a1b2c3d4e5f6a7b8-0001", "to an agent's id", "2026-11-23T12:00:00Z"),
                       self.send("main", "not a send", "2026-11-23T13:00:00Z", name="Read")):
            self.assertEqual(coworker.last_list("cw-a", "Plan: the move", self.home, "E:/repo"),
                             "2026-11-23T10:00:00Z to main\nthe list")

    def test_last_list_is_empty_where_there_is_none(self):
        with self.lead(self.send("fences", "x"), self.send("a1b2c3d4e5f6a7b8-0001", "y"), {"type": "user"}):
            self.assertEqual(coworker.last_list("cw-a", "Plan: the move", self.home, "E:/repo"), "")
            self.assertEqual(coworker.last_list("cw-none", "Plan: the move", self.home, "E:/repo"), "")

    def test_the_watch_ends_once_no_coworker_wrote_a_line_and_an_api_error_is_a_stop(self):
        from unittest import mock
        config, lead = self.team()
        mate = os.path.join(os.path.splitext(lead)[0], "subagents", "agent-afences-1.jsonl")
        os.makedirs(os.path.dirname(mate))
        with open(lead, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": "the round's list"}}) + "\n")
        open(mate, "w").close()
        began = 1_000_000.0
        now = [began]

        def sleep(seconds):
            now[0] += seconds

        def clock():
            return now[0]

        def wrote(path, at):
            os.utime(path, (at, at))
        home, here = self.home, "E:/repo"
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
            wrote(lead, began - 500)
            wrote(mate, began + 5)                 # a teammate's line, after the watch began
            self.assertEqual(coworker.watch(["cw-a"], home, here, quiet=60, clock=clock, sleep=sleep), ("quiet", 70))
            now[0] = began
            wrote(mate, began - 400)               # idle since before the round: no line of this round yet
            self.assertEqual(coworker.watch(["cw-a"], home, here, quiet=60, first=30, clock=clock, sleep=sleep),
                             ("silent", 30))
            now[0] = began
            self.assertEqual(coworker.watch(["cw-none"], home, here, first=20, clock=clock, sleep=sleep),
                             ("silent", 20))
            now[0] = began
            wrote(mate, began + 5)
            self.assertEqual(coworker.watch(["cw-a"], home, here, quiet=10 ** 9, longest=30, clock=clock,
                                            sleep=sleep), ("long", 30))
            self.assertFalse(coworker.stopped("cw-a", home, here))
            with open(lead, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "assistant", "isApiErrorMessage": True,
                                    "message": {"content": "API Error: 529 Overloaded"}}) + "\n")
                f.write(json.dumps({"type": "system"}) + "\n")
            self.assertTrue(coworker.stopped("cw-a", home, here), "the last assistant row is the error")
            self.assertFalse(coworker.stopped("cw-none", home, here))

    def test_a_path_that_holds_a_quote_is_refused_before_any_claim_and_a_read_only_draft_raises_nothing(self):
        self.assertEqual(len(coworker.drafts(self.path, "E:/it's/repo")), 2, "nothing is made, nothing checked")
        with self.assertRaises(ValueError):
            coworker.land(self.path, "E:/it's/repo", WHO, "auto", self.home, PLANNER, self.home, claim=True)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")), "nothing claimed")

    def test_a_failure_after_the_claim_removes_the_nodes_of_that_call(self):
        from unittest import mock
        with mock.patch.object(coworker, "script", side_effect=ValueError("late")):
            with self.assertRaises(ValueError):
                self.land()
        relay.forget(self.home)
        self.assertEqual(relay.nodes(self.home), {}, "no name is stranded")
        found = self.land()
        found[1]["lines"] = [None]                 # the second entry's start file cannot be made
        with self.assertRaises(TypeError):
            coworker.write(found, self.base, self.home)
        self.assertFalse(os.path.exists(found[0]["folder"]), "what the write made is taken out, and its node")
        self.assertEqual(relay.nodes(self.home), {}, "and the nodes of that call with it")
        self.assertEqual([one["folder"] for one in self.land()], [self.node(1), self.node(2)], "free again")

    def test_wait_report_counts_only_a_report_written_after_the_wait_began_whatever_the_claim_time(self):
        """A worker that went on working after its first report writes another: the wait for it is not done at once
        for the first, written after the node's claim and before the wait began."""
        one = self.land()[0]
        store = relay.nodes(self.home)[one["name"]]
        claimed = time.time() - 900
        os.utime(os.path.join(store, "phi", relay.NODE), (claimed, claimed))
        with open(one["report"], "w", encoding="utf-8") as f:
            f.write("the first report\n")
        first = time.time() - 300
        os.utime(one["report"], (first, first))
        now = [0.0]

        def tick(s):
            now[0] += s

        def rewrite(s):
            tick(s)
            if now[0] >= 20:
                with open(one["report"], "w", encoding="utf-8") as f:
                    f.write("the second report\n")
        self.assertEqual(coworker.wait_report(one["report"], self.home, one["name"], longest=30,
                                              clock=lambda: now[0], sleep=tick), ("long", 30))
        now[0] = 0.0
        self.assertEqual(coworker.wait_report(one["report"], self.home, one["name"], longest=60,
                                              clock=lambda: now[0], sleep=rewrite), ("done", 20))

    def test_kept_takes_the_checkout_from_the_node_so_a_wait_works_from_any_folder(self):
        from unittest import mock
        config = os.path.join(self.base, "config")
        session = "0c0ffee0-0000-4000-8000-000000000002"
        relay.claim(self.home, self.home, "cw-b", "reader", PLANNER, ["1"], session=session, checkout="E:/repo")
        lead = os.path.join(config, "projects", "E--repo", session + ".jsonl")
        os.makedirs(os.path.dirname(lead))
        open(lead, "w").close()
        began = 1_000_000.0
        os.utime(lead, (began - 500, began - 500))
        self.assertEqual(relay.node_record(self.home, "cw-b")["checkout"], "E:/repo")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
            self.assertEqual(coworker.kept("cw-b", self.home, "E:/elsewhere"), [lead])
            now = [began]
            self.assertEqual(coworker.watch(["cw-b"], self.home, "E:/elsewhere", first=20,
                                            clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s)),
                             ("silent", 20), "a line from before the watch")

    def test_the_command_prints_the_groups_and_with_land_writes_each_node_and_the_call_that_starts_it(self):
        command = [sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "coworkers", self.path,
                   "--p4", self.home, "--session", "cli-0001", "--checkout", self.base]
        ran = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(len(ran.stdout.strip().split("\n")), 2, "one line a group")
        self.assertFalse(os.path.isdir(os.path.join(self.home, ".claude")), "with no --land it only prints")
        land = subprocess.run(command + ["--land"], capture_output=True, text=True, timeout=60)
        self.assertEqual(land.returncode, 0, land.stderr)
        self.assertEqual(land.stdout.count("`mcp__terminal__run_in_terminal` with "), 2)
        self.assertIn(f'"cwd": "{self.base.replace(chr(92), "/")}"', land.stdout, "each runs in the checkout")
        relay.forget(self.home)
        self.assertEqual(len(relay.stores(self.home)), 3)
        again = subprocess.run(command + ["--land"], capture_output=True, text=True, timeout=60)
        self.assertEqual(again.returncode, 2, "a plan's workers are started once")
        none = subprocess.run(command[:6] + [self.path + ".gone"] + command[7:], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(none.returncode, 2)
        for gone in ("--start", "--for"):
            old = subprocess.run(command + [gone] + (["cli-0002"] if gone == "--for" else []), capture_output=True,
                                 text=True, timeout=60)
            self.assertEqual(old.returncode, 2, f"{gone} is gone")


if __name__ == "__main__":
    unittest.main(verbosity=1)
