#!/usr/bin/env python3
"""p4.py — the P4 closure resolver/validator for the roboto plugin.

This turns the otherwise-inert `metadata.p4` frontmatter into something that
actually runs. The Claude Code harness never parses `metadata.p4` (it reads only
`name`/`description`/`when_to_use` etc. and lets the model decide what to load),
so the closure/dependency model used to live purely as prose the model *might*
follow. This script makes that model executable and checkable.

It reads every `skills/<name>/SKILL.md`, derives the closures from each skill's
`metadata.p4.tiers` (nothing is stored — closures are computed), builds the
dependency + gate graph, and resolves/validates it.

Usage:
  p4.py                     Same as `validate`.
  p4.py validate            Validate every closure + the whole graph. Exit 1 on any issue.
  p4.py resolve <closure>   Resolve one closure: members, transitive deps, active gates, satisfied?
  p4.py check <closure>     Gate-check one closure: valid?, issues. Exit 1 if invalid.
  p4.py plugins             The plugins roboto sits on: each declared dependency, the copy found
                            and its version against the declared range, the plugin skills the
                            roboto skills bind, and each sibling's stage mapping. Exit 1 on any issue.
  p4.py list                List skills and a summary of their metadata.p4.

Model (derived, not stored):
  * `identity` + `rubric` are the ALWAYS-ON base: members of every closure, and
    deliberately never listed in any skill's `depends_on` (declared once in the
    roboto agent). This script flags any skill that re-lists them.
  * A closure's members = `identity` + `rubric` + every skill whose
    `metadata.p4.tiers` lists that closure.
  * `depends_on` uses three id-spaces: skill names (must resolve to a skill dir,
    and be present in the closure), P4 gate ids (prompty|prompter|pioneer|
    puppeteer), which resolve to the fixed gate graph rather than to a skill, and
    plugin-qualified skills `<plugin>:<skill>` — a skill of another plugin, named
    the way Claude Code names it — which resolve through the plugin edge below.
  * `optional_depends_on` enhances but is NOT required for closure.
  * A skill's `hooks.on_<gate>` and its `phases` are two declarations of the same
    fact. A non-empty hook on a gate absent from `phases` is an undeclared hook.

The puppeteer->prompty edge:
  `/p4-puppeteer` registers a closure with TWO writes -- a row in the `rubric`
  gate table and the closure name in each member's `tiers` -- and `/p4-prompty`
  then selects that closure by scoring the request against those same rubric
  rows. The tiers half is a graph this script derives; the rubric half was, until
  now, unvalidated prose. `reconcile_rubric` closes that loop: it parses the gate
  table out of `skills/rubric/SKILL.md` and checks it against the derived
  closures, so a row without a closure (unselectable phantom), a closure without
  a row (unreachable), a false marginal-capability claim, or a rung that drops
  what the rung below it declared all fail the gate instead of shipping.

The plugin edge:
  roboto sits on the marketplace's standalone plugins -- vlds and the discipline
  family -- declared as `dependencies` in `.claude-plugin/plugin.json`, which the
  harness installs with roboto and checks against the declared semver range when
  roboto loads, disabling roboto while a copy sits outside it. The
  disciplines ship without `metadata.p4`; each carries a prose "Stage mapping" of
  its rules onto the four P4 gates, asserted and never validated. `check_plugins`
  validates that edge from roboto's side: every `<plugin>:<skill>` reference names
  a declared dependency; every declared dependency is located (the marketplace
  entry in the source tree, else the installed cache beside this plugin) at a
  version inside its range and is referenced by some skill; the referenced skill
  exists in the copy found; and a sibling's stage mapping names P4 gates that
  share at least one gate with the phases of the roboto skill binding it.
"""

import json
import os
import re
import sys
from pathlib import Path

ALWAYS_ON = ("identity", "rubric")
GATES = ("prompty", "prompter", "pioneer", "puppeteer")
# Fixed gate chain (each gate pulls the gates before it). identity is always-on,
# so it is omitted here; this models gate prerequisites only.
GATE_CHAIN = {
    "prompty": [],
    "prompter": ["prompty"],
    "pioneer": ["prompty", "prompter"],
    "puppeteer": ["prompty", "prompter", "pioneer"],
}

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PLUGIN_ROOT / "skills"
PLUGIN_JSON = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

