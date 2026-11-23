#!/usr/bin/env python3
"""cards.py and the set of p4conf.CARD_SET: what p4-phi settles before a session's start with no approval card, in
force only by the store's own file, and the guards of phi.py that read it.

    python -m pytest tests/p4-phi/test_cards.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import cards  # noqa: E402
import issues  # noqa: E402
import p4conf  # noqa: E402
from test_phi import CLI, GRAND, TOP, jload, write  # noqa: E402
import test_relay  # noqa: E402  its tree of three sessions, taken by its setUp and never as a class of this module

A, B = test_relay.A, test_relay.B

ARCHIVE = "mcp__ccd_session_mgmt__archive_session"


def say_yes(p4):
    """Puts the set in force for a store as ezexe's press does: the key, which the command writes, and the yes,
    which phi.py's hook keeps at the end of the call whose approval card ezexe pressed."""
    p4conf.set_key(p4, p4conf.CARDS_KEY, p4conf.card_set_id())
    assert p4conf.cards_yes(p4, session="local_top00001", call="toolu_yes")


def yes_of(p4):
    """The yes kept in the store's phi/cards.json, or None."""
    return (jload(p4conf.cards_file(p4)) if os.path.exists(p4conf.cards_file(p4)) else {}).get("yes")


class TheSet(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = os.path.join(self._tmp.name, "proj")
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        os.makedirs(self.p4)
        self.local = os.path.join(self.proj, ".claude", "settings.local.json")
        config = os.path.join(self._tmp.name, "claude-config")
        os.makedirs(config)
        self._env = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": config})
        self._env.start()
        for k in [k for k in os.environ if k.startswith("P4_")]:
            os.environ.pop(k)
        keep = p4conf.keep_settings

        def kept(project, *args, p4=None, **kw):       # p4-phi's `layout` entry writes what it asks for first
            p4conf.want_settings(p4 or os.path.join(p4conf.main_root(project)[0], ".claude", "p4"))
            return keep(project, *args, p4=p4, **kw)
        self._asking = mock.patch.object(p4conf, "keep_settings", kept)
        self._asking.start()

    def tearDown(self):
        self._asking.stop()
        self._env.stop()
        self._tmp.cleanup()

    def rules(self, key):
        got = p4conf._get(jload(self.local) if os.path.exists(self.local) else {}, key)
        return got if isinstance(got, list) else []

    def test_the_set_is_in_force_only_by_the_stores_own_file_and_only_as_this_copy_has_it(self):
        """What is settled with no approval card is a permission, so nothing puts the set in force but ezexe's yes:
        `phi.cards` in the store's p4.json names the set as this copy has it, and the store's record holds the yes
        to that set, in its phi/cards.json. No variable stands in for the key, an id of another set is no yes to this one, and a set that
        changed has another id."""
        self.assertFalse(p4conf.cards_on(self.p4), "off in a store that says nothing")
        self.assertFalse(p4conf.cards_on(""))
        sid = p4conf.card_set_id()
        self.assertRegex(sid, r"^[0-9a-f]{10}$")
        with mock.patch.dict(os.environ, {"P4_PHI_CARDS": sid}):
            self.assertFalse(p4conf.cards_on(self.p4), "no variable puts it in force")
        self.assertNotIn(p4conf.CARDS_KEY, p4conf.env_keys(), "the key has no variable")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, "0123456789")
        self.assertFalse(p4conf.cards_on(self.p4), "the yes to another set")
        self.assertFalse(p4conf.cards_yes(self.p4, session="s", call="c"), "and no yes is kept for a key that is not it")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, True)
        self.assertFalse(p4conf.cards_on(self.p4), "a plain true names no set")
        say_yes(self.p4)
        self.assertTrue(p4conf.cards_on(self.p4))
        self.assertNotIn(p4conf.CARDS_KEY, p4conf.env_keys(), "and none is written for it")
        changed = p4conf.CARD_SET + (("more", "One more thing settled with no card."),)
        with mock.patch.object(p4conf, "CARD_SET", changed):
            self.assertNotEqual(p4conf.card_set_id(), sid)
            self.assertFalse(p4conf.cards_on(self.p4), "a set that changed is in force nowhere until a new yes")
        names = [name for name, _ in p4conf.CARD_SET]
        self.assertEqual(names, ["tools", "archive", "own-branch", "push", "refusal", "start", "general"], "the whole set")
        for word in ("deny", "credential", "password", "token"):
            self.assertNotIn(word, json.dumps(p4conf.CARD_SET).lower(), "it lifts no deny rule, touches no credential")

    def test_a_write_of_the_key_by_any_way_but_the_approved_command_leaves_the_set_off(self):
        """The guard asked ezexe for the command and not for the key, so a session could write `phi.cards` into
        p4.json another way and have the set in force with no yes. The set is now in force only with the yes that
        phi.py's hook keeps in the store's record at the end of the call whose approval card ezexe pressed. The key
        written by set_key, by an edit of the file, or by the command itself where no hook of p4-phi runs, as in
        the app's Terminal panel, leaves the set off, and the keeper writes none of the set's rules."""
        sid = p4conf.card_set_id()
        p4conf.keep_settings(self.proj)
        tools = lambda: [r for r in self.rules(p4conf.ALLOW_KEY) if r.startswith("mcp__")]   # noqa: E731
        asked_tools = lambda: [r for r in jload(p4conf.asks_file(self.p4))["permissions"]["allow"]   # noqa: E731
                               if r.startswith("mcp__")]
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertFalse(p4conf.cards_on(self.p4), "set_key")
        data = jload(p4conf.path(self.p4))
        data["phi"]["cards"] = sid
        write(p4conf.path(self.p4), json.dumps(data))
        self.assertFalse(p4conf.cards_on(self.p4), "an edit of p4.json")
        status, lines = cards.switch(self.p4, True, sid)
        self.assertEqual(status, 0)
        self.assertIn("The set is not in force yet", lines[0])
        self.assertEqual(len(lines), 1, "the keeper runs once for the command, when the yes is kept")
        self.assertFalse(p4conf.cards_on(self.p4), "the command where no card was raised for it")
        self.assertEqual(tools(), [], "the keeper writes no rule of a set that is not in force")
        self.assertIn("no yes of ezexe's is kept for it", cards.text(self.p4)[0])
        # a record that is not this store's, and a yes to another set
        yes = {"set": sid, "store": p4conf.fwd(os.path.join(self._tmp.name, "other", ".claude", "p4")), "at": "x"}
        write(p4conf.cards_file(self.p4), json.dumps({**jload(p4conf.cards_file(self.p4)), "yes": yes}))
        self.assertFalse(p4conf.cards_on(self.p4), "a yes given for another store")
        write(p4conf.cards_file(self.p4), json.dumps({**jload(p4conf.cards_file(self.p4)),
                                                      "yes": {**yes, "store": p4conf.fwd(self.p4), "set": "0" * 10}}))
        self.assertFalse(p4conf.cards_on(self.p4), "a yes to another set")
        # the yes, as the hook keeps it
        said = cards.kept(self.p4, "local_top00001", "toolu_1")
        self.assertIn(f"ezexe's yes to the set {sid} is kept", said[0])
        self.assertIn("the set is in force", said[0])
        self.assertTrue(p4conf.cards_on(self.p4))
        self.assertEqual(sorted(asked_tools()), sorted(p4conf.CARD_TOOLS), "and the file p4-phi writes asks for the set")
        self.assertEqual(tools(), [], "the local file follows when the keeper next runs")
        p4conf.keep_settings(self.proj)
        self.assertEqual(sorted(tools()), sorted(p4conf.CARD_TOOLS), "and the keeper copied it")
        kept = yes_of(self.p4)
        self.assertEqual((kept["set"], kept["session"], kept["call"]), (sid, "local_top00001", "toolu_1"))
        # each yes is one press for one writing of the key
        self.assertEqual(cards.switch(self.p4, False)[0], 0)
        self.assertIsNone(yes_of(self.p4), "`off` takes the yes out with the key")
        self.assertEqual(asked_tools(), [], "`off` changes what the file asks for")
        p4conf.keep_settings(self.proj)
        self.assertEqual(tools(), [], "and the local file follows after the keeper")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertFalse(p4conf.cards_on(self.p4), "the key written again after an `off`")
        say_yes(self.p4)
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, None)
        p4conf.keep_settings(self.proj)
        self.assertIsNone(yes_of(self.p4), "the key taken out by hand: the keeper drops the yes")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertFalse(p4conf.cards_on(self.p4))
        say_yes(self.p4)
        cards.switch(self.p4, True, sid)
        self.assertTrue(p4conf.cards_on(self.p4), "the command run again where the set is in force writes nothing")

    def tools(self):
        return sorted(r for r in self.rules(p4conf.ALLOW_KEY) if r.startswith("mcp__"))

    def test_a_script_told_the_main_checkout_reads_its_settings_from_a_worktree(self):
        """A session in a git worktree: its command hooks run with `CLAUDE_PROJECT_DIR` at the main checkout's root,
        and p4-phi's hooks module now hands its scripts that same folder, by `$.process.hookEnv`, where it handed
        the session's own. So a script the module runs reads `phi.upkeep` and `phi.cards` from the main checkout's
        p4.json, as a command hook does, and not from a store the worktree holds."""
        import phi
        say_yes(self.p4)
        p4conf.set_key(self.p4, "phi.upkeep", True)
        worktree = os.path.join(self.proj, ".claude", "worktrees", "w1")
        os.makedirs(os.path.join(worktree, ".claude", "p4"))           # a store of its own, which says neither
        apps = os.path.join(self._tmp.name, "app")
        os.makedirs(apps)
        payload = {"session_id": "cli-w1", "cwd": worktree}
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj, "P4_PHI_APP_SESSIONS": apps}):
            me = phi.Me(payload)
            self.assertEqual(os.path.normcase(me.store), os.path.normcase(self.p4), "the main checkout's store")
            self.assertTrue(phi.cards_on(me))
            self.assertTrue(p4conf.upkeep_on(me.store))
        # as the module told it before: the session's own folder, whose store holds neither setting
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": worktree, "P4_PHI_APP_SESSIONS": apps}):
            me = phi.Me(payload)
            self.assertEqual(os.path.normcase(me.store), os.path.normcase(os.path.join(worktree, ".claude", "p4")))
            self.assertFalse(phi.cards_on(me))
            self.assertFalse(p4conf.upkeep_on(me.store))

    def test_the_first_read_carries_the_yes_of_the_record_over_once(self):
        """A store whose keeper's record holds a yes for this store and set, as one kept before cards.json stood: the
        first cards_on answers true, cards.json then holds the yes and "carried", and a cardsYes written into the
        record after that is not read."""
        sid = p4conf.card_set_id()
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        yes = {"set": sid, "store": p4conf.fwd(self.p4), "at": "2026-11-19 10:00:00"}
        write(p4conf.record_path(self.p4), json.dumps({"cardsYes": yes}))
        self.assertFalse(os.path.exists(p4conf.cards_file(self.p4)))
        self.assertTrue(p4conf.cards_on(self.p4), "the yes of the record, carried at the first read")
        got = jload(p4conf.cards_file(self.p4))
        self.assertEqual(got["yes"], yes)
        self.assertRegex(got["carried"], r"^\d{4}-\d\d-\d\d$")
        self.assertEqual(cards.switch(self.p4, False)[0], 0)
        write(p4conf.record_path(self.p4), json.dumps({"cardsYes": yes}))
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertFalse(p4conf.cards_on(self.p4), "a cardsYes written into the record after the carry is not read")

    def test_a_record_without_a_yes_carries_nothing_and_off_then_a_key_by_hand_leaves_the_set_off(self):
        sid = p4conf.card_set_id()
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertFalse(p4conf.cards_on(self.p4))
        self.assertIn("carried", jload(p4conf.cards_file(self.p4)), "looked at once")
        say_yes(self.p4)
        self.assertTrue(p4conf.cards_on(self.p4))
        self.assertEqual(cards.switch(self.p4, False)[0], 0)
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertFalse(p4conf.cards_on(self.p4), "cards off, then the key by hand")
    def test_cards_on_where_the_set_is_in_force_writes_nothing(self):
        """`phi.py cards on` took a standing yes out before it wrote the key, so a second run of it, or one in the
        app's Terminal panel where no hook of p4-phi keeps a yes, left a set that was in force off. Where the set
        is in force the command writes nothing and says so."""
        sid = p4conf.card_set_id()
        say_yes(self.p4)
        yes = yes_of(self.p4)
        status, lines = cards.switch(self.p4, True, sid)
        self.assertEqual(status, 0)
        self.assertIn("in force already", lines[0])
        self.assertEqual(len(lines), 1)
        self.assertEqual(yes_of(self.p4), yes, "the standing yes is not taken out")
        self.assertTrue(p4conf.cards_on(self.p4))
        # where the set is off the command asks as before, and runs no keeper of its own: `kept` runs the one
        self.assertEqual(cards.switch(self.p4, False)[0], 0)
        status, lines = cards.switch(self.p4, True, sid)
        self.assertEqual((status, len(lines)), (0, 1))
        self.assertIn(cards.ASKED, lines[0])
        self.assertFalse(p4conf.cards_on(self.p4))

    def test_the_keeper_writes_the_tool_rules_only_while_the_set_is_in_force(self):
        """The `tools` part of the set: an allow rule for each tool a p4 hooks module declares, as entries of
        `permissions.allow` p4 owns under the record's `toolRules`. They come with the yes and go with it, a rule a
        person already wrote stays theirs, p4's rules for phi.py are as before, and no ask or deny rule is written."""
        mine = "mcp__p4-phi__done"
        write(self.local, json.dumps({"permissions": {"allow": [mine, "Bash(ls *)"]}}))
        p4conf.keep_settings(self.proj)
        before = self.rules(p4conf.ALLOW_KEY)
        self.assertEqual([r for r in before if r.startswith("mcp__")], [mine], "set off: no rule of the set")
        self.assertEqual(self.rules(p4conf.ASK_KEY), [], "no ask rule, with phi.upkeep off")
        say_yes(self.p4)
        p4conf.keep_settings(self.proj)
        allow = self.rules(p4conf.ALLOW_KEY)
        self.assertEqual(sorted(r for r in allow if r.startswith("mcp__")), sorted(p4conf.CARD_TOOLS))
        self.assertEqual(allow[:len(before)], before, "nothing of the list before is moved or dropped")
        rec = p4conf.read_record(self.p4)
        owned = rec["toolRules"][p4conf.fwd(self.local)]["entries"]
        self.assertEqual(sorted(owned), sorted(t for t in p4conf.CARD_TOOLS if t != mine), "the person's own stays theirs")
        self.assertEqual(self.rules(p4conf.ASK_KEY), [], "nor with the set in force")
        self.assertEqual(self.rules(p4conf.DENY_KEY), list(p4conf.DENY_RULES), "and no deny rule")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, None)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ALLOW_KEY), before, "the yes withdrawn: p4's rules go, the person's stays")
        self.assertNotIn("toolRules", p4conf.read_record(self.p4))

    def test_the_general_part_is_written_only_while_the_set_is_in_force(self):
        """CARD_SET's `general`: the keeper writes its allow rules into the local file where ezexe's yes to the set
        stands, and takes its own entries out again with the set. KEEPER 14 came with the part, so a store's
        next start runs the whole check."""
        self.assertGreaterEqual(p4conf.KEEPER, 14)
        p4conf.keep_settings(self.proj, p4=self.p4)
        self.assertNotIn("Bash(git *)", self.rules(p4conf.ALLOW_KEY), "set off")
        say_yes(self.p4)
        p4conf.keep_settings(self.proj, p4=self.p4)
        general = list(p4conf.GENERAL_RULES) + (list(p4conf.GENERAL_WIN) if sys.platform.startswith("win") else [])
        for rule in general:
            self.assertIn(rule, p4conf.want_settings(self.p4)["permissions"]["allow"], "p4-phi asks for it")
            self.assertIn(rule, self.rules(p4conf.ALLOW_KEY))
        p4conf.cards_no(self.p4)
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, None)
        p4conf.keep_settings(self.proj, p4=self.p4)
        self.assertNotIn("Bash(git *)", self.rules(p4conf.ALLOW_KEY), "taken out with the set")

    def test_a_leftover_ask_rule_goes_only_with_upkeep_on_and_the_set_in_force(self):
        """The `archive` part: a store started anew lost the record of the ask rule p4 wrote, so with `phi.upkeep`
        on the keeper left the entry as a person's and the card came before every archive, 32 times on 2026-11-19.
        With the set in force the entry of p4's exact text is taken out. Another ask rule is never touched, and
        with `phi.upkeep` off the keeper writes none back."""
        other = "Bash(git push --force *)"
        write(self.local, json.dumps({"permissions": {"ask": [ARCHIVE, other]}}))
        p4conf.set_key(self.p4, "phi.upkeep", True)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ASK_KEY), [ARCHIVE, other], "set off: not p4's own by the record, so left")
        say_yes(self.p4)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ASK_KEY), [other], "the leftover is taken out, and no other ask rule")
        self.assertNotIn("askRules", p4conf.read_record(self.p4))
        p4conf.set_key(self.p4, "phi.upkeep", False)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ASK_KEY), [other], "upkeep off: p4 writes no ask rule back")

    def test_a_brief_tells_its_session_to_push_by_a_clause_that_says_so(self):
        """The `push` part reads the brief: a clause with the word, no refusal beside it and no other session named
        as the one that pushes."""
        for text in ("Work lands as commits pushed fast-forward to `main`, with no pull request and no GitHub issue.",
                     "Another session writes there too, so rebase on `origin/main` before each push.",
                     "Commit the file.\nThen push it to origin.", "Done looks like: three commits pushed to main."):
            self.assertTrue(cards.brief_pushes(text), text)
        for text in ("Commit on your branch and do not push; the orchestrator pushes.", "Push nothing.",
                     "It never pushes to main.", "Write the file and commit it.", "Commit, and don't push it.",
                     "Your parent pushes the branch once you report.", "", None,
                     "Commit without pushing, and report the hash."):
            self.assertFalse(cards.brief_pushes(text), text)

    def test_every_kind_of_card_is_listed_with_how_it_is_settled_or_why_it_stays(self):
        """`phi.py cards` and the page docs/claude-settings.html carry one list: each kind of approval card, what
        raises it, and how it is settled before a start or why it stays."""
        names = [name for name, _, _ in cards.KINDS]
        self.assertEqual(len(names), len(set(names)))
        for name, why, how in cards.KINDS:
            self.assertRegex(how, r"^(Settled by|It stays|A start in the project never raises it)", name)
            self.assertTrue(why.endswith(".") and how.endswith("."), name)
        text = "\n".join(cards.text(self.p4))
        self.assertIn(f"The set {p4conf.card_set_id()} of what p4-phi settles with no approval card is not in force",
                      text)
        for name in names:
            self.assertIn(f"- {name}. ", text)
        self.assertIn(p4conf.card_set_id(), cards.approval(self.p4))
        for _, words in p4conf.CARD_SET:
            self.assertIn(words, cards.approval(self.p4), "the card's text is the set whole")

    def test_the_page_lists_every_kind_and_the_set_as_the_code_has_them(self):
        """docs/claude-settings.html, "Approval cards and a session's start", holds a row for each kind of card, each
        part of the set, and the set's name as this copy has it."""
        import html
        import re
        root = os.path.normpath(os.path.join(SRC, "..", "..", "..", ".."))
        with open(os.path.join(root, "docs", "claude-settings.html"), encoding="utf-8") as f:
            page = f.read()
        start = page.index('<section id="approval-cards-and-a-sessions-start"')
        part = html.unescape(re.sub(r"<[^>]+>", "", page[start:page.index("</section>", start)]))
        self.assertIn('<a href="#approval-cards-and-a-sessions-start">', page, "the section is in the page's contents")
        for name, why, how in cards.KINDS:
            self.assertIn(name[:1].upper() + name[1:], part, name)
            for words in (why, how):
                self.assertIn(words.replace("`", ""), part, name)
        for name, words in p4conf.CARD_SET:
            self.assertIn(f"{name}: {words.replace('`', '')}", part, name)
        self.assertIn(p4conf.card_set_id(), part, "the page was written from this set")

    def test_every_landing_command_of_a_line_is_read(self):
        """A line that rebases and then pushes holds both, and issues.landing names the first alone, so a push
        behind a rebase would pass as the rebase."""
        self.assertEqual(issues.landings("cd x && git fetch -q origin && git rebase origin/main && "
                                         "git -C y push origin HEAD:main"), ["git rebase", "git push"])
        self.assertEqual(issues.landings('git commit -m "push it" && bash -c "git pull --rebase"'), ["git pull"])
        self.assertEqual(issues.landings("git status && git log --grep 'push'"), [])
        self.assertEqual(issues.landings("git push && git push origin x && gh pr merge 3"), ["git push", "gh pr merge"])
        for cmd in ("git push origin main", 'pwsh -Command "git push"', "gh pr merge 12 --squash", "git status"):
            self.assertEqual(issues.landings(cmd)[:1], [issues.landing(cmd)] if issues.landing(cmd) else [])


