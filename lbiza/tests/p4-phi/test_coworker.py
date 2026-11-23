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

    def drafts(self, path=None, checkout="E:/repo", mode="auto", windows=True, claim=True):
        return coworker.drafts(path or self.path, checkout, WHO, mode, self.home, PLANNER, self.home, claim=claim,
                               windows=windows)

    def land(self, path=None, mode="auto", claim=True):
        return coworker.land(path or self.path, "E:/repo", WHO, mode, self.home, PLANNER, self.home, claim=claim,
                             windows=True)

    def test_each_group_that_earns_a_team_is_one_start_file_in_its_node_in_the_checkout(self):
        first, second = self.drafts()
        name = first["name"]
        self.assertRegex(name, r"^cw-the-exporter-s-m-1-[0-9a-f]{4}$")
        self.assertEqual((first["sections"], first["fences"], first["team"]), (["1"], 5, True))
        self.assertEqual((second["name"], second["sections"]), (name.replace("-m-1-", "-m-2-"), ["2"]))
        self.assertEqual((first["folder"], second["folder"]), (self.node(1), self.node(2)))
        other = os.path.join(self.base, "other", "plan.md")
        os.makedirs(os.path.dirname(other))
        with open(other, "w", encoding="utf-8") as f:
            f.write(PLAN)
        self.assertNotEqual(coworker.drafts(other, "E:/repo", WHO)[0]["name"], name, "another plan of one title")
        self.assertEqual(first["file"], f"start-{name}.ps1")
        self.assertEqual(len(first["lines"]), 4)
        self.assertIn("'CLAUDE_CODE_HOST_SESSION_ID'", first["lines"][0])
        self.assertEqual(first["lines"][1], "$env:CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = '1'")
        self.assertEqual(first["lines"][2], "Set-Location 'E:\\repo'")
        run = first["lines"][3]
        level = plans.CHILD_LEVELS["static"]
        at = first["folder"].replace("/", "\\")
        self.assertRegex(first["session"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")
        for word in (f"claude --name {name} --session-id {first['session']} --model {level['model']} ",
                     f"--effort {level['effort']} ", "--permission-mode auto ",
                     f"--settings '{at}\\coworker-settings.json' '"):
            self.assertIn(word, run, word)
        for word in (" -p ", "--worktree", "--add-dir"):
            self.assertNotIn(word, run, word)
        self.assertEqual(first["typed"], f"& '{at}\\start-{name}.ps1'")
        n = relay.node_record(self.home, name)
        self.assertEqual((n["kind"], n["parent"], n["sections"], n["session"]),
                         ("reader", PLANNER, ["1"], first["session"]))

    def test_a_task_names_its_sections_reads_in_the_checkout_and_holds_no_character_a_shell_reads(self):
        first = self.drafts()[0]
        said = first["lines"][3].split("coworker-settings.json' '", 1)[1][:-1]
        self.assertNotRegex(said, r"['\"`$;|&<>\\]")
        self.assertIn("section 1 of the plan file " + self.path.replace("\\", "/"), said)
        self.assertIn("judge them against this folder, the checkout.", said)
        self.assertNotIn("worktree", said)
        self.assertIn("the session named Plan: the exporter s  move   HOME,", said)

    def test_the_script_is_a_posix_shells_elsewhere_and_names_no_mode_where_none_is_known(self):
        first = self.drafts(checkout="/repo", mode="", windows=False)[0]
        self.assertEqual(first["file"], f"start-{first['name']}.sh")
        self.assertTrue(first["lines"][0].startswith("unset CLAUDE_CODE_HOST_SESSION_ID "))
        self.assertEqual(first["lines"][1:3], ["export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1", "cd '/repo'"])
        self.assertNotIn("--permission-mode", first["lines"][3])
        self.assertEqual(first["typed"], f"sh '{self.node()}/start-{first['name']}.sh'")

    def test_drafts_with_claim_false_makes_no_folder_and_an_entry_holds_its_name_alone(self):
        found = self.drafts(claim=False)
        self.assertEqual([sorted(one) for one in found], [["fences", "name", "sections", "team"]] * 2)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))
        self.assertEqual([sorted(one) for one in self.land(claim=False)], [["name", "sections"]] * 2)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))

    def test_one_small_group_of_prose_earns_no_team_and_gets_no_start_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SMALL)
        self.assertEqual(coworker.drafts(self.path, "E:/repo", WHO),
                         [{"sections": ["1"], "fences": 1, "team": False}])
        self.assertEqual(len(self.land()), 1, "a terminal worker lands a group that earns no team")

    def test_the_files_are_written_into_the_node_with_p4s_two_plugins_off_and_no_other_setting(self):
        found = self.drafts(checkout=self.base)
        wrote = coworker.write(found, self.base)
        self.assertEqual(sorted(os.listdir(found[0]["folder"])),
                         sorted(["coworker-settings.json", found[0]["file"], relay.NODE]))
        self.assertEqual(len(wrote), 4)
        with open(os.path.join(found[0]["folder"], "coworker-settings.json"), encoding="utf-8") as f:
            settings = json.load(f)
        self.assertEqual(list(settings), ["enabledPlugins"])
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
        self.assertIn("--permission-mode auto ", run)
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
        first = self.drafts()
        coworker.write(first, self.base)
        again = self.drafts()
        self.assertEqual([one["started"] for one in again], [one["folder"] for one in first])
        self.assertFalse([one for one in again if one.get("file")])
        self.assertEqual(coworker.write(again, self.base), [])
        self.assertEqual(len(relay.stores(self.home)), 3, "no further store")
        landed = self.land()
        self.assertEqual([one["started"] for one in self.land()], [one["folder"] for one in landed])

    def test_a_reading_teams_start_lines_are_the_scripts_with_no_worktree_and_its_session(self):
        first = self.drafts()[0]
        name = first["name"]
        task = coworker.task(self.path, [s for s in coworker.sections.parse(PLAN, "E:/repo")[1] if s["n"] == "1"], WHO)
        same = coworker.script(name, "E:/repo", "auto", task, first["folder"], windows=True, worktree=False,
                               team=True, session=first["session"])
        self.assertEqual((first["file"], first["lines"], first["typed"]), same)
        self.assertNotIn("--worktree", first["lines"][3])
        self.assertIn(coworker.TEAMS, first["lines"][1])

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

    def test_a_path_that_holds_a_quote_is_refused_and_no_start_file_is_drafted(self):
        with self.assertRaises(ValueError):
            coworker.drafts(self.path, "E:/it's/repo", WHO)
        with self.assertRaises(ValueError):
            self.drafts(checkout="E:/it's/repo")
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude")))

    def test_the_command_prints_the_groups_and_with_start_writes_each_node_and_the_call_that_starts_it(self):
        command = [sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "coworkers", self.path,
                   "--p4", self.home, "--session", "cli-0001", "--checkout", self.base]
        ran = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(len(ran.stdout.strip().split("\n")), 2, "one line a group")
        self.assertFalse(os.path.isdir(os.path.join(self.home, ".claude")), "with no --start it only prints")
        # `--for` names the planner by its record's title, which the task then holds, and its nodes are its own
        record = os.path.join(self.home, "phi", "sessions", "cli-0002")
        os.makedirs(record)
        with open(os.path.join(record, "session.json"), "w", encoding="utf-8") as f:
            json.dump({"sessionId": "cli-0002", "title": "Plan: the move"}, f)
        ran = subprocess.run(command + ["--for", "cli-0002", "--start"], capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(ran.stdout.count("`mcp__terminal__run_in_terminal` with "), 2)
        self.assertIn(f'"cwd": "{self.base.replace(chr(92), "/")}"', ran.stdout, "each runs in the checkout")
        relay.forget(self.home)
        self.assertEqual(len(relay.stores(self.home)), 3)
        folder = self.node(1)
        start = sorted(n for n in os.listdir(folder) if n.startswith("start-"))[0]
        with open(os.path.join(folder, start), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("the session named Plan: the move,", text)
        self.assertIn("--session-id ", text)
        self.assertNotIn("--worktree", text)
        self.assertEqual(relay.node_record(self.home, start[6:].rsplit(".", 1)[0])["parent"], "cli-0002")
        again = subprocess.run(command + ["--for", "cli-0002", "--start"], capture_output=True, text=True, timeout=60)
        self.assertEqual(again.returncode, 2, "a plan's coworkers are started once")
        self.assertIn("was started already", again.stderr)
        land = subprocess.run(command + ["--for", "cli-0002", "--land"], capture_output=True, text=True, timeout=60)
        self.assertEqual(land.returncode, 2, "no mode that asks nothing")
        none = subprocess.run(command[:6] + [self.path + ".gone"] + command[7:], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(none.returncode, 2)
        quoted = os.path.join(self.base, "it's")
        os.makedirs(quoted)
        waiting = subprocess.run(command + ["--wait", "--checkout", quoted], capture_output=True, text=True,
                                 timeout=60)
        self.assertEqual(waiting.returncode, 2, waiting.stderr)
        nobody = subprocess.run(command + ["--for", "cli-9999"], capture_output=True, text=True, timeout=60)
        self.assertEqual(nobody.returncode, 2)
        old = subprocess.run(command + ["--write", self.base], capture_output=True, text=True, timeout=60)
        self.assertEqual(old.returncode, 2, "--write is gone")


if __name__ == "__main__":
    unittest.main(verbosity=1)
