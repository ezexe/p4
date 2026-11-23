#!/usr/bin/env python3
"""Tests for scripts/hook.py, the p4-phi hooks that hooks/recall-hook.sh runs.

Run: python -m pytest tests/p4-phi/test_hooks.py

It needs only the standard library's unittest and no network. Each hook runs as Claude Code runs it,
`sh hooks/recall-hook.sh <name>` with the JSON payload on stdin and CLAUDE_PLUGIN_ROOT and CLAUDE_PROJECT_DIR set, on
a small git project holding a store, a folder `.claude/p4` with a p4.json. Checked: the hooks.json events, matchers,
timeouts and the commands recall-hook.sh runs; silence where a hook has nothing to add; the layout hook finding the store and making none
where there is none; the text of an Agent call handed to its subagent's start, in process with phi.py's text
patched; the one folder, `phi/served`, that hook.pending_dir and rows.origin_dir name; every handler in a project with
no store.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
os.environ["P4_PHI"] = "0"          # phi.py's routed checks stay out of these tests: they touch no live store

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "scripts"))
sys.path.insert(0, SRC)
import p4conf  # noqa: E402

ROOT = os.path.dirname(SRC)
RUN = os.path.join(ROOT, "hooks", "recall-hook.sh")
HOOKS_JSON = os.path.join(ROOT, "hooks", "hooks.json")


def own_hooks(path, runner):
    """The plugin's hooks.json events and groups whose commands all run `runner`: in p4-phi's one hooks.json,
    run-hook.sh runs phi.py's hooks and recall-hook.sh runs hook.py's."""
    with open(path, encoding="utf-8") as f:
        h = json.load(f)["hooks"]
    out = {}
    for ev, groups in h.items():
        mine = [g for g in groups if all(runner in x["command"] for x in g["hooks"])]
        if mine:
            out[ev] = mine
    return out
SESSION = "cccc3333-0000-4000-8000-000000000000"


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def make_store(proj):
    """A store as the layout hook makes it: the folder `.claude/p4` with a p4.json, and nothing else."""
    write(os.path.join(proj, ".claude", "p4", "p4.json"), "{}\n")


def make_project(root):
    """A git project with a few tracked files and one commit, and a store at .claude/p4."""
    proj = os.path.join(root, "proj")
    os.makedirs(proj)
    git(proj, "init", "-q")
    write(os.path.join(proj, "src", "narwhal_port.py"), "def open_narwhal_port():\n    return 1\n")
    write(os.path.join(proj, "README.md"), "# Narwhal tools\n\nProbe the narwhal port.\n")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "add the narwhal port probe")
    make_store(proj)
    return proj


def run_hook(name, payload, proj, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj, "P4_RECALL_SYNC": "1", **(extra_env or {})})
    r = subprocess.run(["sh", RUN, name], input=json.dumps(payload), capture_output=True, text=True, env=env,
                       timeout=60)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = make_project(self.tmp.name)
        self.p4 = os.path.join(self.proj, ".claude", "p4")

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None


class HooksJson(unittest.TestCase):
    def test_events_matchers_timeouts(self):
        h = own_hooks(HOOKS_JSON, "/hooks/recall-hook.sh")
        self.assertEqual(set(h), {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
                                  "PostToolBatch", "SubagentStop", "ConfigChange", "SubagentStart"})
        # ezexe/p4#246: the settings watcher runs in the layout hook at every start, and here at a change of a
        # settings file, which it never blocks
        self.assertEqual(h["ConfigChange"][0]["matcher"], "local_settings|project_settings|user_settings")
        self.assertEqual(h["SessionStart"][0]["matcher"], "startup|resume|clear|compact|fork")
        self.assertEqual(h["SessionStart"][0]["hooks"][0]["timeout"], 15)
        self.assertEqual(len(h["SessionStart"]), 1, "the layout hook alone: no catch-up")
        self.assertEqual(h["UserPromptSubmit"][0]["hooks"][0]["timeout"], 10)
        self.assertEqual(h["PreToolUse"][0]["matcher"], "Agent")
        self.assertEqual(h["PreToolUse"][0]["hooks"][0]["timeout"], 10)
        self.assertEqual(h["SubagentStop"][0]["matcher"], ".+")
        names = {x["command"].split()[-1] for ev in h.values() for m in ev for x in m["hooks"]}
        self.assertEqual(names, {"layout", "watch", "agent", "lookup-record", "lookup-batch", "subagent-start",
                                 "subagent-stop", "settings"}, "no catch-up, recall, close or train")
        import hook
        for name in names:
            self.assertIn(name, hook.HANDLERS, name)
        for ev in h.values():
            for m in ev:
                for x in m["hooks"]:
                    self.assertEqual(x["type"], "command")
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/recall-hook.sh", x["command"])
        with open(HOOKS_JSON, encoding="utf-8") as f:
            stop = json.load(f)["hooks"]["Stop"]
        self.assertEqual([x["command"].split()[-1] for g in stop for x in g["hooks"]], ["stop"],
                         "phi.py's stop hook alone")

    def test_runner_runs_isolated_and_never_fails(self):
        with open(RUN, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('-I -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/hook.py"', text, "isolated, and in UTF-8 mode whatever the code page")
        self.assertIn("exit 0", text)
        r = subprocess.run(["sh", RUN, "no-such-hook"], input="{}", capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_PLUGIN_ROOT": ROOT})
        self.assertEqual(r.returncode, 0)
        self.assertIn("systemMessage", r.stdout)


class Payload(unittest.TestCase):
    def test_bare_windows_path_is_read_not_failed(self):
        import hook
        self.assertEqual(hook.parse_payload('{"cwd":"E:\\projects\\p4-phi","source":"startup"}'),
                         {"cwd": "E:\\projects\\p4-phi", "source": "startup"})

    def test_valid_json_and_empty_are_unchanged(self):
        import hook
        self.assertEqual(hook.parse_payload(json.dumps({"cwd": "E:\\new\\t", "x": "a\nb"})), {"cwd": "E:\\new\\t", "x": "a\nb"})
        self.assertEqual(hook.parse_payload("  "), {})
        with self.assertRaises(json.JSONDecodeError):
            hook.parse_payload('{"cwd": ')


class Ready(Base):
    def test_ready_returns_the_store_with_p4_json_alone_and_none_with_none(self):
        import hook
        payload = {"cwd": self.proj}
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj}):
            self.assertEqual(hook.ready(payload), self.p4, "a p4.json and no phi/store and no phi/models")
            os.remove(os.path.join(self.p4, "p4.json"))
            os.makedirs(p4conf.sub(self.p4, "store"))
            os.makedirs(p4conf.sub(self.p4, "models"))
            self.assertIsNone(hook.ready(payload), "the folders of the removed retrieval make no store")
            shutil.rmtree(self.p4)
            self.assertIsNone(hook.ready(payload), "no store at all")


class Layout(Base):
    def test_h_layout_makes_no_folder_where_there_is_no_store(self):
        """p4-temportal's `store make` is the maker, so the layout hook finds no store and does nothing, and makes
        no folder."""
        import hook
        shutil.rmtree(os.path.join(self.proj, ".claude"))
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj}):
            self.assertIsNone(hook.h_layout({"cwd": self.proj}))
        r = run_hook("layout", {"hook_event_name": "SessionStart", "source": "startup", "cwd": self.proj}, self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude")), "no .claude folder was made")
        for name in ("init_layout", "seed_gitignore", "exclude_line", "GITIGNORE"):
            self.assertFalse(hasattr(hook, name), f"{name} moved to p4-temportal's store.py")

    def test_the_layout_entry_leaves_what_p4_phi_asks_for_in_the_store(self):
        """The layout entry, run on a made store, writes the store's settings.local.json: the allow rules p4-phi
        asks the keeper for, in Claude Code's settings format."""
        r = run_hook("layout", {"hook_event_name": "SessionStart", "source": "startup", "cwd": self.proj}, self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        asked = os.path.join(self.p4, "settings.local.json")
        self.assertTrue(os.path.isfile(asked), "p4-phi wrote its file in the store")
        with open(asked, encoding="utf-8") as f:
            got = json.load(f)
        allow = got["permissions"]["allow"]
        self.assertTrue(allow and all("phi.py" in rule for rule in allow), allow)

    def test_a_served_record_older_than_a_day_is_swept(self):
        """A served record whose session never got to take it, as a session ended by a crash, is swept by the next
        layout hook once it is a day old."""
        import hook
        served = hook.served_dir(self.p4)
        old, fresh = os.path.join(served, "turn-dead0000.json"), os.path.join(served, "turn-live0000.json")
        for p in (old, fresh):
            write(p, '{"ids": []}')
        t = time.time() - 2 * 86400
        os.utime(old, (t, t))
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        self.assertFalse(os.path.exists(old), "two days old: swept")
        self.assertTrue(os.path.exists(fresh), "fresh: a live session's record stays")

    def test_a_start_hands_no_pinned_rule_and_the_rules_files_are_claude_codes_to_load(self):
        """memory.md, "Organize rules with `.claude/rules/`": "Rules without `paths` frontmatter are loaded at launch
        with the same priority as `.claude/CLAUDE.md`", and context-window.md, "What survives compaction":
        "Project-root CLAUDE.md and unscoped rules | Re-injected from disk". So the layout hook hands no block at any
        source."""
        for source in ("startup", "resume", "clear", "compact"):
            r = run_hook("layout", {"hook_event_name": "SessionStart", "source": source, "cwd": self.proj}, self.proj)
            self.assertEqual((r.returncode, r.stdout), (0, ""), source)


class Watch(Base):
    def test_a_change_of_claude_code_is_handed_once_and_nothing_else(self):
        import hook
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "hello", "session_id": SESSION, "cwd": self.proj}
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj}):
            self.assertIsNone(hook.h_watch(payload), "no pending file: silent")
            write(os.path.join(self.p4, "phi", "claude-code-watch.pending.json"), "{}")
            with mock.patch.object(p4conf, "claim_watch", return_value=["a line", "another"]) as claim:
                out = hook.h_watch(payload)
                claim.assert_called_once()
            self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                          "additionalContext": "a line\nanother"}})
            with mock.patch.object(p4conf, "claim_watch", return_value=[]):
                self.assertIsNone(hook.h_watch(payload), "a pending file that holds nothing")


