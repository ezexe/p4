"""The marketplace maps p4-temportal's former names to it, by the renames map Claude Code reads, and its README names
the python the tests run with."""
import json
import re
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[3]
MARKETPLACE = LBIZA / ".claude-plugin" / "marketplace.json"
README = LBIZA / "README.md"
PLUGIN = LBIZA / "plugins" / "p4-temportal" / ".claude-plugin" / "plugin.json"


class RenamesTest(unittest.TestCase):
    def setUp(self):
        self.market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.plugin = json.loads(PLUGIN.read_text(encoding="utf-8"))

    def test_former_names_map_to_p4_temportal(self):
        renames = self.market.get("renames", {})
        for old in ("p4-memory", "p4-scratchpad"):
            self.assertEqual(renames.get(old), self.plugin["name"], old)

    def test_every_chain_resolves(self):
        renames = self.market.get("renames", {})
        listed = {p["name"] for p in self.market["plugins"]}
        for start in renames:
            name, seen = start, set()
            while name in renames:
                self.assertNotIn(name, seen, f"renames cycle at {start}")
                seen.add(name)
                name = renames[name]
            self.assertTrue(name is None or name in listed, start)


class ReadmeTest(unittest.TestCase):
    def test_no_run_command_names_python3(self):
        """ezexe/p4#122: a bare python3 can be the WindowsApps alias, so each python command the README writes is
        `python -I -X utf8`, as the test files write it."""
        runs = re.findall(r"`(python[^`]*)`", README.read_text(encoding="utf-8"))
        self.assertTrue(runs)
        self.assertEqual([r for r in runs if not r.startswith("python -I -X utf8 ")], [])


if __name__ == "__main__":
    unittest.main()
