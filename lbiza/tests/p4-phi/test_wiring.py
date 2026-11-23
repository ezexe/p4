#!/usr/bin/env python3
"""Every entry of p4-phi's hooks/hooks.json, run as the real command, and the two runners' own shell logic.

Each command is run the way Claude Code runs a shell-form command hook: `sh -c` with `${CLAUDE_PLUGIN_ROOT}` put in
with forward slashes, the event's input as one JSON object on stdin, and the plugin's variables in the environment.
Every entry runs twice, in a project with no store and in a project whose store the layout entry has just made.
Each run must exit 0, write nothing on stderr, and print nothing or one JSON object whose `hookSpecificOutput` names
the entry's own event.
The gate of recall-hook.sh runs against a stand-in python that only says it ran, and each runner runs with no python
on PATH at all, the marketplace's catalog at the repository's root is held to each plugin's own plugin.json, and every
plugin folder to an entry of that catalog.

Run: python -m pytest tests/p4-phi/test_wiring.py
"""

import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

# the folder of the code these tests run
SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "plugins", "p4-phi", "hooks"))
ROOT = os.path.dirname(SRC)
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
          "PreToolUse": "tools", "PostToolUse": "tools", "PostToolBatch": None,
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
        return {"run-hook.sh": set(phi.HOOKS), "recall-hook.sh": set(hook.HANDLERS)}
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
    elif event == "PostToolBatch":
        body["tool_calls"] = [{"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "toolu_wiring1",
                               "tool_response": "a.txt"}]
    elif event == "SubagentStart":
        body.update(agent_id="a0000wiring", agent_type="general-purpose")
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
                "P4_RECALL_SYNC": "1", "P4_PHI_GH": os.path.join(tmp, "no-gh"),
                "HOME": home, "USERPROFILE": home, "APPDATA": os.path.join(home, "AppData", "Roaming"),
                "LOCALAPPDATA": os.path.join(home, "AppData", "Local")})
    for d in (env["CLAUDE_CONFIG_DIR"], env["P4_PHI_APP_SESSIONS"], env["APPDATA"], env["LOCALAPPDATA"]):
        os.makedirs(d, exist_ok=True)
    return env


def cpu_run(args, **kw):
    """subprocess.run of `args` -> (the finished process, the CPU seconds it and every process it started spent).
    On Windows the process starts suspended inside a job object of its own, which every process it starts joins, and
    the job's accounting gives the user and kernel time of all of them. Elsewhere getrusage of the reaped children
    gives the same. CPU time is the work the entry does, which a machine busy with other suites does not lengthen
    the way it lengthens the time on the clock."""
    if os.name != "nt":
        import resource
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        r = subprocess.run(args, capture_output=True, **kw)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        return r, (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    import ctypes
    from ctypes import wintypes

    class Accounting(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                    ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k32.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.c_void_p)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    job = k32.CreateJobObjectW(None, None)
    timeout = kw.pop("timeout", None)
    text_in = kw.pop("input", None)
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=0x4, **kw)                        # CREATE_SUSPENDED
        if not k32.AssignProcessToJobObject(job, int(p._handle)):
            p.kill()
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
        ntdll.NtResumeProcess(int(p._handle))
        out, err = p.communicate(text_in, timeout=timeout)
        acc = Accounting()
        if not k32.QueryInformationJobObject(job, 1, ctypes.byref(acc), ctypes.sizeof(acc), None):
            raise OSError(ctypes.get_last_error(), "QueryInformationJobObject")
        r = subprocess.CompletedProcess(args, p.returncode, out, err)
        return r, (acc.TotalUserTime + acc.TotalKernelTime) / 1e7
    finally:
        k32.CloseHandle(job)


