#!/usr/bin/env python3
"""Every entry of p4-phi's hooks/hooks.json, run as the real command, and the two runners' own shell logic.

Each command is run the way Claude Code runs a shell-form command hook: `sh -c` with `${CLAUDE_PLUGIN_ROOT}` put in
with forward slashes, the event's input as one JSON object on stdin, and the plugin's variables in the environment.
Every entry runs twice, in a project with no store and in a project whose store the layout entry has just made.
Each run must exit 0, write nothing on stderr, and print nothing or one JSON object whose `hookSpecificOutput` names
the entry's own event.
The gate of recall-hook.sh runs against a stand-in python that only says it ran, and each runner runs with no python
on PATH at all, the marketplace's catalog is held to each plugin's own plugin.json, and every plugin folder to an entry
of that catalog.

Run: python3 test_wiring.py
"""

import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
HOOKS_JSON = os.path.join(ROOT, "hooks", "hooks.json")
RECALL = os.path.join(ROOT, "hooks", "recall-hook.sh")
PHI_RUN = os.path.join(ROOT, "hooks", "run-hook.sh")
SH = shutil.which("sh") or "sh"
STAND_IN = "#!/bin/sh\nprintf 'RAN'\nfor a in \"$@\"; do printf ' %s' \"$a\"; done\nprintf '\\n'\ncat >/dev/null\n"
SLASHED = ROOT.replace("\\", "/")
COMMAND = re.compile(r'^sh "\$\{CLAUDE_PLUGIN_ROOT\}/hooks/(run-hook\.sh|recall-hook\.sh)" ([a-z-]+)$')
SESSION = "77770000-0000-4000-8000-000000000001"
EVENTS = {"SessionStart": ("startup", "resume", "clear", "compact", "fork"),
          "UserPromptSubmit": None, "Stop": None,
          "StopFailure": ("rate_limit", "authentication_failed", "oauth_org_not_allowed", "account_on_hold",
                          "billing_error", "invalid_request", "model_not_found", "server_error", "max_output_tokens",
                          "cloud_credential_error", "unknown"),
          "SessionEnd": ("clear", "resume", "logout", "prompt_input_exit", "other"),
          "PreToolUse": "tools", "PostToolUse": "tools",
          "PostToolUseFailure": "tools", "SubagentStop": "agents", "SubagentStart": "agents",
          "ConfigChange": ("user_settings", "project_settings", "local_settings", "policy_settings", "skills")}


def entries():
    """(event, matcher, hook) for every command of hooks.json, in its order."""
    with open(HOOKS_JSON, encoding="utf-8") as f:
        h = json.load(f)["hooks"]
    return [(ev, g.get("matcher"), x) for ev, groups in h.items() for g in groups for x in g["hooks"]]


def handlers():
    """The hook names each runner's script answers: phi.HOOKS for run-hook.sh, hook.HANDLERS for recall-hook.sh."""
    sys.path.insert(0, SCRIPTS)
    try:
        import hook
        import phi
        # recall-hook.sh runs lookup-record-async as lookup-record, in the background the async entry gives it
        return {"run-hook.sh": set(phi.HOOKS), "recall-hook.sh": set(hook.HANDLERS) | {"lookup-record-async"}}
    finally:
        sys.path.remove(SCRIPTS)


def tool_for(matcher):
    """A tool the matcher takes: the one it names, or Bash for a matcher of every tool."""
    return "Agent" if matcher == "Agent" else "Bash"


def payload(event, matcher, proj, tmp):
    body = {"session_id": SESSION, "cwd": proj, "hook_event_name": event, "permission_mode": "default",
            "transcript_path": os.path.join(tmp, "transcript.jsonl")}
    if event == "SessionStart":
        body["source"] = "startup" if not matcher else matcher.split("|")[0]
    elif event == "UserPromptSubmit":
        body["prompt"] = "Make the exporter write its ports table"
    elif event == "Stop":
        body.update(stop_hook_active=False, last_assistant_message="done")
    elif event == "StopFailure":
        body.update(error="rate_limit", error_details="429 Too Many Requests",
                    last_assistant_message="API Error: Rate limit reached")
    elif event == "SessionEnd":
        body["reason"] = "prompt_input_exit"
    elif event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
        tool = tool_for(matcher)
        body.update(tool_name=tool, tool_use_id="toolu_wiring1",
                    tool_input={"description": "find it", "prompt": "Find the exporter's ports table",
                                "subagent_type": "general-purpose"} if tool == "Agent" else {"command": "ls"})
        if event == "PostToolUse":
            body["tool_response"] = {"stdout": "a.txt", "stderr": "", "interrupted": False}
        if event == "PostToolUseFailure":
            body.update(error="Exit code 2: ls: cannot access 'nowhere'", is_interrupt=False)
    elif event == "SubagentStop":
        body.update(agent_id="a0000wiring", agent_type="general-purpose", stop_hook_active=False,
                    last_assistant_message="done", agent_transcript_path=os.path.join(tmp, "agent.jsonl"))
    return body