class Guards(unittest.TestCase):
    """The guards of phi.py with the set off, where each raises Claude Code's approval card as before, and with the
    set in force, where a session another session started is asked nothing and refused what its brief does not
    cover."""

    def setUp(self):
        test_relay.ThreeSessions.setUp(self)
        self.own = os.path.join(self.work, ".claude", "worktrees", "the-flush")
        subprocess.run(["git", "-C", self.work, "worktree", "add", "-q", "-b", "claude/the-flush", self.own],
                       check=True, capture_output=True)
        self.pusher, self.keeper = GRAND, "local_keeper01"
        CLI.setdefault(self.keeper, "ffff6666-0000-4000-8000-000000000000")
        self.t.record(self.pusher, TOP, title="the flush worker", cwd=self.own)
        self.t.record(self.keeper, TOP, title="the keep worker", cwd=self.own)
        said = "Task:\nRework the flush.\n\nWork lands as commits pushed fast-forward to `main`."
        self.assertEqual(self.t.say(self.pusher, said).returncode, 0)
        self.assertEqual(self.t.say(self.keeper, "Task:\nRework the flush and commit it. Do not push.").returncode, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def on(self):
        say_yes(self.t.p4)

    def guard(self, name, host, cmd, cwd=None, tool="Bash", call=None):
        r = self.t.hook(name, host, {"hook_event_name": "PreToolUse", "tool_name": tool,
                                     "tool_input": {"command": cmd}, **({"cwd": cwd} if cwd else {}),
                                     **({"tool_use_id": call} if call else {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def test_the_force_guard_asks_at_the_top_and_refuses_in_a_started_session(self):
        """With the set in force a git command that forces is ezexe's: asked in the top session, refused in a
        session another session started. With the set off, and for a plain push, the guard says nothing."""
        cmd = "git push --force origin main"
        self.assertIsNone(self.guard("force-guard", TOP, cmd), "set off: as before")
        self.on()
        self.assertEqual(self.guard("force-guard", TOP, cmd)["permissionDecision"], "ask")
        self.assertEqual(self.guard("force-guard", self.pusher, cmd)["permissionDecision"], "deny")
        self.assertIsNone(self.guard("force-guard", TOP, "git push origin main"))
        self.assertIsNone(self.guard("force-guard", TOP, "git commit -m 'git push --force'"), "a quoted word is data")
        both = "git status && git push --force origin main"
        self.assertEqual(self.guard("force-guard", TOP, both)["permissionDecision"], "ask", "the line is read whole")
        chained = "git commit -am x && git reset --hard HEAD~1"
        self.assertEqual(self.guard("force-guard", TOP, chained, cwd=self.work)["permissionDecision"], "ask",
                         "a reset behind another command is never judged by the tree as it stands")
        import hook
        for tool in ("Bash", "PowerShell"):
            names = hook.PHI_CHECK[tool]
            self.assertLess(names.index("store-guard"), names.index("force-guard"), tool)
            self.assertLess(names.index("force-guard"), names.index("branch-guard"), tool)

    def test_what_a_line_runs_that_the_general_part_never_covers(self):
        for cmd, kind in (("git push -f", "push"), ("git push origin +main", "push"),
                          ("git push origin :old", "push"), ("git -C x push --force-with-lease", "push"),
                          ("git branch -D old", "branch"), ("git branch -f main HEAD~3", "move"),
                          ("git worktree remove --force w", "worktree"), ("git reset --hard HEAD~1", "reset"),
                          ("git checkout -f main", "reset"), ("git clean -fd", "clean"),
                          ("git stash drop", "stash"), ("git update-ref -d refs/heads/x", "ref"),
                          ("git reflog expire --all", "ref"), ("git credential fill", "login"),
                          ("git config credential.helper store", "login")):
            self.assertEqual([k for _, k, _ in issues.risks(cmd)], [kind], cmd)
        for cmd in ("git push origin main", "git branch -d old", "git worktree remove w", "git reset --soft HEAD~1",
                    "git clean -n", "git commit -m 'reset --hard'", "git restore a.txt", "git stash", "ls"):
            self.assertEqual(issues.risks(cmd), [], cmd)
        self.assertEqual([k for _, k, _ in issues.risks("git reset --hard && git push -f")], ["reset", "push"])

    def test_a_project_that_files_no_new_issue_has_the_call_asked_at_the_top_and_refused_below(self):
        """`phi.new_issues` false: `gh issue create` is ezexe's to allow, so the top session gets the card and,
        with the set in force, a session another session started is refused."""
        cmd = "gh issue create --title x --body y"
        p4conf.set_key(self.t.p4, "phi.new_issues", False)
        self.assertEqual(self.guard("issue-guard", TOP, cmd)["permissionDecision"], "ask")
        self.on()
        self.assertEqual(self.guard("issue-guard", self.pusher, cmd)["permissionDecision"], "deny")
        self.assertEqual(self.guard("issue-guard", TOP, cmd)["permissionDecision"], "ask", "ezexe's own session")

    def test_the_brief_is_read_at_the_first_message(self):
        self.assertIs(self.t.session(self.pusher).get("pushes"), True)
        self.assertIs(self.t.session(self.keeper).get("pushes"), False)
        self.assertNotIn("pushes", self.t.session(TOP), "a session no session started keeps none")

    def test_with_the_set_off_every_guard_raises_its_card_as_before(self):
        """Nothing changes until ezexe has said yes: a started session's rebase and push are asked about, in its
        own worktree too and whatever its brief says, ezexe/p4#232."""
        for cmd in ("git rebase origin/main", "git push origin HEAD:main", "git pull", "git merge main"):
            out = self.guard("branch-guard", self.pusher, cmd, cwd=self.own)
            self.assertEqual(out["permissionDecision"], "ask", cmd)
            self.assertIn("merges and pushes", out["permissionDecisionReason"])
            self.assertNotIn("raises no approval card", out["permissionDecisionReason"])
        self.assertEqual(self.guard("branch-guard", B, "git switch main")["permissionDecision"], "ask")

    def test_with_the_set_in_force_a_worktrees_own_branch_and_a_push_its_brief_names_run_unasked(self):
        """The `own-branch` and `push` parts: in a worktree of its own a started session rebases, merges and pulls
        unasked, since those move its own branch alone, and pushes unasked where its brief tells it to. The 39
        cards of 2026-11-19 were all of these, in sessions whose briefs said to push to `main`."""
        self.on()
        for cmd in ("git rebase origin/main", "git pull --rebase", "git merge origin/main", "git push origin HEAD:main",
                    "git fetch -q origin && git rebase origin/main && git push origin HEAD:main",
                    'bash -c "git push origin HEAD:main"'):
            self.assertIsNone(self.guard("branch-guard", self.pusher, cmd, cwd=self.own), cmd)
        for cmd in ("git rebase origin/main", "git pull", "git merge origin/main"):
            self.assertIsNone(self.guard("branch-guard", self.keeper, cmd, cwd=self.own), f"its own branch: {cmd}")
        # a line aimed at a checkout the session shares is judged there, whatever folder the hook runs in
        main = self.work.replace(chr(92), "/")
        for cmd in (f"git -C {main} pull", f"cd {main} && git push origin HEAD:main", f'git -C "{main}" rebase main'):
            out = self.guard("branch-guard", self.pusher, cmd, cwd=self.own)
            self.assertEqual(out["permissionDecision"], "deny", cmd)

    def test_with_the_set_in_force_what_the_brief_does_not_cover_is_refused_with_the_session_to_ask(self):
        """The `refusal` part: no card is raised in a session another session started. A push its brief does not
        tell it to make, behind a rebase too, a landing by gh, a landing from a checkout it shares and a move of
        that checkout are refused, and the reason names the session to ask."""
        self.on()
        for host, cmd, cwd, word in ((self.keeper, "git push origin HEAD:main", self.own, "`git push`"),
                                     (self.keeper, "git rebase origin/main && git push", self.own, "`git push`"),
                                     (self.pusher, "gh pr merge 12 --squash", self.own, "`gh pr merge`"),
                                     (B, "git push origin main", None, "`git push`"),
                                     (B, "git rebase main", None, "`git rebase`"),
                                     (B, "git switch main", None, "moving the checkout")):
            out = self.guard("branch-guard", host, cmd, cwd=cwd)
            self.assertEqual(out["permissionDecision"], "deny", cmd)
            self.assertIn(word, out["permissionDecisionReason"], cmd)
            self.assertIn(f"ask `{TOP}` with SendMessage", out["permissionDecisionReason"], cmd)
            self.assertIn("raises no approval card in a session another session started", out["permissionDecisionReason"])
        self.assertIsNone(self.guard("branch-guard", TOP, "git push origin main"), "the top session is no child")

    def test_a_session_from_before_the_key_has_its_brief_read_from_its_transcript(self):
        """A session that was running when the set came in force kept no `pushes`: its first message is read from
        its transcript once, so a brief that said to push still covers the push."""
        self.on()
        import phi
        s = self.t.session(self.keeper)
        s.pop("pushes")
        write(os.path.join(self.t.dir(self.keeper), "session.json"), json.dumps(s))
        path = os.path.join(self._tmp.name, "first.jsonl")
        write(path, json.dumps({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "Task:\nRework the flush, then push it to origin."}]}}) + "\n")
        r = self.t.hook("branch-guard", self.keeper, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                      "tool_input": {"command": "git push origin HEAD:main"},
                                                      "cwd": self.own, "transcript_path": path})
        self.assertEqual(r.stdout.strip(), "", "its brief said to push")
        self.assertIs(self.t.session(self.keeper).get("pushes"), True, "read once, and kept")
        self.assertTrue(callable(phi.brief_pushes))

    def push(self, host, path):
        r = self.t.hook("branch-guard", host, {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                               "tool_input": {"command": "git push origin HEAD:main"},
                                               "cwd": self.own, "transcript_path": path})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else ""

    def before_the_key(self, host, clis, task):
        """A session as one from before the key: no `pushes`, the CLI session ids it has run under, and the task
        kept at its first message."""
        s = self.t.session(host)
        s.pop("pushes", None)
        s.update(cliSessionIds=list(clis), task=task)
        write(os.path.join(self.t.dir(host), "session.json"), json.dumps(s))

    def test_a_transcript_that_opens_with_a_compactions_summary_is_not_read_as_the_brief(self):
        """A review point of the set: a session from before the key whose transcript opens with a compaction's
        summary had the summary read as its brief, so a push its brief covers was refused, and a summary that
        speaks of a push would have passed one its brief forbids. The summary row, which Claude Code marks
        `isCompactSummary`, is no brief: the brief is read from the transcript of an earlier CLI session id of the
        session, and where none holds it, from the task kept at its first message."""
        self.on()
        folder = os.path.join(self._tmp.name, "transcripts")
        row = lambda text, **more: json.dumps({"type": "user", "message": {"role": "user", "content": text},   # noqa: E731
                                               **more}) + "\n"
        summary = "This session is being continued from a previous conversation. The work is to rework the flush."
        opened = os.path.join(folder, "new-cli.jsonl")
        write(opened, row(summary, isCompactSummary=True, isVisibleInTranscriptOnly=True)
              + row("Carry on from where you stopped."))
        # the brief stands in the transcript of the session's first CLI id
        write(os.path.join(folder, "old-cli.jsonl"), row("Task:\nRework the flush, then push it to origin."))
        self.before_the_key(self.keeper, ["old-cli", "new-cli"], "Rework the flush.")
        self.assertEqual(self.push(self.keeper, opened), "", "its brief said to push")
        self.assertIs(self.t.session(self.keeper).get("pushes"), True)
        # no earlier transcript holds it: the task kept at the first message is read
        self.before_the_key(self.keeper, ["new-cli"], "Rework the flush, then push it to origin.")
        self.assertEqual(self.push(self.keeper, opened), "", "the kept task said to push")
        # and a summary that speaks of a push is no brief that tells the session to push
        pushy = os.path.join(folder, "pushy-cli.jsonl")
        write(pushy, row("This session is being continued. Earlier turns push the branch to origin.",
                         isCompactSummary=True) + row("Carry on."))
        write(os.path.join(folder, "first-cli.jsonl"), row("Task:\nRework the flush and commit it. Do not push."))
        self.before_the_key(self.pusher, ["first-cli", "pushy-cli"], "Rework the flush and commit it.")
        self.assertEqual(self.push(self.pusher, pushy), "deny", "its brief said not to")
        self.assertIs(self.t.session(self.pusher).get("pushes"), False)

    def test_a_starter_whose_app_record_holds_no_mode_is_still_checked_before_a_start(self):
        """A review point of the set: the step before a start read the starter's permission mode from the app's
        record alone, so a starter whose record holds none had a start of another class pass unchecked. The mode is
        read from the hook's own input, hooks.md's `permission_mode`, then the app's record, then what the
        session's last prompt carried. Where nothing says, a start that names a mode is refused, and one that
        leaves the mode out goes on."""
        self.on()
        self.assertNotIn("permissionMode", jload(os.path.join(self.t.app, A + ".json")))
        out = self.start(A, permission_mode="plan")
        self.assertEqual(out["permissionDecision"], "deny", "nothing says the starter's mode")
        self.assertIn("this session's own mode is not known", out["permissionDecisionReason"])
        self.assertIn("Leave `permission_mode` out", out["permissionDecisionReason"])
        self.assertIsNone(self.start(A), "the mode left out inherits the starter's, whatever it is")
        # the mode the session's last prompt carried
        r = self.t.hook("user-prompt-submit", A, {"hook_event_name": "UserPromptSubmit", "prompt": "carry on",
                                                  "permission_mode": "bypassPermissions"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.t.session(A).get("permissionMode"), "bypassPermissions")
        out = self.start(A, permission_mode="plan")
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("is of another class than this session's own `bypassPermissions`", out["permissionDecisionReason"])
        self.assertIsNone(self.start(A, permission_mode="bypassPermissions"), "of the starter's class")
        # the hook's own input says the mode the session is in now, ahead of what was kept
        path = os.path.join(self._tmp.name, A + "-t.jsonl")
        write(path, "x")
        r = self.t.hook("start-advice", A, {"hook_event_name": "PreToolUse", "permission_mode": "auto",
                                            "tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
                                            "tool_input": {"initiation": "user_asked", "context": "fresh",
                                                           "title": "a child", "use_worktree": False,
                                                           "permission_mode": "plan",
                                                           "prompt": "Read the docs.\nFiles: none"}})
        self.assertEqual(r.stdout.strip(), "", "auto and plan are one class")
        self.assertEqual(cards.before_start({"permission_mode": "auto"}, "", TOP, (TOP, "top"))[:12], "phi (p4-phi)")
        self.assertEqual(cards.before_start({"permission_mode": "auto"}, "", "", (TOP, "top")), "", "no child: no step")

    def test_the_store_guard_and_the_start_advice_refuse_in_a_started_session_and_ask_at_the_top(self):
        """A hand push in a store and a start p4-phi advises another way were asked about in every session. With
        the set in force a started session is refused with the session to ask, and the top session, where ezexe
        is, still gets the card."""
        store = self.t.p4.replace("\\", "/")
        subprocess.run(["git", "init", "-q", store], check=True, capture_output=True)
        cmd = f"cd {store} && git push origin main"
        self.assertEqual(self.guard("store-guard", B, cmd)["permissionDecision"], "ask", "set off")
        self.on()
        out = self.guard("store-guard", B, cmd)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("Two machines write the same", out["permissionDecisionReason"])
        self.assertIn(f"ask `{TOP}` with SendMessage", out["permissionDecisionReason"])
        self.assertEqual(self.guard("store-guard", TOP, cmd)["permissionDecision"], "ask", "ezexe's own session")

    def start(self, who, **inp):
        path = os.path.join(self._tmp.name, who + "-t.jsonl")
        write(path, "x")
        r = self.t.hook("start-advice", who, {"hook_event_name": "PreToolUse",
                                              "tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
                                              "tool_input": {"initiation": "user_asked", "context": "fresh",
                                                             "title": "a child", "use_worktree": False,
                                                             "prompt": "Read the docs.\nFiles: none", **inp}})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

    def mode(self, host, mode):
        path = os.path.join(self.t.app, host + ".json")
        write(path, json.dumps({**jload(path), "permissionMode": mode}))

    def test_the_step_before_a_start_refuses_what_would_leave_the_session_cut_off_or_waiting(self):
        """The `start` part, at the hook on the start call. A started session's start in another class of
        permission mode is refused, since cross-session-messaging.md holds every message between a session that
        bypasses permission prompts and one that does not, and the desktop app cannot show that approval. So is
        its start in another folder, on another host or in the cloud, which can raise the app's own card or the
        trust dialog: the reason names the top session, which makes it in a turn of ezexe's. A start that leaves
        the mode out, or names one of the starter's class, goes on."""
        self.mode(A, "bypassPermissions")
        self.assertIsNone(self.start(A, permission_mode="plan"), "set off: as before")
        self.on()
        for mode in ("plan", "auto", "default", "acceptEdits"):
            out = self.start(A, permission_mode=mode)
            self.assertEqual(out["permissionDecision"], "deny", mode)
            self.assertIn(f"`permission_mode` `{mode}` is of another class than this session's own "
                          f"`bypassPermissions`", out["permissionDecisionReason"])
            self.assertIn("Leave `permission_mode` out", out["permissionDecisionReason"])
        self.assertIsNone(self.start(A), "the mode left out inherits the starter's")
        self.assertIsNone(self.start(A, permission_mode="bypassPermissions"))
        self.mode(A, "auto")
        self.assertIsNone(self.start(A, permission_mode="plan"), "auto and plan are one class")
        self.assertEqual(self.start(A, permission_mode="bypassPermissions")["permissionDecision"], "deny")
        for inp in ({"cwd": "C:/elsewhere"}, {"target": "cloud"}, {"target": "ssh", "host": "devbox"},
                    {"preset": "mine"}):
            out = self.start(A, **inp)
            self.assertEqual(out["permissionDecision"], "deny", inp)
            self.assertIn(f"\"top\" `{TOP}` with SendMessage", out["permissionDecisionReason"])
        self.assertIsNone(self.start(A, target="local"))
        self.assertIsNone(self.start(A, cwd=self.t.proj), "the project's own folder, named, is no start elsewhere")
        self.mode(TOP, "bypassPermissions")
        self.assertIsNone(self.start(TOP, permission_mode="plan"), "the top session's start is ezexe's to see")
        self.assertIsNone(self.start(TOP, cwd="C:/elsewhere"))

    def test_the_yes_is_one_approval_card_and_a_started_session_is_refused_the_command(self):
        """`phi.py cards on <id>` is the one card the set has: p4-phi's guard answers `ask` for the command in the
        top session, with the set whole as the card's text, so the yes is ezexe's own press in every permission
        mode. A session another session started is refused, by the guard and by the command."""
        sid = p4conf.card_set_id()
        cmd = f'python -I -X utf8 "C:/plugins/p4-phi/scripts/phi.py" cards on {sid}'
        out = self.guard("cards-guard", TOP, cmd)
        self.assertEqual(out["permissionDecision"], "ask")
        for _, words in p4conf.CARD_SET:
            self.assertIn(words, out["permissionDecisionReason"])
        self.assertIn(sid, out["permissionDecisionReason"])
        self.assertEqual(self.guard("cards-guard", TOP, cmd, tool="PowerShell")["permissionDecision"], "ask")
        kid = self.guard("cards-guard", A, cmd)
        self.assertEqual(kid["permissionDecision"], "deny")
        self.assertIn(f"\"top\" `{TOP}`", kid["permissionDecisionReason"])
        for other in (f'python "x/phi.py" cards', 'python "x/phi.py" cards off', "grep -n 'cards on' phi.py",
                      'python "x/phi.py" upkeep on'):
            self.assertIsNone(self.guard("cards-guard", TOP, other), other)
        import hook
        for tool in ("Bash", "PowerShell"):
            self.assertEqual(hook.PHI_CHECK[tool][0], "cards-guard", "ahead of every other check of a shell call")
        spaced = f'python "x/phi.py"      cards    on  {sid}'
        self.assertEqual(self.guard("cards-guard", TOP, spaced)["permissionDecision"], "ask", "however it is spaced")
        module = os.path.join(os.path.dirname(SRC), "hooks", "register.ts")
        with open(module, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("CARDS_ON.test(text)", source, "the hooks module passes the call to python's check")
        self.assertIn("]+cards[^A-Za-z0-9]+on[", source, "by a pattern that takes any run of separators, as python's")
        # the command itself: refused in a started session, refused for another set's id, and it only asks
        r = self.t.cli(A, "cards", "on", sid)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(p4conf.cards_on(self.t.p4))
        r = self.t.cli(TOP, "cards", "on", "0123456789")
        self.assertEqual(r.returncode, 2)
        self.assertIn(sid, r.stderr)
        self.assertFalse(p4conf.cards_on(self.t.p4))
        r = self.t.cli(TOP, "cards", "on", sid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("The set is not in force yet", r.stdout)
        self.assertEqual(p4conf.cards_asked(self.t.p4), sid)
        self.assertFalse(p4conf.cards_on(self.t.p4), "run where no card was raised: the key and no yes")

    def after(self, host, cmd, call, event="PostToolUse", tool="Bash"):
        r = self.t.hook("cards-yes", host, {"hook_event_name": event, "tool_name": tool, "tool_use_id": call,
                                            "tool_input": {"command": cmd}, "tool_response": {"stdout": ""}})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout.strip() else ""

    def test_the_yes_is_kept_at_the_end_of_the_call_whose_card_was_raised_and_of_no_other(self):
        """The whole way a yes is given: the guard raises the card for a call and marks that call, ezexe presses,
        the command writes the key, and the hook after the call keeps the yes for the store the card named.
        hooks.md gives PostToolUse as fired "after a tool has already executed successfully", so that hook's run
        for a marked call is the press. A call that failed, a call no card was raised for, a second end of the
        same call, a call in a session another session started and a card whose command wrote no key keep none."""
        sid = p4conf.card_set_id()
        cmd = f'python -I -X utf8 "C:/plugins/p4-phi/scripts/phi.py" cards on {sid}'
        self.assertEqual(self.t.cli(TOP, "cards", "on", sid).returncode, 0)
        self.assertEqual(self.after(TOP, cmd, "toolu_unasked"), "", "no card was raised for this call")
        self.assertFalse(p4conf.cards_on(self.t.p4))
        self.assertEqual(self.guard("cards-guard", TOP, cmd, call="toolu_failed")["permissionDecision"], "ask")
        self.assertEqual(self.after(TOP, cmd, "toolu_failed", event="PostToolUseFailure"), "", "the call failed")
        self.assertFalse(p4conf.cards_on(self.t.p4))
        self.assertEqual(self.guard("cards-guard", A, cmd, call="toolu_kid")["permissionDecision"], "deny")
        self.assertEqual(self.after(A, cmd, "toolu_kid"), "", "refused in a started session, so nothing to keep")
        self.assertFalse(p4conf.cards_on(self.t.p4))
        self.assertEqual(self.guard("cards-guard", TOP, cmd, call="toolu_other")["permissionDecision"], "ask")
        self.assertEqual(self.after(TOP, "git status", "toolu_other"), "", "another command under the same id")
        # the card pressed for a command that wrote no key
        self.assertEqual(self.t.cli(TOP, "cards", "off").returncode, 0)
        self.assertEqual(self.guard("cards-guard", TOP, cmd, call="toolu_nokey")["permissionDecision"], "ask")
        self.assertEqual(self.after(TOP, cmd, "toolu_nokey"), "", "the key names no set")
        self.assertFalse(p4conf.cards_on(self.t.p4))
        # the press
        self.assertEqual(self.guard("cards-guard", TOP, cmd, call="toolu_yes1")["permissionDecision"], "ask")
        self.assertEqual(self.t.cli(TOP, "cards", "on", sid).returncode, 0)
        self.assertFalse(p4conf.cards_on(self.t.p4), "asked about and not ended yet")
        said = self.after(TOP, cmd, "toolu_yes1")
        self.assertIn(f"phi (p4-phi): ezexe's yes to the set {sid} is kept for the store", said)
        self.assertIn("the set is in force", said)
        self.assertTrue(p4conf.cards_on(self.t.p4))
        kept = yes_of(self.t.p4)
        self.assertEqual((kept["session"], kept["call"]), (TOP, "toolu_yes1"))
        shown = self.t.cli(A, "cards").stdout
        self.assertIn(f"The set {sid} of what p4-phi settles with no approval card is in force", shown)
        # one press keeps one yes: the same call's end a second time keeps nothing after an `off`
        self.assertEqual(self.t.cli(TOP, "cards", "off").returncode, 0)
        self.assertFalse(p4conf.cards_on(self.t.p4))
        p4conf.set_key(self.t.p4, p4conf.CARDS_KEY, sid)
        self.assertEqual(self.after(TOP, cmd, "toolu_yes1"), "")
        self.assertFalse(p4conf.cards_on(self.t.p4))
        import hook
        self.assertEqual(hook.PHI_YES, {"Bash": "cards-yes", "PowerShell": "cards-yes"})
        for tool in ("Bash", "PowerShell"):
            self.assertIn(tool, hook.WAITED, "the yes is kept in the entry the call waits on")

    def test_a_press_is_kept_while_the_keepers_lock_is_held(self):
        """The yes is p4-phi's own file, written whole by a rename, so a press is kept while the keeper holds its
        settings lock, and the hook says the set is in force."""
        sid = p4conf.card_set_id()
        cmd = f'python -I -X utf8 "C:/plugins/p4-phi/scripts/phi.py" cards on {sid}'
        self.assertEqual(self.guard("cards-guard", TOP, cmd, call="toolu_lock")["permissionDecision"], "ask")
        self.assertEqual(self.t.cli(TOP, "cards", "on", sid).returncode, 0)
        lock = os.path.join(self.t.p4, p4conf.SETTINGS_LOCK)
        open(lock, "w").close()
        said = self.after(TOP, cmd, "toolu_lock")
        os.remove(lock)
        self.assertIn(f"ezexe's yes to the set {sid} is kept for the store", said)
        self.assertTrue(p4conf.cards_on(self.t.p4))
    def runner(self, name, host, payload):
        """One entry of p4-phi's hooks.json as Claude Code runs it: `sh hooks/recall-hook.sh <name>` with the hook's
        input on stdin, and no P4_RECALL_SYNC, so the runner ends a clean call before python starts as it does in a
        session -> the hook's `hookSpecificOutput`, {} where it printed nothing."""
        env = self.t.env(host)
        env.pop("P4_RECALL_SYNC", None)
        r = subprocess.run(["sh", os.path.join(os.path.dirname(SRC), "hooks", "recall-hook.sh"), name],
                           input=json.dumps({"session_id": CLI.get(host, host), "cwd": self.t.proj, **payload}),
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout).get("hookSpecificOutput") or {} if r.stdout.strip() else {}

    def test_the_yes_is_kept_through_the_runner_as_hooks_json_runs_it(self):
        """The guard and the handler through `recall-hook.sh`, the runner hooks.json names. That runner ends a call
        that worked and printed no word that reads like an error before python starts, and the command's own
        output holds no such word, so without an arm for it no yes was ever kept in a session: p4-phi 0.11.100 to
        0.11.103. The runner passes a payload that holds the command on to python, in the entry the call waits
        on, and the batch's entry, which runs in the background and writes the call's lookup row, keeps no yes."""
        sid = p4conf.card_set_id()
        for n, (tool, cmd) in enumerate((("Bash", f'python -I -X utf8 "C:/plugins/p4-phi/scripts/phi.py" cards on {sid}'),
                                         ("PowerShell", f"python 'C:/plugins/p4-phi/scripts/phi.py'   cards   on {sid}"))):
            call = {"tool_name": tool, "tool_input": {"command": cmd}, "tool_use_id": f"toolu_run{n}"}
            asked = self.runner("lookup-check", TOP, {"hook_event_name": "PreToolUse", **call})
            self.assertEqual(asked.get("permissionDecision"), "ask", tool)
            ran = self.t.cli(TOP, "cards", "on", sid)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertFalse(p4conf.cards_on(self.t.p4))
            done = {"hook_event_name": "PostToolUse", **call, "tool_response": {"stdout": ran.stdout, "stderr": ""}}
            behind = {"hook_event_name": "PostToolBatch", "tool_calls": [dict(call, tool_response=ran.stdout)]}
            self.assertEqual(self.runner("lookup-batch", TOP, behind), {}, "left to the entry the call waits on")
            self.assertFalse(p4conf.cards_on(self.t.p4))
            said = self.runner("lookup-record", TOP, done).get("additionalContext") or ""
            self.assertIn(f"phi (p4-phi): ezexe's yes to the set {sid} is kept for the store", said, tool)
            self.assertTrue(p4conf.cards_on(self.t.p4), tool)
            self.assertEqual(self.t.cli(TOP, "cards", "off").returncode, 0)
        # a shell call that only names the script is ended before python starts, as before
        other = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "toolu_run9",
                 "tool_input": {"command": 'python "C:/plugins/p4-phi/scripts/phi.py" cards'},
                 "tool_response": {"stdout": "The set is not in force.", "stderr": ""}}
        self.assertEqual(self.runner("lookup-record", TOP, other), {})


if __name__ == "__main__":
    unittest.main()