def run_entry(event, matcher, hook, proj, tmp, cpu=False):
    """One entry as Claude Code runs it -> the finished process, and with `cpu` the CPU seconds of its processes."""
    command = hook["command"].replace("${CLAUDE_PLUGIN_ROOT}", SLASHED)
    for name in ("transcript.jsonl", "agent.jsonl"):
        path = os.path.join(tmp, name)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "uuid": "u0", "message": {
                    "content": "Make the exporter write its ports table"}}) + "\n" + json.dumps(
                    {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}) + "\n")
    kw = dict(input=json.dumps(payload(event, matcher, proj, tmp)), text=True, encoding="utf-8", errors="replace",
              env=environment(proj, tmp), cwd=proj, timeout=hook.get("timeout") or 60)
    if cpu:
        return cpu_run(["sh", "-c", command], **kw)
    return subprocess.run(["sh", "-c", command], capture_output=True, **kw)


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
                self.assertIn(event, ("Stop", "PostToolUse", "PostToolUseFailure", "PostToolBatch", "SubagentStop"))

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
            self.assertTrue(os.path.isfile(os.path.join(seed, ".claude", "p4", "p4.json")), "the layout entry made no store")

            def make(tmp):
                proj = os.path.join(tmp, "a new project")
                shutil.copytree(seed, proj)
                return proj
            self.run_all("a new store", make)