def environment(proj, tmp):
    """What Claude Code gives a plugin's hook command, with the home and app-data folders moved into `tmp`."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "P4_", "ANTHROPIC"))}
    home = os.path.join(tmp, "home")
    env.update({"CLAUDE_PLUGIN_ROOT": SLASHED, "CLAUDE_PROJECT_DIR": proj,
                "CLAUDE_PLUGIN_DATA": os.path.join(tmp, "data"), "CLAUDE_CONFIG_DIR": os.path.join(tmp, "config"),
                "P4_PHI_APP_SESSIONS": os.path.join(tmp, "app-sessions"),
                "P4_PHI_STORES": os.path.join(tmp, "config", "p4-stores.json"),
                "P4_PHI_WATCH": "0", "P4_RECALL_SYNC": "1", "P4_PHI_GH": os.path.join(tmp, "no-gh"),
                "HOME": home, "USERPROFILE": home, "APPDATA": os.path.join(home, "AppData", "Roaming"),
                "LOCALAPPDATA": os.path.join(home, "AppData", "Local")})
    for d in (env["CLAUDE_CONFIG_DIR"], env["P4_PHI_APP_SESSIONS"], env["APPDATA"], env["LOCALAPPDATA"]):
        os.makedirs(d, exist_ok=True)
    return env


def run_entry(event, matcher, hook, proj, tmp):
    """One entry as Claude Code runs it -> the finished process."""
    command = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", SLASHED)
    for name in ("transcript.jsonl", "agent.jsonl"):
        path = os.path.join(tmp, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "uuid": "u0", "message": {
                    "content": "Make the exporter write its ports table"}}) + "\n" + json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}) + "\n")
    return subprocess.run(["sh", "-c", command], input=json.dumps(payload(event, matcher, proj, tmp)),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=environment(proj, tmp), cwd=proj, timeout=hook.get("timeout") or 60)


class Wiring(unittest.TestCase):
    def test_every_entry_names_its_runner_and_a_handler_of_it(self):
        known = handlers()
        for event, matcher, hook in entries():
            self.assertEqual(hook["type"], "command")
            m = COMMAND.match(hook["command"])
            self.assertTrue(m, hook["command"])
            runner, name = m.groups()
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "hooks", runner)), runner)
            self.assertIn(name, known[runner], f"{event}: {runner} {name} reaches no handler")

    def test_every_entry_is_on_an_event_and_a_matcher_claude_code_documents(self):
        for event, matcher, hook in entries():
            self.assertIn(event, EVENTS)
            if EVENTS[event] is None:
                self.assertIsNone(matcher, f"{event} ignores a matcher")
            elif isinstance(EVENTS[event], tuple) and matcher:
                self.assertTrue(set(matcher.split("|")) <= set(EVENTS[event]), matcher)
            if hook.get("async"):
                self.assertIn(event, ("Stop", "PostToolUse", "PostToolUseFailure", "SubagentStop"))

    def check(self, label, event, hook, r):
        where = f"{label}, {event}: {hook['command']}"
        self.assertEqual(r.returncode, 0, (where, r.stderr[-800:]))
        self.assertEqual(r.stderr.strip(), "", where)
        if not r.stdout.strip():
            return
        out = json.loads(r.stdout)
        self.assertIsInstance(out, dict, where)
        self.assertNotIn("systemMessage", out, (where, out))
        spec = out.get("hookSpecificOutput")
        if spec is not None:
            self.assertEqual(spec.get("hookEventName"), event, where)

    def run_all(self, label, make):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as top:
            jobs = []
            for k, (event, matcher, hook) in enumerate(entries()):
                tmp = os.path.join(top, f"e{k}")
                os.makedirs(tmp)
                jobs.append((event, matcher, hook, make(tmp), tmp))
            with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
                done = list(ex.map(lambda j: (j, run_entry(*j)), jobs))
            for (event, matcher, hook, proj, tmp), r in done:
                self.check(label, event, hook, r)

    def test_every_entry_runs_in_a_project_with_no_store(self):
        def make(tmp):
            proj = os.path.join(tmp, "a new project")
            os.makedirs(proj)
            return proj
        self.run_all("no store", make)

    def test_every_entry_runs_in_a_project_whose_store_was_just_made(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as base:
            seed = os.path.join(base, "a new project")
            os.makedirs(seed)
            layout = [e for e in entries() if e[2]["command"].endswith(" layout")][0]
            r = run_entry(*layout, seed, base)
            self.check("layout", layout[0], layout[2], r)
            self.assertTrue(os.path.isdir(os.path.join(seed, ".claude", "p4", "phi")), "the layout entry made no store")

            def make(tmp):
                proj = os.path.join(tmp, "a new project")
                shutil.copytree(seed, proj)
                return proj
            self.run_all("a new store", make)


class SessionEndBudget(unittest.TestCase):
    """SessionEnd hooks share 1.5 seconds, and a plugin hook's timeout does not raise it, by
    https://code.claude.com/docs/en/hooks#sessionend."""

    BUDGET = 1.5

    def test_the_session_end_entry_logs_the_end_and_its_reason_within_the_budget(self):
        """ezexe/p4#151: the entry, run as Claude Code runs it, logs the end as a turn's end with its reason. Each run
        is a cold interpreter, and the fastest of three is held to the budget, so a machine busy with the rest of the
        suite does not decide it."""
        e = {ev: (ev, m, x) for ev, m, x in entries() if x["command"].endswith((" user-prompt-submit", " session-end",
                                                                                " layout"))}
        self.assertNotIn("timeout", e["SessionEnd"][2], "a plugin's timeout does not raise the shared budget")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            proj = os.path.join(tmp, "a new project")
            os.makedirs(proj)
            for ev in ("SessionStart", "UserPromptSubmit"):
                r = run_entry(*e[ev], proj, tmp)
                self.assertEqual((r.returncode, r.stderr.strip()), (0, ""), ev)
            spent = []
            for _ in range(3):
                started = time.perf_counter()
                r = run_entry(*e["SessionEnd"], proj, tmp)
                spent.append(time.perf_counter() - started)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            self.assertLess(min(spent), self.BUDGET, spent)
            log = os.path.join(proj, ".claude", "p4", "phi", "sessions", SESSION, "log.jsonl")
            with open(log, encoding="utf-8") as f:
                row = json.loads(f.read().splitlines()[-1])
            self.assertEqual((row["hook"], row["event"], row["ended"]), ("stop", "SessionEnd", "prompt_input_exit"))


