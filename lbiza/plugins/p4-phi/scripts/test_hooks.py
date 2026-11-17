#!/usr/bin/env python3
"""Tests for scripts/hook.py, the p4-phi hooks that hooks/recall-hook.sh runs.

Run: python3 test_hooks.py

It needs only the standard library's unittest and no network. Each hook runs as Claude Code runs it,
`sh hooks/recall-hook.sh <name>` with the JSON payload on stdin and CLAUDE_PLUGIN_ROOT and CLAUDE_PROJECT_DIR set, on
a small git project holding the fixture store. Checked: the hooks.json events, matchers, timeouts and async flag;
each output's JSON shape against the hooks reference; silence where a hook has nothing to add; `updatedInput`
carrying every original Agent field; the row opened and completed from `last_assistant_message`; a notification
complete on arrival; usage labels, used when the served document's path appears in an Edit input and unused otherwise;
the repo labels of a turn; exit 0 and one notice on a corrupt store; the pinned block cut at 1,500 characters; the
`.git/info/exclude` line never added twice; the store's .gitignore seeded under its marker; every handler in a
project with no store.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
os.environ["P4_PHI"] = "0"          # phi.py's routed checks stay out of these tests: they touch no live store

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import p4conf  # noqa: E402
import labels as lb  # noqa: E402
import store as st  # noqa: E402
from test_store import make_store, write  # noqa: E402

ROOT = os.path.dirname(HERE)
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


def git(cwd, *args):
    subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})


def make_project(root):
    """A git project with a few tracked files and one commit, and the fixture store at .claude/p4."""
    proj = os.path.join(root, "proj")
    os.makedirs(proj)
    git(proj, "init", "-q")
    write(os.path.join(proj, "src", "narwhal_port.py"), "def open_narwhal_port():\n    return 1\n\n"
          "class NarwhalProbe:\n    pass\n")
    write(os.path.join(proj, "README.md"), "# Narwhal tools\n\nProbe the narwhal port.\n\n## Building\n\nRun make.\n")
    write(os.path.join(proj, "docs", "zebrafish.md"), "# The zebrafish plotter\n\nGolden images.\n")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "add the narwhal port probe")
    make_store(proj)
    return proj


def run_hook(name, payload, proj, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    # P4_RECALL_INJECT=1 lets every retrieval line through, since these tests check what is shown; the default is
    # checked by test_default_is_rules_and_facts. P4_RECALL_SYNC=1 makes recall-hook.sh wait for every lookup-record.
    env.update({"CLAUDE_PLUGIN_ROOT": ROOT, "CLAUDE_PROJECT_DIR": proj, "P4_RECALL_INJECT": "1", "P4_RECALL_SYNC": "1",
                **(extra_env or {})})
    r = subprocess.run(["sh", RUN, name], input=json.dumps(payload), capture_output=True, text=True, env=env,
                       timeout=60)
    return r


def transcript(path, prompt, calls, reply, cwd, sidechain=False):
    """A transcript file in Claude Code's JSON-lines shape: the prompt, one assistant message per tool call with its
    result, the reply text."""
    lines = [{"type": "user", "message": {"role": "user", "content": prompt}, "timestamp": "2026-11-01T18:00:00.000Z",
              "cwd": cwd, "isSidechain": sidechain, "uuid": "u0", **({} if sidechain else {"origin": {"kind": "human"}})}]
    for k, (name, inp, result) in enumerate(calls):
        lines.append({"type": "assistant", "isSidechain": sidechain, "message": {
            "id": f"m{k}", "content": [{"type": "tool_use", "id": f"t{k}", "name": name, "input": inp}],
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 1000 * (k + 1)}}})
        lines.append({"type": "user", "isSidechain": sidechain, "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{k}", "content": result}]}})
    lines.append({"type": "assistant", "isSidechain": sidechain, "message": {"id": "mz", "content": [
        {"type": "text", "text": reply}], "usage": {"input_tokens": 50}}})
    write(path, "\n".join(json.dumps(l) for l in lines) + "\n")
    return path


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
        self.assertEqual(set(h), {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop",
                                  "SubagentStop"})
        self.assertEqual(h["SessionStart"][0]["matcher"], "startup|resume|clear|compact|fork")
        self.assertEqual(h["SessionStart"][0]["hooks"][0]["timeout"], 15)
        self.assertEqual(h["UserPromptSubmit"][0]["hooks"][0]["timeout"], 10)
        self.assertEqual(h["PreToolUse"][0]["matcher"], "Agent")
        self.assertEqual(h["PreToolUse"][0]["hooks"][0]["timeout"], 10)
        stop = h["Stop"][0]["hooks"]
        self.assertEqual([x["command"].split()[-1] for x in stop], ["close", "train"])
        self.assertEqual(stop[0]["timeout"], 30)
        self.assertIs(stop[1]["async"], True)
        self.assertEqual(h["SubagentStop"][0]["matcher"], ".*")
        for ev in h.values():
            for m in ev:
                for x in m["hooks"]:
                    self.assertEqual(x["type"], "command")
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}/hooks/recall-hook.sh", x["command"])

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


class Layout(Base):
    def test_silent_and_idempotent(self):
        shutil.rmtree(self.p4)
        r = run_hook("layout", {"hook_event_name": "SessionStart", "source": "startup", "cwd": self.proj}, self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", "SessionStart prints nothing when no rule is pinned")
        for sub in ("store", "models", ".git"):
            self.assertTrue(os.path.exists(p4conf.sub(self.p4, sub)), sub)
        self.assertTrue(os.path.exists(os.path.join(self.p4, ".gitignore")))
        self.assertTrue(os.path.exists(p4conf.sub(self.p4, "models", "index.json")))
        self.assertTrue(os.path.exists(p4conf.sub(self.p4, "models", "repo.json")), "the repo indexed")
        run_hook("layout", {"source": "resume", "cwd": self.proj}, self.proj)
        with open(os.path.join(self.proj, ".git", "info", "exclude"), encoding="utf-8") as f:
            self.assertEqual(f.read().count(".claude/p4/"), 1, "the exclude line added once")
        status = subprocess.run(["git", "-C", self.proj, "status", "--porcelain"], capture_output=True, text=True)
        self.assertNotIn(".claude", status.stdout,
                         "the store, a git repository of its own, stays out of the project's git status")

    def test_the_sync_files_are_seeded_once_the_store_has_an_origin(self):
        """A store with no origin never syncs, so the layout hook seeds no sync workflow, script or defaults into it;
        once it has an origin, the next layout hook seeds them."""
        shutil.rmtree(self.p4)
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        self.assertFalse(os.path.exists(os.path.join(self.p4, ".github")), "no origin: nothing seeded")
        bare = os.path.join(self.tmp.name, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.p4, "remote", "add", "origin", bare], check=True, capture_output=True)
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        for f in ("p4_sync.py", "p4_defaults.json", os.path.join("workflows", "p4-sync.yml")):
            self.assertTrue(os.path.exists(os.path.join(self.p4, ".github", f)), f)

    def test_a_served_record_older_than_a_day_is_swept(self):
        """A served record is removed at the Stop or SubagentStop that reads it, and one whose session never got
        there, as a session ended by a crash, is swept by the next layout hook once it is a day old."""
        old, fresh = lb.served_path(self.p4, "turn-dead0000"), lb.served_path(self.p4, "turn-live0000")
        for p in (old, fresh):
            write(p, '{"ids": []}')
        t = time.time() - 2 * 86400
        os.utime(old, (t, t))
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        self.assertFalse(os.path.exists(old), "two days old: swept")
        self.assertTrue(os.path.exists(fresh), "fresh: a live session's record stays")

    def gitignore(self, text=None):
        gi = os.path.join(self.p4, ".gitignore")
        if text is not None:
            write(gi, text)
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        with open(gi, encoding="utf-8") as f:
            return f.read()

    def test_gitignore_missing_seeded_lines_are_appended_under_a_marker(self):
        import hook
        old = "# seeded once by p4-recall; your edits win\ntemportal/scratchpad/.out/\nphi/models/served/\nphi/models/index.json\n" \
              "phi/models/repo.json\nphi/models/*.tmp\n__pycache__/\n*.png\n*.jpg\n*.zip\n*.gz\n# mine\nbuild/\n"
        got = self.gitignore(old)
        self.assertTrue(got.startswith(old), "what was there is untouched and in its order")
        tail = got[len(old):].splitlines()
        self.assertRegex(tail[0], r"^# seeded by p4-recall \d{4}-\d{2}-\d{2}$")
        self.assertEqual(tail[1:], ["phi/models/deps.json", "phi/models/near.json", "phi/models/lookups.db*", "phi/models/view/", ".layout.lock",
                                    "phi/sessions/*/log.jsonl", "phi/sessions/*/session.md", "phi/sessions.md",
                                    "phi/rules.md", "phi/catchup.json", "phi/**/*.tmp", "phi/**/*.lock", "phi/sessions/*/.calls/", "phi/.agents/", "phi/.nudge/", "*.pyc",
                                    "phi/models/ranker.pt"])
        self.assertEqual(self.gitignore(), got, "a second run adds nothing")
        self.assertEqual(hook.seed_gitignore(os.path.join(self.p4, ".gitignore")), [])

    def test_gitignore_vlds_header_counts_as_a_marker(self):
        got = self.gitignore("# Seeded by the vlds plugin (hooks/p4-layout.sh) when the repository has no .gitignore; "
                             "ezexe's edits win.\n*.wav\nphi/models/index.json\nphi/models/repo.json\n")
        self.assertIn("\n# seeded by p4-recall ", got)
        self.assertTrue(got.endswith("phi/models/ranker.pt\n"))
        self.assertIn("temportal/scratchpad/.out/\n", got)
        self.assertNotIn("*.pt\n", got, "the anchor and the chain are tracked in LFS: no blanket *.pt")
        for line in ("phi/models/index.json", "phi/models/repo.json"):
            self.assertEqual(got.count(line + "\n"), 1, f"{line}: a line the file already holds is never appended again")

    def test_gitignore_without_marker_is_ezexes(self):
        theirs = "*.wav\nphi/models/index.json\nbuild/\n"
        self.assertEqual(self.gitignore(theirs), theirs, "a seeded line present and no marker: ezexe's edits win")
        own = "# my rules\nbuild/\n*.log\n"
        got = self.gitignore(own)
        self.assertTrue(got.startswith(own) and "# seeded by p4-recall " in got and got.endswith("phi/models/ranker.pt\n"),
                        "no seeded line at all: the whole block, under the marker")
        # ezexe deletes the marker block: nothing comes back
        cut = got[:got.index("# seeded by p4-recall")] + "phi/models/ranker.pt\n"
        self.assertEqual(self.gitignore(cut), cut)

    def test_pinned_block_cut_at_1500(self):
        rules = [[("ruling", f"pinned rule number {k} " + "x" * 120), ("status", "LIVE"), ("pinned", "yes"),
                  ("time", f"2026-10-{10 + k:02d} 10:00")] for k in range(20)]
        write(p4conf.sub(self.p4, "store", "rules.md"), st.render("rules.md", rules))
        o = self.out(run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj))
        ctx = o["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(o["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertTrue(ctx.startswith("Standing rules from ezexe:"))
        self.assertLessEqual(len(ctx), 1500)
        self.assertIn("pinned rule number 19", ctx.split("\n")[1], "newest first")


class Recall(Base):
    def test_lines_shape_and_row(self):
        text = "does the quokka harness run the zebrafish plotter golden images on every push?"
        o = self.out(run_hook("recall", {"hook_event_name": "UserPromptSubmit", "session_id": SESSION,
                                         "prompt": text, "cwd": self.proj}, self.proj))
        self.assertEqual(set(o), {"hookSpecificOutput"})
        self.assertEqual(o["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        lines = o["hookSpecificOutput"]["additionalContext"].split("\n")
        self.assertTrue(1 <= len(lines) <= 5, lines)
        for l in lines:
            self.assertTrue(l.startswith("- "), l)
        rows = st.load_file(self.p4, f"messages/{SESSION[:8]}.md")
        self.assertEqual(len(rows), 1)
        self.assertIn("quokka", rows[0].fields["fingerprint"])
        self.assertFalse(st.completed(rows[0]))
        served = lb.read_served(self.p4, f"turn-{SESSION}")
        self.assertTrue(served["ids"])
        self.assertEqual(served["task"], rows[0].id)

    def test_off_prints_nothing_but_logs_shadow(self):
        """With P4_RECALL_INJECT=0 no line reaches the model; what retrieval would have shown is logged as shadow, so
        the close hook's usage labels still learn from it. The same holds for a subagent's prompt."""
        text = "does the quokka harness run the zebrafish plotter golden images on every push?"
        r = run_hook("recall", {"hook_event_name": "UserPromptSubmit", "session_id": SESSION, "prompt": text,
                                "cwd": self.proj}, self.proj, {"P4_RECALL_INJECT": "0"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        served = lb.read_served(self.p4, f"turn-{SESSION}")
        self.assertTrue(served["ids"] and served["shadow"])
        r = run_hook("agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent", "cwd": self.proj,
                               "tool_input": {"prompt": text, "description": "d", "subagent_type": "general-purpose"}},
                     self.proj, {"P4_RECALL_INJECT": "0"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_default_is_rules_and_facts(self):
        """With no override the mode is the default, rules-facts: only rule and fact lines reach the model, and the
        rest of what retrieval found is logged."""
        import hook
        text = "does the quokka harness run the zebrafish plotter golden images on every push?"
        r = run_hook("recall", {"hook_event_name": "UserPromptSubmit", "session_id": SESSION, "prompt": text,
                                "cwd": self.proj}, self.proj, {"P4_RECALL_INJECT": ""})
        self.assertEqual(r.returncode, 0)
        shown = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"].split("\n") if r.stdout else []
        self.assertTrue(all(hook.RULES_FACTS.match(l) for l in shown), shown)
        served = lb.read_served(self.p4, f"turn-{SESSION}")
        self.assertEqual(served["shown"], len(shown))
        self.assertGreaterEqual(served["lines"], served["shown"])
        self.assertEqual(hook.inject_mode(self.p4), "rules-facts")
        self.assertEqual(hook.injected(self.p4, ["- 2026-11-01 rule: a", "- 2026-11-01 correction: b",
                                                 "- you have said \"x\" 3 times"]), ["- 2026-11-01 rule: a"])

    def test_ordinary_message_silent(self):
        for text in ("hi", "what is the weather like today"):
            r = run_hook("recall", {"session_id": SESSION, "prompt": text, "cwd": self.proj}, self.proj)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "", text)

    def test_notification_complete_on_arrival(self):
        r = run_hook("recall", {"session_id": SESSION, "prompt": "<task-notification>the quokka harness zebrafish "
                                "plotter golden images</task-notification>", "cwd": self.proj}, self.proj)
        self.assertEqual(r.stdout, "", "a notification gets no retrieval")
        self.assertIsNone(lb.read_served(self.p4, f"turn-{SESSION}"))
        rows = st.load_file(self.p4, f"messages/{SESSION[:8]}.md")
        self.assertEqual(rows[0].fields["arrival"], "notification")
        self.assertTrue(st.completed(rows[0]))

    def test_corrupt_store_exit_0_one_notice(self):
        os.makedirs(p4conf.sub(self.p4, "models"), exist_ok=True)
        with open(p4conf.sub(self.p4, "models", "index.json"), "w") as f:
            f.write('{"version": 5, "sources": [0, 0], "docs": [[')
        shutil.rmtree(p4conf.sub(self.p4, "store", "messages"))
        write(p4conf.sub(self.p4, "store", "messages"), "not a directory")   # the row cannot be written
        r = run_hook("recall", {"session_id": SESSION, "prompt": "the quokka harness zebrafish plotter",
                                "cwd": self.proj}, self.proj)
        self.assertEqual(r.returncode, 0)
        o = json.loads(r.stdout)
        self.assertEqual(list(o), ["systemMessage"], "a notice for ezexe, nothing for the model")
        self.assertEqual(o["systemMessage"].count("\n"), 0)


class Agent(Base):
    INPUT = {"prompt": "check whether the quokka harness runs the zebrafish plotter golden images on every push",
             "description": "Check the harness", "subagent_type": "Explore", "model": "haiku"}

    def test_updated_input_keeps_every_field(self):
        o = self.out(run_hook("agent", {"hook_event_name": "PreToolUse", "tool_name": "Agent",
                                        "tool_input": dict(self.INPUT), "tool_use_id": "toolu_1",
                                        "session_id": SESSION, "cwd": self.proj}, self.proj))
        hso = o["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        up = hso["updatedInput"]
        self.assertEqual(set(up), set(self.INPUT))
        for k in ("description", "subagent_type", "model"):
            self.assertEqual(up[k], self.INPUT[k])
        self.assertTrue(up["prompt"].startswith(self.INPUT["prompt"]))
        notes = up["prompt"][len(self.INPUT["prompt"]):]
        self.assertTrue(notes.startswith("\n\nNotes from this repo's memory:\n- "), notes)
        self.assertLessEqual(notes.count("\n- "), 5)
        self.assertNotIn("permissionDecision", hso, "no permission decision unless P4_AGENT_ALLOW=1")
        o2 = self.out(run_hook("agent", {"tool_name": "Agent", "tool_input": dict(self.INPUT), "cwd": self.proj},
                               self.proj, {"P4_AGENT_ALLOW": "1"}))
        self.assertEqual(o2["hookSpecificOutput"]["permissionDecision"], "allow")

    def test_unrelated_task_untouched(self):
        r = run_hook("agent", {"tool_name": "Agent", "tool_input": {"prompt": "what is the weather like today",
                                                                    "description": "x"}, "cwd": self.proj},
                     self.proj)
        self.assertEqual(r.stdout, "")


class Close(Base):
    def turn(self, prompt, calls, reply):
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        run_hook("recall", {"session_id": SESSION, "prompt": prompt, "cwd": self.proj}, self.proj)
        tp = transcript(os.path.join(self.tmp.name, "t.jsonl"), prompt, calls, reply, self.proj)
        r = run_hook("close", {"hook_event_name": "Stop", "session_id": SESSION, "transcript_path": tp,
                               "last_assistant_message": reply, "stop_hook_active": False, "cwd": self.proj},
                     self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", "Stop prints nothing")
        return lb.read_tsv(lb.mpath(self.p4, lb.TRAIN))

    def test_row_completed_from_reply(self):
        self.turn("probe the narwhal port and open it", [],
                  "Opened the narwhal port with open_narwhal_port.\n\nDetails follow.")
        rows = st.load_file(self.p4, f"messages/{SESSION[:8]}.md")
        self.assertTrue(st.completed(rows[-1]))
        self.assertEqual(rows[-1].fields["addressed"], "Opened the narwhal port with open_narwhal_port.")
        self.assertEqual(rows[-1].fields["state"], "FRESH")
        self.assertEqual(rows[-1].fields["recommended"], "", "a reply that recommends nothing leaves it empty")

    def test_row_keeps_the_recommending_sentence(self):
        self.turn("should the narwhal port stay open or be closed after each probe", [],
                  "Here is what the probe showed, in four parts.\n\nThe port stays open now. I'd keep it open and "
                  "close it only at exit, since reopening costs 40 ms. The tests pass either way.")
        rows = st.load_file(self.p4, f"messages/{SESSION[:8]}.md")
        self.assertEqual(rows[-1].fields["addressed"], "Here is what the probe showed, in four parts.")
        self.assertEqual(rows[-1].fields["recommended"],
                         "I'd keep it open and close it only at exit, since reopening costs 40 ms.")


    def test_usage_used_by_an_edit_and_repo_labels(self):
        f = os.path.join(self.proj, "src", "narwhal_port.py")
        got = self.turn("probe the narwhal port and open it", [
            ("Read", {"file_path": f}, "def open_narwhal_port()"),
            ("Read", {"file_path": os.path.join(self.proj, "docs", "zebrafish.md")}, "# The zebrafish plotter"),
            ("Grep", {"pattern": "narwhal"}, os.path.join(self.proj, "README.md")),
            ("Edit", {"file_path": f, "old_string": "return 1", "new_string": "return 2"}, "ok")],
            "Changed open_narwhal_port to return 2.")
        usage = [r for r in got if r["source"] == "usage"]
        self.assertTrue(usage, got)
        by = {r["entry"]: r for r in usage}
        if "repo:src/narwhal_port.py" in by:
            self.assertEqual(by["repo:src/narwhal_port.py"]["label"], "1", "its path is in the Edit input")
        self.assertTrue(all(r["weight"] == "0.3" for r in usage))
        repo = {r["entry"]: r for r in got if r["source"] == "repo"}
        self.assertEqual(repo["repo:src/narwhal_port.py"]["label"], "1")
        self.assertEqual(repo["repo:src/narwhal_port.py"]["weight"], "1.0")
        self.assertEqual(repo["repo:docs/zebrafish.md"]["note"], "dropped")
        self.assertEqual(repo["repo:docs/zebrafish.md"]["weight"], "0.3")
        self.assertEqual(repo["repo:README.md"]["note"], "unopened")
        self.assertEqual(repo["repo:README.md"]["weight"], "0.2")
        self.assertIn(st.load_file(self.p4, f"messages/{SESSION[:8]}.md")[-1].id,
                      lb.read_tasks(self.p4), "the task recorded")
        self.assertIsNone(lb.read_served(self.p4, f"turn-{SESSION}"), "the served log consumed")

    def test_task_kinds_first_then_new_then_short(self):
        f = os.path.join(self.proj, "src", "narwhal_port.py")
        edit = [("Edit", {"file_path": f, "old_string": "return 1", "new_string": "return 2"}, "ok")]
        self.turn("probe the narwhal port and open it", edit, "Changed open_narwhal_port to return 2.")
        row_id = st.load_file(self.p4, f"messages/{SESSION[:8]}.md")[-1].id
        self.assertEqual(lb.read_tasks(self.p4)[row_id]["kind"], "first", "ezexe's first message in the session")
        self.turn("does the quokka harness run the zebrafish plotter golden images on every push", edit,
                  "I will look later.")
        self.turn("ship it", edit, "Pushed.")
        kinds = [t["kind"] for t in lb.read_tasks(self.p4).values() if t["session"] == SESSION[:8]]
        self.assertEqual(sorted(kinds), ["first", "new", "short"])

    def test_unused_when_nothing_cites_it(self):
        got = self.turn("does the quokka harness run the zebrafish plotter golden images on every push", [],
                        "I will look later.")
        usage = [r for r in got if r["source"] == "usage"]
        self.assertTrue(usage)
        self.assertTrue(all(r["label"] == "0" for r in usage), usage)
        self.assertTrue(all(r["note"] == "unused; shown" for r in usage), "injection is on in these tests")

    def test_usage_note_says_shadow_when_nothing_was_injected(self):
        prompt = "does the quokka harness run the zebrafish plotter golden images on every push"
        run_hook("layout", {"source": "startup", "cwd": self.proj}, self.proj)
        run_hook("recall", {"session_id": SESSION, "prompt": prompt, "cwd": self.proj}, self.proj,
                 {"P4_RECALL_INJECT": "0"})
        tp = transcript(os.path.join(self.tmp.name, "t.jsonl"), prompt, [], "I will look later.", self.proj)
        r = run_hook("close", {"hook_event_name": "Stop", "session_id": SESSION, "transcript_path": tp,
                               "last_assistant_message": "I will look later.", "stop_hook_active": False,
                               "cwd": self.proj}, self.proj, {"P4_RECALL_INJECT": "0"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        usage = [x for x in lb.read_tsv(lb.mpath(self.p4, lb.TRAIN)) if x["source"] == "usage"]
        self.assertTrue(usage)
        self.assertTrue(all(x["note"] == "unused; shadow" for x in usage), usage)

    def test_train_hook_prints_nothing(self):
        r = run_hook("train", {"session_id": SESSION, "cwd": self.proj}, self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


class Judged(Base):
    """row_close judges the row it completes from its `resembles:`: ECHO, SUPERSEDED or FRESH, with `match:`."""

    def close(self, prompt, reply, when):
        import rows
        rows.row_open(self.p4, SESSION, prompt, when)
        rows.row_close(self.p4, SESSION, reply, when)
        return st.load_file(self.p4, f"messages/{SESSION[:8]}.md")[-1]

    def test_echo_supersede_fresh(self):
        first = self.close("rename the walrus branch to walrus-mac", "Renamed the walrus branch to walrus-mac.",
                           "2026-11-01 10:00")
        self.assertEqual(first.fields["state"], "FRESH")
        self.assertNotIn("match", first.fields)
        echo = self.close("rename the walrus branch to walrus-mac", "Renamed the walrus branch to walrus-mac; "
                          "nothing else changed.", "2026-11-01 10:05")
        self.assertEqual(echo.fields["resembles"], first.id)
        self.assertEqual(echo.fields["state"], "ECHO")
        self.assertEqual(echo.fields["match"], "the 2026-11-01 10:00 row, the same answer again")
        sup = self.close("rename the walrus branch to walrus-mac", "Moved it under the release branch instead "
                         "and pushed; the old name is gone.", "2026-11-01 10:09")
        self.assertEqual(sup.fields["state"], "SUPERSEDED")
        self.assertTrue(sup.fields["match"].endswith("row, answered anew"), sup.fields)
        self.assertIn(sup.fields["match"].split(" row")[0][4:], ("2026-11-01 10:00", "2026-11-01 10:05"),
                      "it names the earlier row it resembled")
        fresh = self.close("measure the axolotl latency on the second rig", "Measured: 3 ms.", "2026-11-01 10:20")
        self.assertEqual(fresh.fields["state"], "FRESH")
        self.assertNotIn("match", fresh.fields)
        text = st.read_text(p4conf.sub(self.p4, "store", "messages", f"{SESSION[:8]}.md"))
        self.assertEqual(text.count("- fingerprint:"), 4, "rows are extended in place, never rewritten")

    def test_identical_short_answer_is_an_echo(self):
        self.close("ship it", "Pushed the branch.", "2026-11-01 10:00")
        self.close("ship it", "Pushed the branch.", "2026-11-01 10:01")
        rows_ = st.load_file(self.p4, f"messages/{SESSION[:8]}.md")
        self.assertEqual([r.fields["state"] for r in rows_], ["FRESH", "ECHO"], "identical token sets, under three")


class Recommended(unittest.TestCase):
    """rows.recommended_sentence: the reply's first sentence that recommends, any paragraph, code blocks out."""

    def test_sentences(self):
        import rows
        self.assertEqual(rows.recommended_sentence("Done. Pinned CMake 4.4.\n\nYou should pin it everywhere rather "
                                                   "than keep 3.x working. Tests pass."),
                         "You should pin it everywhere rather than keep 3.x working.")
        self.assertEqual(rows.recommended_sentence("Use git worktree instead of a second clone; it shares objects."),
                         "Use git worktree instead of a second clone; it shares objects.")
        self.assertEqual(rows.recommended_sentence("Two files changed.\n\n```\nwe should never see this\n```\n\n"
                                                   "The fix is to pin the runner image."),
                         "The fix is to pin the runner image.")
        self.assertEqual(rows.recommended_sentence("I read the file. It has 40 lines. Nothing to change."), "")
        self.assertEqual(rows.recommended_sentence("Should I run the tests now?"), "",
                         "a question back is not a recommendation")
        self.assertEqual(rows.recommended_sentence(""), "")
        long = "I recommend " + "a very long clause " * 40 + "here."
        got = rows.recommended_sentence(long)
        self.assertLessEqual(len(got), rows.RECOMMENDED_CHARS)
        self.assertTrue(got.endswith("…"))


