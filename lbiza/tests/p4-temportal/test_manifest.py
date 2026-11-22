"""The marketplace maps p4-temportal's former names to it, by the renames map Claude Code reads, and describes each
plugin in its manifest's own words. The marketplace's one catalog is at the repository's root."""
import json
import unittest
from pathlib import Path

LBIZA = Path(__file__).resolve().parents[2]
MARKETPLACE = LBIZA.parent / ".claude-plugin" / "marketplace.json"
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


class DescriptionTest(unittest.TestCase):
    def test_each_plugin_is_described_in_the_same_words_by_the_catalog_and_by_its_manifest(self):
        """https://code.claude.com/docs/en/plugins/marketplace-reference.md, "Display fields": "For a field you set
        on the entry, users see the entry's value, even when `plugin.json` sets a different one." So a listing shows
        the catalog's words whatever the manifest says, and a plugin whose two descriptions differ is described two
        ways. Each entry's description is its manifest's, word for word."""
        market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        self.assertTrue(market["plugins"])
        for entry in market["plugins"]:
            manifest = MARKETPLACE.parents[1] / entry["source"] / ".claude-plugin" / "plugin.json"
            own = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(own["description"], entry["name"])
            self.assertEqual(entry["description"], own["description"], entry["name"])


if __name__ == "__main__":
    unittest.main()