# A plugin-qualified skill reference, as Claude Code names a plugin's skill: `<plugin>:<skill>`.
PLUGIN_REF = re.compile(r"^([a-z0-9][a-z0-9-]*):([a-z0-9][a-z0-9-]*)$")


def is_plugin_ref(dep):
    return bool(PLUGIN_REF.match(dep))


# --- parsing -------------------------------------------------------------

def _inline_list(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [x.strip().strip('"').strip("'") for x in raw.split(",") if x.strip()]


def _as_refs(items):
    """A dependency list as strings.

    Some YAML parsers read an unquoted `vlds:gate` inside a flow list as a one-pair
    mapping; fold such an item back into the plugin reference it was written as.
    """
    out = []
    for x in items or []:
        if isinstance(x, dict) and len(x) == 1:
            k, v = next(iter(x.items()))
            out.append(f"{k}:{v}")
        else:
            out.append(str(x))
    return out


def _frontmatter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    return text[4:end] if end != -1 else None


def _parse(fm):
    """Pull name + the metadata.p4 fields we need.

    Prefers a real YAML parser; falls back to targeted regex for the inline-list
    style this repo uses uniformly, so the script needs no third-party deps.
    """
    try:
        import yaml  # optional; nicer if present
        data = yaml.safe_load(fm) or {}
        p4 = (data.get("metadata") or {}).get("p4") or {}
        hooks = p4.get("hooks") or {}
        return {
            "name": data.get("name"),
            "depends_on": _as_refs(p4.get("depends_on")),
            "optional_depends_on": _as_refs(p4.get("optional_depends_on")),
            "tiers": list(p4.get("tiers") or []),
            "phases": list(p4.get("phases") or []),
            "hooked": sorted(k[3:] for k, v in hooks.items() if k.startswith("on_") and v),
        }
    except Exception:
        def grab(pat):
            m = re.search(pat, fm, re.M)
            return _inline_list(m.group(1)) if m else []
        name_m = re.search(r"^name:\s*(.+)$", fm, re.M)
        return {
            "name": name_m.group(1).strip() if name_m else None,
            # negative lookbehind so this does not also match optional_depends_on
            "depends_on": grab(r"(?<![\w_])depends_on:\s*(\[.*?\])"),
            "optional_depends_on": grab(r"optional_depends_on:\s*(\[.*?\])"),
            "tiers": grab(r"tiers:\s*(\[.*?\])"),
            "phases": grab(r"phases:\s*(\[.*?\])"),
            "hooked": sorted(m.group(1) for m in re.finditer(r"on_(\w+):\s*\[\s*\w", fm)),
        }


def load_skills():
    if not SKILLS_DIR.is_dir():
        sys.exit(f"error: skills dir not found at {SKILLS_DIR}")
    skills = {}
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        fm = _frontmatter(f.read_text(encoding="utf-8"))
        if fm is None:
            continue
        skills[d.name] = _parse(fm)
    return skills


# --- graph helpers -------------------------------------------------------

def all_closures(skills):
    cs = set()
    for s in skills.values():
        cs.update(s["tiers"])
    return sorted(cs)


def members(skills, closure):
    m = set(ALWAYS_ON)
    for name, s in skills.items():
        if closure in s["tiers"]:
            m.add(name)
    return sorted(m)


def active_gates(skills, member_names):
    g = set()
    for n in member_names:
        for p in skills.get(n, {}).get("phases", []):
            if p in GATES:
                g.add(p)
                g.update(GATE_CHAIN[p])
    return sorted(g, key=GATES.index)


def skill_deps(deps):
    return [d for d in deps if d not in GATES and not is_plugin_ref(d)]


def gate_deps(deps):
    return [d for d in deps if d in GATES]


def gate_hookers(skills, member_names):
    """How many members hook each gate directly, by their own `phases`.

    The bare list of active gates cannot discriminate between closures: the
    always-on base declares all four phases, so every closure activates the whole
    chain. The per-gate count is the part that actually varies.
    """
    return {g: sum(1 for n in member_names if g in skills.get(n, {}).get("phases", []))
            for g in GATES}


# --- the rubric gate table (the puppeteer->prompty half) -----------------

RUBRIC_MD = SKILLS_DIR / "rubric" / "SKILL.md"


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _ticked(cell):
    """The backticked identifiers in a table cell, in order."""
    return re.findall(r"`([\w-]+)`", cell)


def load_rubric_rows(path=RUBRIC_MD):
    """Parse the rubric gate table -- the surface `prompty` selects a closure from.

    Columns, in order: #, signal, marginal capability it adds, builds on, closure.
    Returns (rows, error); `error` is set whenever the table cannot be found or no
    row parses, so the caller fails closed instead of silently checking nothing.
    """
    if not path.is_file():
        return [], f"rubric gate table: {path} not found"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        c = _cells(line)
        if len(c) < 5 or not c[0].isdigit():
            continue
        rows.append({
            "n": int(c[0]),
            "marginal": _ticked(c[2]),
            "builds_on": _ticked(c[3]),
            "closure": (_ticked(c[4]) or [None])[0],
        })
    if not rows:
        return [], f"rubric gate table: no numbered rows parsed from {path}"
    return rows, None


def reconcile_rubric(skills, rows):
    """Check the rubric gate table against the derived closure graph.

    This is the puppeteer->prompty edge: `/p4-puppeteer` writes a rubric row AND
    the members' tiers, and `/p4-prompty` selects on the row. Returns a list of
    (closure, message) pairs so a single-closure gate-check can filter.
    """
    out = []
    derived = set(all_closures(skills))
    seen = {}

    for r in rows:
        c, n = r["closure"], r["n"]
        if c is None:
            out.append((None, f"rubric row {n}: closure cell names no backticked closure"))
            continue
        if c in seen:
            out.append((c, f"rubric row {n}: closure '{c}' already selected by row {seen[c]}"))
        seen[c] = n
        if c not in derived:
            out.append((c, f"rubric row {n}: '{c}' is selectable but no skill's tiers lists it (phantom row)"))
            continue
        mem = set(members(skills, c))
        for parent in r["builds_on"]:
            if parent not in derived:
                out.append((c, f"rubric row {n}: builds on '{parent}', which is not a closure"))
                continue
            pmem = set(members(skills, parent))
            dropped = sorted(pmem - mem)
            if dropped:
                out.append((c, f"rubric row {n}: '{c}' builds on '{parent}' but drops {', '.join(dropped)}"))
            for skill in r["marginal"]:
                if skill in pmem:
                    out.append((c, f"rubric row {n}: '{skill}' is claimed as marginal but is already in '{parent}'"))
        for skill in r["marginal"]:
            if skill not in skills:
                out.append((c, f"rubric row {n}: marginal capability '{skill}' resolves to no skill"))
            elif skill not in mem:
                out.append((c, f"rubric row {n}: claims marginal '{skill}', which is not a member of '{c}'"))

    for c in sorted(derived - set(seen)):
        out.append((c, f"closure '{c}' has no rubric row -- prompty can never select it (unreachable)"))
    return out


# --- the plugin edge (roboto -> the marketplace's standalone plugins) ------

def load_manifest(path=PLUGIN_JSON):
    """This plugin's own manifest: (name, version, dependencies, error).

    Each dependency comes back as {"name", "range", "marketplace"}; `range` is None
    for a bare-name entry, which tracks whatever version the marketplace provides.
    """
    if not path.is_file():
        return None, None, [], f"plugin manifest: {path} not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return None, None, [], f"plugin manifest: {path} is not valid JSON ({e})"
    deps = []
    for entry in data.get("dependencies") or []:
        if isinstance(entry, str):
            deps.append({"name": entry, "range": None, "marketplace": None})
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            deps.append({"name": entry["name"], "range": entry.get("version"),
                         "marketplace": entry.get("marketplace")})
        else:
            return (data.get("name"), data.get("version"), deps,
                    f"plugin manifest: dependency entry {entry!r} names no plugin")
    return data.get("name"), data.get("version"), deps, None


def find_marketplace(start=PLUGIN_ROOT, levels=4):
    """The marketplace root and manifest above this plugin in a source tree, or (None, None).

    The installed cache keeps no marketplace manifest beside a plugin, so (None, None)
    there is the normal answer and the cache layout is used instead.
    """
    p = start
    for _ in range(levels):
        p = p.parent
        m = p / ".claude-plugin" / "marketplace.json"
        if m.is_file():
            try:
                return p, json.loads(m.read_text(encoding="utf-8"))
            except ValueError:
                return p, None
    return None, None


def _manifest_version(path):
    try:
        return json.loads((path / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def version_key(v):
    """Sort key for a version string: a pre-release sorts below its release, junk lowest."""
    core, _, pre = (v or "").partition("-")
    try:
        nums = tuple(int(x) for x in core.split("."))
    except ValueError:
        return ((-1,), 0, v or "")
    return (nums + (0,) * (3 - len(nums)), 0 if pre else 1, pre)


def locate_plugin(name, market=None):
    """The copy of plugin `name` that this tree would load, or None.

    In a source tree, the marketplace entry's local `source`; in the installed cache,
    the highest version directory of `<cache>/<marketplace>/<name>/` beside this plugin.
    Returns {"name", "path", "version", "layout"}; `path` is None for an entry whose
    source is not a local directory, which leaves its skills uncheckable here.
    """
    root, data = market if market is not None else find_marketplace()
    if data:
        for entry in data.get("plugins") or []:
            if entry.get("name") != name:
                continue
            src = entry.get("source")
            if isinstance(src, str):
                path = (root / src).resolve()
                return {"name": name, "path": path,
                        "version": _manifest_version(path) or entry.get("version"),
                        "layout": "marketplace"}
            return {"name": name, "path": None, "version": entry.get("version"),
                    "layout": "marketplace, non-local source"}
        return None
    base = PLUGIN_ROOT.parent.parent / name
    if base.is_dir():
        copies = [d for d in base.iterdir() if d.is_dir() and (d / ".claude-plugin" / "plugin.json").is_file()]
        if copies:
            best = max(copies, key=lambda d: version_key(_manifest_version(d) or d.name))
            return {"name": name, "path": best, "version": _manifest_version(best) or best.name,
                    "layout": "cache"}
    return None


_RANGE_TOKEN = re.compile(r"^(>=|<=|>|<|=|\^|~)?v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.-]+)?$")


def _expand(tok):
    """One npm-style range token as [(op, version)] comparators, or None when unreadable."""
    m = _RANGE_TOKEN.match(tok)
    if not m:
        return None
    op = m.group(1) or ""
    parts = [int(g) for g in m.group(2, 3, 4) if g is not None]
    pre = m.group(5) or ""
    a, b, c = (parts + [0, 0, 0])[:3]
    base = f"{a}.{b}.{c}{pre}"
    if op in (">=", ">", "<=", "<"):
        return [(op, base)]
    if op == "^":
        upper = f"{a + 1}.0.0" if a else (f"0.{b + 1}.0" if b else f"0.0.{c + 1}")
        return [(">=", base), ("<", upper)]
    if op == "~":
        upper = f"{a}.{b + 1}.0" if len(parts) >= 2 else f"{a + 1}.0.0"
        return [(">=", base), ("<", upper)]
    if len(parts) == 3:
        return [("=", base)]
    upper = f"{a}.{b + 1}.0" if len(parts) == 2 else f"{a + 1}.0.0"
    return [(">=", base), ("<", upper)]


def _holds(version, op, target):
    a, b = version_key(version), version_key(target)
    return {">=": a >= b, ">": a > b, "<=": a <= b, "<": a < b, "=": a == b}[op]


def satisfies(version, rng):
    """Whether `version` lies inside an npm-style range, or None when the range is unreadable.

    Reads comparator sets joined by `||`, each a space-separated AND of `>=`, `>`, `<=`,
    `<`, `=`, `^`, `~`, or bare (exact, or a partial version's whole span) tokens.
    """
    text = "" if rng is None else str(rng).strip()
    if text in ("", "*", "x", "latest"):
        return True
    for alt in text.split("||"):
        comps = []
        for tok in alt.split():
            c = _expand(tok)
            if c is None:
                return None
            comps.extend(c)
        if comps and all(_holds(version, op, t) for op, t in comps):
            return True
    return False


_STAGE_BULLET = re.compile(r"^\s*[-*]\s+\*\*(prompty|prompter|pioneer|puppeteer)\b")


def stage_mapping(text):
    """The gates a sibling skill's `## Stage mapping` section binds rules to, or None without one.

    A gate counts when it opens one of the section's bold bullets (`- **pioneer (...)**`).
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("## Stage mapping")), None)
    if start is None:
        return None
    gates = set()
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        m = _STAGE_BULLET.match(line)
        if m:
            gates.add(m.group(1))
    return gates


def plugin_refs(skills):
    """(skill, ref, hard) for every plugin-qualified entry in a skill's dependency lists."""
    out = []
    for n, s in sorted(skills.items()):
        out.extend((n, d, True) for d in s["depends_on"] if is_plugin_ref(d))
        out.extend((n, d, False) for d in s["optional_depends_on"] if is_plugin_ref(d))
    return out


def check_plugins(skills):
    """Validate the plugin edge. Returns (issues, report).

    `issues` is a list of (skill-or-None, message) so a closure check can keep the ones
    its members raise; `report` carries what was found, for `plugins` and `resolve`.
    """
    issues = []
    name, version, deps, err = load_manifest()
    report = {"plugin": name, "version": version, "deps": [], "refs": []}
    if err:
        issues.append((None, err))
    market = find_marketplace()
    located = {}
    for d in deps:
        if d["name"] in located:
            issues.append((None, f"dependency '{d['name']}' is declared twice"))
            continue
        loc = locate_plugin(d["name"], market)
        located[d["name"]] = loc
        ok = None
        where = "the marketplace entry" if market[1] else "the installed cache"
        if loc is None:
            issues.append((None, f"dependency '{d['name']}' is not in {where} beside this plugin (not found)"))
        elif loc["version"] is None:
            issues.append((None, f"dependency '{d['name']}': the copy found declares no version, so its range cannot be checked"))
        else:
            ok = satisfies(loc["version"], d["range"])
            if ok is None:
                issues.append((None, f"dependency '{d['name']}': range {d['range']!r} is not a readable semver range"))
            elif not ok:
                issues.append((None, f"dependency '{d['name']}' {d['range']}: the copy found is {loc['version']} (dependency-version-unsatisfied)"))
        report["deps"].append(dict(d, loc=loc, ok=ok))

    referenced = set()
    for skill, ref, hard in plugin_refs(skills):
        plugin, sk = ref.split(":", 1)
        referenced.add(plugin)
        entry = {"skill": skill, "ref": ref, "hard": hard, "mapping": None, "found": False}
        report["refs"].append(entry)
        if plugin == name:
            issues.append((skill, f"{skill}: '{ref}' names this plugin itself -- use the bare skill name"))
            continue
        if plugin not in located:
            issues.append((skill, f"{skill}: '{ref}' names plugin '{plugin}', which .claude-plugin/plugin.json does not declare as a dependency"))
            continue
        loc = located[plugin]
        if loc is None or loc["path"] is None:
            continue  # the dependency's own issue already says why nothing can be read
        md = loc["path"] / "skills" / sk / "SKILL.md"
        if not md.is_file():
            issues.append((skill, f"{skill}: '{ref}' resolves to no skill -- {plugin} {loc['version']} has no skills/{sk}/SKILL.md (dangling)"))
            continue
        entry["found"] = True
        gates = stage_mapping(md.read_text(encoding="utf-8"))
        entry["mapping"] = gates
        if gates is None:
            continue
        if not gates:
            issues.append((skill, f"{skill}: '{ref}' has a stage mapping section that names no P4 gate"))
        elif not gates & set(skills[skill]["phases"]):
            issues.append((skill, f"{skill}: binds '{ref}' at none of the gates its stage mapping covers "
                                  f"({', '.join(sorted(gates, key=GATES.index))}); phases: {', '.join(skills[skill]['phases']) or '(none)'}"))

    for d in deps:
        if d["name"] not in referenced:
            issues.append((None, f"dependency '{d['name']}' is referenced by no skill -- a dependency with no caller"))
    return issues, report


def _show(path):
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)


# --- commands ------------------------------------------------------------

def cmd_resolve(skills, closure):
    cs = all_closures(skills)
    if closure not in cs:
        print(f"unknown closure: {closure!r}. known closures: {', '.join(cs)}")
        return 2
    m = members(skills, closure)
    pulled = [n for n in m if n not in ALWAYS_ON]
    missing = {}
    gates_from_deps = set()
    absent = [n for n in m if n not in skills]
    for n in m:
        if n in absent:
            continue
        deps = skills[n]["depends_on"]
        gates_from_deps.update(gate_deps(deps))
        miss = [d for d in skill_deps(deps) if d not in m]
        if miss:
            missing[n] = miss
    gates = sorted(set(active_gates(skills, m)) | gates_from_deps, key=GATES.index)
    issues, report = check_plugins(skills)
    member_set = set(m)
    refs = [r for r in report["refs"] if r["skill"] in member_set]
    plugin_missing = [msg for sk, msg in issues if sk in member_set]
    versions = {d["name"]: (d["loc"] or {}).get("version") for d in report["deps"]}

    print(f"closure: {closure}")
    print(f"  members ({len(m)}): {', '.join(m)}")
    print(f"    always-on: {', '.join(ALWAYS_ON)}")
    print(f"    pulled by tier: {', '.join(pulled) or '(none)'}")
    if absent:
        print(f"    MISSING SKILL.md: {', '.join(absent)}")
    if refs:
        print("  plugin skills bound:")
        for r in refs:
            plugin = r["ref"].split(":", 1)[0]
            kind = "required" if r["hard"] else "optional"
            print(f"    {r['ref']} ({kind}, by {r['skill']}) -- {plugin} {versions.get(plugin) or 'not found'}")
    hookers = gate_hookers(skills, m)
    print(f"  active gates: {', '.join(gates) or '(none)'}")
    print(f"    members hooking each: {', '.join(f'{g}={hookers[g]}' for g in gates)}")
    satisfied = not missing and not absent and not plugin_missing
    print(f"  dependencies_satisfied: {str(satisfied).lower()}")
    if missing:
        for n, miss in sorted(missing.items()):
            print(f"    missing: {n} -> {', '.join(miss)}")
    for msg in plugin_missing:
        print(f"    plugin: {msg}")
    return 0 if satisfied else 1


def _closure_issues(skills, closure):
    issues = []
    m = set(members(skills, closure))
    for n in sorted(m):
        if n not in skills:
            # Only the always-on base can be a member without a SKILL.md behind it,
            # and it is the model's most load-bearing assumption -- report it, never crash.
            issues.append(f"always-on base skill '{n}' has no skills/{n}/SKILL.md")
            continue
        for d in skills[n]["depends_on"]:
            if d in GATES or is_plugin_ref(d):
                continue
            if d not in skills:
                issues.append(f"{n}: depends_on '{d}' resolves to no skill (dangling)")
            elif d not in m:
                issues.append(f"{n}: depends_on '{d}' not present in closure '{closure}'")
        for p in skills[n]["phases"]:
            if p not in GATES:
                issues.append(f"{n}: phase '{p}' is not a valid gate id")
        for a in ALWAYS_ON:
            if a in skills[n]["depends_on"]:
                issues.append(f"{n}: lists always-on '{a}' in depends_on (should be implicit)")
    return issues


def cmd_check(skills, closure):
    cs = all_closures(skills)
    if closure not in cs:
        print(f"unknown closure: {closure!r}. known closures: {', '.join(cs)}")
        return 2
    issues = _closure_issues(skills, closure)
    member_set = set(members(skills, closure))
    plugin_issues, _ = check_plugins(skills)
    issues.extend(msg for sk, msg in plugin_issues if sk is None or sk in member_set)

    rows, err = load_rubric_rows()
    if err:
        issues.append(err)
        row = None
    else:
        issues.extend(msg for c, msg in reconcile_rubric(skills, rows) if c == closure)
        row = next((r for r in rows if r["closure"] == closure), None)

    print(f"closure: {closure}")
    print(f"  members: {', '.join(members(skills, closure))}")
    if row:
        builds = ", ".join(row["builds_on"]) or "(base)"
        adds = ", ".join(row["marginal"]) or "(contract only)"
        print(f"  rubric row: {row['n']} -- builds on {builds}; adds {adds}")
    elif not err:
        print("  rubric row: (none -- prompty can never select this closure)")
    print(f"  valid: {str(not issues).lower()}")
    for i in issues:
        print(f"  issue: {i}")
    return 0 if not issues else 1


def cmd_validate(skills):
    names = set(skills)
    issues = []
    for n, s in sorted(skills.items()):
        for d in s["depends_on"]:
            if d in GATES or is_plugin_ref(d):
                continue
            if d in ALWAYS_ON:
                issues.append(f"{n}: depends_on lists always-on '{d}' (should be implicit -- declared in agents/roboto.md)")
            elif d not in names:
                issues.append(f"{n}: depends_on '{d}' resolves to no skill (dangling)")
        for d in s["optional_depends_on"]:
            if d in GATES or d in names or is_plugin_ref(d):
                continue
            issues.append(f"{n}: optional_depends_on '{d}' resolves to no skill (dangling)")
        for p in s["phases"]:
            if p not in GATES:
                issues.append(f"{n}: phase '{p}' is not a valid gate id")
        for g in s["hooked"]:
            if g not in GATES:
                issues.append(f"{n}: hook 'on_{g}' is not a valid gate id")
            elif g not in s["phases"]:
                issues.append(f"{n}: hooks on_{g} is non-empty but '{g}' is absent from phases (undeclared hook)")
        if not s["tiers"]:
            issues.append(f"{n}: no tiers (member of no closure)")
    for c in all_closures(skills):
        issues.extend(_closure_issues(skills, c))

    rows, err = load_rubric_rows()
    if err:
        issues.append(err)
    else:
        issues.extend(msg for _, msg in reconcile_rubric(skills, rows))

    plugin_issues, report = check_plugins(skills)
    issues.extend(msg for _, msg in plugin_issues)

    closures = all_closures(skills)
    print(f"skills: {len(skills)}  |  closures: {', '.join(closures)}  |  rubric rows: {len(rows)}"
          f"  |  plugin dependencies: {len(report['deps'])}, bindings: {len(report['refs'])}")
    if not issues:
        print("VALID: every closure is dependency-closed; no dangling refs; hooks match phases;")
        print("       every rubric row resolves and every closure is selectable; convention holds;")
        print("       every plugin reference resolves through a declared dependency in range.")
        return 0
    issues = sorted(set(issues))  # the same defect reaches this list once per closure it breaks
    print(f"INVALID: {len(issues)} issue(s):")
    for i in issues:
        print(f"  - {i}")
    return 1


def cmd_plugins(skills):
    issues, report = check_plugins(skills)
    print(f"plugin: {report['plugin'] or '(unnamed)'} {report['version'] or ''}".rstrip())
    print(f"  dependencies ({len(report['deps'])}):")
    for d in report["deps"]:
        loc = d["loc"]
        rng = d["range"] or "(latest)"
        if loc is None:
            print(f"    {d['name']} {rng} -- not found")
            continue
        where = _show(loc["path"]) if loc["path"] else "(no local path)"
        state = {True: "in range", False: "OUT OF RANGE", None: "unchecked"}[d["ok"]]
        print(f"    {d['name']} {rng} -- {loc['version']} at {where} ({loc['layout']}), {state}")
    print(f"  bindings ({len(report['refs'])}):")
    for r in report["refs"]:
        kind = "required" if r["hard"] else "optional"
        if not r["found"]:
            mapping = "unresolved"
        elif r["mapping"] is None:
            mapping = "no stage mapping"
        else:
            both = [g for g in GATES if g in r["mapping"] and g in skills[r["skill"]]["phases"]]
            mapping = (f"stage mapping {', '.join(g for g in GATES if g in r['mapping']) or '(none)'}; "
                       f"bound at {', '.join(both) or '(no shared gate)'}")
        print(f"    {r['skill']} -> {r['ref']} ({kind}): {mapping}")
    if not issues:
        print("VALID: every dependency is found in range and referenced; every binding resolves.")
        return 0
    msgs = sorted(set(msg for _, msg in issues))
    print(f"INVALID: {len(msgs)} issue(s):")
    for msg in msgs:
        print(f"  - {msg}")
    return 1


def cmd_list(skills):
    width = max(len(n) for n in skills) if skills else 0
    for n, s in sorted(skills.items()):
        tier = ",".join(s["tiers"]) or "-"
        dep = ",".join(s["depends_on"]) or "-"
        opt = ",".join(s["optional_depends_on"]) or "-"
        ph = ",".join(s["phases"]) or "-"
        print(f"{n.ljust(width)}  tiers=[{tier}]  depends_on=[{dep}]  optional=[{opt}]  phases=[{ph}]")
    return 0


def main(argv):
    skills = load_skills()
    cmd = argv[0] if argv else "validate"
    if cmd == "validate":
        return cmd_validate(skills)
    if cmd == "list":
        return cmd_list(skills)
    if cmd == "plugins":
        return cmd_plugins(skills)
    if cmd in ("resolve", "check"):
        if len(argv) < 2:
            print(f"usage: p4.py {cmd} <closure>   (closures: {', '.join(all_closures(skills))})")
            return 2
        fn = cmd_resolve if cmd == "resolve" else cmd_check
        return fn(skills, argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
