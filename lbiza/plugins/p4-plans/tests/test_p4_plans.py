#!/usr/bin/env python3
"""Offline tests of the p4-plans plugin: settings, the evidence checker, and the skills' shape.

    python3 -I lbiza/plugins/p4-plans/tests/test_p4_plans.py
"""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "skills" / "plan-planner" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import settings  # noqa: E402


def repo(tmp, config=None):
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    if config is not None:
        (tmp / ".claude" / "p4").mkdir(parents=True, exist_ok=True)
        (tmp / ".claude" / "p4" / "p4.json").write_text(json.dumps({"plans": config}), encoding="utf-8")
    return tmp


def run(script, *args, cwd):
    return subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8")


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_defaults_without_a_config(self):
        s = settings.load(repo(self.tmp))
        self.assertIsNone(s["config"])
        self.assertEqual((s["plans_dir"], s["link_prefix"]), (".claude/plans", "../../"))
        self.assertEqual(set(settings.DEFAULTS), {"plans_dir", "archive_branch", "archive_worktree", "changelog"})

    def test_config_merges_nested_and_reports_unknown_keys(self):
        # an older p4.json still carries the settings that were retired: they are unknown keys now, printed by
        # nothing and reported once
        repo(self.tmp, {"plans_dir": ".claude/skills/plan-planner", "archive_branch": "done",
                        "role_models": {"writer": "general-purpose/opus/high"}, "owner_title": "the boss", "gates": 4})
        r = run("settings.py", "--json", cwd=self.tmp)
        s = json.loads(r.stdout)
        self.assertEqual(s["link_prefix"], "../../../")
        self.assertEqual((s["archive_branch"], s["changelog"]), ("done", "CHANGELOG.md"))
        for retired in ("role_models", "owner_title", "gates"):
            self.assertNotIn(retired, s)
        self.assertIn("unknown key(s)", r.stderr)

    def test_one_value_bare_and_a_missing_one_fails(self):
        repo(self.tmp, {"changelog": "HISTORY.md", "archive_branch": None})
        sub = self.tmp / "deep"
        sub.mkdir()
        self.assertEqual(run("settings.py", "changelog", cwd=sub).stdout.strip(), "HISTORY.md")
        self.assertEqual(run("settings.py", "archive_branch", cwd=sub).stdout.strip(), "null")
        self.assertEqual(run("settings.py", "owner_title", cwd=sub).returncode, 1)
        self.assertEqual(run("settings.py", "nope", cwd=sub).returncode, 1)


class Checker(unittest.TestCase):
    def setUp(self):
        self.tmp = repo(Path(tempfile.mkdtemp()))
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        (self.tmp / "plans").mkdir()

    def plan(self, link, fence):
        text = (f"# X_PLAN: x\n\n## 1\n\nnothing\n\n# X_PLAN: every layer in source\n\n"
                f"- 1: [src/a.py:1-2](../{link})\n\n```python\n{fence}\n```\n")
        p = self.tmp / "plans" / "X_PLAN.md"
        p.write_text(text, encoding="utf-8")
        return run("check_evidence.py", str(p), ".", cwd=self.tmp)

    def test_a_true_entry_has_no_findings(self):
        r = self.plan("src/a.py:1-2", "def f():\n    return 1")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("done: 0 finding(s)", r.stdout)

    def test_a_missing_file_and_a_drifted_fence_are_findings(self):
        self.assertIn("MISSING", self.plan("src/b.py:1-2", "def f():").stdout)
        r = self.plan("src/a.py:1-2", "def g():")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"NOFENCE|MOVED")


class Skills(unittest.TestCase):
    def test_frontmatter_and_every_named_setting_exists(self):
        names = set(settings.DEFAULTS) | {"root", "config", "link_prefix"}
        for f in ["skills/plan-planner/SKILL.md", "skills/sub-agentic/SKILL.md"]:
            text = (PLUGIN / f).read_text(encoding="utf-8")
            m = re.match(r"---\nname: ([a-z-]+)\ndescription: (.+?)\n---\n", text, re.S)
            self.assertIsNotNone(m, f)
            self.assertEqual(m.group(1), Path(f).parent.name)
            self.assertLess(len(m.group(2)), 1024, f)
        for f in ["skills/plan-planner/SKILL.md", "skills/plan-planner/flight-ops.md", "skills/sub-agentic/SKILL.md"]:
            text = (PLUGIN / f).read_text(encoding="utf-8")
            for name in re.findall(r"`([a-z_]+)(?:\.[a-z_]+)?`(?:/|,|\s|\)|\.|$)", text):
                not_settings = {"none", "complete", "todo", "subagent_type", "cross_check", "evidence_finder"}
                if name in not_settings or "_" not in name and name not in names:
                    continue
                self.assertIn(name, names, f"{f}: `{name}` is no setting")
            fences = [ln for ln in text.splitlines() if ln.lstrip().startswith("```")]
            self.assertEqual(len(fences) % 2, 0, f"{f}: fences unbalanced")

    def test_no_repository_specifics_left(self):
        for f in (PLUGIN / "skills").rglob("*.md"):
            text = f.read_text(encoding="utf-8").lower()
            for word in ("waxiom", "cef", "juce", "audioplugin", "the boss", "gates.py", "g1", "_win", "_mac"):
                self.assertNotIn(word, text, f"{f.name}: {word}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