class Matchers(unittest.TestCase):
    """Each matcher read as the hooks page reads it: `*`, `""` or none take every value, a matcher of letters,
    digits, `_`, `-`, spaces, `,` and `|` is a list of exact names, and any other is an unanchored regex."""

    @staticmethod
    def takes(matcher, value):
        if matcher in (None, "", "*"):
            return True
        if re.fullmatch(r"[A-Za-z0-9_\- ,|]+", matcher):
            return value in {x.strip() for x in re.split(r"[|,]", matcher)}
        return re.search(matcher, value) is not None

    def matcher_of(self, event, handler):
        return next(m for ev, m, x in entries() if ev == event and x["command"].endswith(" " + handler))

    def test_layout_runs_on_every_start_a_fork_included(self):
        m = self.matcher_of("SessionStart", "layout")
        for source in EVENTS["SessionStart"]:
            self.assertTrue(self.takes(m, source), source)

    def test_subagent_stop_leaves_out_an_empty_agent_type(self):
        m = self.matcher_of("SubagentStop", "subagent-stop")
        self.assertFalse(self.takes(m, ""), m)
        for name in ("Explore", "general-purpose", "p4-phi:sweep"):
            self.assertTrue(self.takes(m, name), name)


class Manifests(unittest.TestCase):
    """The marketplace's catalog against each plugin's own plugin.json: Claude Code warns when an entry's version and
    its plugin.json's differ, platform row P16."""

    def test_each_marketplace_entry_has_its_plugins_name_and_version(self):
        lbiza = os.path.dirname(os.path.dirname(ROOT))
        with open(os.path.join(lbiza, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        self.assertTrue(market["plugins"])
        for entry in market["plugins"]:
            with open(os.path.join(lbiza, entry["source"], ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
                plugin = json.load(f)
            self.assertEqual(plugin["name"], entry["name"], entry["source"])
            self.assertEqual(plugin.get("version"), entry.get("version"), entry["name"])

    def test_every_plugin_folder_has_a_marketplace_entry(self):
        """A plugin folder the catalog does not list cannot be installed from the marketplace, platform row P14."""
        lbiza = os.path.dirname(os.path.dirname(ROOT))
        with open(os.path.join(lbiza, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        listed = {os.path.normcase(os.path.normpath(os.path.join(lbiza, e["source"])))
                  for e in market["plugins"] if isinstance(e.get("source"), str)}
        plugins = os.path.join(lbiza, "plugins")
        for name in sorted(os.listdir(plugins)):
            folder = os.path.join(plugins, name)
            if os.path.isfile(os.path.join(folder, ".claude-plugin", "plugin.json")):
                self.assertIn(os.path.normcase(os.path.normpath(folder)), listed, name)


def marker_name(agent_id):
    """The name phi.py gives an open subagent's marker, `agent_marker` in phi.py."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(agent_id))[:80]


class Gate(unittest.TestCase):
    """recall-hook.sh's lookup-check gate, against a stand-in python that only says it ran and with what."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        tmp = self._tmp.name
        self.bin = os.path.join(tmp, "bin")
        os.makedirs(self.bin)
        stand_in = os.path.join(self.bin, "fakepy")
        with open(stand_in, "w", encoding="utf-8", newline="\n") as f:
            f.write(STAND_IN)
        os.chmod(stand_in, 0o755)
        for name in ("python3", "python", "py"):
            shutil.copy(stand_in, os.path.join(self.bin, name))
        self.data = os.path.join(tmp, "data")
        os.makedirs(self.data)
        with open(os.path.join(self.data, ".python"), "w", encoding="utf-8", newline="\n") as f:
            f.write(stand_in.replace("\\", "/") + "\n")              # where Windows reads the proved python
        self.proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(self.proj, ".claude", "p4", "phi"))

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, tool, tool_input, **more):
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "P4_"))}
        env.update(CLAUDE_PLUGIN_ROOT=SLASHED, CLAUDE_PROJECT_DIR=self.proj, CLAUDE_PLUGIN_DATA=self.data,
                   PATH=self.bin + os.pathsep + env.get("PATH", ""))
        payload = json.dumps({"session_id": SESSION, "hook_event_name": "PreToolUse", "tool_name": tool,
                              "tool_input": tool_input, "cwd": self.proj, **more})
        r = subprocess.run([SH, RECALL, "lookup-check"], input=payload, capture_output=True, text=True, env=env,
                           cwd=self.proj, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_a_message_to_another_session_reaches_phis_go_guard(self):
        """hook.py hands SendMessage and the app's send_message to phi.py's go-guard, so the gate lets both through."""
        for tool in ("SendMessage", "mcp__ccd_session_mgmt__send_message"):
            out = self.check(tool, {"to": "local_x", "message": "go ahead"})
            self.assertTrue(out.startswith("RAN ") and out.endswith("scripts/hook.py lookup-check"), (tool, out))

    def test_only_a_subagents_own_marker_opens_the_gate_for_it(self):
        """phi.py marks an open subagent with a file named after its id; a marker another subagent left behind, when
        no SubagentStop removed it, opens the gate for no other subagent."""
        agents = os.path.join(self.proj, ".claude", "p4", "phi", ".agents")
        os.makedirs(agents)
        old, new = "a5f0c2d9e8b7a6f41", "a389c1db97089b3bf"           # ids as the Agent tool gives them
        open(os.path.join(agents, marker_name(old)), "w").close()
        self.assertEqual(self.check("Read", {"file_path": "a.py"}, agent_id=new), "")
        open(os.path.join(agents, marker_name(new)), "w").close()
        self.assertTrue(self.check("Read", {"file_path": "a.py"}, agent_id=new).startswith("RAN "))

    def test_a_read_ends_in_the_gate_and_a_web_call_reaches_hook_py(self):
        self.assertEqual(self.check("Read", {"file_path": "a.py"}), "")
        self.assertTrue(self.check("WebFetch", {"url": "https://example.com"}).startswith("RAN "))

    def test_git_opens_the_gate_only_as_a_word_of_the_command(self):
        """A path holding `github` starts no python for a plain shell call; a git command still reaches hook.py."""
        where = {"transcript_path": "C:/Users/x/github/proj/s.jsonl"}
        for cmd in ("ls", "ls github", "cat .gitignore", "ls ~/git/x", "digit"):
            self.assertEqual(self.check("Bash", {"command": cmd, "description": "list github"}, **where), "", cmd)
        for cmd in ("git status", "cd a && git log", "ls; git diff", "cd repo\ngit push", "cd repo\tgit push",
                    "cd repo\r\ngit push", "git\npush", "git.exe push", "cd a && C:/Git/bin/git.exe push",
                    "git-lfs push", "git.cmd push", "cd a && git-lfs push", "cd repo\ngit.cmd push"):
            self.assertTrue(self.check("Bash", {"command": cmd}, **where).startswith("RAN "), cmd)


class SharedProbe(unittest.TestCase):
    """Both runners find their python through hooks/find-python.sh and repeat none of its search."""

    def test_both_runners_source_the_one_search(self):
        for runner in (PHI_RUN, RECALL):
            with open(runner, encoding="utf-8") as f:
                text = f.read()
            self.assertIn('f="${CLAUDE_PLUGIN_ROOT}/hooks/find-python.sh"', text, runner)
            self.assertIn('. "$f"', text, runner)
            self.assertNotIn("for c in $order", text, runner)
            self.assertNotIn("sys.executable", text, runner)

    def test_a_missing_finder_ends_in_the_message_and_exit_0(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "P4_"))}
            env.update(CLAUDE_PLUGIN_ROOT=tmp.replace("\\", "/"), CLAUDE_PROJECT_DIR=tmp)
            for runner, name in ((PHI_RUN, "session-start"), (RECALL, "layout")):
                r = subprocess.run([SH, runner, name], input="{}", capture_output=True, text=True, env=env, cwd=tmp,
                                   timeout=60)
                self.assertEqual(r.returncode, 0, (name, r.stderr))
                self.assertIn("no working python found", r.stdout, name)