class AgentPre(unittest.TestCase):
    """A subagent's call that phi.py has news for still meets the guards and the web lookup: the news goes beside
    their answer, never in its place."""
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


class SubagentStop(Base):
    def test_usage_for_the_subagent(self):
        inp = dict(Agent.INPUT, prompt="look at the quokka harness")
        o = self.out(run_hook("agent", {"tool_name": "Agent", "tool_input": inp, "cwd": self.proj}, self.proj))
        prompt = o["hookSpecificOutput"]["updatedInput"]["prompt"]
        at = transcript(os.path.join(self.tmp.name, "agent-a1.jsonl"), prompt,
                        [("Read", {"file_path": os.path.join(self.proj, "docs", "zebrafish.md")}, "# z")],
                        "The quokka harness checks the zebrafish plotter's golden images.", self.proj,
                        sidechain=True)
        r = run_hook("subagent-stop", {"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "Explore",
                                       "agent_transcript_path": at, "session_id": SESSION,
                                       "last_assistant_message": "The quokka harness checks the zebrafish "
                                                                 "plotter's golden images.",
                                       "cwd": self.proj}, self.proj)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        got = lb.read_tsv(lb.mpath(self.p4, lb.TRAIN))
        usage = [x for x in got if x["source"] == "usage"]
        self.assertTrue(usage)
        self.assertTrue(usage[0]["task"].startswith("agent:"))
        self.assertTrue(any(x["label"] == "1" for x in usage),
                        "the reply carries two of a served document's rare terms the task did not")
        self.assertTrue(any(t["kind"] == "agent" for t in lb.read_tasks(self.p4).values()))

    def test_a_prompt_ending_in_a_newline_keeps_its_usage_labels(self):
        """The subagent-stop hook finds what the agent hook served by the prompt before the notes, with its trailing
        whitespace trimmed, so the agent hook keys it the same way."""
        inp = dict(Agent.INPUT, prompt="look at the quokka harness\n")
        o = self.out(run_hook("agent", {"tool_name": "Agent", "tool_input": inp, "cwd": self.proj}, self.proj))
        prompt = o["hookSpecificOutput"]["updatedInput"]["prompt"]
        reply = "The quokka harness checks the zebrafish plotter's golden images."
        at = transcript(os.path.join(self.tmp.name, "agent-a2.jsonl"), prompt,
                        [("Read", {"file_path": os.path.join(self.proj, "docs", "zebrafish.md")}, "# z")],
                        reply, self.proj, sidechain=True)
        run_hook("subagent-stop", {"hook_event_name": "SubagentStop", "agent_id": "a2", "agent_type": "Explore",
                                   "agent_transcript_path": at, "session_id": SESSION,
                                   "last_assistant_message": reply, "cwd": self.proj}, self.proj)
        self.assertTrue([x for x in lb.read_tsv(lb.mpath(self.p4, lb.TRAIN)) if x["source"] == "usage"],
                        "the subagent's usage labels are written")
        served = os.path.dirname(lb.served_path(self.p4, "agent-x"))
        left = [f for f in os.listdir(served) if f.startswith("agent-")] if os.path.isdir(served) else []
        self.assertEqual(left, [], "the served record is consumed")


