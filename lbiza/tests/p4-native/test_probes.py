"""Deciding tests for p4-native's watched conditions: that each fault of the host has a probe which names its
decision, that no probe runs at a session's start, that no probe changes a session, and that the README lists them."""
import json
import re
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
# the folder of the code these tests read
PLUGIN = LBIZA / "plugins" / "p4-native"
PROBES = (PLUGIN / "hooks" / "probes.ts").read_text(encoding="utf-8")
MODULE = (PLUGIN / "hooks" / "register.ts").read_text(encoding="utf-8")
README = (PLUGIN / "README.md").read_text(encoding="utf-8")
SKILL = (PLUGIN / "skills" / "host" / "SKILL.md").read_text(encoding="utf-8")
WEIGHED = json.loads((PLUGIN / "hooks" / "weighed.json").read_text(encoding="utf-8"))

# Each probe of probes.ts as its fields read: one `{ ... }` of the list PROBES.
LIST = PROBES.split("export const PROBES: readonly Probe[] = [", 1)[1].split("\n]\n", 1)[0]
ENTRIES = [e for e in re.split(r"(?m)^  \{$", LIST) if "id:" in e]


def field(entry, name):
    """One field of a probe: a quoted word, or the strings of a text joined."""
    found = re.search(rf"(?ms)^    {name}:\s*(.*?)(?=^    \w+:|^  \}})", entry)
    if not found:
        return ""
    return "".join(a or b or c for a, b, c in re.findall(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|`((?:[^`\\]|\\.)*)`",
                                                           found.group(1))).replace("\\'", "'").replace("\\`", "`")


BY_ID = {field(e, "id"): e for e in ENTRIES}

# The faults seen live that the plugin was begun with, each with the probe that watches it.
FAULTS = {
    "start_session is refused on a turn no person began": "start-on-an-unattended-turn",
    "list_events answers no messages for a session at work": "list-events-of-a-session-at-work",
    "a module's $.tool.call does not reach the app's tools in a scripted run": "app-tools-in-a-terminal-session",
    "a module's $.tool.call reached the app's tools in the desktop app": "module-call-of-an-app-tool",
    "$.session.compact is refused in a session a program started": "session-compact-from-a-module",
    "agent teams are not in the desktop app": "agent-teams-in-the-desktop-app",
    "a first prompt that begins with /goal runs no command": "goal-as-a-first-prompt",
    "a cross-session message is held when the permission modes differ": "message-held-across-permission-modes",
    "a .claude/skills/ copy named like an installed plugin does not load": "skills-copy-named-like-an-installed-plugin",
}


class ListTest(unittest.TestCase):
    def test_each_fault_has_one_probe_and_each_probe_names_its_decision(self):
        self.assertEqual(len(BY_ID), len(ENTRIES), "each id once")
        for fault, probe in FAULTS.items():
            self.assertIn(probe, BY_ID, fault)
        for name, entry in BY_ID.items():
            self.assertRegex(name, r"^[a-z]+(-[a-z]+)+$")
            self.assertRegex(field(entry, "decision"), r"p4-phi|p4-temportal|p4 plugin|p4 hooks module|settings keeper|terminal worker", name)
            self.assertTrue(field(entry, "fault"), name)
            self.assertIn(field(entry, "was"), ("blocked", "open"), name)
            self.assertIn(field(entry, "kind"), ("asked", "seen", "by hand"), name)
            self.assertIn("fits:", entry, name)

    def test_the_start_probe_reads_the_prompt_that_began_the_turn(self):
        """A prompt delivered into a running turn carries the turn's id and began no turn, as the API types say of
        `turnId`: "Absent for a prompt submitted while the session was idle". Seen in the desktop app on Claude Code
        2.1.326: a task's notice arrived in the middle of a turn ezexe's own message began, and a start later in
        that turn was told as one on an unattended turn. The turn after such a prompt has no origin told."""
        hook = MODULE.split("on('prompt.submit'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("if (e.turnId === undefined) origin = e.origin?.kind", hook)
        self.assertIn("else {\n      isJoined = true\n      if (!isUnattended(e.origin?.kind)) origin = undefined\n    }", hook)
        self.assertNotIn("\n    origin = e.origin?.kind", hook)
        end = MODULE.split("on('turn.complete'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("if (e.agentId === undefined && isJoined) {\n      isJoined = false\n      origin = undefined", end)
        test = (PLUGIN / "hooks" / "register.test.ts").read_text(encoding="utf-8")
        self.assertIn("a start after a task notice came into a turn a person began leaves the condition as it was", test)

    def test_a_turn_a_message_of_a_person_came_into_is_no_unattended_turn(self):
        """Seen in the desktop app on 2026-11-22: a task's notice began a turn, ezexe wrote into it twice, the app
        then started a session on it, and the probe told that as a start on a turn no person began. A prompt
        that came into a turn and is not known to be unattended leaves the turn with no origin, so a start on it
        says nothing, and a notice that came into a turn a notice began changes nothing."""
        probes = (PLUGIN / "hooks" / "probes.ts").read_text(encoding="utf-8")
        self.assertIn("export function isUnattended(kind: string | undefined): boolean {\n"
                      "  return kind !== undefined && UNATTENDED.has(kind)\n}", probes)
        self.assertIn("if (isStarted && isAsked && isUnattended(kind)) {", probes)
        test = (PLUGIN / "hooks" / "register.test.ts").read_text(encoding="utf-8")
        self.assertIn("a start on a turn a task notice began, after a message of a person came into it, leaves the "
                      "condition blocked", test)
        self.assertIn("A turn that a notice began and that a message of a person then came into is attended", README)

    def test_a_probe_the_module_does_not_ask_names_its_check(self):
        for name, entry in BY_ID.items():
            if field(entry, "kind") != "asked":
                self.assertTrue(field(entry, "check"), name)

    def test_the_module_reads_every_asked_probe(self):
        """An `asked` probe is read by `askOne` of register.ts or by `fromMap` of probes.ts, by its id."""
        for name, entry in BY_ID.items():
            if field(entry, "kind") == "asked":
                self.assertTrue(f"probe.id === '{name}'" in MODULE or f"id === '{name}'" in PROBES, name)

    def test_the_readme_lists_every_probe_with_its_kind(self):
        for name, entry in BY_ID.items():
            self.assertIn(f"- `{name}`, {field(entry, 'kind')}: ", README, name)
        listed = re.findall(r"(?m)^- `([a-z-]+)`, (?:asked|seen|by hand): ", README)
        self.assertEqual(sorted(listed), sorted(BY_ID))


class RunTest(unittest.TestCase):
    """The probes run when the Claude Code version changes and on request, never at every start."""

    def test_a_start_reads_the_probes_file_and_runs_no_probe(self):
        start = MODULE.split("on('session.start'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("starting = look($).then(() => check($))", start)
        for call in ("run($)", "ask($", "askOne($", "settle($", "pay($"):
            self.assertNotIn(call, start)
        check = MODULE.split("async function check(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("isDue = opened.book.hosts[kindOf(kept)]?.claude !== kept.claude", check)
        for call in ("run($)", "ask($", "askOne($", "$.tool.call", "$.session.compact"):
            self.assertNotIn(call, check)

    def test_the_first_turn_runs_them_only_where_they_are_due(self):
        turn = MODULE.split("on('turn.start'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("if (isDue) await look($).then(() => run($))", turn)
        self.assertEqual(turn.count("run($)"), 1)
        self.assertEqual(MODULE.count("await run($)"), 1, "and once more on request, in `probed`")

    def test_the_answers_are_kept_by_the_kind_of_host(self):
        """The desktop app runs a Claude Code of its own beside the one on the PATH, so one version for the machine
        would run the probes at every switch between the two."""
        self.assertIn("return `${host.host}/${host.run}`", MODULE)
        self.assertIn("const BOOK = 'native/probes.json'", MODULE)
        self.assertIn(".claude/p4/native/probes.json", README)


class HarmlessTest(unittest.TestCase):
    """A probe changes nothing in the session it reads."""

    def test_each_tool_the_module_calls_only_reads(self):
        tools = dict(re.findall(r"(?m)^export const ([A-Z]+) = '(mcp__ccd_\w+)'$", PROBES))
        self.assertEqual(tools, {"START": "mcp__ccd_session__start_session",
                                 "SELF": "mcp__ccd_session_mgmt__get_session",
                                 "SESSIONS": "mcp__ccd_session_mgmt__list_sessions",
                                 "EVENTS": "mcp__ccd_session_mgmt__list_events"})
        asked = MODULE.split("async function askOne(", 1)[1].split("\n}\n", 1)[0]
        self.assertEqual(sorted(re.findall(r"\bcall\(\$, ([A-Z]+),", asked)), ["EVENTS", "SELF", "SESSIONS"])
        self.assertEqual(sorted(set(re.findall(r"\bcall\(\$, ([A-Z]+),", MODULE))), ["EVENTS", "PUSH", "SELF", "SESSIONS"],
                         "beside the probes, the option `push` calls Claude Code's own tool that notifies")
        self.assertEqual(MODULE.count("$.tool.call("), 1, "the one call site, in `call`")

    def test_the_start_tool_is_watched_and_never_called(self):
        """Asking would start a session, so the probe is read off a start the session makes itself, which the hook
        passes on untouched and hands back as the app answered it."""
        self.assertIn("const START_ID = 'mcp__ccd_session__start_session'", MODULE)
        hook = MODULE.split("on('tool.call', { tool: START_ID }", 1)[1].split("\n\n  on(", 1)[0]
        self.assertIn("const out = await next(e)", hook)
        self.assertIn("return out", hook)
        self.assertIn(".catch(($, e, next) => next(e))", hook)
        self.assertEqual(field(BY_ID["start-on-an-unattended-turn"], "kind"), "seen")

    def test_the_compaction_a_probe_asks_for_is_vetoed_and_asked_at_a_turns_end(self):
        """Seen in the desktop app on Claude Code 2.1.326, `$.session.compact` called while a `tool.call` hook is
        held is rejected with "called from a tool.call hook", and in a scripted run on 2.1.328 the call at
        `turn.complete` was rejected with the headless refusal before any hook heard it. Where the platform lets
        the call through, the module's own hook vetoes the compaction, by the instruction the probe gave it."""
        self.assertIn("on('session.compact', ($, e, next) => (e.instructions === NO_COMPACTION ? { skip: VETO } : next(e)))",
                      MODULE)
        self.assertEqual(MODULE.count("$.session.compact("), 1)
        self.assertIn("$.session.compact({ instructions: NO_COMPACTION })", MODULE)
        self.assertIn("atTurnEnd: true", BY_ID["session-compact-from-a-module"])
        end = MODULE.split("on('turn.complete'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("await pay($)", end)


class EvidenceTest(unittest.TestCase):
    """A verdict is taken from what differs between the two states, never from a line both states print."""

    def test_list_events_is_judged_by_the_rows_under_its_header_at_three_calls(self):
        """The tool's header reads "showing n of m messages" whether or not anything is under it, and the fault
        comes and goes: a session at work was answered "(no messages)", a lone stub of a tool call, and rows with
        the assistant's words, at different calls. So the probe is open only where every call holds assistant
        text."""
        self.assertIn("answer: spoken.length > 0 ? 'open' : 'blocked'", PROBES)
        self.assertIn("const STUB = /^\\[assistant\\] \\(called [^)]*\\)$/", PROBES)
        self.assertIn("export const EVENTS_LIMITS = [3, 14, 30] as const", PROBES)
        self.assertIn("for (const limit of EVENTS_LIMITS) readings.push(await call($, EVENTS, { session_id: busy, limit }))",
                      MODULE)
        self.assertIn("return ofAllEvents(readings)", MODULE)

    def test_an_answer_kept_under_an_older_rule_is_compared_with_nothing(self):
        """The probe's first rule read the header and kept `open`. With `reads` raised, the kept answer counts as
        none, so the corrected verdict starts no notice that a decision's ground was lost."""
        self.assertIn("reads: 2,", BY_ID["list-events-of-a-session-at-work"])
        self.assertIn("(last.reads ?? 1) === (probe.reads ?? 1) ? last : undefined", MODULE)
        self.assertEqual(MODULE.count("keptOf(ran, probe)"), 2, "where a change is judged and where the list is printed")

    def test_a_start_went_through_only_where_the_answer_holds_the_new_sessions_id(self):
        self.assertIn("out.deny === undefined && SESSION.test(text)", PROBES)


class ToldOnceTest(unittest.TestCase):
    def test_a_notice_is_taken_out_of_the_file_by_the_prompt_that_carries_it(self):
        take = MODULE.split("async function take(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("notices: []", take)
        prompt = MODULE.split("on('prompt.submit'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("const notices = hasNotices ? await take($).catch(() => []) : []", prompt,
                      "a prompt reads no file where no notice waits")
        self.assertIn("if (lines.length === 0) return next(e)", prompt)
        self.assertIn("context: [...(e.context ?? []), lines.join('\\n')]", prompt)

    def test_the_skill_says_what_a_session_does_with_a_notice(self):
        self.assertIn("p4-native: the watched condition ${probe.id} changed on", MODULE)
        self.assertIn("p4-native: Claude Code changed from ${ran.claude} to ${host.claude} on", MODULE)
        self.assertIn("`p4-native: the watched condition`", SKILL)
        self.assertIn("`p4-native: Claude Code changed from`", SKILL)


class ChoicesTest(unittest.TestCase):
    def test_only_what_ezexe_said_is_called_ezexes_choice_and_the_rest_a_sessions_verdict(self):
        """ezexe chose two things, no pull requests and the two skills that shape a plan and set an agent's model and
        effort by its role. The section called a session's verdicts ezexe's own until 2026-11-22, when ezexe said
        which were which and reopened three of them, plan mode, the prompts on a schedule and `/schedule`."""
        section = README.split("## What ezexe chose, and what sessions decided\n", 1)[1].split("\n## ", 1)[0]
        for name in BY_ID:
            self.assertNotIn(name, section)
        for word in ("autofix", "/model", "/fast", "/permissions", "/sandbox"):
            self.assertFalse(word in LIST, f"no probe watches a choice of ezexe's or a verdict that stands: {word}")
        for row in ("/plan", "EnterPlanMode", "ExitPlanMode", "CronCreate", "CronDelete", "CronList", "/schedule"):
            held = WEIGHED["rows"][row]
            self.assertIn("p4-phi", held.get("open") or held.get("used") or [], row)
            self.assertNotIn("p4-phi", held.get("declined") or {}, f"{row} is open or used, and no longer declined")


if __name__ == "__main__":
    unittest.main()