class Agent(Base):
    INPUT = {"prompt": "check whether the quokka harness runs the zebrafish plotter golden images on every push",
             "description": "Check the harness", "subagent_type": "Explore", "model": "haiku"}
    TEXT = "phi (p4-phi): this subagent serves step 3 of the plan"

    def payload(self, **more):
        return {"session_id": SESSION, "cwd": self.proj, **more}

    def bound(self, agent_id, tool_use_id):
        """The file hooks/register.ts writes when `agent.spawn` answers: the subagent's id, bound to the Agent call
        that launched it."""
        import hook
        d = hook.pending_dir(self.payload())
        os.makedirs(d, exist_ok=True)
        write(os.path.join(d, hook.BOUND + agent_id), tool_use_id + "\n")

    def test_the_subagent_prompt_stays_and_its_text_comes_at_its_start(self):
        """ezexe/p4#243, row D2: the Agent call runs with its prompt as written, and phi.py's text reaches the
        subagent as context at its SubagentStart, once. The patch of hook.phi_text keeps it a test of the delivery
        and not of phi.py's session records."""
        import hook
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj}), \
                mock.patch.object(hook, "phi_text", side_effect=lambda name, payload: self.TEXT if name == "agent-launch" else ""):
            o = hook.h_agent(self.payload(hook_event_name="PreToolUse", tool_name="Agent",
                                          tool_input=dict(self.INPUT), tool_use_id="toolu_1"))
            self.assertIsNone(o, "the prompt stays as written")
            start = self.payload(hook_event_name="SubagentStart", agent_id="a9", agent_type="Explore")
            self.bound("a9", "toolu_1")
            hso = hook.h_subagent_start(start)["hookSpecificOutput"]
            self.assertEqual(hso, {"hookEventName": "SubagentStart", "additionalContext": self.TEXT})
            self.assertIsNone(hook.h_subagent_start(dict(start, agent_id="a10")), "each launch's text reaches one subagent")
            d = hook.pending_dir(self.payload())
            self.assertEqual(os.path.relpath(d, self.proj).replace(os.sep, "/"), ".claude/p4/phi/served/start-" + SESSION)
            self.assertEqual(os.listdir(d), [], "the launch's file and its binding are taken")
        o2 = self.out(run_hook("agent", {"tool_name": "Agent", "tool_input": dict(self.INPUT), "cwd": self.proj},
                               self.proj, {"P4_AGENT_ALLOW": "1"}))
        self.assertEqual(o2, {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}},
                         "P4_AGENT_ALLOW=1 adds allow and nothing else")

    def test_a_start_takes_the_text_of_its_own_launch_whatever_the_order_and_the_type(self):
        """The plugin's hooks module binds a subagent's id to the Agent call that launched it: `agent.spawn` carries
        the call's `tool_use_id` and answers the subagent's id. Two launches of one agent type wait: the start
        bound to the later one takes that one's text and leaves the earlier one's, where the order of launches would
        have handed it the earlier."""
        import hook
        other = dict(self.INPUT, prompt="read how the zebrafish plotter writes its golden images to disk")
        texts = {self.INPUT["prompt"]: "text of the first launch", other["prompt"]: "text of the second launch"}
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj}), \
                mock.patch.object(hook, "phi_text", side_effect=lambda name, payload: (
                    texts[payload["tool_input"]["prompt"]] if name == "agent-launch" else "")):
            for tid, inp in (("toolu_first", self.INPUT), ("toolu_second", other)):
                hook.h_agent(self.payload(hook_event_name="PreToolUse", tool_name="Agent", tool_input=dict(inp),
                                          tool_use_id=tid))
            d = hook.pending_dir(self.payload())
            self.assertEqual(len(os.listdir(d)), 2, "both launches wait")
            self.bound("a21", "toolu_second")
            start = self.payload(hook_event_name="SubagentStart", agent_id="a21", agent_type="Explore")
            got = hook.h_subagent_start(start)["hookSpecificOutput"]["additionalContext"]
            self.assertEqual(got, "text of the second launch")
            left = [n for n in os.listdir(d)]
            self.assertEqual(len(left), 1, left)
            self.assertTrue(left[0].endswith("-toolu_first.json"), "the earlier launch still waits for its own start")
            self.bound("a22", "toolu_first")
            first = hook.h_subagent_start(dict(start, agent_id="a22"))
            self.assertEqual(first["hookSpecificOutput"]["additionalContext"], "text of the first launch")
            self.assertEqual(os.listdir(d), [], "each launch taken by its own start, and each binding with it")

    def test_the_hooks_module_writes_the_binding_where_launch_of_reads_it(self):
        """hooks/register.ts holds the store's folder and the file's name as literals, since a module has no python:
        both are held here to hook.pending_dir and hook.BOUND, and the session's id is spelled as python spells it."""
        import hook
        with open(os.path.join(ROOT, "hooks", "register.ts"), encoding="utf-8") as f:
            module = f.read()
        d = hook.pending_dir({"session_id": "cli 0001/x", "cwd": self.proj})
        self.assertEqual(os.path.relpath(d, self.proj).replace(os.sep, "/"),
                         ".claude/p4/phi/served/start-cli_0001_x")
        self.assertEqual(os.path.relpath(os.path.join(self.p4, p4conf.FILE), self.proj).replace(os.sep, "/"),
                         ".claude/p4/p4.json", "the file whose presence says the project has a store")
        for said in ("const SERVED = '.claude/p4/phi/served'", "const STORE_FILE = '.claude/p4/p4.json'",
                     f"const BOUND = '{hook.BOUND}'", "`${project}/${SERVED}/start-${named(await $.session.id())}`",
                     "id.replace(/[^\\w-]/g, '_')", "`${folder}/${BOUND}${named(agentId)}`, `${toolUseId}\\n`",
                     "on('agent.spawn'", "on('classic.SubagentStart'"):
            self.assertIn(said, module, said)
        self.bound("a 31", "toolu_31")
        self.assertEqual(hook.launch_of({"session_id": SESSION, "cwd": self.proj, "agent_id": "a 31"}), "",
                         "an id is read under the name the module writes it by")
        self.bound("a_31", "toolu_31")
        self.assertEqual(hook.launch_of({"session_id": SESSION, "cwd": self.proj, "agent_id": "a 31"}), "toolu_31")

    def test_origin_dir_and_pending_dir_name_the_same_phi_served_folder(self):
        """rows.origin_dir, which phi.py and the origin of a prompt read, and hook.pending_dir, where a launch's
        text waits, are one folder, `phi/served`, where the project has a store, and none but the temp folder's where
        it has not."""
        import hook
        import rows
        for session in (SESSION, "cli 0001/x", ""):
            with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj}):
                pending = hook.pending_dir({"session_id": session, "cwd": self.proj})
            self.assertEqual(os.path.normpath(rows.origin_dir(self.proj, session)), os.path.normpath(pending), session)
            self.assertEqual(os.path.dirname(os.path.normpath(pending)), os.path.normpath(hook.served_dir(self.p4)))
        bare = os.path.join(self.tmp.name, "no store")
        os.makedirs(bare)
        self.assertEqual(rows.origin_dir(bare, SESSION), "", "no store: the origin is kept in the tree's store")
        self.assertTrue(hook.pending_dir({"session_id": SESSION, "cwd": bare}).startswith(tempfile.gettempdir()))

    def test_a_start_no_launch_is_bound_to_gets_no_text(self):
        """A launch whose Agent call failed or was denied starts no subagent, so no start is bound to it and a later
        start of the same type gets none of its text; neither does a start the hooks module bound to another call,
        such as a workflow's agent; a launch no start took is swept once old."""
        import hook
        launch = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": dict(self.INPUT),
                  "tool_use_id": "toolu_gone", "session_id": SESSION, "cwd": self.proj}
        run_hook("agent", launch, self.proj)
        r = run_hook("lookup-record", dict(launch, hook_event_name="PostToolUseFailure", error="denied"), self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        start = {"hook_event_name": "SubagentStart", "agent_id": "a11", "agent_type": "Explore",
                 "session_id": SESSION, "cwd": self.proj}
        self.assertIsNone(self.out(run_hook("subagent-start", start, self.proj)), "no launch bound: no text")
        self.bound("a12", "toolu_of_a_workflow")
        self.assertIsNone(self.out(run_hook("subagent-start", dict(start, agent_id="a12"), self.proj)),
                          "bound to a call that kept no text")
        d = hook.pending_dir({"session_id": SESSION, "cwd": self.proj})
        self.assertEqual([n for n in os.listdir(d) if n.startswith(hook.BOUND)], [], "a binding is read once")
        self.assertTrue(os.listdir(d), "the failed call's launch waits, for no start")
        hook.sweep_served(self.p4, now_s=time.time() + hook.PENDING_S + 60)
        self.assertFalse(os.path.exists(d), "an old launch and then its empty folder are swept")

    def test_unrelated_task_untouched(self):
        r = run_hook("agent", {"tool_name": "Agent", "tool_input": {"prompt": "what is the weather like today",
                                                                    "description": "x"}, "cwd": self.proj},
                     self.proj)
        self.assertEqual(r.stdout, "")


class AgentPre(unittest.TestCase):
    """A subagent's call that phi.py has news for still meets the guards: the news goes beside their answer, never
    in its place."""
    NEWS = "phi (p4-phi): the brief's file moved since this subagent's launch"

    def setUp(self):
        import hook
        self.hook = hook
        self._kept = (hook.phi_text, hook.phi_route)
        hook.phi_text = lambda name, payload: self.NEWS if name == "agent-pre" else ""

    def tearDown(self):
        self.hook.phi_text, self.hook.phi_route = self._kept

    def call(self, tool, inp):
        return self.hook.h_lookup_check({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp,
                                         "agent_id": "a1", "session_id": SESSION, "cwd": tempfile.gettempdir()})

    def test_a_guard_still_denies(self):
        deny = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": "a guard's reason"}}
        self.hook.phi_route = lambda payload, table: deny
        hso = self.call("Bash", {"command": "git checkout -b side"})["hookSpecificOutput"]
        self.assertEqual((hso["permissionDecision"], hso["permissionDecisionReason"]), ("deny", "a guard's reason"))
        self.assertEqual(hso["additionalContext"], self.NEWS)

    def test_the_news_alone_when_nothing_else_answers(self):
        self.hook.phi_route = lambda payload, table: None
        out = self.call("Read", {"file_path": "README.md"})
        self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": self.NEWS}})


class PathChecks(unittest.TestCase):
    """A started session's paths through hook.py's routing: an edit outside them is refused by `lookup-check`, and a
    shell call whose `tool_response.bashEditDiff` lists a changed file outside them is named by `lookup-record`."""

    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("no git")
        from test_phi import KID, TOP, Tree
        self.KID = KID
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.t = t = Tree(os.path.realpath(self._tmp.name))
        git(t.proj, "init", "-q", ".")
        t.record(TOP, title="the exporter top")
        t.record(KID, TOP, title="the flush child")
        t.say(TOP, "Build the exporter")
        t.say(KID, "Task:\nPort the flush.\nFiles: a.py")

    def run_recall(self, name, payload, root=None, **env):
        payload = {"session_id": __import__("test_phi").CLI[self.KID], "cwd": self.t.proj, **payload}
        env = {**self.t.env(self.KID, **env), "CLAUDE_PLUGIN_ROOT": root or ROOT}
        return subprocess.run(["sh", os.path.join(root or ROOT, "hooks", "recall-hook.sh"), name],
                              input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)

    def mine(self, name):
        return os.path.join(self.t.proj, name)

    def test_lookup_check_refuses_an_edit_a_write_and_a_notebook_edit_outside_the_paths(self):
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            r = self.run_recall("lookup-check", {"hook_event_name": "PreToolUse", "tool_name": tool,
                                                 "tool_input": {key: self.mine("b.py")}})
            hso = json.loads(r.stdout)["hookSpecificOutput"]
            self.assertEqual(hso["permissionDecision"], "deny", tool)
            self.assertIn("outside", hso["permissionDecisionReason"], tool)
            r = self.run_recall("lookup-check", {"hook_event_name": "PreToolUse", "tool_name": tool,
                                                 "tool_input": {key: self.mine("a.py")}})
            self.assertNotIn("deny", r.stdout, tool)

    def test_the_path_guard_stands_ahead_of_the_nudge_in_the_check_of_each_edit_tool(self):
        import hook
        for tool in ("Edit", "Write", "NotebookEdit"):
            self.assertEqual(hook.PHI_CHECK[tool][0], "path-guard", tool)
            self.assertIn("nudge", hook.PHI_CHECK[tool], tool)

    def bash(self, *changed, diff=True):
        resp = {"stdout": "", "stderr": ""}
        if diff:
            resp["bashEditDiff"] = {"files": [], "moreFiles": 0, "changedFiles": list(changed)}
        return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "make"},
                "tool_response": resp}

    def test_lookup_record_names_the_changed_path_outside_the_session_and_not_the_one_inside(self):
        inside, outside = self.mine("a.py"), self.mine("b.py")
        r = self.run_recall("lookup-record", self.bash(inside, outside))
        said = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("b.py", said)
        self.assertNotIn("a.py", said.split("outside")[0], "the path inside is not named as changed")
        self.assertEqual(self.run_recall("lookup-record", self.bash(inside)).stdout.strip(), "", "all inside")
        self.assertEqual(self.run_recall("lookup-record", self.bash(diff=False)).stdout.strip(), "", "no field")

    def test_the_shell_hook_starts_python_for_a_clean_bash_payload_that_lists_changed_files_and_for_none_else(self):
        root = os.path.join(self._tmp.name, "root")
        os.makedirs(os.path.join(root, "scripts"))
        os.makedirs(os.path.join(root, "hooks"))
        for name in ("recall-hook.sh", "find-python.sh"):
            shutil.copy(os.path.join(ROOT, "hooks", name), os.path.join(root, "hooks", name))
        mark = os.path.join(root, "started")
        write(os.path.join(root, "scripts", "hook.py"), f"open({mark!r}, 'a').close()\n")
        env = {"P4_RECALL_SYNC": ""}
        self.run_recall("lookup-record", self.bash(diff=False), root=root, **env)
        self.assertFalse(os.path.exists(mark), "a clean call with no list starts none")
        self.run_recall("lookup-record", self.bash(self.mine("b.py")), root=root, **env)
        self.assertTrue(os.path.exists(mark), "a clean call that changed files starts python")