class KeptScripts(unittest.TestCase):
    """What stays of the scripts after the training, ranking and recall left: no kept file names a removed one."""

    def test_every_import_of_every_kept_script_is_standard_library_or_a_file_of_the_scripts_folder(self):
        """An ast walk of each script's `import` and `from` statements, those inside functions too: each name is in
        the standard library or is a file of the scripts folder, so no kept script imports a removed one."""
        import ast
        files = sorted(f for f in os.listdir(SCRIPTS) if f.endswith(".py"))
        kept = {f[:-3] for f in files}
        for gone in ("catchup", "deps", "digests", "labels", "lookups", "near", "notices", "p4", "ranker", "repo",
                     "said", "store", "storeenv", "sync", "teacher", "train", "view"):
            self.assertNotIn(gone, kept, f"{gone}.py is removed")
        self.assertIn("pathfilter", kept, "the one file kept for the store's git filter")
        seen = 0
        for name in files:
            with open(os.path.join(SCRIPTS, name), encoding="utf-8") as f:
                tree = ast.parse(f.read(), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                else:
                    continue
                for mod in mods:
                    seen += 1
                    top = mod.split(".")[0]
                    self.assertTrue(top in sys.stdlib_module_names or top in kept, f"{name}: imports {mod}")
        self.assertGreater(seen, 100, "the walk saw the imports of the scripts")


class NoGitBash(unittest.TestCase):
    """onFailure, by https://code.claude.com/docs/en/hooks, "Block the action when a hook fails" and "Failed hooks on
    Windows without Git Bash", Claude Code v2.1.295 and later."""

    def test_a_hook_that_cannot_start_never_blocks_a_call(self):
        """ezexe/p4#121: on Windows without Git Bash a shell-form hook runs in PowerShell, where `sh` is missing, and a
        PreToolUse hook that fails there with onFailure unset blocks the tool call. Both runners exit 0 whatever
        their python does, so p4-phi's guards already let a call through when they break; each entry on which
        onFailure acts sets continue, so a runner that never starts does the same. Stop, SubagentStop and async
        entries set none, since the docs say onFailure does nothing there."""
        acts = 0
        for event, matcher, hook in entries():
            if event in ("Stop", "SubagentStop") or hook.get("async"):
                self.assertNotIn("onFailure", hook, (event, hook["command"]))
            else:
                self.assertEqual(hook.get("onFailure"), "continue", (event, hook["command"]))
                acts += event == "PreToolUse"
        self.assertTrue(acts, "the PreToolUse entries are the ones that can block a call")


class SessionEndBudget(unittest.TestCase):
    """SessionEnd hooks share 1.5 seconds, and a plugin hook's timeout does not raise it, by
    https://code.claude.com/docs/en/hooks#sessionend."""

    BUDGET = 1.5

    def test_the_session_end_entry_logs_the_end_and_its_reason_within_the_budget(self):
        """ezexe/p4#151: the entry, run as Claude Code runs it, logs the end as a turn's end with its reason. The
        budget is Claude Code's own, by hooks.md: "SessionEnd hooks share a 1.5-second budget". Each run is a cold
        interpreter, and the CPU time of every process the entry starts, the least of three runs, is held to it:
        a machine busy with other suites lengthens the time on the clock and leaves the work the entry does."""
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
                r, used = run_entry(*e["SessionEnd"], proj, tmp, cpu=True)
                spent.append(used)
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

    def test_the_session_start_entry_runs_after_every_compaction(self):
        """ezexe/p4#155: Claude Code's own way to keep context through a compaction is a SessionStart hook on the
        `compact` source, by https://code.claude.com/docs/en/hooks-guide#re-inject-context-after-compaction, and that
        source comes after a typed /compact and an auto-compaction alike. phi.py's session-start entry hands a
        puppeteer its board's path there, so no PreCompact entry and no typed instruction is needed."""
        m = self.matcher_of("SessionStart", "session-start")
        self.assertTrue(self.takes(m, "compact"), m)

    def test_subagent_stop_leaves_out_an_empty_agent_type(self):
        m = self.matcher_of("SubagentStop", "subagent-stop")
        self.assertFalse(self.takes(m, ""), m)
        for name in ("Explore", "general-purpose", "p4-phi:check"):
            self.assertTrue(self.takes(m, name), name)


class Manifests(unittest.TestCase):
    """The marketplace's one catalog, `.claude-plugin/marketplace.json` at the repository's root, against each plugin's
    own plugin.json. A plugin's version lives in its plugin.json alone, so no entry of the catalog can differ from it:
    https://code.claude.com/docs/en/plugins/loading.md, "How Claude Code computes the version", has "The `version`
    field in the plugin's manifest comes first", and Claude Code warns when an entry's version and its plugin.json's
    differ, platform row P16."""

    def test_each_marketplace_entry_has_its_plugins_name_and_leaves_the_version_to_its_plugin_json(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))
        with open(os.path.join(repo, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        self.assertTrue(market["plugins"])
        for entry in market["plugins"]:
            with open(os.path.join(repo, entry["source"], ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
                plugin = json.load(f)
            self.assertEqual(plugin["name"], entry["name"], entry["source"])
            self.assertNotIn("version", entry, entry["name"])
            self.assertRegex(plugin.get("version") or "", r"^\d+\.\d+\.\d+$", entry["name"])

    def test_every_plugin_folder_has_a_marketplace_entry(self):
        """A plugin folder the catalog does not list cannot be installed from the marketplace, platform row P14."""
        lbiza = os.path.dirname(os.path.dirname(ROOT))
        repo = os.path.dirname(lbiza)
        with open(os.path.join(repo, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        listed = {os.path.normcase(os.path.normpath(os.path.join(repo, e["source"])))
                  for e in market["plugins"] if isinstance(e.get("source"), str)}
        plugins = os.path.join(lbiza, "plugins")
        for name in sorted(os.listdir(plugins)):
            folder = os.path.join(plugins, name)
            if os.path.isfile(os.path.join(folder, ".claude-plugin", "plugin.json")):
                self.assertIn(os.path.normcase(os.path.normpath(folder)), listed, name)

    def test_p4_phis_readme_gives_the_commands_that_install_from_the_repository(self):
        """p4-phi's README gives the line that adds the marketplace by the repository's name and one install line
        for each plugin of the catalog, and does not add it by a folder's path: `lbiza/` holds no catalog, and an
        install from GitHub is a copy in Claude Code's cache. The repository's README gives no command: it names
        the wiki's Install page, which holds them, and `lbiza/` holds no README of its own, since what one said is
        on the wiki's pages."""
        lbiza = os.path.dirname(os.path.dirname(ROOT))
        repo = os.path.dirname(lbiza)
        with open(os.path.join(repo, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        self.assertFalse(os.path.exists(os.path.join(lbiza, "README.md")))
        readme = os.path.join(ROOT, "README.md")
        with open(readme, encoding="utf-8") as f:
            lines = [line.strip() for line in f]
        self.assertIn("claude plugin marketplace add ezexe/p4", lines, readme)
        for entry in market["plugins"]:
            self.assertIn(f"claude plugin install {entry['name']}@{market['name']}", lines, readme)
        self.assertEqual([line for line in lines if line.startswith("claude plugin marketplace add ")],
                         ["claude plugin marketplace add ezexe/p4"], readme)


class CheckRunner(unittest.TestCase):
    """recall-hook.sh as a runner of `hook.py lookup-check`, against a stand-in python that only says it ran and with
    what. The script holds no gate: the plugin's hooks module tells which calls python has a check for, and
    hooks/register.test.ts holds the tests of that."""

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

    def test_the_runner_starts_hook_py_for_whatever_call_it_is_handed(self):
        """A message to another session, which hook.py hands to phi.py's go-guard, and a read alike: the script
        tests nothing of the call."""
        for tool, tool_input in (("SendMessage", {"to": "local_x", "message": "go ahead"}),
                                 ("mcp__ccd_session_mgmt__send_message", {"session_id": "local_x", "message": "go"}),
                                 ("Read", {"file_path": "a.py"}), ("Bash", {"command": "ls"})):
            out = self.check(tool, tool_input)
            self.assertTrue(out.startswith("RAN ") and out.endswith("scripts/hook.py lookup-check"), (tool, out))
        with open(RECALL, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("lookup-check", text.split("set -u", 1)[1], "the script tests nothing of a check's call")
        self.assertNotIn("EnterWorktree", text)

    def test_no_pretooluse_entry_runs_for_every_tool(self):
        """hooks.json starts no shell before a tool call but the Agent call's: the check before any other call is
        the hooks module's, at `tool.check`."""
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
            entries = json.load(f)["hooks"]["PreToolUse"]
        self.assertEqual([e.get("matcher") for e in entries], ["Agent"])
        self.assertNotIn("lookup-check", json.dumps(entries))

    def test_entering_a_worktree_has_no_check(self):
        """hook.PHI_CHECK routed EnterWorktree to phi.py's branch guard, which has answered nothing for the tool since
        each session that writes has a worktree of its own. So the entry is gone, and the hooks module lists no such
        tool either."""
        sys.path.insert(0, SCRIPTS)
        try:
            import hook
        finally:
            sys.path.remove(SCRIPTS)
        self.assertNotIn("EnterWorktree", hook.PHI_CHECK)
        with open(os.path.join(ROOT, "hooks", "register.ts"), encoding="utf-8") as f:
            self.assertNotIn("EnterWorktree", f.read())


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


class Module(unittest.TestCase):
    """The hooks module, by https://code.claude.com/docs/en/plugins/mods/reference.md, "Files": hooks.json holds
    "`modules`: an array with one path, relative to this file, to the hooks module" and "Can also hold settings hooks
    under `hooks`", and the module "Exports `register(on, options)`"."""

    MODULE = os.path.join(SRC, "register.ts")

    def text(self):
        with open(self.MODULE, encoding="utf-8") as f:
            return f.read()

    def manifest(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_hooks_json_names_the_module_beside_the_command_hooks_and_it_exists(self):
        with open(HOOKS_JSON, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(d.get("modules"), ["./register.ts"], "one path, relative to hooks.json")
        self.assertTrue(d.get("hooks"), "the command hooks stay beside it")
        self.assertTrue(os.path.isfile(self.MODULE))
        self.assertRegex(self.text(), r"(?m)^export const register: Register = ")
        self.assertTrue(os.path.isfile(os.path.join(SRC, "register.test.ts")), "its tests, for `claude plugin test`")

    def test_the_module_names_no_path_of_one_machine(self):
        """It reads the python the runners proved from the plugin's data folder or the plugin's own folder, as
        find-python.sh keeps it, and finds both through the mod API."""
        text = self.text()
        self.assertNotRegex(text, r"(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])\w|/Users/|/home/|AppData")
        self.assertIn("$.plugin.root", text)
        self.assertIn("/.python", text)
        for name in ("CLAUDE_PLUGIN_DATA", "CLAUDE_CODE_PLUGIN_CACHE_DIR", "CLAUDE_CONFIG_DIR"):
            self.assertIn(f"$.env.get('{name}')", text)

    def test_the_manifest_names_the_contract_of_the_panes_pages(self):
        """A mod "that keeps values in `$.state`" ships a types contract, named in plugin.json as `types`. This module
        keeps one value, the pages its pane draws, and the contract declares it under the plugin's name."""
        self.assertEqual(self.manifest().get("types"), "./types/index.d.ts")
        with open(os.path.join(ROOT, "types", "index.d.ts"), encoding="utf-8") as f:
            contract = f.read()
        self.assertIn("declare module 'claude-code'", contract)
        self.assertIn("interface PluginState", contract)
        self.assertIn(f"'{self.manifest()['name']}': {{ pages: Shaped<PhiPage[]>; tree: Shaped<PhiNode[]> }}", contract)
        self.assertNotRegex(contract, r"(?m)^\s*(import|/// <reference)", "a contract holds no import or reference")
        self.assertEqual(re.findall(r"\{ plugin: '([^']+)', key: '([^']+)' \}", self.text()),
                         [("p4-phi", "pages"), ("p4-phi", "tree")])

    def test_the_panes_pages_are_the_files_python_writes(self):
        """The module holds the three pages' file names as literals, since it reads them with no python: the board
        controls.board writes, the ledger of requests asks.render writes and the ledger puppeteer.refresh writes, each
        in the session's own folder. The pane opens by its command alone, and a drawing writes nothing."""
        sys.path.insert(0, SCRIPTS)
        try:
            import phi                      # it hands controls the session folder, as a hook's run does
            import asks
            import controls
            import puppeteer
        finally:
            sys.path.remove(SCRIPTS)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as home:
            folder = phi.session_dir(home, "s1").replace("\\", "/")
            pages = [controls.board_path(home, "s1"), asks.page_path(home, "s1"), puppeteer.ledger_path(home, "s1")]
            self.assertEqual([os.path.dirname(page) for page in pages], [folder] * 3)
            names = [os.path.basename(page) for page in pages]
        text = self.text()
        self.assertEqual(re.findall(r"file: '([^']+)'", text), names)
        self.assertEqual(text.count("$.ui.open("), 1, "the command's own open, and none at a session's start")
        self.assertIn("on('command.run', { command: 'phi-pane' }", text)
        self.assertIn("name: 'phi-pane'", text)
        # the pane's Progress view: the tree's atom, the command that writes it, and the timer over its files
        for word in ("atom({ plugin: 'p4-phi', key: 'tree' } as const", "ask($, ['progress'], PROGRESS_MS)",
                     "$.clock.every(PANE_MS", "e.tool_name === STEP_TOOL"):
            self.assertIn(word, text, word)
        self.assertNotIn("$.fs.stat(", text, "a file's time is read from its folder's list, which the list holds")
        self.assertTrue(os.path.isfile(os.path.join(SCRIPTS, "progress.py")))
        render = text.split("on('ui.render'", 1)[1].split("on('tool.check'", 1)[0]
        for write in ("update(", "$.state.set", "$.fs.write", "$.ui.open"):
            self.assertNotIn(write, render, "a render hook never writes")

    def test_the_manifest_names_no_engines_range(self):
        """The manifest reference says of `engines`: "Requires Claude Code v2.1.323 or later. To keep the plugin
        working on v2.0.15 through v2.1.75, omit `engines`. Those versions reject the manifest with an `Unrecognized key` error when it
        has the field", https://code.claude.com/docs/en/plugins/manifest-reference.md. The module's calls are in
        every Claude Code that reads the field, so a range would turn nothing off and would cost those versions the
        whole plugin."""
        self.assertNotIn("engines", self.manifest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
