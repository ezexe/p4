#!/usr/bin/env python3
"""coworker.py: a plan's groups of sections as the coworkers that read and land them.

    python -m pytest tests/p4-phi/test_coworker.py

agent-teams.md: "In non-interactive mode with the `-p` flag, including Agent SDK sessions, Claude doesn't spawn
teammates", and worktrees.md: a worktree started with `--worktree <name>` is on "a new branch named
`worktree-<name>`". A coworker's start file is an interactive `claude` run with the team variable set in its shell,
a worktree of its own name and a settings file that turns p4's plugins off.
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
import plans  # noqa: E402

TICKS = chr(96) * 3
FIVE = "".join(f"{TICKS}python\nx = {k}\n{TICKS}\n\n" for k in range(5))    # a group's fill, sections.FULL
PLAN = ("# The exporter's move\n\n## Context\n\nNo worker lands this.\n\n"
        "## 1. The writer\n\n- **Files:** `src/export/writer.py`\n- **Depends on:** none\n"
        "- **Checks:** `python -m pytest tests/test_writer.py`\n\n" + FIVE +
        "## 2. The page\n\n- **Files:** `docs/export.md`\n- **Depends on:** none\n\n" + FIVE)
SMALL = "# A note\n\n## 1. The page\n\n- **Files:** `docs/export.md`\n\n" + f"{TICKS}markdown\nA line.\n{TICKS}\n"
WHO = "Plan: the exporter's \"move\" $HOME"


class Coworker(unittest.TestCase):
    def setUp(self):
        base = tempfile.TemporaryDirectory(prefix="p4-phi-coworker-")
        self.addCleanup(base.cleanup)
        self.base = os.path.realpath(base.name)    # the long path, since a short one holds a `~` a task line drops
        self.path = os.path.join(self.base, "plan.md")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(PLAN)

    def test_each_group_that_earns_a_team_is_one_start_file_in_a_worktree_of_its_own_name(self):
        first, second = coworker.drafts(self.path, "E:/repo", WHO, "auto", "E:/notes/terminal-workers", windows=True)
        name = first["name"]
        self.assertRegex(name, r"^cw-the-exporter-s-m-1-[0-9a-f]{4}$")
        self.assertEqual((first["sections"], first["fences"], first["team"]), (["1"], 5, True))
        self.assertEqual((second["name"], second["sections"]), (name.replace("-m-1-", "-m-2-"), ["2"]))
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
        for word in (f"claude --name {name} --worktree {name} ",
                     f"--model {level['model']} --effort {level['effort']} ", "--permission-mode auto ",
                     "--settings 'E:\\notes\\terminal-workers\\coworker-settings.json' '"):
            self.assertIn(word, run, word)
        self.assertNotIn(" -p ", run, "a scripted run spawns no teammate")
        self.assertEqual(first["typed"], f"& 'E:\\notes\\terminal-workers\\start-{name}.ps1'")

    def test_a_task_names_its_sections_and_holds_no_character_a_shell_reads(self):
        first = coworker.drafts(self.path, "E:/repo", WHO, "auto", "E:/notes", windows=True)[0]
        said = first["lines"][3].split("coworker-settings.json' '", 1)[1][:-1]
        self.assertNotRegex(said, r"['\"`$;|&<>\\]")
        self.assertIn("section 1 of the plan file " + self.path.replace("\\", "/"), said)
        self.assertIn("the session named Plan: the exporter s  move   HOME,", said)

    def test_the_script_is_a_posix_shells_elsewhere_and_names_no_mode_where_none_is_known(self):
        first = coworker.drafts(self.path, "/repo", WHO, "", "/notes", windows=False)[0]
        self.assertEqual(first["file"], f"start-{first['name']}.sh")
        self.assertTrue(first["lines"][0].startswith("unset CLAUDE_CODE_HOST_SESSION_ID "))
        self.assertEqual(first["lines"][1:3], ["export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1", "cd '/repo'"])
        self.assertNotIn("--permission-mode", first["lines"][3])
        self.assertEqual(first["typed"], f"sh '/notes/start-{first['name']}.sh'")

    def test_one_small_group_of_prose_earns_no_team_and_gets_no_start_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(SMALL)
        self.assertEqual(coworker.drafts(self.path, "E:/repo", WHO),
                         [{"sections": ["1"], "fences": 1, "team": False}])
        self.assertEqual(len(coworker.land(self.path, self.base, self.base + "/w", WHO, "auto", windows=True)), 1,
                         "a terminal worker lands a group that earns no team")

    def test_the_files_are_written_with_p4s_two_plugins_off_and_no_other_setting(self):
        folder = os.path.join(self.base, "notes", "terminal-workers")
        found = coworker.drafts(self.path, "E:/repo", WHO, "auto", folder, windows=True)
        wrote = coworker.write(folder, found)
        self.assertEqual(sorted(os.listdir(folder)),
                         ["coworker-settings.json"] + sorted(one["file"] for one in found))
        self.assertEqual(len(wrote), 3)
        with open(os.path.join(folder, "coworker-settings.json"), encoding="utf-8") as f:
            settings = json.load(f)
        self.assertEqual(list(settings), ["enabledPlugins"])
        self.assertEqual(sorted(settings["enabledPlugins"]),
                         ["p4-phi@p4-marketplace", "p4-temportal@p4-marketplace"])
        self.assertEqual(set(settings["enabledPlugins"].values()), {False})
        with open(os.path.join(folder, found[0]["file"]), encoding="utf-8") as f:
            self.assertEqual(f.read().rstrip("\n").split("\n"), found[0]["lines"])

    def land(self, path=None, folder="E:/notes/workers", mode="auto"):
        return coworker.land(path or self.path, "E:/repo", folder, WHO, mode, windows=True)

    def test_a_terminal_worker_starts_with_no_worktree_the_mode_it_was_given_and_a_goal_as_its_prompt(self):
        one, second = self.land()
        name = one["name"]
        self.assertRegex(name, r"^tw-the-exporter-s-m-1-[0-9a-f]{4}$")
        self.assertEqual(name, coworker.worker_name(self.path, ["1"]))
        self.assertEqual(second["name"], name.replace("-m-1-", "-m-2-"))
        self.assertEqual(one["file"], f"start-{name}.ps1")
        self.assertEqual(len(one["lines"]), 3, "no team variable")
        self.assertNotIn(coworker.TEAMS, "\n".join(one["lines"]))
        run = one["lines"][-1]
        self.assertNotIn("--worktree", run)
        self.assertIn("--permission-mode auto ", run)
        self.assertTrue(run.startswith(f"claude --name {name} --add-dir='E:\\notes\\workers' --model "), run)
        self.assertIn("--settings 'E:\\notes\\workers\\coworker-settings.json' '/goal ", run)
        prompt = run.rsplit(" '", 1)[1]
        self.assertTrue(run.endswith("'") and prompt.startswith("/goal "), "the goal is the last argument")
        self.assertEqual(prompt[:-1], one["goal"])
        for word in (f"section 1 of the plan {self.path.replace(chr(92), '/')}", f"the brief {one['brief_file']} says",
                     f"the report {one['report']} is written", "Stop after 60 turns"):
            self.assertIn(word, one["goal"], word)
        self.assertEqual(one["brief_file"], f"E:/notes/workers/brief-{name}.md")
        self.assertEqual(one["report"], f"E:/notes/workers/report-{name}.md")
        self.assertEqual(one["typed"], f"& 'E:\\notes\\workers\\start-{name}.ps1'")

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
        folder = os.path.join(self.base, "notes", "workers")
        found = coworker.land(self.path, self.base, folder, WHO, "auto", windows=True)
        wrote = coworker.write(folder, found)
        self.assertEqual(sorted(os.listdir(folder)),
                         sorted(["coworker-settings.json"] + [o["file"] for o in found]
                                + [os.path.basename(o["brief_file"]) for o in found]))
        self.assertEqual(len(wrote), 5)
        with open(found[0]["brief_file"], encoding="utf-8") as f:
            self.assertEqual(f.read().rstrip("\n"), found[0]["brief"])

    def test_a_reading_teams_start_lines_are_what_they_were(self):
        first = coworker.drafts(self.path, "E:/repo", WHO, "auto", "E:/notes", windows=True)[0]
        name = first["name"]
        task = coworker.task(self.path, [s for s in coworker.sections.parse(PLAN, "E:/repo")[1] if s["n"] == "1"], WHO)
        same = coworker.script(name, "E:/repo", "auto", task, "E:/notes", windows=True, worktree=True, team=True,
                               extra=())
        self.assertEqual((first["file"], first["lines"], first["typed"]), same)
        self.assertIn(f" --worktree {name} ", first["lines"][3])
        self.assertIn(coworker.TEAMS, first["lines"][1])

    def send(self, to, message, at="2026-11-23T10:00:00Z", name="SendMessage"):
        return {"type": "assistant", "timestamp": at,
                "message": {"content": [{"type": "text", "text": "ok"},
                                        {"type": "tool_use", "name": name, "input": {"to": to, "message": message}}]}}

    def lead(self, *rows):
        from unittest import mock
        config = os.path.join(self.base, "config")
        lead = os.path.join(config, "projects", "E--repo--claude-worktrees-cw-a", "cli-1.jsonl")
        os.makedirs(os.path.dirname(lead), exist_ok=True)
        with open(lead, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        return mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config})

    def test_last_list_gives_the_last_message_to_the_holders_title(self):
        title = "Plan: the move"
        with self.lead(self.send(title, "round 1", "2026-11-23T10:00:00Z"),
                       self.send(title, "round 2\nline two", "2026-11-23T11:00:00Z"),
                       self.send("fences", "to a teammate", "2026-11-23T12:00:00Z"),
                       self.send("main", "after", "2026-11-23T13:00:00Z")):
            self.assertEqual(coworker.last_list("cw-a", title),
                             "2026-11-23T11:00:00Z to Plan: the move\nround 2\nline two")

    def test_where_none_names_the_holder_the_last_one_sent_outside_the_team_is_given(self):
        with self.lead(self.send("main", "the list", "2026-11-23T10:00:00Z"),
                       self.send("sources", "to a teammate", "2026-11-23T11:00:00Z"),
                       self.send("checks", "again", "2026-11-23T11:30:00Z"),
                       self.send("a1b2c3d4e5f6a7b8-0001", "to an agent's id", "2026-11-23T12:00:00Z"),
                       self.send("main", "not a send", "2026-11-23T13:00:00Z", name="Read")):
            self.assertEqual(coworker.last_list("cw-a", "Plan: the move"), "2026-11-23T10:00:00Z to main\nthe list")

    def test_last_list_is_empty_where_there_is_none(self):
        with self.lead(self.send("fences", "x"), self.send("a1b2c3d4e5f6a7b8-0001", "y"), {"type": "user"}):
            self.assertEqual(coworker.last_list("cw-a", "Plan: the move"), "")
            self.assertEqual(coworker.last_list("cw-none", "Plan: the move"), "")
            self.assertEqual(coworker.last_list("../cw-a", "Plan: the move"), "")

    def test_the_watch_ends_once_no_coworker_wrote_a_line_and_an_api_error_is_a_stop(self):
        from unittest import mock
        config = os.path.join(self.base, "config")
        lead = os.path.join(config, "projects", "E--repo--claude-worktrees-cw-a", "cli-1.jsonl")
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
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config}):
            wrote(lead, began - 500)
            wrote(mate, began + 5)                 # a teammate's line, after the watch began
            self.assertEqual(coworker.watch(["cw-a"], quiet=60, clock=clock, sleep=sleep), ("quiet", 70))
            now[0] = began
            wrote(mate, began - 400)               # idle since before the round: no line of this round yet
            self.assertEqual(coworker.watch(["cw-a"], quiet=60, first=30, clock=clock, sleep=sleep), ("silent", 30))
            now[0] = began
            self.assertEqual(coworker.watch(["cw-none"], first=20, clock=clock, sleep=sleep), ("silent", 20))
            now[0] = began
            wrote(mate, began + 5)
            self.assertEqual(coworker.watch(["cw-a"], quiet=10 ** 9, longest=30, clock=clock, sleep=sleep),
                             ("long", 30))
            self.assertFalse(coworker.stopped("cw-a"))
            with open(lead, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "assistant", "isApiErrorMessage": True,
                                    "message": {"content": "API Error: 529 Overloaded"}}) + "\n")
                f.write(json.dumps({"type": "system"}) + "\n")
            self.assertTrue(coworker.stopped("cw-a"), "the last assistant row is the error")
            self.assertFalse(coworker.stopped("cw-none"))
            self.assertFalse(coworker.stopped("../cw-a"))

    def test_a_path_that_holds_a_quote_is_refused_and_no_start_file_is_drafted(self):
        with self.assertRaises(ValueError):
            coworker.drafts(self.path, "E:/it's/repo", WHO, "auto", "E:/notes", windows=True)
        with self.assertRaises(ValueError):
            coworker.drafts(self.path, "E:/repo", WHO, "auto", "E:/it's/notes", windows=True)

    def test_the_command_prints_the_groups_and_with_write_the_call_that_starts_each(self):
        home = os.path.join(self.base, "proj", ".claude", "p4")
        os.makedirs(home)
        folder = os.path.join(self.base, "notes")
        command = [sys.executable, "-I", "-X", "utf8", os.path.join(SRC, "phi.py"), "coworkers", self.path,
                   "--p4", home, "--session", "cli-0001", "--checkout", self.base]
        ran = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(len(ran.stdout.strip().split("\n")), 2, "one line a group")
        self.assertFalse(os.path.isdir(folder), "with no --write it only prints")
        ran = subprocess.run(command + ["--write", folder], capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(ran.stdout.count("`mcp__terminal__run_in_terminal` with "), 2)
        self.assertEqual(len(os.listdir(folder)), 3)
        # `--for` names the planner by its record's title, which the task then holds, and `--land` prints a message each
        record = os.path.join(home, "phi", "sessions", "cli-0002")
        os.makedirs(record)
        with open(os.path.join(record, "session.json"), "w", encoding="utf-8") as f:
            json.dump({"sessionId": "cli-0002", "title": "Plan: the move"}, f)
        ran = subprocess.run(command + ["--for", "cli-0002", "--write", folder], capture_output=True, text=True,
                             timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        start = sorted(n for n in os.listdir(folder) if n.startswith("start-"))[0]
        with open(os.path.join(folder, start), encoding="utf-8") as f:
            self.assertIn("the session named Plan: the move,", f.read())
        land = subprocess.run(command + ["--for", "cli-0002", "--land"], capture_output=True, text=True, timeout=60)
        self.assertEqual(land.returncode, 2, "no --write")
        self.assertIn("--write", land.stderr)
        # a name whose worktree is there is opened by Claude Code with what it holds, so nothing is written
        os.makedirs(os.path.join(self.base, ".claude", "worktrees", start[6:].rsplit(".", 1)[0]))
        again = subprocess.run(command + ["--write", folder], capture_output=True, text=True, timeout=60)
        self.assertEqual(again.returncode, 2)
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
