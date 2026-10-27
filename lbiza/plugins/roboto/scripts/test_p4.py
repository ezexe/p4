#!/usr/bin/env python3
"""test_p4.py — tests for p4.py's plugin edge and its semver range reader.

Each test builds a throwaway marketplace tree under a temp directory, copies p4.py into the fixture
plugin, and runs it as a subprocess, so PLUGIN_ROOT resolves inside the fixture exactly as it does in
a real source tree or in the installed cache. The range reader and the YAML fold are unit-tested
in-process.

Run, from the roboto plugin root:  python scripts/test_p4.py   (exit 0 when every test passes)
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p4  # noqa: E402

ALL_GATES = ["prompty", "prompter", "pioneer", "puppeteer"]

RUBRIC_TABLE = """
| # | Signal | Marginal capability it adds | Builds on | Closure |
| - | ------ | --------------------------- | --------- | ------- |
| 0 | trivial | — | — | `minimal` |
| 1 | shaped | `x` | `minimal` | `standard` |
"""

SIBLING_SKILL = """---
name: disc
description: fixture discipline
disable-model-invocation: true
---

# Disc

## Stage mapping — the rules against the P4 gates

- **prompty** — read the need.
- **puppeteer (gate the commit):** rule 1.

## Appendix

- **pioneer** — outside the section, so not a mapped gate.
"""


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill_md(name, tiers, phases, depends=(), optional=()):
    return (f"---\nname: {name}\ndescription: fixture\nmetadata:\n  p4:\n    type: skill\n"
            f"    phases: [{', '.join(phases)}]\n    depends_on: [{', '.join(depends)}]\n"
            f"    optional_depends_on: [{', '.join(optional)}]\n    tiers: [{', '.join(tiers)}]\n---\n\n# {name}\n")


def build(root, deps, x_depends=(), x_optional=(), x_phases=("puppeteer",), sib_version="1.2.0",
          sib_skill=True, layout="source"):
    """A marketplace with the fixture roboto (`mister`) and one sibling (`sib`); returns the plugin root."""
    if layout == "source":
        market = root / "mk"
        plugin = market / "plugins" / "roboto"
        sib = market / "plugins" / "sib"
        write(market / ".claude-plugin" / "marketplace.json", json.dumps({"name": "mk", "plugins": [
            {"name": "mister", "source": "./plugins/roboto", "version": "0.0.2"},
            {"name": "sib", "source": "./plugins/sib", "version": sib_version}]}))
    else:
        plugin = root / "cache" / "mk" / "mister" / "0.0.2"
        sib = root / "cache" / "mk" / "sib" / sib_version
        # an older copy beside the current one, without the skill: picking it would dangle the binding
        write(root / "cache" / "mk" / "sib" / "1.0.0" / ".claude-plugin" / "plugin.json",
              json.dumps({"name": "sib", "version": "1.0.0"}))
    write(plugin / ".claude-plugin" / "plugin.json",
          json.dumps({"name": "mister", "version": "0.0.2", "dependencies": deps}))
    write(plugin / "skills" / "identity" / "SKILL.md", skill_md("identity", ["minimal", "standard"], ALL_GATES))
    write(plugin / "skills" / "rubric" / "SKILL.md",
          skill_md("rubric", ["minimal", "standard"], ALL_GATES) + RUBRIC_TABLE)
    write(plugin / "skills" / "x" / "SKILL.md", skill_md("x", ["standard"], list(x_phases), x_depends, x_optional))
    (plugin / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "p4.py", plugin / "scripts" / "p4.py")
    write(sib / ".claude-plugin" / "plugin.json", json.dumps({"name": "sib", "version": sib_version}))
    if sib_skill:
        write(sib / "skills" / "disc" / "SKILL.md", SIBLING_SKILL)
    return plugin


def run(plugin, *args):
    r = subprocess.run([sys.executable, str(plugin / "scripts" / "p4.py"), *args],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


def scenario(**kw):
    tmp = tempfile.TemporaryDirectory()
    return tmp, build(Path(tmp.name), **kw)


def expect(code, out, want_code, *needles):
    assert code == want_code, f"exit {code}, wanted {want_code}:\n{out}"
    for n in needles:
        assert n in out, f"missing {n!r} in:\n{out}"


# --- tests -----------------------------------------------------------------

def test_source_layout_valid():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": ">=1.2.0"}], x_depends=["sib:disc"])
    with tmp:
        expect(*run(plugin, "validate"), 0, "plugin dependencies: 1, bindings: 1", "VALID")
        expect(*run(plugin, "plugins"), 0, "sib >=1.2.0 -- 1.2.0 at", "(marketplace), in range",
               "x -> sib:disc (required): stage mapping prompty, puppeteer; bound at puppeteer")


def test_cache_layout_picks_highest_copy():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": ">=1.2.0"}], x_depends=["sib:disc"], layout="cache")
    with tmp:
        expect(*run(plugin, "plugins"), 0, "sib >=1.2.0 -- 1.2.0 at", "(cache), in range")
        expect(*run(plugin, "validate"), 0, "VALID")


def test_bare_name_dependency_tracks_latest():
    tmp, plugin = scenario(deps=["sib"], x_optional=["sib:disc"])
    with tmp:
        expect(*run(plugin, "plugins"), 0, "sib (latest) -- 1.2.0", "x -> sib:disc (optional)")


def test_undeclared_plugin():
    tmp, plugin = scenario(deps=[], x_depends=["sib:disc"])
    with tmp:
        expect(*run(plugin, "validate"), 1, "names plugin 'sib', which .claude-plugin/plugin.json does not declare")
        expect(*run(plugin, "check", "standard"), 1, "does not declare as a dependency")


def test_dangling_plugin_skill():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": ">=1.0.0"}], x_depends=["sib:disc"], sib_skill=False)
    with tmp:
        expect(*run(plugin, "validate"), 1, "has no skills/disc/SKILL.md (dangling)")
        expect(*run(plugin, "resolve", "standard"), 1, "dependencies_satisfied: false", "plugin: x: 'sib:disc'")


def test_out_of_range():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": ">=2.0.0"}], x_depends=["sib:disc"])
    with tmp:
        expect(*run(plugin, "validate"), 1, "the copy found is 1.2.0 (dependency-version-unsatisfied)")
        expect(*run(plugin, "plugins"), 1, "OUT OF RANGE")


def test_unreadable_range():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": "1.x"}], x_depends=["sib:disc"])
    with tmp:
        expect(*run(plugin, "validate"), 1, "is not a readable semver range")


def test_dependency_without_caller():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": ">=1.0.0"}])
    with tmp:
        expect(*run(plugin, "validate"), 1, "dependency 'sib' is referenced by no skill")


def test_missing_dependency():
    tmp, plugin = scenario(deps=[{"name": "ghost", "version": ">=1.0.0"}, {"name": "sib"}], x_depends=["sib:disc"])
    with tmp:
        expect(*run(plugin, "validate"), 1, "dependency 'ghost' is not in the marketplace entry beside this plugin (not found)")


def test_disjoint_stage_mapping():
    tmp, plugin = scenario(deps=[{"name": "sib"}], x_depends=["sib:disc"], x_phases=("prompter",))
    with tmp:
        expect(*run(plugin, "validate"), 1, "at none of the gates its stage mapping covers (prompty, puppeteer); phases: prompter")


def test_self_reference():
    tmp, plugin = scenario(deps=[], x_optional=["mister:identity"])
    with tmp:
        expect(*run(plugin, "validate"), 1, "'mister:identity' names this plugin itself")


def test_resolve_lists_bindings():
    tmp, plugin = scenario(deps=[{"name": "sib", "version": ">=1.2.0"}], x_depends=["sib:disc"])
    with tmp:
        expect(*run(plugin, "resolve", "standard"), 0, "plugin skills bound:",
               "sib:disc (required, by x) -- sib 1.2.0", "dependencies_satisfied: true")
        code, out = run(plugin, "resolve", "minimal")
        expect(code, out, 0)
        assert "plugin skills bound" not in out, out


def test_satisfies():
    cases = [
        ("0.0.38", ">=0.0.38", True), ("0.0.37", ">=0.0.38", False), ("0.0.39", "^0.0.38", False),
        ("0.0.38", "^0.0.38", True), ("2.1.5", "~2.1.0", True), ("2.2.0", "~2.1.0", False),
        ("2.9.0", "^2.0", True), ("3.0.0", "^2.0", False), ("2.1.9", "2.1", True), ("2.2.0", "2.1", False),
        ("2.1.0", "=2.1.0", True), ("2.1.1", "2.1.0", False), ("1.5.0", ">=1.0.0 <2.0.0", True),
        ("2.0.0", ">=1.0.0 <2.0.0", False), ("3.1.0", "~2.1 || >=3.0", True), ("2.0.0-beta.1", ">=2.0.0", False),
        ("1.0.0", None, True), ("1.0.0", "*", True), ("1.0.0", "1.x", None),
    ]
    for version, rng, want in cases:
        got = p4.satisfies(version, rng)
        assert got is want, f"satisfies({version!r}, {rng!r}) = {got!r}, wanted {want!r}"


def test_yaml_fold():
    assert p4._as_refs([{"vlds": "gate"}, "prompter", "sib:disc"]) == ["vlds:gate", "prompter", "sib:disc"]
    assert p4.is_plugin_ref("emission-discipline:discipline")
    assert not p4.is_plugin_ref("prompter") and not p4.is_plugin_ref("a:b:c")


def test_stage_mapping_reader():
    assert p4.stage_mapping(SIBLING_SKILL) == {"prompty", "puppeteer"}
    assert p4.stage_mapping("# no section\n- **pioneer** x\n") is None
    assert p4.stage_mapping("## Stage mapping\n\nprose only\n") == set()


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n{e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
