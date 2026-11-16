#!/usr/bin/env python3
"""test_skillex.py: p4-skillex's watcher, the skills it writes into the store, the search that follows, and the copy
that offers a store skill to every session of the project.

    python -I -X utf8 lbiza/plugins/p4-skillex/hooks/test_skillex.py
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import skillex  # noqa: E402

CHECK = '''"""Show that a words commit leaves each Python file's syntax tree unchanged.

Usage: python {name}.py <old file> <new file>
"""
import ast
import sys


class Normalize(ast.NodeTransformer):
    def visit_Constant(self, node):
        if isinstance(node.value, (str, bytes)):
            return ast.copy_location(ast.Constant(value=""), node)
        return node

    def visit_JoinedStr(self, node):
        values = [v for v in node.values if isinstance(v, ast.FormattedValue)]
        return ast.copy_location(ast.JoinedStr(values=values), node)


def strip_docstrings(tree):
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            if isinstance(getattr(body[0], "value", None), ast.Constant):
                node.body = body[1:] or [ast.Pass()]
    return tree


def dump_of(path):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    return ast.dump(Normalize().visit(strip_docstrings(tree)))


def compare(old_path, new_path, {extra}):
    same = dump_of(old_path) == dump_of(new_path)
    print("unchanged" if same else "changed")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(compare(sys.argv[1], sys.argv[2]))
'''

OTHERS = [
    '''import csv, statistics
def summarize_timings(rows):
    durations = [float(row["seconds"]) for row in rows]
    return statistics.mean(durations), statistics.median(durations), max(durations)
def load_rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\\t"))
mean_value, median_value, worst = summarize_timings(load_rows("timings.tsv"))
print(mean_value, median_value, worst)
''',
    '''import json, urllib.request
def fetch_issue(owner, repository, number):
    url = f"https://api.github.com/repos/{owner}/{repository}/issues/{number}"
    with urllib.request.urlopen(url) as response:
        payload = json.load(response)
    return payload["title"], payload["state"], payload["labels"]
title_text, state_value, label_list = fetch_issue("someone", "something", 1)
print(title_text, state_value, len(label_list))
''',
    '''#!/bin/sh
# Render every page of the site with pandoc and count the broken links.
for page in pages/*.md; do
  pandoc --standalone --from markdown --to html5 "$page" -o "build/$(basename "$page" .md).html"
done
grep -rho 'href="[^"]*"' build | sort | uniq -c | sort -rn | head -n 20
linkcheck --recursive --timeout 10 build/index.html > broken-links.txt
wc -l broken-links.txt
''',
]

BRIEF = "# A brief\n\nThis brief is handed from a session to the one it starts, with its words of instruction, " \
        "its file set, its levels, its proof and its report, and every child keeps a copy of it.\n"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Env:
    """Sets environment variables for one test and restores them."""

    def __init__(self, **values):
        self.values = values
        self.old = {}

    def __enter__(self):
        for k, v in self.values.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Store(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="p4-skillex-")
        self.p4 = os.path.join(self.root, ".claude", "p4")
        self.tmp = os.path.join(self.p4, "temportal", "tmp")
        os.makedirs(self.tmp)
        self.found = os.path.join(self.root, "found")
        put(os.path.join(self.found, "skills", "syntax-tree-check", "SKILL.md"),
            "---\nname: syntax-tree-check\ndescription: Checks that a words commit leaves the Python syntax tree "
            "unchanged, docstrings removed and strings blanked.\n---\n\nRun it.\n")
        put(os.path.join(self.found, "skills", "deploy-site", "SKILL.md"),
            "---\nname: deploy-site\ndescription: Deploys the static site to the hosting bucket and purges the CDN.\n"
            "---\n\nRun it.\n")
        self.env = Env(P4_SKILLEX_SEARCH_ROOTS=self.found)
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()
        shutil.rmtree(self.root, ignore_errors=True)

    def script(self, session, rel, name, extra):
        return put(os.path.join(self.tmp, session, rel), CHECK.format(name=name, extra=extra))

    def write(self, path):
        return skillex.cmd_write(self.p4, {"session_id": "x", "tool_input": {"file_path": path}})

    def skills(self):
        return skillex.store_skills(self.p4)


class Watcher(Store):
    def test_a_script_written_in_a_third_session_becomes_a_skill(self):
        self.script("s1", "astcheck.py", "astcheck", "verbose=False")
        self.script("s2", "tools/wordcheck.py", "wordcheck", "quiet=True")
        newest = self.script("s3", "astcheck.py", "astcheck", "show_diff=False")
        out = self.write(newest)
        self.assertEqual(self.skills(), ["astcheck"])
        d = os.path.join(self.p4, "skillex", "astcheck")
        text = read(os.path.join(d, "SKILL.md"))
        self.assertTrue(text.startswith("---\nname: astcheck\ndescription: \"Show that a words commit leaves"), text)
        self.assertIn("${CLAUDE_SKILL_DIR}/scripts/astcheck.py", text)
        self.assertEqual(read(os.path.join(d, "scripts", "astcheck.py")), read(newest))
        self.assertEqual(sorted(read(os.path.join(d, "sources.txt")).split()),
                         ["tmp/s1/astcheck.py", "tmp/s2/tools/wordcheck.py", "tmp/s3/astcheck.py"])
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("wrote the skill `astcheck`", ctx)
        self.assertIn("`syntax-tree-check`", ctx)

    def test_scratch_that_holds_no_skill_writes_nothing(self):
        for i, s in enumerate(("s1", "s2", "s3")):
            put(os.path.join(self.tmp, s, "brief.md"), BRIEF)                     # a brief handed down, not work
            put(os.path.join(self.tmp, s, f"work{i}.py"), OTHERS[i])               # three unrelated scripts
            snap = os.path.join(self.tmp, s, "tree-451291b")                       # a repository's export
            put(os.path.join(snap, "README.md"), "# repo\n")
            put(os.path.join(snap, "astcheck.py"), CHECK.format(name="astcheck", extra="snap=1"))
        self.script("s1", "astcheck.py", "astcheck", "only_here=1")               # written in one session alone
        written = [os.path.join(self.tmp, s, f) for s, f in (("s3", "brief.md"), ("s3", "work2.py"),
                                                            ("s3", "tree-451291b/astcheck.py"), ("s1", "astcheck.py"))]
        for p in written:
            self.assertIsNone(self.write(p), p)
        self.assertEqual(self.skills(), [])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".claude", "skills")))

    def test_two_sessions_are_not_yet_brewing(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.assertIsNone(self.write(self.script("s2", "astcheck.py", "astcheck", "b=2")))
        self.assertEqual(self.skills(), [])

    def test_a_script_holding_a_secret_brews_no_skill(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        for secret in ('API_KEY = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"',
                       'headers = {"token": "f00dfeedcafe1234beef"}',
                       "-----BEGIN OPENSSH PRIVATE KEY-----"):
            p = self.script("s3", "astcheck.py", "astcheck", "c=3")
            put(p, read(p) + secret + "\n")
            self.assertIsNone(self.write(p), secret)
        self.assertEqual(self.skills(), [])
        self.assertFalse(skillex.holds_secret(self.script("s3", "astcheck.py", "astcheck", 'tokens=None, mode="fast"')))

    def test_a_file_outside_temportal_is_never_looked_at(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        outside = put(os.path.join(self.root, "src", "astcheck.py"), CHECK.format(name="astcheck", extra="c=3"))
        self.assertIsNone(self.write(outside))
        self.assertEqual(self.skills(), [])

    def test_the_search_runs_only_after_the_skill_exists_and_only_once(self):
        calls = []
        real_search = skillex.search_similar

        def spy(p4, skill_dir):
            calls.append(os.path.isfile(os.path.join(skill_dir, "SKILL.md")))
            return real_search(p4, skill_dir)

        skillex.search_similar = spy
        try:
            put(os.path.join(self.tmp, "s1", "work0.py"), OTHERS[0])
            self.write(put(os.path.join(self.tmp, "s2", "work0.py"), OTHERS[0] + "extra_name = 1\n"))
            self.assertEqual(calls, [], "no skill, so no search")
            self.script("s1", "astcheck.py", "astcheck", "a=1")
            self.script("s2", "astcheck.py", "astcheck", "b=2")
            self.write(self.script("s3", "astcheck.py", "astcheck", "c=3"))
            self.assertEqual(calls, [True], "one search, with SKILL.md already on disk")
            self.write(self.script("s4", "astcheck.py", "astcheck", "d=4"))
            self.assertEqual(calls, [True], "a refresh of the same skill searches nothing")
        finally:
            skillex.search_similar = real_search
        self.assertEqual(self.skills(), ["astcheck"])
        d = os.path.join(self.p4, "skillex", "astcheck")
        self.assertIn("tmp/s4/astcheck.py", read(os.path.join(d, "sources.txt")))
        similar = json.loads(read(os.path.join(d, "similar.json")))
        self.assertEqual([m["name"] for m in similar], ["syntax-tree-check"])
        self.assertEqual(similar[0]["path"], "found/skills/syntax-tree-check/SKILL.md", "a path inside the project")
        other = "Z:/elsewhere/x" if os.name == "nt" else "/elsewhere/x"
        self.assertIsNone(skillex.shown(other, self.p4), "no absolute path outside the project and the home folder")
        text = read(os.path.join(d, "SKILL.md"))
        self.assertIn("## Similar existing skills", text, "the refresh keeps the link")
        self.assertNotIn("deploy-site", text)

    def test_a_refresh_keeps_what_was_written_by_hand(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        self.write(self.script("s3", "astcheck.py", "astcheck", "c=3"))
        d = os.path.join(self.p4, "skillex", "astcheck")
        md = os.path.join(d, "SKILL.md")
        put(md, read(md).replace("# astcheck\n", "# astcheck\n\nRun it before every words commit.\n"))
        os.remove(os.path.join(self.tmp, "s1", "astcheck.py"))            # an idle tmp was cleared
        newest = self.script("s4", "tools/words_check.py", "words_check", "d=4")
        self.write(newest)
        text = read(md)
        self.assertIn("Run it before every words commit.", text)
        self.assertIn("- `tmp/s1/astcheck.py`", text, "a cleared source stays recorded")
        self.assertIn("- `tmp/s4/tools/words_check.py`", text)
        self.assertEqual(os.listdir(os.path.join(d, "scripts")), ["astcheck.py"])
        self.assertEqual(read(os.path.join(d, "scripts", "astcheck.py")), read(newest))
        self.assertEqual(read(os.path.join(self.root, ".claude", "skills", "astcheck", "SKILL.md")), text)

    def started_a_minute_ago(self, sid):
        skillex.cmd_start(self.p4, {"session_id": sid})
        st = skillex.read_session(self.p4, sid)
        st["since"] -= 60
        skillex.write_session(self.p4, sid, st)

    def test_a_script_written_by_a_shell_command_is_seen_at_stop(self):
        self.started_a_minute_ago("s3")
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        self.script("s3", "check.py", "check", "c=3")         # no Write call: a heredoc, say
        out = skillex.cmd_stop(self.p4, {"session_id": "s3"})
        self.assertEqual(self.skills(), ["astcheck"])
        self.assertIn("`astcheck`", out["systemMessage"])
        self.assertIsNone(skillex.cmd_stop(self.p4, {"session_id": "s3"}), "nothing changed since the last look")

    def test_stop_skips_what_the_write_hook_saw_and_keeps_the_newest_version(self):
        self.started_a_minute_ago("s3")
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        out = skillex.cmd_write(self.p4, {"session_id": "s3", "tool_input": {
            "file_path": self.script("s3", "astcheck.py", "astcheck", "c=3")}})
        self.assertIn("wrote the skill", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(skillex.cmd_stop(self.p4, {"session_id": "s3"}), "the Write hook already saw it")
        self.started_a_minute_ago("s4")
        older = self.script("s4", "zz_old.py", "zz_old", "older=1")
        newest = self.script("s4", "aa_new.py", "aa_new", "newest=1")
        os.utime(older, (os.path.getatime(older), os.path.getmtime(newest) - 5))
        skillex.cmd_stop(self.p4, {"session_id": "s4"})
        d = os.path.join(self.p4, "skillex", "astcheck", "scripts", "astcheck.py")
        self.assertEqual(read(d), read(newest), "the newest version is the one kept, whatever the folder's order")

    def test_a_stop_with_no_recorded_start_only_records_one(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        self.script("s3", "astcheck.py", "astcheck", "c=3")
        self.assertIsNone(skillex.cmd_stop(self.p4, {"session_id": "s3"}))
        self.assertEqual(self.skills(), [])
        self.assertIsNotNone(skillex.read_session(self.p4, "s3"))
        self.assertEqual(read(os.path.join(self.p4, "skillex", ".state", ".gitignore")), "*\n")

    def test_a_chain_of_links_brews_though_the_ends_do_not_match(self):
        def chained(session, first, last):                # identifiers ident_<first> to ident_<last - 1>
            body = chr(10).join(f"ident_{n:02d} = {n}" for n in range(first, last))
            return put(os.path.join(self.tmp, session, "chain.py"), body + chr(10))

        a, b, c = chained("s1", 1, 21), chained("s2", 6, 26), chained("s3", 11, 31)
        ids = {p: skillex.identifiers(p) for p in (a, b, c)}
        self.assertGreaterEqual(skillex.jaccard(ids[a], ids[b]), skillex.SIMILAR)
        self.assertGreaterEqual(skillex.jaccard(ids[b], ids[c]), skillex.SIMILAR)
        self.assertLess(skillex.jaccard(ids[a], ids[c]), skillex.SIMILAR, "the fixture must not link a and c")
        self.write(c)
        self.assertEqual(len(self.skills()), 1)

    def test_a_script_two_folders_down_is_never_compared(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        self.assertIsNone(self.write(self.script("s3", "deep/er/astcheck.py", "astcheck", "c=3")))
        self.assertEqual(self.skills(), [])

    def test_a_session_folder_with_a_readme_of_its_own_is_still_scratch(self):
        put(os.path.join(self.tmp, "s3", "README.md"), "# what this session did\n")
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        self.write(self.script("s3", "astcheck.py", "astcheck", "c=3"))
        self.assertEqual(self.skills(), ["astcheck"])

    def test_a_name_the_project_own_skill_holds_is_avoided(self):
        own = put(os.path.join(self.root, ".claude", "skills", "astcheck", "SKILL.md"), "---\nname: astcheck\n---\nmine\n")
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        out = self.write(self.script("s3", "astcheck.py", "astcheck", "c=3"))
        self.assertEqual(self.skills(), ["astcheck-2"])
        self.assertIn(".claude/skills/astcheck-2/", out["hookSpecificOutput"]["additionalContext"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".claude", "skills", "astcheck-2", "SKILL.md")))
        self.assertEqual(read(own), "---\nname: astcheck\n---\nmine\n")
        put(os.path.join(self.p4, "skillex", "x" * 64, "SKILL.md"), "---\nname: long\n---\n")
        self.assertEqual(len(skillex.free_name(self.p4, "x" * 64)), 64)

    def test_the_search_stops_at_its_deadline(self):
        old = skillex.SEARCH_DEADLINE_S
        skillex.SEARCH_DEADLINE_S = 0.0
        try:
            self.script("s1", "astcheck.py", "astcheck", "a=1")
            self.script("s2", "astcheck.py", "astcheck", "b=2")
            self.write(self.script("s3", "astcheck.py", "astcheck", "c=3"))
        finally:
            skillex.SEARCH_DEADLINE_S = old
        d = os.path.join(self.p4, "skillex", "astcheck")
        self.assertEqual(json.loads(read(os.path.join(d, "similar.json"))), [])
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".claude", "skills", "astcheck", "SKILL.md")))

    def test_a_write_through_the_scratchpad_link_counts_as_its_session(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        os.makedirs(os.path.join(self.tmp, "s3"))
        link = os.path.join(self.root, "scratchpad")
        target = os.path.join(self.tmp, "s3")
        if os.name == "nt":                                  # p4-temportal links the scratchpad with a junction
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
            if r.returncode:
                self.skipTest("no junction here")
        else:
            os.symlink(target, link, target_is_directory=True)
        put(os.path.join(link, "astcheck.py"), CHECK.format(name="astcheck", extra="c=3"))
        self.write(os.path.join(link, "astcheck.py"))
        self.assertEqual(self.skills(), ["astcheck"])
        self.assertIn("tmp/s3/astcheck.py", read(os.path.join(self.p4, "skillex", "astcheck", "sources.txt")))

    def test_scan_reports_what_is_brewing_and_writes_nothing(self):
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "tools/words_check.py", "words_check", "b=2")
        self.script("s3", "astcheck.py", "astcheck", "c=3")
        put(os.path.join(self.tmp, "s3", "work1.py"), OTHERS[1])
        found = skillex.scan(self.p4)
        self.assertEqual([n for n, _ in found], ["astcheck"])
        self.assertEqual(len(found[0][1]), 3)
        self.assertFalse(os.path.exists(os.path.join(self.p4, "skillex")))


class Loading(Store):
    """A store skill reaches a session through the project's .claude/skills/, which Claude Code scans at start and
    watches during a session, with reloadSkills asking for a scan again after a SessionStart hook changed it."""

    def store_skill(self, name, body="Say what the skill does.\n"):
        return put(os.path.join(self.p4, "skillex", name, "SKILL.md"),
                   f"---\nname: {name}\ndescription: A store skill for the loading test.\n---\n\n{body}")

    def test_the_first_start_makes_the_store_and_the_skills_folder(self):
        out = skillex.cmd_start(self.p4, {"session_id": "s1"})
        self.assertTrue(os.path.isdir(os.path.join(self.p4, "skillex")))
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".claude", "skills")))
        self.assertTrue(out["hookSpecificOutput"]["reloadSkills"])
        self.assertIsNone(skillex.cmd_start(self.p4, {"session_id": "s2"}), "nothing changed: no scan asked")

    def test_a_store_skill_is_offered_through_the_project_skills_folder(self):
        src = self.store_skill("demo-brew")
        put(os.path.join(self.p4, "skillex", "demo-brew", "scripts", "demo.py"), "print('demo')\n")
        out = skillex.cmd_start(self.p4, {"session_id": "s1"})
        self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "SessionStart", "reloadSkills": True}})
        copy = os.path.join(self.root, ".claude", "skills", "demo-brew")
        self.assertEqual(read(os.path.join(copy, "SKILL.md")), read(src))
        self.assertEqual(read(os.path.join(copy, "scripts", "demo.py")), "print('demo')\n")
        self.assertTrue(os.path.isfile(os.path.join(copy, skillex.MARKER)))
        self.assertEqual(read(os.path.join(copy, ".gitignore")), "*\n", "git never tracks a copy")
        name, desc = skillex.front(read(os.path.join(copy, "SKILL.md")))
        self.assertEqual(name, os.path.basename(copy))
        self.assertRegex(name, r"^[a-z0-9-]{1,64}$")
        self.assertTrue(desc)
        self.assertIsNone(skillex.cmd_start(self.p4, {"session_id": "s2"}), "an unchanged copy asks for no scan")
        put(os.path.join(copy, "stale.txt"), "left behind\n")
        self.assertTrue(skillex.cmd_start(self.p4, {})["hookSpecificOutput"]["reloadSkills"])
        self.assertFalse(os.path.exists(os.path.join(copy, "stale.txt")), "a file the store lacks leaves the copy")

    def test_a_changed_store_skill_is_copied_again_and_a_removed_one_leaves(self):
        self.store_skill("demo-brew")
        skillex.cmd_start(self.p4, {})
        src = self.store_skill("demo-brew", "Say it differently.\n")
        self.assertTrue(skillex.cmd_start(self.p4, {})["hookSpecificOutput"]["reloadSkills"])
        copy = os.path.join(self.root, ".claude", "skills", "demo-brew")
        self.assertEqual(read(os.path.join(copy, "SKILL.md")), read(src))
        shutil.rmtree(os.path.join(self.p4, "skillex", "demo-brew"))
        skillex.cmd_start(self.p4, {})
        self.assertFalse(os.path.exists(copy))

    def test_a_copy_cut_short_keeps_its_marker(self):
        self.store_skill("demo-brew")
        put(os.path.join(self.p4, "skillex", "demo-brew", "scripts", "demo.py"), "print('demo')\n")
        skillex.cmd_start(self.p4, {})
        copy = os.path.join(self.root, ".claude", "skills", "demo-brew")
        self.store_skill("demo-brew", "Say it differently.\n")
        real_copy, calls = skillex.shutil.copyfile, []

        def fails_second(a, b):
            calls.append(b)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_copy(a, b)

        skillex.shutil.copyfile = fails_second
        try:
            with self.assertRaises(OSError):
                skillex.cmd_start(self.p4, {})
        finally:
            skillex.shutil.copyfile = real_copy
        self.assertTrue(os.path.isfile(os.path.join(copy, skillex.MARKER)), "a half copy never loses its marker")
        self.assertIn("Say what the skill does.", read(os.path.join(copy, "SKILL.md")), "the old copy stands")
        self.assertTrue(skillex.cmd_start(self.p4, {})["hookSpecificOutput"]["reloadSkills"])
        self.assertIn("Say it differently.", read(os.path.join(copy, "SKILL.md")), "the next start finishes it")
        self.assertEqual(os.listdir(os.path.join(self.p4, "skillex", ".state", "staging")), [])

    def test_a_removal_cut_short_leaves_no_unmarked_copy(self):
        self.store_skill("demo-brew")
        skillex.cmd_start(self.p4, {})
        copy = os.path.join(self.root, ".claude", "skills", "demo-brew")
        shutil.rmtree(os.path.join(self.p4, "skillex", "demo-brew"))
        real_rmtree = skillex.shutil.rmtree

        def fails_after_the_marker(path, *a, **k):
            if os.path.isfile(os.path.join(path, skillex.MARKER)):
                os.remove(os.path.join(path, skillex.MARKER))
                if not k.get("ignore_errors"):
                    raise OSError("file in use")
            return real_rmtree(path, *a, **k)

        skillex.shutil.rmtree = fails_after_the_marker
        try:
            skillex.cmd_start(self.p4, {})
        except OSError:
            pass
        finally:
            skillex.shutil.rmtree = real_rmtree
        self.assertFalse(os.path.isdir(copy) and not os.path.isfile(os.path.join(copy, skillex.MARKER)),
                         "an unmarked copy would be taken for the project's own skill for ever")

    def test_the_project_own_skill_of_the_same_name_is_never_touched(self):
        own = put(os.path.join(self.root, ".claude", "skills", "demo-brew", "SKILL.md"), "---\nname: demo-brew\n---\nmine\n")
        self.store_skill("demo-brew")
        skillex.cmd_start(self.p4, {})
        self.assertEqual(read(own), "---\nname: demo-brew\n---\nmine\n")
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(own), skillex.MARKER)))

    def test_a_brewed_skill_is_copied_as_soon_as_it_is_written(self):
        skillex.cmd_start(self.p4, {})
        self.script("s1", "astcheck.py", "astcheck", "a=1")
        self.script("s2", "astcheck.py", "astcheck", "b=2")
        self.write(self.script("s3", "astcheck.py", "astcheck", "c=3"))
        copy = os.path.join(self.root, ".claude", "skills", "astcheck")
        self.assertEqual(read(os.path.join(copy, "SKILL.md")), read(os.path.join(self.p4, "skillex", "astcheck", "SKILL.md")))
        self.assertFalse(os.path.exists(os.path.join(copy, "sources.txt")))


class Hook(unittest.TestCase):
    def run_main(self, argv, stdin):
        old = sys.argv, sys.stdin, sys.stdout
        sys.argv = ["skillex.py", *argv]
        sys.stdin = io.TextIOWrapper(io.BytesIO(stdin.encode("utf-8")), encoding="utf-8")
        sys.stdout = io.StringIO()
        try:
            code = skillex.main()
            return code, sys.stdout.getvalue()
        finally:
            sys.argv, sys.stdin, sys.stdout = old

    def test_a_broken_payload_or_an_unknown_command_exits_0_with_a_notice(self):
        root = tempfile.mkdtemp(prefix="p4-skillex-hook-")
        try:
            with Env(CLAUDE_PROJECT_DIR=root):
                self.assertEqual(self.run_main(["write"], "not json"), (0, ""))
                code, out = self.run_main(["nonsense"], "{}")
            self.assertEqual(code, 0)
            self.assertIn("unknown command 'nonsense'", out)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_the_hooks_file_wires_each_command_the_script_has(self):
        with open(os.path.join(HERE, "hooks.json"), encoding="utf-8") as f:
            wired = re.findall(r"run-hook\.sh\\?\" (\w+)", f.read())
        self.assertEqual(sorted(wired), ["start", "stop", "write"])


if __name__ == "__main__":
    unittest.main()