class ZeroConfiguration(unittest.TestCase):
    """The plugin works in a project nobody set up. An empty folder with no `.claude`, no P4_* variable and no
    settings file: every handler runs clean, the delegation rule is given, a top-level session's long command is
    moved to a background task, and the store is made by the plugin's own SessionStart hook, with no step from
    ezexe."""

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
        self.assertIn("built-in, levels", start["additionalContext"])
        self.assertIn("act-don't-wait", start["additionalContext"])
        self.assertEqual(pre["updatedInput"], {**self.LONG, "run_in_background": True})
        self.assertEqual((said, plain, stop), ({}, {}, {}))
        self.assertFalse(os.path.exists(os.path.join(self.proj, ".claude")), "phi.py's own handlers write nothing")

    def test_the_first_session_start_makes_the_store_and_the_rest_follows(self):
        self.run_hook("recall-hook.sh", "layout", hook_event_name="SessionStart", source="startup")
        p4 = os.path.join(self.proj, ".claude", "p4")
        self.assertTrue(os.path.isdir(p4conf.sub(p4, "store")), "made by the plugin's own SessionStart hook")
        conf = p4conf.load(p4, write=False)["phi"]
        self.assertEqual((conf["levels"], conf["act_dont_wait"], conf["top_orchestrates"], conf["home"]),
                         (True, True, True, None), "p4.json is written with the working defaults")
        self.env["P4_PHI_WATCH"] = "0"       # only so this test leaves no watcher behind in its temporary folder
        start, said, pre, plain, stop = self.handlers()
        self.assertIn("built-in, levels", start["additionalContext"])
        self.assertEqual(pre["updatedInput"]["run_in_background"], True)
        with open(os.path.join(p4, "phi", "sessions", self.sid, "session.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["task"], "Make the exporter write its ports table")
        self.assertTrue(os.path.exists(os.path.join(p4, "phi", "sessions", self.sid, "turns.jsonl")), "the turn kept")
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "data", ".python"))
                        or os.name != "nt", "the proven interpreter is remembered in the plugin's data folder")


if __name__ == "__main__":
    unittest.main(verbosity=1)
