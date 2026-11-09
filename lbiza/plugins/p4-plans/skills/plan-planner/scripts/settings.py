#!/usr/bin/env python3
"""
The repository's p4-plans settings: the `plans` section of <root>/.claude/p4/p4.json (every p4 plugin's settings,
p4conf.py) merged over the defaults, printed for the agent.

    python3 -I <plan-planner skill dir>/scripts/settings.py            # every setting, one `name: value` per line
    python3 -I <plan-planner skill dir>/scripts/settings.py --json     # the same as JSON
    python3 -I <plan-planner skill dir>/scripts/settings.py plans_dir  # one value, bare

Run from anywhere inside the repository; the root is `git rev-parse --show-toplevel`, else the working directory.
When .claude/p4/ exists and p4.json is missing (or lacks a newer key), the file is written with every default.
An unknown key is reported on stderr and has no effect, so a typo never silently changes a rule.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p4conf  # noqa: E402  (every p4 plugin's settings: <root>/.claude/p4/p4.json)

P4 = Path(".claude") / "p4"
DEFAULTS = p4conf.DEFAULTS["plans"]


def root(start=None):
    try:
        out = subprocess.run(["git", "-C", str(start or Path.cwd()), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(start or Path.cwd())


def load(start=None, warn=True):
    """The plans settings, plus `root`, `config` (p4.json, or null) and `link_prefix` (plans_dir up to the root)."""
    r = root(start)
    p4 = r / P4
    s = {k: v for k, v in p4conf.load(str(p4), warn=warn)["plans"].items() if k in DEFAULTS}
    f = Path(p4conf.path(str(p4)))
    s.update({"root": str(r), "config": str(f) if f.is_file() else None,
              "link_prefix": "../" * len(Path(s["plans_dir"]).parts)})
    return s


def main(argv):
    s = load()
    if argv and argv[0] == "--json":
        print(json.dumps(s, indent=1))
    elif argv:
        v = s
        for part in argv[0].split("."):
            if not isinstance(v, dict) or part not in v:
                print(f"p4-plans: no setting {argv[0]}", file=sys.stderr)
                return 1
            v = v[part]
        print(json.dumps(v) if isinstance(v, (dict, list)) or v is None else v)
    else:
        for k, v in s.items():
            print(f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) or v is None else v}")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
