"""The marketplace maps p4-temportal's former names to it, by the renames map Claude Code reads."""
import json
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[3]
MARKETPLACE = LBIZA / ".claude-plugin" / "marketplace.json"
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


if __name__ == "__main__":
    unittest.main()