def no_python_path(tmp):
    """A PATH that finds `sh` and `mkdir` and no python: the shell's own folder where it holds none, as Git's does
    on Windows, else a folder of links to the two."""
    folder = os.path.dirname(SH)
    if not any(shutil.which(n, path=folder) for n in ("python3", "python", "py")):
        return folder
    links = os.path.join(tmp, "shbin")
    os.makedirs(links)
    for tool in ("sh", "mkdir"):
        os.symlink(shutil.which(tool), os.path.join(links, tool))
    return links


class NoPython(unittest.TestCase):
    """Each runner with no python on PATH and none remembered: it ends with exit 0 and says so to ezexe."""

    def test_each_runner_says_so_when_it_finds_no_python(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "P4_"))}
            env.update(PATH=no_python_path(tmp), CLAUDE_PLUGIN_ROOT=SLASHED, CLAUDE_PROJECT_DIR=tmp,
                       CLAUDE_PLUGIN_DATA=os.path.join(tmp, "data"), HOME=tmp, USERPROFILE=tmp)
            for runner, name in ((PHI_RUN, "session-start"), (RECALL, "layout")):
                r = subprocess.run([SH, runner, name], input="{}", capture_output=True, text=True, env=env, cwd=tmp,
                                   timeout=60)
                self.assertEqual(r.returncode, 0, (name, r.stderr))
                out = json.loads(r.stdout) if r.stdout.strip() else {}
                self.assertIn("no working python found", out.get("systemMessage", ""),
                              (os.path.basename(runner), r.stdout))


if __name__ == "__main__":
    unittest.main(verbosity=2)
