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

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def rules(self, key):
        got = p4conf._get(jload(self.local) if os.path.exists(self.local) else {}, key)
        return got if isinstance(got, list) else []

    def test_the_set_is_in_force_only_by_the_stores_own_file_and_only_as_this_copy_has_it(self):
        """What is settled with no approval card is a permission, so nothing puts the set in force but ezexe's yes,
        kept as `phi.cards` in the store's p4.json: the id of the set as this copy has it. No variable stands in
        for the key, an id of another set is no yes to this one, and a set that changed has another id."""
        self.assertFalse(p4conf.cards_on(self.p4), "off in a store that says nothing")
        self.assertFalse(p4conf.cards_on(""))
        sid = p4conf.card_set_id()
        self.assertRegex(sid, r"^[0-9a-f]{10}$")
        with mock.patch.dict(os.environ, {"P4_PHI_CARDS": sid}):
            self.assertFalse(p4conf.cards_on(self.p4), "no variable puts it in force")
        self.assertNotIn(p4conf.CARDS_KEY, p4conf.env_keys(), "the key has no variable")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, "0123456789")
        self.assertFalse(p4conf.cards_on(self.p4), "the yes to another set")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, True)
        self.assertFalse(p4conf.cards_on(self.p4), "a plain true names no set")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, sid)
        self.assertTrue(p4conf.cards_on(self.p4))
        self.assertNotIn(p4conf.CARDS_KEY, p4conf.env_wants(self.p4), "and none is written for it")
        changed = p4conf.CARD_SET + (("more", "One more thing settled with no card."),)
        with mock.patch.object(p4conf, "CARD_SET", changed):
            self.assertNotEqual(p4conf.card_set_id(), sid)
            self.assertFalse(p4conf.cards_on(self.p4), "a set that changed is in force nowhere until a new yes")
        names = [name for name, _ in p4conf.CARD_SET]
        self.assertEqual(names, ["tools", "archive", "own-branch", "push", "refusal", "start"], "the whole set")
        for word in ("deny", "credential", "password", "token"):
            self.assertNotIn(word, json.dumps(p4conf.CARD_SET).lower(), "it lifts no deny rule, touches no credential")

    def test_the_keeper_writes_the_tool_rules_only_while_the_set_is_in_force(self):
        """The `tools` part of the set: an allow rule for each tool a p4 hooks module declares, as entries of
        `permissions.allow` p4 owns under the record's `toolRules`. They come with the yes and go with it, a rule a
        person already wrote stays theirs, and p4's rules for phi.py and its deny rule are as before."""
        mine = "mcp__p4-phi__done"
        write(self.local, json.dumps({"permissions": {"allow": [mine, "Bash(ls *)"]}}))
        p4conf.keep_settings(self.proj)
        before = self.rules(p4conf.ALLOW_KEY)
        self.assertEqual([r for r in before if r.startswith("mcp__")], [mine], "set off: no rule of the set")
        self.assertEqual(self.rules(p4conf.ASK_KEY), [ARCHIVE], "the ask rule stands while phi.upkeep is off")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, p4conf.card_set_id())
        p4conf.keep_settings(self.proj)
        allow = self.rules(p4conf.ALLOW_KEY)
        self.assertEqual(sorted(r for r in allow if r.startswith("mcp__")), sorted(p4conf.CARD_TOOLS))
        self.assertEqual(allow[:len(before)], before, "nothing of the list before is moved or dropped")
        rec = p4conf.read_record(self.p4)
        owned = rec["toolRules"][p4conf.fwd(self.local)]["entries"]
        self.assertEqual(sorted(owned), sorted(t for t in p4conf.CARD_TOOLS if t != mine), "the person's own stays theirs")
        self.assertEqual(self.rules(p4conf.ASK_KEY), [ARCHIVE], "the set alone moves no ask rule")
        self.assertEqual(self.rules(p4conf.DENY_KEY), list(p4conf.DENY_RULES), "and no deny rule")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, None)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ALLOW_KEY), before, "the yes withdrawn: p4's rules go, the person's stays")
        self.assertNotIn("toolRules", p4conf.read_record(self.p4))

    def test_a_leftover_ask_rule_goes_only_with_upkeep_on_and_the_set_in_force(self):
        """The `archive` part: a store started anew lost the record of the ask rule p4 wrote, so with `phi.upkeep`
        on the keeper left the entry as a person's and the card came before every archive, 32 times on 2026-11-19.
        With the set in force the entry of p4's exact text is taken out. Another ask rule is never touched, and
        with `phi.upkeep` off the rule stays, set or no set."""
        other = "Bash(git push --force *)"
        write(self.local, json.dumps({"permissions": {"ask": [ARCHIVE, other]}}))
        p4conf.set_key(self.p4, "phi.upkeep", True)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ASK_KEY), [ARCHIVE, other], "set off: not p4's own by the record, so left")
        p4conf.set_key(self.p4, p4conf.CARDS_KEY, p4conf.card_set_id())
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ASK_KEY), [other], "the leftover is taken out, and no other ask rule")
        self.assertNotIn("askRules", p4conf.read_record(self.p4))
        p4conf.set_key(self.p4, "phi.upkeep", False)
        p4conf.keep_settings(self.proj)
        self.assertEqual(self.rules(p4conf.ASK_KEY), [other, ARCHIVE], "upkeep off: p4 writes its ask rule again")

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
        for want in ("a guard of p4-phi", "the ask rule on the archive tool", "a tool a p4 hooks module declares",
                     "a message between two sessions held", "the question about mods", "the trust dialog",
                     "a start the app does not make", "a question to ezexe", "a plan's approval"):
            self.assertIn(want, names)
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
        """docs/claude-settings.html, "Approval cards and a session's start", holds a row for each kind of card with
        the count of 2026-11-19, each part of the set, and the set's name as this copy has it."""
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
        self.assertEqual(part.count("On 2026-11-19"), 1)
        for count in ("42. 39 came at tool.check", "32, in four sessions", "47 held, of which 39 expired"):
            self.assertIn(count, part)

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
        p4conf.set_key(self.t.p4, p4conf.CARDS_KEY, p4conf.card_set_id())

    def guard(self, name, host, cmd, cwd=None, tool="Bash"):
        r = self.t.hook(name, host, {"hook_event_name": "PreToolUse", "tool_name": tool,
                                     "tool_input": {"command": cmd}, **({"cwd": cwd} if cwd else {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None

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
        self.assertIn("sync --push --p4", out["permissionDecisionReason"])
        self.assertIn(f"ask `{TOP}` with SendMessage", out["permissionDecisionReason"])
        self.assertEqual(self.guard("store-guard", TOP, cmd)["permissionDecision"], "ask", "ezexe's own session")

    def start(self, who, **inp):
        path = os.path.join(self._tmp.name, who + "-t.jsonl")
        write(path, "x")
        r = self.t.hook("start-advice", who, {"hook_event_name": "PreToolUse",
                                              "tool_name": "mcp__ccd_session__start_session", "transcript_path": path,
                                              "tool_input": {"initiation": "user_asked", "context": "fresh",
                                                             "title": "a child", "use_worktree": True,
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
        module = os.path.join(os.path.dirname(SRC), "hooks", "register.ts")
        with open(module, encoding="utf-8") as f:
            self.assertIn("CARDS_ON.test(text)", f.read(), "the hooks module passes the call to python's check")
        # the command itself: refused in a started session, refused for another set's id, and read back
        r = self.t.cli(A, "cards", "on", sid)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(p4conf.cards_on(self.t.p4))
        r = self.t.cli(TOP, "cards", "on", "0123456789")
        self.assertEqual(r.returncode, 2)
        self.assertIn(sid, r.stderr)
        self.assertFalse(p4conf.cards_on(self.t.p4))
        r = self.t.cli(TOP, "cards", "on", sid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the set is in force", r.stdout)
        self.assertTrue(p4conf.cards_on(self.t.p4))
        shown = self.t.cli(A, "cards").stdout
        self.assertIn(f"The set {sid} of what p4-phi settles with no approval card is in force", shown)
        self.assertEqual(self.t.cli(TOP, "cards", "off").returncode, 0)
        self.assertFalse(p4conf.cards_on(self.t.p4))


if __name__ == "__main__":
    unittest.main()
