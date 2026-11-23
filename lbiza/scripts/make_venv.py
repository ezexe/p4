#!/usr/bin/env python3
"""make_venv.py: give this p4 checkout its Python environment, by the command every repository uses.

    python3 lbiza/scripts/make_venv.py                # create or top up it, with ezexe/phi from ../phi, else GitHub
    python3 lbiza/scripts/make_venv.py --phi <path>   # ezexe/phi from that checkout, installed editable
    python3 lbiza/scripts/make_venv.py --no-torch     # leave torch out
    python3 lbiza/scripts/make_venv.py --check        # only report what it has

The build is p4-phi's, lbiza/plugins/p4-phi/scripts/storeenv.py, run as `p4.py venv`, and this script runs it for
this checkout with the arguments it was given. The environment is `.claude/p4/.venv` in the main checkout, the store
of the repository, where every repository's is, and a worktree of this checkout builds the main checkout's. Use it
by its interpreter's full path, `.claude/p4/.venv/bin/python` or on Windows `.claude\\p4\\.venv\\Scripts\\python.exe`.

Before p4-phi held the build, this script built `.venv` at the checkout's root. Python's venv page says of an
environment "If for any reason you need to move the environment to a new location, you should recreate it at the
desired location and delete the one at the old location", so one found at the root is named and left for ezexe to
remove, and nothing is copied out of it.

This script uses the standard library only, so it runs before the environment exists.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # the checkout's root, which holds this script's lbiza/scripts/
P4PY = ROOT / "lbiza" / "plugins" / "p4-phi" / "scripts" / "p4.py"
OLD = ROOT / ".venv"        # where this script built the environment before the store held it


def command(argv):
    """`p4.py venv` for this checkout, with the arguments this script was given."""
    return [sys.executable, "-I", "-X", "utf8", str(P4PY), "venv", "--p4", str(ROOT), *argv]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.version_info < (3, 7):
        raise SystemExit(f"make_venv.py: this script needs Python 3.7 or newer, and this is Python "
                         f"{sys.version.split()[0]}")
    code = subprocess.call(command(argv))
    if OLD.is_dir():
        print(f"make_venv.py: {OLD} is the environment this script built before the store held it; nothing reads "
              f"it at that place now and an environment cannot be moved, so remove that folder by hand")
    return code


if __name__ == "__main__":
    sys.exit(main())