TEMPORTAL_HOOKS = os.path.join(os.path.dirname(ROOT), "p4-temportal", "hooks")


def seed_by_temportal(proj):
    """The store a new project gets from p4-temportal's store.init_layout, run from that plugin's folder, so a test of
    what follows the maker starts where a session start leaves a new project."""
    made = subprocess.run([sys.executable, "-I", "-X", "utf8", "-c",
                           "import os, sys; sys.path.insert(0, os.getcwd()); import store; "
                           "store.init_layout(sys.argv[1])", proj],
                          cwd=TEMPORTAL_HOOKS, capture_output=True, text=True, timeout=60)
    assert made.returncode == 0, made.stderr
    assert os.path.isfile(os.path.join(proj, ".claude", "p4", "p4.json")), "store.init_layout made no store"


class ZeroConfiguration(unittest.TestCase):
    """The plugin works in a project nobody set up. An empty folder with no `.claude`, no P4_* variable and no
    settings file: every handler runs clean, the delegation rule is given, a top-level session's long command is
    moved to a background task, and, once p4-temportal's maker has made the store, the rest follows with no step from ezexe."""

    LONG = {"command": "python -m pytest -q", "description": "Run the tests"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proj = os.path.join(self.tmp.name, "a new project")
        os.makedirs(self.proj)
        self.sid = "eeee5555-0000-4000-8000-000000000000"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("P4_", "CLAUDE_", "CLAUDECODE"))}
        # what Claude Code itself gives a plugin's hook command, and nothing of the plugin's own
        self.env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": self.proj,
                         "CLAUDE_PLUGIN_DATA": os.path.join(self.tmp.name, "data"),
                         "CLAUDE_CONFIG_DIR": os.path.join(self.tmp.name, "config")})

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, runner, name, **payload):
        body = {"session_id": self.sid, "cwd": self.proj, **payload}
        r = subprocess.run(["sh", os.path.join(ROOT, "hooks", runner), name], input=json.dumps(body),
                           capture_output=True, text=True, env=self.env, timeout=90)
        self.assertEqual(r.returncode, 0, (name, r.stderr))
        self.assertNotIn("Traceback", r.stderr, name)
        out = json.loads(r.stdout) if r.stdout.strip() else {}
        self.assertNotIn("systemMessage", out, (name, out))
        return out.get("hookSpecificOutput") or out

    def handlers(self):
        start = self.run_hook("run-hook.sh", "session-start", hook_event_name="SessionStart", source="startup")
        said = self.run_hook("run-hook.sh", "user-prompt-submit", hook_event_name="UserPromptSubmit",
                             prompt="Make the exporter write its ports table")
        pre = self.run_hook("recall-hook.sh", "lookup-check", hook_event_name="PreToolUse", tool_name="Bash",
                            tool_input=dict(self.LONG), tool_use_id="toolu_zero1")
        plain = self.run_hook("recall-hook.sh", "lookup-check", hook_event_name="PreToolUse", tool_name="Bash",
                              tool_input={"command": "ls"}, tool_use_id="toolu_zero2")
        t = os.path.join(self.tmp.name, "t.jsonl")
        write(t, json.dumps({"type": "user", "uuid": "u0", "message": {
            "content": "Make the exporter write its ports table"}}) + "\n" + json.dumps({"type": "assistant", "message": {
                "content": [{"type": "text", "text": "done"}]}}) + "\n")
        stop = self.run_hook("run-hook.sh", "stop", hook_event_name="Stop", transcript_path=t,
                             last_assistant_message="done")
        return start, said, pre, plain, stop

    def test_every_handler_runs_in_a_project_with_no_store(self):
        start, said, pre, plain, stop = self.handlers()
        self.assertEqual(start, {}, "a start hands no rule: the rules are a section of the system prompt")
        self.assertEqual(pre, {}, "the call runs as sent with no line: the app moves it at its own timeout")
        self.assertEqual((said, plain, stop), ({}, {}, {}))
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude")), "phi.py's own handlers write nothing")

    def test_p4_temportals_maker_comes_first_and_the_rest_follows(self):
        seed_by_temportal(self.proj)
        self.run_hook("recall-hook.sh", "layout", hook_event_name="SessionStart", source="startup")
        p4 = os.path.join(self.proj, ".claude", "p4")
        self.assertTrue(os.path.isfile(os.path.join(p4, "p4.json")), "made by p4-temportal's store.init_layout")
        self.assertFalse(os.path.exists(p4conf.sub(p4, "store")), "with no phi/store")
        self.assertFalse(os.path.exists(p4conf.sub(p4, "models")), "and no phi/models")
        conf = p4conf.load(p4, write=False)["phi"]
        self.assertEqual((conf["levels"], conf["act_dont_wait"], conf["top_orchestrates"], conf["home"]),
                         (True, True, True, None), "p4.json is written with the working defaults")
        self.env["P4_PHI_WATCH"] = "0"       # only so this test leaves no watcher behind in its temporary folder
        start, said, pre, plain, stop = self.handlers()
        self.assertNotIn("built-in, ", json.dumps(start), "a start hands no rule")
        self.assertEqual(pre, {}, "the call runs as sent with no line")
        with open(os.path.join(p4, "phi", "sessions", self.sid, "session.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["task"], "Make the exporter write its ports table")
        self.assertTrue(os.path.exists(os.path.join(p4, "phi", "sessions", self.sid, "turns.jsonl")), "the turn kept")
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "data", ".python"))
                        or os.name != "nt", "the proven interpreter is remembered in the plugin's data folder")


if __name__ == "__main__":
    unittest.main(verbosity=1)
