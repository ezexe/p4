"""Deciding tests for hooks.json: read it and count what each start source runs."""
import json
import unittest
from pathlib import Path

# the folder of the code these tests run
SRC = Path(__file__).resolve().parents[2] / "plugins" / "p4-temportal" / "hooks"
FILE = json.loads((SRC / "hooks.json").read_text(encoding="utf-8"))
HOOKS = FILE["hooks"]


def runs(event, source):
    """The commands an event runs for a matcher value such as a SessionStart source."""
    out = []
    for group in HOOKS.get(event, []):
        m = group.get("matcher", "")
        if m in ("", "*") or source in [v.strip() for v in m.replace(",", "|").split("|")]:
            out += [h["command"] for h in group["hooks"]]
    return out


def every_command():
    return [h["command"] for groups in HOOKS.values() for g in groups for h in g["hooks"]]


class SessionStartTest(unittest.TestCase):
    def test_the_memory_start_runs_once_per_context(self):
        counts = {s: sum("memory migrate" in c for c in runs("SessionStart", s))
                  for s in ("startup", "clear", "compact", "resume", "fork")}
        print("memory migrate runs per source:", counts)
        self.assertEqual(counts, {"startup": 1, "clear": 1, "compact": 1, "resume": 0, "fork": 0})


class StoreMakerTest(unittest.TestCase):
    def test_the_store_is_made_once_at_every_start_source_and_the_entry_makes_it(self):
        """The store's one maker, `store make`, runs at each of the five start sources p4-phi's layout entry runs at."""
        import os
        import shutil
        import subprocess
        import sys
        import tempfile
        counts = {s: sum("store make" in c for c in runs("SessionStart", s))
                  for s in ("startup", "resume", "clear", "compact", "fork")}
        self.assertEqual(counts, {"startup": 1, "resume": 1, "clear": 1, "compact": 1, "fork": 1})
        group = [g for g in HOOKS["SessionStart"] if any("store make" in h["command"] for h in g["hooks"])][0]
        self.assertEqual((group["matcher"], group["hooks"][0]["timeout"], group["hooks"][0]["onFailure"]),
                         ("startup|resume|clear|compact|fork", 30, "continue"))
        tmp = tempfile.mkdtemp()
        try:
            proj = os.path.join(tmp, "empty")
            os.makedirs(proj)
            subprocess.run(["git", "init", "-q"], cwd=proj, check=True, capture_output=True)
            command = group["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", SRC.parent.as_posix())
            env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
            env.update(CLAUDE_PLUGIN_ROOT=SRC.parent.as_posix(), CLAUDE_PROJECT_DIR=proj)
            r = subprocess.run(["sh", "-c", command], input=json.dumps({"source": "startup", "cwd": proj}),
                               capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(proj, ".claude", "p4", "p4.json")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NativeMemoryTest(unittest.TestCase):
    def test_no_event_moves_memory(self):
        """ezexe/p4#92: Claude Code writes the auto memory itself, so no hook mirrors a write or sweeps at Stop."""
        moves = [c for c in every_command() if "memory mirror" in c or "memory sweep" in c]
        self.assertEqual(moves, [])

    def test_a_write_or_an_edit_starts_no_hook(self):
        """ezexe/p4#118: hook runs per Write or Edit, which the mirror made one each, are none now that Claude Code
        writes the store's memory itself."""
        on_write = [g for g in HOOKS.get("PostToolUse", [])
                    if any(t in (g.get("matcher") or "*").split("|") for t in ("*", "Write", "Edit"))]
        self.assertEqual(on_write, [])


class AppScratchpadTest(unittest.TestCase):
    def test_no_event_runs_a_scratchpad_tmp_command(self):
        """ezexe/p4#131: each session's scratchpad is the app's, so no start, turn end or session end links, stages,
        commits or sweeps one."""
        tmp = [c for e in ("SessionStart", "Stop", "SessionEnd") for s in ("startup", "resume", "clear", "compact", "")
               for c in runs(e, s) if "scratchpad tmp-" in c]
        self.assertEqual(sorted(set(tmp)), [])



class ModuleTest(unittest.TestCase):
    """The hooks module runs the retention sweep, so no command hook does. By
    https://code.claude.com/docs/en/plugins/mods/reference.md, "Files", hooks/hooks.json holds "`modules`: an array
    with one path, relative to this file, to the hooks module" and "Can also hold settings hooks under `hooks`", and
    the module "Exports `register(on, options)`"."""

    def test_hooks_json_names_the_module_beside_the_command_hooks(self):
        self.assertEqual(FILE.get("modules"), ["./register.ts"], "one path, relative to hooks.json")
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^export const register: Register = ")
        self.assertTrue((SRC / "register.test.ts").is_file(), "its tests, for `claude plugin test`")

    def test_the_module_hands_the_settings_it_read_to_the_start_hooks(self):
        """The types file of the bundled skill plugin-authoring gives `$.settings.read({ source })` as "one source's
        settings as loaded" and puts the hooks modules above the command hooks in a classic event's chain. So the
        module reads the four sources at classic.SessionStart and adds them to the input under the name p4conf.py
        reads them by, and a start hook of this plugin takes them before it reads a settings file."""
        import ast
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        names = {}
        for node in ast.parse((SRC / "p4conf.py").read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("HANDED_KEY", "HANDED_SOURCES"):
                names[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertIn(f"const HANDED = '{names['HANDED_KEY']}'", text)
        listed = ", ".join(f"'{source}'" for source in names["HANDED_SOURCES"])
        self.assertIn(f"const SOURCES = [{listed}] as const", text)
        self.assertIn("on('classic.SessionStart'", text)
        self.assertIn("$.settings.read({ source })", text)
        for script in ("p4_memory.py", "scratchpad.py"):
            self.assertIn("p4conf.hand_settings(payload, p4conf.settings_file(project_root(payload)))",
                          (SRC / script).read_text(encoding="utf-8"), script)

    def test_the_module_names_the_plan_files_a_session_wrote_to_the_last_sweep(self):
        """settings-reference.md, `plansDirectory`: unset, "Claude Code uses `~/.claude/plans`". The key the keeper
        writes holds from the next session, so the module notes the plan files written in a folder named plans at
        classic.PostToolUse and hands them to `lifetime.py tick` at the session's end, which copies them."""
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        for said in ("on('classic.PostToolUse'", "'--plan'", "'--plan-edited'", "wrote.type === 'create'"):
            self.assertIn(said, text)
        script = (SRC / "lifetime.py").read_text(encoding="utf-8")
        for said in ('"--plan"', '"--plan-edited"', "def keep_plans(root, made, edited=()):", "shutil.copy2(path, kept)"):
            self.assertIn(said, script)
        self.assertNotIn("shutil.move", script.split("def keep_plans", 1)[1].split("\ndef ", 1)[0])

    def test_no_command_hook_runs_the_retention_sweep(self):
        """The module sweeps at a session's start, on its timer and at the session's end, and it runs lifetime.py with
        no `sh`. A SessionEnd command hook shares 1.5 seconds with every other one, which a plugin's `timeout` does
        not raise, by https://code.claude.com/docs/en/hooks.md, "SessionEnd input"."""
        self.assertEqual([c for c in every_command() if " lifetime " in c], [])
        self.assertNotIn("SessionEnd", HOOKS)
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        for call in ("['tick']", "['tick', '--let-go']", "on('session.start'", "on('session.end'", "$.clock.every("):
            self.assertIn(call, text)
        self.assertNotRegex(text, r"""['"]sh['"]""")

    def test_the_module_runs_the_commands_lifetime_py_takes(self):
        """`tick` and its `--let-go` are what lifetime.py's main reads, and the waits of the two files agree."""
        import sys
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        import lifetime
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        main =(SRC / "lifetime.py").read_text(encoding="utf-8")
        self.assertIn('if sub == "tick":', main)
        self.assertIn('"--let-go" in args[1:]', main)
        self.assertIn(f"const LEAST_WAIT_MS = {int(lifetime.LEAST_WAIT_S * 1000):_}", text)
        self.assertIn(f"const MOST_WAIT_MS = {int(lifetime.MOST_WAIT_S * 1000):_}", text)

    def test_the_module_hooks_every_compaction_and_starts_one_by_its_own_call_first(self):
        """The types of Claude Code 2.1.326 give `session.compact` as the event of every compaction, whose `next`
        takes the instructions and resolves to the messages the conversation reads afterwards, and
        `$.session.compact` as a plugin's own call, whose compaction leaves no command in the transcript. Seen in
        the desktop app on that build and in a scripted session on 2.1.328, that call is refused in a session a
        program started, and `/compact` run by `$.command.run` compacts there with the module's own hook hearing
        it. So the module makes its own call first and runs the command where the call is refused, with no words
        after the command, since its hook tells every summary the keep list, and the line of the two files agrees."""
        import re
        import sys
        if str(SRC) not in sys.path:
            sys.path.insert(0, str(SRC))
        import lifetime
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        hooked = re.findall(r"(?m)^  on\('([\w.]+)'", text)
        for event in ("session.compact", "turn.start", "turn.complete"):
            self.assertEqual(hooked.count(event), 1, event)
        self.assertIn("await $.session.compact({ instructions: KEEP })", text)
        self.assertIn("await $.command.run({ command: 'compact' })", text)
        self.assertNotIn("args: KEEP", text, "the keep list is no word of a command")
        self.assertLess(text.index("await $.session.compact({ instructions: KEEP })"),
                        text.index("await $.command.run({ command: 'compact' })"))
        self.assertRegex(text, rf"(?m)^const COMPACT_AT = {lifetime.COMPACT_AT}$")
        self.assertIn("$.session.usage({ breakdown: 'summary' })", text)
        self.assertIn("$.clock.after(QUIET_MS,", text)

    def test_the_list_of_written_files_is_handed_at_the_sessionstart_of_a_compaction(self):
        """context-window.md, "What survives compaction": of SessionStart hooks that match the `compact` source,
        "Claude Code runs them and adds their output to the compacted context". The module's `classic.SessionStart`
        hook hands the list as additional context where the source is `compact`, reads the list before from the
        conversation as the model is sent it, and keeps the message for a compaction no SessionStart came inside
        of and for a subagent's transcript."""
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        for said in ("if (e.source !== 'compact' || owed === undefined) return out",
                     "additionalContext: [...(out.additionalContext ?? []), text]",
                     "await $.session.messages({ as: 'api' })",
                     "messages: isTaken ? rest : [...rest, kept]"):
            self.assertIn(said, text, said)
        test = (SRC / "register.test.ts").read_text(encoding="utf-8")
        for case in ("the ledger of the main conversation is handed at the SessionStart Claude Code raises inside a "
                     "compaction, and is no message",
                     "the ledger of the compaction before is read from the conversation as the model is sent it",
                     "at a terminal's prompt the quiet minute compacts by $.session.compact with the keep list, "
                     "and no command runs",
                     "in a session a program started, a quiet minute after a turn compacts by /compact with no "
                     "words after it"):
            self.assertIn(case, test, case)

    def test_the_modules_test_holds_the_keep_list_word_for_word(self):
        import re
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        said = re.search(r"(?m)^const KEEP =\n((?:  .+\n)+)", text).group(1).rstrip()
        test = (SRC / "register.test.ts").read_text(encoding="utf-8")
        self.assertIn(said, test, "the module's test holds the list word for word")

    def test_the_memory_start_after_a_compaction_is_kept(self):
        """`session.compact` hands a hook no summary string and no way to read what the summary kept, and a hooks
        module does not load in a session started with `--safe-mode` or `--bare`. So the SessionStart command hook
        with the source `compact` stays, which runs the memory start again in the compacted context."""
        self.assertEqual(sum("memory migrate" in c for c in runs("SessionStart", "compact")), 1)

    def test_the_slash_command_runs_the_commands_lifetime_py_takes(self):
        """`/lifetime` hands lifetime.py the word typed after it, so each of the module's four is a command of
        lifetime.py's own parser, and the command is registered and answered by one literal name. By
        https://code.claude.com/docs/en/plugins/mods/api.md, "Add a command": "Register it, then handle `command.run`
        for its name." """
        import re
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        main = (SRC / "lifetime.py").read_text(encoding="utf-8")
        names = re.findall(r"\['(\w+)', \d\],", text)
        self.assertEqual(names, ["list", "set", "clear", "now"])
        for name in names:
            self.assertIn(f'sp.add_parser("{name}"', main)
        self.assertIn("name: 'lifetime',", text)
        self.assertIn("on('command.run', { command: 'lifetime' }", text)

    def test_the_tool_runs_the_same_commands_once_its_call_is_allowed(self):
        """The module registers one tool, `lifetime`, and serves it at `tool.run`, which the API types of Claude Code
        2.1.326 give as the event that fires once a call is allowed. It answers no `tool.call` before the call went
        down, where https://code.claude.com/docs/en/plugins/mods/api.md, "Add a tool", serves a tool and an answer
        skips the permission check: a `set`, a `clear` and a `now` end in deleted files. On Claude Code 2.1.330 no
        glob selects `tool.run`, so there it serves the call at `tool.call` after `next(e)`, once Claude Code
        answered that the allowed call found no hook at its run. The tool takes the four commands the slash command
        takes, and hands a path after `--`, which lifetime.py's parser reads as the end of options."""
        import re
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"on\('(tool\.[\w*]+)'", text), ["tool.*"])
        hook = text.split("on('tool.*', { tool: TOOL_ID }, async ($, e, next) => {", 1)[1].split("\n  })", 1)[0]
        self.assertEqual([line.strip() for line in hook.strip().split("\n") if line.strip()], [
            "if (next.event === 'tool.run') return called($, e)",
            "const out = await next(e)",
            "return next.event === 'tool.call' && isUnserved(out) ? called($, e) : out",
        ], "the call goes down before anything is served at tool.call")
        self.assertIn("const UNSERVED = 'registered the tool lifetime but no hook answered this call'", text)
        self.assertIn("out.isError === true || typeof out.deny === 'string'", text)
        self.assertIn("const TOOL_ID = 'mcp__p4-temportal__lifetime'", text)
        self.assertEqual(text.count("$.tool.register("), 1)
        self.assertIn("name: 'lifetime',\n  description:", text)
        self.assertIn("enum: ['list', 'set', 'clear', 'now']", text)
        self.assertEqual(re.findall(r"\['(\w+)', \d\],", text), ["list", "set", "clear", "now"])
        self.assertIn("['--', ...rest]", text)
        caught = text.split("on('tool.*'", 1)[1].split(".catch(", 1)[1].split("\n  )", 1)[0]
        self.assertIn("next.event === 'tool.run' || (next.event === 'tool.call' && next.called)", caught)
        self.assertIn("{ deny: 'p4-temportal could not run lifetime.py.' }", caught)
        test = (SRC / "register.test.ts").read_text(encoding="utf-8")
        self.assertNotIn("$.tool.run(", test, "a call enters at tool.call, as a session's call does")
        for case in ("a call the permission check refused comes back with its refusal, and lifetime.py does not run",
                     "a call that came back up as allowed and unserved runs lifetime.py once, at tool.call",
                     "where a glob reaches tool.run, as on Claude Code 2.1.326 to 2.1.328, the allowed call is served "
                     "there"):
            self.assertIn(case, test, case)

    def test_a_module_loaded_anew_inside_the_quiet_minute_takes_it_up_again(self):
        """https://code.claude.com/docs/en/plugins/mods/reference.md says of a reload that `register` runs again in
        a fresh environment and that the old environment's `after` waits end, and that `$.state` is the session's.
        So the module keeps the end of the main conversation's last turn there, under a key its contract declares,
        and a start of the module arms the timer for what is left of the minute. Seen in the desktop app on Claude
        Code 2.1.326 before this: a plugin update arrived inside the minute and no compaction followed."""
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        self.assertIn("const ENDED = { plugin: 'p4-temportal', key: 'turnEnded' } as const", text)
        start = text.split("on('session.start'", 1)[1].split("\n  })", 1)[0]
        self.assertIn("await resume($)", start)
        resume = text.split("async function resume(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("await $.state.get(ENDED)", resume)
        self.assertIn("Math.min(Math.max(left, 0), QUIET_MS)", resume)
        self.assertEqual(text.count("await mark($, 0)"), 2, "a turn that begins, and a minute that was looked at")
        manifest = json.loads((SRC.parent / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["types"], "./types/index.d.ts")
        contract = (SRC.parent / "types" / "index.d.ts").read_text(encoding="utf-8")
        self.assertIn("'p4-temportal': { turnEnded: TurnEnded }", contract)
        test = (SRC / "register.test.ts").read_text(encoding="utf-8")
        self.assertIn("a module loaded anew one second after a turn ended still compacts when the minute is over", test)

    def test_the_module_names_no_event_an_older_claude_code_lacks(self):
        """A module that names an event its Claude Code does not know is refused whole, and `tool.run` is no event on
        2.1.311 and 2.1.322. The API types say of `on`: "To span versions, ... hook a glob such as `prompt.*` and
        test `next.event`." So the module names `tool.run` in no registration, and on a build older than the first
        whose types declare the event it registers no tool, since nothing would serve one there."""
        import re
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        self.assertNotIn("on('tool.run'", text)
        self.assertIn("const RUNS_FROM = [2, 1, 326] as const", text)
        offer = text.split("async function offer(", 1)[1].split("\n}\n", 1)[0]
        self.assertLess(offer.index("await $.command.register("), offer.index("if (!(await hasRun($)))"))
        self.assertLess(offer.index("if (!(await hasRun($)))"), offer.index("await $.tool.register(TOOL)"))
        has_run = text.split("async function hasRun(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("await $.session.version()", has_run)
        self.assertEqual(has_run.count("return true"), 3, "no release read, a newer one, and a read that failed")
        # every event the module names by itself is one Claude Code 2.1.311 knows, as `claude plugin validate` of
        # that build read it
        named = set(re.findall(r"\bon\('([a-z]+\.[A-Za-z.]+)'", text))
        self.assertEqual(named, {"classic.SessionStart", "classic.PostToolUse", "session.start", "session.compact",
                                 "turn.start", "turn.complete", "command.run", "session.end"})


class FileChangedTest(unittest.TestCase):
    """The notebook's logs, build output and binaries move into its `.out/` when they appear, and at each start. By
    https://code.claude.com/docs/en/hooks.md, "FileChanged": a group with "an omitted matcher" is one "which matches
    every watched file and adds nothing to the watch list", and the watch list is seeded "with a SessionStart or
    CwdChanged hook that returns `watchPaths`"."""

    def test_a_watched_file_runs_the_notebooks_move_and_no_matcher_adds_a_file_to_watch(self):
        groups = HOOKS["FileChanged"]
        self.assertEqual([g.get("matcher") for g in groups], [None])
        self.assertEqual(sum("scratchpad notebook-changed" in c for c in runs("FileChanged", "run.log")), 1)

    def test_the_move_at_a_start_stays_and_hands_the_notebook_to_watch(self):
        for source in ("startup", "resume", "clear", "compact"):
            self.assertEqual(sum("scratchpad notebook-out" in c for c in runs("SessionStart", source)), 1, source)


class StoreWatchTest(unittest.TestCase):
    """The settings watch, the changelog watch and the keeper at a settings change run from p4-temportal's entries. By
    https://code.claude.com/docs/en/hooks.md, "ConfigChange" matches `user_settings`, `project_settings`,
    `local_settings`, `policy_settings` and `skills`; "FileChanged" runs a group with an omitted matcher for every
    watched file."""

    def command(self, event, name):
        found = [h for g in HOOKS[event] for h in g["hooks"] if h["command"].endswith(f"store {name}")]
        self.assertEqual(len(found), 1, (event, name))
        return found[0]

    def test_the_entries_name_store_settings_prompt_and_asks_on_documented_matchers(self):
        config = [g for g in HOOKS["ConfigChange"] if any(h["command"].endswith("store settings") for h in g["hooks"])]
        self.assertEqual(len(config), 1)
        self.assertTrue(set(config[0]["matcher"].split("|")) <= {"user_settings", "project_settings", "local_settings",
                                                                  "policy_settings", "skills"}, config[0]["matcher"])
        for event, name in (("ConfigChange", "settings"), ("UserPromptSubmit", "prompt"), ("FileChanged", "asks")):
            hook = self.command(event, name)
            self.assertEqual((hook["type"], hook["onFailure"]), ("command", "continue"), name)
        self.assertTrue(all("matcher" not in g for g in HOOKS["UserPromptSubmit"]), "UserPromptSubmit ignores a matcher")
        self.assertTrue(all("matcher" not in g for g in HOOKS["FileChanged"]), "no matcher adds a file to the watch")


class StoreWatchRunTest(unittest.TestCase):
    """Each entry run as Claude Code runs it: `sh -c <command>` with the plugin's root, in a made store."""

    def setUp(self):
        import os
        import shutil
        import subprocess
        import tempfile
        self.assertIsNotNone(shutil.which("sh"), "sh is not found: a command hook starts it")
        self.assertIsNotNone(shutil.which("git"), "git is not found: the store makes a repository")
        self.tmp = tempfile.mkdtemp(prefix="p4-hooks-json-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        self.config = os.path.join(self.tmp, "config")
        os.makedirs(self.config)
        self.assertEqual(subprocess.run(["git", "init", "-q", self.proj], capture_output=True).returncode, 0)
        self.p4 = os.path.join(self.proj, ".claude", "p4")
        self.local = os.path.join(self.proj, ".claude", "settings.local.json")
        self.asked = os.path.join(self.p4, "settings.local.json")

    def entry(self, event, name, payload):
        import os
        import subprocess
        command = [h for g in HOOKS[event] for h in g["hooks"] if h["command"].endswith(f"store {name}")][0]["command"]
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "P4_"))}
        env.update(CLAUDE_PLUGIN_ROOT=SRC.parent.as_posix(), CLAUDE_PROJECT_DIR=self.proj, CLAUDE_CONFIG_DIR=self.config)
        r = subprocess.run(["sh", "-c", command], input=json.dumps({"cwd": self.proj, **payload}),
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        return r.stdout.strip()

    def start(self):
        return self.entry("SessionStart", "make", {"hook_event_name": "SessionStart", "source": "startup"})

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def phi_folder(self):
        """A scripts folder laid out as the plugin p4-phi, outside the plugin cache: a checkout loaded by
        --plugin-dir, whose rule the file may ask for."""
        import os
        scripts = os.path.join(self.tmp, "p4-phi", "scripts")
        os.makedirs(scripts)
        os.makedirs(os.path.join(self.tmp, "p4-phi", ".claude-plugin"))
        with open(os.path.join(scripts, "phi.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(self.tmp, "p4-phi", ".claude-plugin", "plugin.json"), "w", encoding="utf-8") as f:
            json.dump({"name": "p4-phi"}, f)
        return scripts.replace(os.sep, "/")

    def ask(self, *rules):
        import os
        os.makedirs(self.p4, exist_ok=True)
        with open(self.asked, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"permissions": {"allow": list(rules)}}, f, indent=2)
            f.write("\n")

    def allow(self):
        import os
        return self.read(self.local)["permissions"]["allow"] if os.path.exists(self.local) else []

    def test_a_prompt_hands_the_pending_lines_once_and_the_second_prompt_nothing(self):
        import os
        self.start()
        pending = os.path.join(self.p4, "temportal", "claude-code-watch.pending.json")
        os.makedirs(os.path.dirname(pending), exist_ok=True)
        with open(pending, "w", encoding="utf-8") as f:
            json.dump({"lines": ["p4-temportal: Claude Code 2.1.401 changed `x`", "another"]}, f)
        out = json.loads(self.entry("UserPromptSubmit", "prompt", {"hook_event_name": "UserPromptSubmit",
                                                                    "prompt": "hello"}))
        self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                      "additionalContext": "p4-temportal: Claude Code 2.1.401 "
                                                                           "changed `x`\nanother"}})
        self.assertEqual(self.entry("UserPromptSubmit", "prompt", {"hook_event_name": "UserPromptSubmit",
                                                                    "prompt": "again"}), "")

    def test_a_changed_asks_file_is_copied_at_its_change_and_no_other_file_moves_the_keeper(self):
        import os
        folder = self.phi_folder()
        rule = f'Bash(python -I -X utf8 "{folder}/phi.py" *)'
        self.ask(rule)
        self.start()
        self.assertEqual(self.allow(), [rule], "the start's whole check copied the rule")
        self.ask(rule, "mcp__p4-phi__note")
        change = {"hook_event_name": "FileChanged", "event": "change"}
        self.entry("FileChanged", "asks", {**change, "file_path": os.path.join(self.p4, "p4.json")})
        self.assertEqual(self.allow(), [rule], "another file at FileChanged writes nothing")
        self.entry("FileChanged", "asks", {**change, "file_path": self.asked})
        self.assertEqual(self.allow(), [rule, "mcp__p4-phi__note"], "the file p4-phi asks in moved the keeper")

    def test_a_prompt_copies_what_the_file_asks_where_no_event_was_raised(self):
        folder = self.phi_folder()
        rule = f'Bash(python -I -X utf8 "{folder}/phi.py" *)'
        self.ask(rule)
        self.start()
        self.ask(rule, "mcp__p4-phi__done")
        self.entry("UserPromptSubmit", "prompt", {"hook_event_name": "UserPromptSubmit", "prompt": "hello"})
        self.assertEqual(self.allow(), [rule, "mcp__p4-phi__done"])

    def test_a_config_change_of_the_local_file_notes_a_key_taken_out_by_hand(self):
        import os
        import sys
        self.start()
        sys.path.insert(0, str(SRC))
        import p4conf
        written = [k for k in ("plansDirectory", "autoMemoryDirectory") if k in self.read(self.local)]
        self.assertTrue(written, "the start wrote a key of its own")
        data = self.read(self.local)
        data.pop(written[0])
        with open(self.local, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.entry("ConfigChange", "settings", {"hook_event_name": "ConfigChange", "source": "local_settings"})
        rec = p4conf.read_record(self.p4)
        self.assertIn(written[0], (rec.get("hand") or {}).get(p4conf.fwd(os.path.abspath(self.local)), []))

    def test_a_start_hands_the_asks_of_the_watch_in_its_system_message(self):
        import os
        os.makedirs(self.p4, exist_ok=True)
        with open(os.path.join(self.p4, "p4.json"), "w", encoding="utf-8") as f:
            json.dump({"claude": {"model": "opus"}}, f)
        out = json.loads(self.start())
        self.assertTrue(out["systemMessage"].startswith("p4-temportal: "), out)
        self.assertIn("model", out["systemMessage"])


class PreCompactTest(unittest.TestCase):
    """A session where the hooks module does not load is told the keep list by a command hook. By
    https://code.claude.com/docs/en/hooks.md, "PreCompact output": "When a PreCompact hook exits 0 and doesn't block,
    Claude Code uses its stdout as instructions for the compaction summary." """

    def keep(self, payload, sub="keep"):
        import subprocess
        import sys
        ran = subprocess.run([sys.executable, "-I", "-X", "utf8", str(SRC / "compact.py"), sub],
                             input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        return ran.stdout

    def module_keep(self):
        import re
        text = (SRC / "register.ts").read_text(encoding="utf-8")
        return "".join(re.findall(r"'([^']*)'", re.search(r"(?m)^const KEEP =\n((?:  .+\n)+)", text).group(1)))

    def test_every_compaction_runs_the_keep_hook_once(self):
        for trigger in ("manual", "auto"):
            self.assertEqual(sum("compact keep" in c for c in runs("PreCompact", trigger)), 1, trigger)

    def test_the_hook_prints_the_modules_keep_list_word_for_word(self):
        for told in (None, "", "Stress the open review."):
            got = self.keep({"hook_event_name": "PreCompact", "trigger": "auto", "custom_instructions": told})
            self.assertEqual(got, self.module_keep() + "\n", told)
        self.assertEqual(self.keep({}), self.module_keep() + "\n", "an input with no instructions hands the list")

    def test_the_hook_is_silent_where_the_instructions_already_hold_the_list(self):
        """The module adds the list at `session.compact`, whoever started the compaction. Seen on
        Claude Code 2.1.328, a PreCompact hook beneath the module is handed the list as `custom_instructions`, so
        this hook prints nothing there and the summary is told the list once."""
        for told in (self.module_keep(), "Stress the open review.\n\n" + self.module_keep()):
            got = self.keep({"hook_event_name": "PreCompact", "trigger": "manual", "custom_instructions": told})
            self.assertEqual(got, "", told)

    def test_an_unknown_subcommand_prints_no_instructions(self):
        self.assertEqual(self.keep({}, sub="nosuch"), "")


class NoGitBashTest(unittest.TestCase):
    def test_a_hook_that_cannot_start_never_blocks_a_call(self):
        """ezexe/p4#121: on Windows without Git Bash, Claude Code runs a shell-form hook in PowerShell, where `sh` is
        missing, and a PreToolUse hook that fails there with onFailure unset blocks the tool call, by
        https://code.claude.com/docs/en/hooks, "Failed hooks on Windows without Git Bash". Each entry sets onFailure to
        continue, so a runner that never starts lets the call go ahead, as one that starts and exits 0 does."""
        hooks = [h for groups in HOOKS.values() for g in groups for h in g["hooks"]]
        self.assertTrue(hooks)
        self.assertEqual([h["command"] for h in hooks if h.get("onFailure") != "continue"], [])


if __name__ == "__main__":
    unittest.main()
